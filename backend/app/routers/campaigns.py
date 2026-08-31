"""Campaign endpoints.

Campaigns are bucketed into three operational portals (active / upcoming /
completed) purely from their free-text ``status`` column — no schema
migration required. ``status_bucket`` is the single source of truth for that
mapping so the list endpoint and the KPI/insight helpers never disagree.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_operator
from ..models import Campaign, DistributionPost, EventType, Invitation, Shop, Shopper, User
from ..serializers import campaign_out, invitation_row, iso, shop_out, shopper_out
from ..services.audit import record_audit
from ..services.distribution import DESTINATION_TYPES, destination_name, generate_post_image, regions_for_shops
from ..services.selection import enforce_over_selection
from ..services.semantic_matching import MATCHING_WEIGHTS, run_matching
from ..services.tenancy import enforce_campaign_access
from ..services.tracking import add_event
from .invitations import _slug, next_reference

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])

UPCOMING_STATUSES = {"draft", "upcoming", "scheduled"}
ACTIVE_STATUSES = {"active", "in_progress", "partially_filled", "filled"}
COMPLETED_STATUSES = {"completed"}
CANCELLED_STATUSES = {"cancelled"}


def status_bucket(status: str) -> str:
    s = (status or "").lower()
    if s in UPCOMING_STATUSES:
        return "upcoming"
    if s in COMPLETED_STATUSES:
        return "completed"
    if s in CANCELLED_STATUSES:
        return "cancelled"
    return "active"


async def _campaign_outreach(session: AsyncSession, campaign_id) -> dict:
    stmt = select(
        func.count(Invitation.id).label("total"),
        func.sum(case((Invitation.sent_at.isnot(None), 1), else_=0)).label("sent"),
        func.sum(case((Invitation.delivered_at.isnot(None), 1), else_=0)).label("delivered"),
        func.sum(case((Invitation.opened_at.isnot(None), 1), else_=0)).label("opened"),
        func.sum(case((Invitation.clicked_at.isnot(None), 1), else_=0)).label("clicked"),
        func.sum(case((Invitation.response == "accepted", 1), else_=0)).label("accepted"),
        func.sum(case((Invitation.response == "declined", 1), else_=0)).label("declined"),
    ).where(Invitation.campaign_id == campaign_id)
    row = (await session.execute(stmt)).one()
    total = int(row.total or 0)
    accepted = int(row.accepted or 0)
    declined = int(row.declined or 0)
    return {
        "invitations": total,
        "sent": int(row.sent or 0),
        "delivered": int(row.delivered or 0),
        "opened": int(row.opened or 0),
        "clicked": int(row.clicked or 0),
        "accepted": accepted,
        "declined": declined,
        "pending": max(0, total - accepted - declined),
    }


async def _campaign_shops_with_coverage(session: AsyncSession, campaign_id) -> list[dict]:
    shops = (
        await session.execute(select(Shop).where(Shop.campaign_id == campaign_id))
    ).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(Invitation.shop_id, func.count(Invitation.id))
                .where(Invitation.campaign_id == campaign_id)
                .group_by(Invitation.shop_id)
            )
        ).all()
    )
    items = []
    for s in shops:
        d = shop_out(s)
        invited = int(counts.get(s.id, 0))
        ratio = (invited / s.required_shoppers) if s.required_shoppers else 0
        d["invited_shoppers"] = invited
        d["coverage"] = "healthy" if ratio >= 1 else ("medium" if ratio >= 0.5 else "low")
        items.append(d)
    return items


def _start_date(campaign: Campaign) -> str | None:
    """Earliest shop visit_start for this campaign, ISO-8601. There is no
    dedicated campaign.start_date column — every shop already carries a
    visit window, so the campaign-level start is derived from that instead
    of adding a schema migration for it."""
    starts = [s.visit_start for s in campaign.shops if s.visit_start is not None]
    if not starts:
        return None
    from ..serializers import iso

    return iso(min(starts))


async def _require_campaign(session: AsyncSession, campaign_id: uuid.UUID, user: User) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    return enforce_campaign_access(campaign, user)


@router.get("")
async def list_campaigns(
    status: str | None = Query(default=None, description="active | upcoming | completed | cancelled"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).options(
        selectinload(Campaign.shops)
    )
    if user.role == "client":
        stmt = stmt.where(Campaign.client_id == user.client_id)
    campaigns = (await session.execute(stmt)).scalars().all()
    out = []
    for c in campaigns:
        bucket = status_bucket(c.status)
        if status and bucket != status.lower():
            continue
        data = campaign_out(c)
        data["bucket"] = bucket
        data["shops_count"] = len(c.shops)
        data["required_shoppers_total"] = sum(s.required_shoppers for s in c.shops)
        data["start_date"] = _start_date(c)
        data["outreach"] = await _campaign_outreach(session, c.id)
        out.append(data)
    return {"items": out, "total": len(out)}


class BulkStatusRequest(BaseModel):
    campaign_ids: list[str] = Field(min_length=1)
    status: Literal["active", "upcoming", "completed", "cancelled"]


@router.post("/bulk/status")
async def bulk_update_status(
    body: BulkStatusRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Bulk archive/status change for the Client Portal's multi-select
    campaign toolbar. Never deletes anything — just moves campaigns between
    the active/upcoming/completed/cancelled buckets, same as editing one
    campaign's status by hand would."""
    updated: list[dict] = []
    errors: list[dict] = []
    for raw_id in body.campaign_ids:
        try:
            campaign_id = uuid.UUID(raw_id)
        except ValueError:
            errors.append({"campaign_id": raw_id, "error": "Invalid campaign id"})
            continue
        campaign = await session.get(Campaign, campaign_id)
        try:
            campaign = enforce_campaign_access(campaign, user)
        except HTTPException as exc:
            errors.append({"campaign_id": raw_id, "error": exc.detail})
            continue
        old_status = campaign.status
        campaign.status = body.status
        updated.append({"campaign_id": raw_id, "name": campaign.name, "old_status": old_status, "new_status": body.status})
        await record_audit(
            session,
            action="campaign.bulk_status_change",
            actor=user.email,
            entity_type="campaign",
            entity_id=raw_id,
            summary=f"{campaign.name} status changed: {old_status} → {body.status}",
            meta={"bulk": True, "count": len(body.campaign_ids)},
        )
    await session.commit()
    return {"updated": updated, "errors": errors}


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = select(Campaign).where(Campaign.id == campaign_id).options(
        selectinload(Campaign.shops)
    )
    campaign = (await session.execute(stmt)).scalar_one_or_none()
    campaign = enforce_campaign_access(campaign, user)
    data = campaign_out(campaign, shops=list(campaign.shops))
    data["bucket"] = status_bucket(campaign.status)
    data["start_date"] = _start_date(campaign)
    data["required_shoppers_total"] = sum(s.required_shoppers for s in campaign.shops)
    data["outreach"] = await _campaign_outreach(session, campaign.id)
    return data


