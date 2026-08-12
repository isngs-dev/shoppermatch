"""Campaign endpoints.

Campaigns are bucketed into three operational portals (active / upcoming /
completed) purely from their free-text ``status`` column — no schema
migration required. ``status_bucket`` is the single source of truth for that
mapping so the list endpoint and the KPI/insight helpers never disagree.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import get_current_user
from ..models import Campaign, EventType, Invitation, Shop, Shopper, User
from ..serializers import campaign_out, invitation_row, shop_out, shopper_out
from ..services.audit import record_audit
from ..services.semantic_matching import MATCHING_WEIGHTS, run_matching
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


async def _require_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("")
async def list_campaigns(
    status: str | None = Query(default=None, description="active | upcoming | completed | cancelled"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).options(
        selectinload(Campaign.shops)
    )
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


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(Campaign).where(Campaign.id == campaign_id).options(
        selectinload(Campaign.shops)
    )
    campaign = (await session.execute(stmt)).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
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
    _: User = Depends(get_current_user),
):
    await _require_campaign(session, campaign_id)
    items = await _campaign_shops_with_coverage(session, campaign_id)
    return {"items": items, "total": len(items)}


@router.get("/{campaign_id}/shoppers")
async def campaign_shoppers(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    await _require_campaign(session, campaign_id)
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
    _: User = Depends(get_current_user),
):
    await _require_campaign(session, campaign_id)
    return await _campaign_outreach(session, campaign_id)


@router.get("/{campaign_id}/tracking")
async def campaign_tracking(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    await _require_campaign(session, campaign_id)
    stmt = (
        select(Invitation)
        .where(Invitation.campaign_id == campaign_id)
        .order_by(Invitation.created_at.desc())
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
            selectinload(Invitation.email_job),
        )
    )
    invitations = (await session.execute(stmt)).scalars().all()
    return {"items": [invitation_row(i) for i in invitations], "total": len(invitations)}


@router.get("/{campaign_id}/insights")
async def campaign_insights(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    await _require_campaign(session, campaign_id)
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
    user: User = Depends(get_current_user),
):
    campaign = await _require_campaign(session, campaign_id)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")

    shoppers = (await session.execute(select(Shopper))).scalars().all()
    result = run_matching(list(shoppers), shop, campaign, radius_km=radius)

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
    user: User = Depends(get_current_user),
):
    """Turn approved AI recommendations into real, trackable invitations —
    the same Invitation model + UUID tracking the rest of the app uses, so
    they immediately show up in Outreach and Tracking. Invitations are
    created but not auto-sent; sending stays an explicit Outreach action."""
    campaign = await _require_campaign(session, campaign_id)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")
    if not body.shopper_ids:
        raise HTTPException(status_code=400, detail="No shoppers selected")

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