@router.get("/{campaign_id}/shops")
async def campaign_shops(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    await _require_campaign(session, campaign_id, user)
    items = await _campaign_shops_with_coverage(session, campaign_id)
    return {"items": items, "total": len(items)}


@router.get("/{campaign_id}/map")
async def campaign_map(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Shop markers for the Campaign Overview map. Required/Invited/Accepted
    come from real invitation rows (grouped counts, same source as the Shops
    tab); Available reuses `run_matching`'s `eligible_count` — the exact same
    hard-filter pipeline the Recommendations tab uses — so this never
    invents a second definition of "eligible"."""
    campaign = await _require_campaign(session, campaign_id, user)
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign_id))).scalars().all()
    shoppers = list((await session.execute(select(Shopper))).scalars().all())

    invited_counts = dict(
        (
            await session.execute(
                select(Invitation.shop_id, func.count(Invitation.id))
                .where(Invitation.campaign_id == campaign_id)
                .group_by(Invitation.shop_id)
            )
        ).all()
    )
    accepted_counts = dict(
        (
            await session.execute(
                select(Invitation.shop_id, func.count(Invitation.id))
                .where(Invitation.campaign_id == campaign_id, Invitation.response == "accepted")
                .group_by(Invitation.shop_id)
            )
        ).all()
    )

    items = []
    for s in shops:
        d = shop_out(s)
        invited = int(invited_counts.get(s.id, 0))
        accepted = int(accepted_counts.get(s.id, 0))
        ratio = (invited / s.required_shoppers) if s.required_shoppers else 0
        d["invited_shoppers"] = invited
        d["accepted_shoppers"] = accepted
        d["coverage"] = "healthy" if ratio >= 1 else ("medium" if ratio >= 0.5 else "low")
        d["available_shoppers"] = run_matching(shoppers, s, campaign)["eligible_count"]
        items.append(d)

    return {
        "campaign": {"id": str(campaign.id), "name": campaign.name, "deadline": campaign_out(campaign).get("deadline")},
        "items": items,
        "total": len(items),
    }


@router.get("/{campaign_id}/shoppers")
async def campaign_shoppers(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    await _require_campaign(session, campaign_id, user)
    stmt = (
        select(Invitation)
        .where(Invitation.campaign_id == campaign_id)
        .order_by(Invitation.created_at.asc())
        .options(selectinload(Invitation.shopper))
    )
    invitations = (await session.execute(stmt)).scalars().all()
    by_shopper: dict[uuid.UUID, dict] = {}
    for inv in invitations:
        if not inv.shopper:
            continue
        entry = by_shopper.setdefault(inv.shopper.id, shopper_out(inv.shopper))
        entry["latest_status"] = inv.status
        entry["latest_response"] = inv.response
        entry["invitation_count"] = entry.get("invitation_count", 0) + 1
    items = list(by_shopper.values())
    return {"items": items, "total": len(items)}


@router.get("/{campaign_id}/outreach")
async def campaign_outreach_endpoint(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    await _require_campaign(session, campaign_id, user)
    return await _campaign_outreach(session, campaign_id)


@router.get("/{campaign_id}/tracking")
async def campaign_tracking(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    await _require_campaign(session, campaign_id, user)
    stmt = (
        select(Invitation)
        .where(Invitation.campaign_id == campaign_id)
        .order_by(Invitation.created_at.desc())
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
            selectinload(Invitation.email_job),
            selectinload(Invitation.automation),
        )
    )
    invitations = (await session.execute(stmt)).scalars().all()
    return {"items": [invitation_row(i) for i in invitations], "total": len(invitations)}


@router.get("/{campaign_id}/insights")
async def campaign_insights(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    await _require_campaign(session, campaign_id, user)
    shops = await _campaign_shops_with_coverage(session, campaign_id)
    outreach = await _campaign_outreach(session, campaign_id)

    insights: list[dict] = []
    for s in shops:
        if s["coverage"] == "low":
            insights.append(
                {
                    "severity": "warning",
                    "title": f"{s['shop_name']} has insufficient shopper coverage",
                    "message": (
                        f"Only {s['invited_shoppers']} of {s['required_shoppers']} required "
                        f"shoppers have been invited. Consider expanding the search radius or "
                        f"recruiting more shoppers for {s['shop_name']}."
                    ),
                }
            )

    if outreach["opened"]:
        ctr = round(outreach["clicked"] / outreach["opened"] * 100)
        insights.append(
            {
                "severity": "warning" if ctr < 40 else "success",
                "title": f"Click-through rate is {ctr}%",
                "message": f"{outreach['clicked']} of {outreach['opened']} opened invitations were clicked.",
            }
        )

    if outreach["sent"] and (outreach["accepted"] + outreach["declined"]) < outreach["sent"] * 0.3:
        insights.append(
            {
                "severity": "info",
                "title": "Outreach response is low",
                "message": "Fewer than 30% of sent invitations have received a response yet.",
            }
        )

    if not outreach["sent"]:
        insights.append(
            {
                "severity": "info",
                "title": "No outreach sent yet",
                "message": "Generate invitations from the Outreach tab to start tracking this campaign.",
            }
        )

    return {"insights": insights, "shops": shops, "outreach": outreach}


# --------------------------------------------------------------------------- #
# AI-assisted shopper matching (semantic similarity + structured scoring),
# scoped to one shop within one campaign. See services/semantic_matching.py
# for the full pipeline and an explanation of the scoring weights.
# --------------------------------------------------------------------------- #
@router.get("/{campaign_id}/shops/{shop_id}/recommendations")
async def ai_shop_recommendations(
    campaign_id: uuid.UUID,
    shop_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    radius: float | None = Query(default=None, ge=0, description="Max distance in km"),
    min_score: int = Query(default=0, ge=0, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = await _require_campaign(session, campaign_id, user)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")

    shoppers = (await session.execute(select(Shopper))).scalars().all()
    parsed = (campaign.parsed_requirements or {}).get("parsed_fields", {}) if campaign.parsed_requirements else {}
    effective_radius = radius if radius is not None else parsed.get("maximum_distance_km")
    result = run_matching(list(shoppers), shop, campaign, radius_km=effective_radius, requirements=parsed)

    recs = [r for r in result["recommendations"] if r["match_score"] >= min_score][:limit]

    top_line = (
        f"top match {recs[0]['name']} ({recs[0]['match_score']}%)"
        if recs
        else "no eligible candidates"
    )
    await record_audit(
        session,
        action="ai_matching.executed",
        actor=user.email,
        entity_type="shop",
        entity_id=str(shop.id),
        summary=(
            f"AI matching executed for {shop.shop_name} ({campaign.name}): "
            f"{result['total_candidates']} analyzed, {top_line}"
        ),
        meta={
            "campaign": campaign.name,
            "shop": shop.shop_name,
            "candidates_analyzed": result["total_candidates"],
            "eligible": result["eligible_count"],
        },
    )
    await session.commit()

    return {
        "campaign_id": str(campaign.id),
        "shop_id": str(shop.id),
        "shop_name": shop.shop_name,
        "required_shoppers": shop.required_shoppers,
        "weights": MATCHING_WEIGHTS,
        "requirement_summary": result["requirement_summary"],
        "total_candidates": result["total_candidates"],
        "eligible_count": result["eligible_count"],
        "excluded": result["excluded"],
        "classification_counts": result["classification_counts"],
        "recommended_count": len(recs),
        "recommendations": recs,
    }


class ApproveRecommendationsRequest(BaseModel):
    shopper_ids: list[str]


@router.post("/{campaign_id}/shops/{shop_id}/recommendations/approve")
async def approve_ai_recommendations(
    campaign_id: uuid.UUID,
    shop_id: uuid.UUID,
    body: ApproveRecommendationsRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Turn approved AI recommendations into real, trackable invitations —
    the same Invitation model + UUID tracking the rest of the app uses, so
    they immediately show up in Outreach and Tracking. Invitations are
    created but not auto-sent; sending stays an explicit Outreach action."""
    campaign = await _require_campaign(session, campaign_id, user)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")
    if not body.shopper_ids:
        raise HTTPException(status_code=400, detail="No shoppers selected")
    await enforce_over_selection(session, shop, len(body.shopper_ids))

    created = []
    for sid in body.shopper_ids:
        try:
            shopper = await session.get(Shopper, uuid.UUID(sid))
        except ValueError:
            continue
        if shopper is None:
            continue
        reference = await next_reference(session)
        inv = Invitation(
            tracking_token=uuid.uuid4(),
            reference=reference,
            campaign_id=campaign.id,
            shop_id=shop.id,
            shopper_id=shopper.id,
            email=shopper.email,
            subject=f"You're invited: {campaign.name}",
            status="created",
            source="AI Recommendation",
            utm_source="ai_recommendation",
            utm_medium="email",
            utm_campaign=_slug(campaign.name),
        )
        inv.campaign = campaign
        inv.shop = shop
        inv.shopper = shopper
        session.add(inv)
        await session.flush()
        await add_event(
            session,
            inv,
            EventType.INVITATION_CREATED,
            {"source": "AI Recommendation", "campaign": campaign.name, "actor": user.email},
        )
        created.append(
            {
                "shopper_id": str(shopper.id),
                "shopper_name": shopper.name,
                "invitation_id": str(inv.id),
                "reference": reference,
            }
        )

    await record_audit(
        session,
        action="ai_recommendations.approved",
        actor=user.email,
        entity_type="shop",
        entity_id=str(shop.id),
        summary=f"Approved {len(created)} AI-recommended shopper(s) for {shop.shop_name} ({campaign.name})",
        meta={"campaign": campaign.name, "shop": shop.shop_name, "shopper_ids": body.shopper_ids},
    )
    await session.commit()
    return {"created": created, "count": len(created)}


# --------------------------------------------------------------------------- #
# Region-Targeted Social Media Posting (conceptual/demo — see
# services/distribution.py for what this does and doesn't actually connect
# to). Sits on the Campaign Detail "Distribution" tab.
# --------------------------------------------------------------------------- #
@router.get("/{campaign_id}/distribution")
async def get_distribution(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = await _require_campaign(session, campaign_id, user)
    shops = await campaign.awaitable_attrs.shops
    grouped = regions_for_shops(list(shops))

    last_posts_stmt = (
        select(DistributionPost)
        .where(DistributionPost.campaign_id == campaign_id)
        .order_by(DistributionPost.posted_at.desc())
    )
    all_posts = (await session.execute(last_posts_stmt)).scalars().all()
    latest_by_key: dict[tuple[str, str], DistributionPost] = {}
    for p in all_posts:
        key = (p.region, p.destination_type)
        if key not in latest_by_key:
            latest_by_key[key] = p

    regions_out = []
    for region, region_shops in sorted(grouped.items()):
        destinations = []
        for dtype, dlabel in DESTINATION_TYPES:
            last = latest_by_key.get((region, dtype))
            destinations.append(
                {
                    "type": dtype,
                    "label": dlabel,
                    "name": destination_name(dtype, region),
                    "last_post": (
                        {
                            "message": last.message,
                            "image_url": last.image_url,
                            "posted_at": iso(last.posted_at),
                            "posted_by": last.posted_by,
                            "status": last.status,
                        }
                        if last
                        else None
                    ),
                }
            )
        regions_out.append(
            {
                "region": region,
                "shop_count": len(region_shops),
                "shop_names": [s.shop_name for s in region_shops],
                "destinations": destinations,
            }
        )

    recent = [
        {
            "id": str(p.id),
            "region": p.region,
            "destination_type": p.destination_type,
            "destination_name": p.destination_name,
            "message": p.message,
            "image_url": p.image_url,
            "posted_at": iso(p.posted_at),
            "posted_by": p.posted_by,
            "status": p.status,
        }
        for p in all_posts[:20]
    ]
    return {"campaign_id": str(campaign_id), "regions": regions_out, "recent_posts": recent}


class DistributionImageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/{campaign_id}/distribution/generate-image")
async def generate_distribution_image(
    campaign_id: uuid.UUID,
    body: DistributionImageRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """The one real AI call in this feature — see
    services/distribution.py::generate_post_image. Returns the image only;
    it isn't saved anywhere until the client actually posts with it."""
    campaign = await _require_campaign(session, campaign_id, user)
    image_url = await generate_post_image(campaign.name, body.message)
    return {"image_url": image_url}


class DistributionPostRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    image_url: str | None = None
    # Omit to post to every region-matched destination for this campaign.
    regions: list[str] | None = None


@router.post("/{campaign_id}/distribution/post")
async def post_distribution(
    campaign_id: uuid.UUID,
    body: DistributionPostRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Simulates the "Post Campaign Creative to the Matched Regional
    Destination" step — same creative, sent once per region-matched
    destination instead of blanket-posted everywhere. No real Meta/
    JobSlinger/TrustedHerd call happens; this durably records what would
    have been posted, same as the rest of this app's demo-mode integrations."""
    campaign = await _require_campaign(session, campaign_id, user)
    shops = await campaign.awaitable_attrs.shops
    grouped = regions_for_shops(list(shops))
    if not grouped:
        raise HTTPException(status_code=400, detail="This campaign has no shops to determine regions from")

    target_regions = body.regions if body.regions is not None else list(grouped.keys())
    unknown = [r for r in target_regions if r not in grouped]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown region(s) for this campaign: {', '.join(unknown)}")

    created = []
    for region in target_regions:
        for dtype, _label in DESTINATION_TYPES:
            post = DistributionPost(
                campaign_id=campaign.id,
                region=region,
                destination_type=dtype,
                destination_name=destination_name(dtype, region),
                message=body.message,
                image_url=body.image_url,
                status="posted",
                posted_by=user.email,
            )
            session.add(post)
            await session.flush()
            created.append(
                {
                    "id": str(post.id),
                    "region": region,
                    "destination_type": dtype,
                    "destination_name": post.destination_name,
                    "posted_at": iso(post.posted_at),
                }
            )

    await record_audit(
        session,
        action="distribution.posted",
        actor=user.email,
        entity_type="campaign",
        entity_id=str(campaign.id),
        summary=f"Posted campaign creative to {len(created)} regional destination(s) for {campaign.name}",
        meta={"campaign": campaign.name, "regions": target_regions, "count": len(created)},
    )
    await session.commit()
    return {"created": created, "count": len(created)}
