"""Client Portal API — /api/client/*.

Every query here is filtered by `Campaign.client_id == current user's
client_id`, enforced server-side (never left to the frontend). No endpoint
in this router ever touches the `shoppers` table or returns any shopper PII
(name, email, phone) — client-facing responses are built from `shop_out()`
and the aggregate outreach/health helpers already used by the Admin API, so
"how many shoppers are confirmed" is a count, never a candidate list.

Nothing here duplicates business logic: campaign bucketing, shop coverage,
outreach funnel counts, and AI campaign health/performance all reuse the
exact same helpers the Admin API uses (`routers.campaigns` and
`services.ai.campaign_predictor`) — this router only adds the client_id
filter and a friendlier response shape on top.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_client
from ..models import Campaign, Client, ClientSocialAccount, User
from ..schemas import AccountActionRequest
from ..security import verify_password
from ..serializers import campaign_out
from ..services import exporters
from ..services import reports as reports_service
from ..services.ai import campaign_predictor
from ..services.audit import record_audit
from ..services import facebook_oauth
from ..services.distribution import DESTINATION_TYPES, default_account_name
from .campaigns import (
    _campaign_outreach,
    _campaign_shops_with_coverage,
    _start_date,
    status_bucket,
)

router = APIRouter(prefix="/api/client", tags=["Client Portal"])


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100) if denominator else 0


def _tracking_summary(outreach: dict) -> dict:
    """Business-level funnel + rates — the same shape as the Admin tracking
    KPIs, minus every internal/technical field (no tracking tokens, no
    provider message ids, no error metadata, no raw invitation ids)."""
    return {
        "sent": outreach["sent"],
        "delivered": outreach["delivered"],
        "opened": outreach["opened"],
        "clicked": outreach["clicked"],
        "accepted": outreach["accepted"],
        "declined": outreach["declined"],
        "delivery_rate": _rate(outreach["delivered"], outreach["sent"]),
        "open_rate": _rate(outreach["opened"], outreach["delivered"]),
        "click_rate": _rate(outreach["clicked"], outreach["opened"]),
        "acceptance_rate": _rate(outreach["accepted"], outreach["clicked"]),
    }


async def _client_campaigns(session: AsyncSession, client_id) -> list[Campaign]:
    stmt = (
        select(Campaign)
        .where(Campaign.client_id == client_id)
        .order_by(Campaign.created_at.desc())
        .options(selectinload(Campaign.shops))
    )
    return list((await session.execute(stmt)).scalars().all())


async def _require_owned_campaign(session: AsyncSession, campaign_id: uuid.UUID, client_id) -> Campaign:
    stmt = (
        select(Campaign)
        .where(Campaign.id == campaign_id, Campaign.client_id == client_id)
        .options(selectinload(Campaign.shops))
    )
    campaign = (await session.execute(stmt)).scalar_one_or_none()
    if campaign is None:
        # 404, not 403 — never confirm/deny another client's campaign exists.
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("/profile")
async def profile(user: User = Depends(require_client)):
    return {
        "user_name": user.name,
        "user_email": user.email,
        "client_id": str(user.client_id),
        "client_name": user.client.company_name if user.client else None,
        "client_status": user.client.status if user.client else None,
    }


# --------------------------------------------------------------------------- #
# Danger zone — self-service account deactivation/deletion. Both require the
# current password re-entered (AccountActionRequest) so a session left open
# on a shared machine can't be used to lock the account out from under the
# real owner. Neither one touches campaigns/shops/invitations: ISN keeps
# those business records regardless of whether the client's login still
# exists, exactly like a SaaS "delete my account" only removes access, not
# the vendor's own records.
# --------------------------------------------------------------------------- #
@router.post("/account/deactivate")
async def deactivate_account(
    body: AccountActionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    client = await session.get(Client, user.client_id)
    if client is not None:
        client.status = "deactivated"
    await record_audit(
        session,
        action="client.account_deactivated",
        actor=user.email,
        entity_type="client",
        entity_id=str(user.client_id),
        summary=f"Account deactivated by {user.email}",
    )
    await session.commit()
    return {"message": "Your account has been deactivated. Contact ISN to reactivate it."}


@router.post("/account/delete")
async def delete_account(
    body: AccountActionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    client = await session.get(Client, user.client_id)
    if client is not None:
        client.status = "deleted"
    await record_audit(
        session,
        action="client.account_deleted",
        actor=user.email,
        entity_type="client",
        entity_id=str(user.client_id),
        summary=f"Account deleted by {user.email}",
    )
    await session.delete(user)
    await session.commit()
    return {"message": "Your account has been deleted. You have been signed out."}


@router.get("/dashboard")
async def dashboard(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaigns = await _client_campaigns(session, user.client_id)

    by_bucket = {"active": 0, "upcoming": 0, "completed": 0, "cancelled": 0}
    total_shops = 0
    completed_shops = 0
    health_buckets = {"on_track": 0, "attention": 0, "completed": 0}
    outreach_totals = {"sent": 0, "delivered": 0, "opened": 0, "clicked": 0, "accepted": 0, "declined": 0}
    campaign_cards = []

    for c in campaigns:
        bucket = status_bucket(c.status)
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        total_shops += c.total_shops or 0
        completed_shops += c.completed_shops or 0

        outreach = await _campaign_outreach(session, c.id)
        for key in outreach_totals:
            outreach_totals[key] += outreach[key]

        if bucket == "completed":
            health_buckets["completed"] += 1
        elif bucket in ("active", "upcoming"):
            health = await campaign_predictor.campaign_health(session, c)
            if health["readiness"] >= 75 and not health["risks"]:
                health_buckets["on_track"] += 1
            else:
                health_buckets["attention"] += 1

        if bucket in ("active", "upcoming"):
            campaign_cards.append({
                "id": str(c.id),
                "name": c.name,
                "bucket": bucket,
                "progress": round((c.completed_shops / c.total_shops) * 100) if c.total_shops else 0,
                "total_shops": c.total_shops or 0,
                "completed_shops": c.completed_shops or 0,
                "deadline": c.deadline.date().isoformat() if c.deadline else None,
            })

    overall_progress = round((completed_shops / total_shops) * 100) if total_shops else 0
    campaign_cards.sort(key=lambda x: (x["bucket"] != "active", x["deadline"] or "9999-99-99"))

    return {
        "client_name": user.client.company_name if user.client else None,
        "active_campaigns": by_bucket["active"],
        "upcoming_campaigns": by_bucket["upcoming"],
        "completed_campaigns": by_bucket["completed"],
        "total_shops": total_shops,
        "completed_shops": completed_shops,
        "pending_shops": max(0, total_shops - completed_shops),
        "overall_progress": overall_progress,
        "campaign_health": health_buckets,
        "outreach": outreach_totals,
        "campaigns": campaign_cards[:6],
    }


@router.get("/campaigns")
async def list_campaigns(
    status: str | None = Query(default=None, description="active | upcoming | completed | cancelled"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaigns = await _client_campaigns(session, user.client_id)
    out = []
    for c in campaigns:
        bucket = status_bucket(c.status)
        if status and bucket != status.lower():
            continue
        data = campaign_out(c)
        data["bucket"] = bucket
        data["shops_count"] = len(c.shops)
        data["start_date"] = _start_date(c)
        outreach = await _campaign_outreach(session, c.id)
        data["progress"] = round((c.completed_shops / c.total_shops) * 100) if c.total_shops else 0
        data["recruitment"] = {
            "required": sum(s.required_shoppers for s in c.shops),
            "confirmed": outreach["accepted"],
        }
        out.append(data)
    return {"items": out, "total": len(out)}


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaign = await _require_owned_campaign(session, campaign_id, user.client_id)
    data = campaign_out(campaign, shops=None)
    data["bucket"] = status_bucket(campaign.status)
    data["start_date"] = _start_date(campaign)
    outreach = await _campaign_outreach(session, campaign.id)
    required = sum(s.required_shoppers for s in campaign.shops)
    data["progress"] = round((campaign.completed_shops / campaign.total_shops) * 100) if campaign.total_shops else 0
    data["recruitment"] = {
        "required": required,
        "confirmed": outreach["accepted"],
        "pending": max(0, required - outreach["accepted"]),
    }
    data["response_rate"] = round((outreach["accepted"] + outreach["declined"]) / outreach["sent"] * 100) if outreach["sent"] else 0
    data["completion_rate"] = data["progress"]
    return data


@router.get("/campaigns/{campaign_id}/shops")
async def campaign_shops(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaign = await _require_owned_campaign(session, campaign_id, user.client_id)
    shops = await _campaign_shops_with_coverage(session, campaign.id)
    # Client-safe shop view: coverage summary only, no shopper identity —
    # shop_out() (used by _campaign_shops_with_coverage) never included PII,
    # but strip the raw lat/lng too since routing detail isn't needed here.
    for s in shops:
        s.pop("latitude", None)
        s.pop("longitude", None)
        pct = round((s["invited_shoppers"] / s["required_shoppers"]) * 100) if s["required_shoppers"] else 0
        s["progress_pct"] = min(100, pct)
        s["completion_status"] = "completed" if s["status"] == "completed" else ("in_progress" if s["invited_shoppers"] > 0 else "pending")
    return {"items": shops, "total": len(shops)}


@router.get("/email-status")
async def email_status(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Bulk-send governor config (non-secret) plus this client's own send
    volume in the trailing 24h — never the cross-tenant total, which is
    admin-only (see routers/misc.py::get_settings_endpoint)."""
    from datetime import timedelta

    from ..config import settings
    from ..models import EmailJob, Invitation
    from ..services.outbox import EmailJobStatus
    from ..services.tracking import now

    campaigns = await _client_campaigns(session, user.client_id)
    campaign_ids = [c.id for c in campaigns]
    sent_last_24h = 0
    if campaign_ids:
        cutoff = now() - timedelta(hours=24)
        stmt = (
            select(func.count(EmailJob.id))
            .join(Invitation, Invitation.id == EmailJob.invitation_id)
            .where(
                Invitation.campaign_id.in_(campaign_ids),
                EmailJob.status == EmailJobStatus.SENT,
                EmailJob.completed_at >= cutoff,
            )
        )
        sent_last_24h = int((await session.execute(stmt)).scalar() or 0)

    return {
        "bulk_email_batch_size": settings.bulk_email_batch_size,
        "bulk_email_daily_limit": settings.bulk_email_daily_limit,
        "bulk_email_batch_delay_seconds": settings.bulk_email_batch_delay_seconds,
        "sent_last_24h": sent_last_24h,
    }


@router.get("/tracking")
async def tracking_overview(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Business-level, campaign-wide outreach funnel across every campaign
    this client owns — no invitation-level detail, no tracking tokens, no
    shopper identity. Sums the same real per-campaign counts the Admin
    Tracking page uses (_campaign_outreach), never a separate rollup."""
    campaigns = await _client_campaigns(session, user.client_id)
    totals = {"sent": 0, "delivered": 0, "opened": 0, "clicked": 0, "accepted": 0, "declined": 0}
    for c in campaigns:
        outreach = await _campaign_outreach(session, c.id)
        for k in totals:
            totals[k] += outreach[k]
    return _tracking_summary(totals)


@router.get("/tracking/campaign/{campaign_id}")
async def tracking_campaign(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaign = await _require_owned_campaign(session, campaign_id, user.client_id)
    outreach = await _campaign_outreach(session, campaign.id)
    result = _tracking_summary(outreach)
    result["campaign_id"] = str(campaign.id)
    result["campaign_name"] = campaign.name
    return result


@router.get("/insights")
async def insights(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Business-level AI insight — reuses the same campaign_health()
    computation the Admin AI Health card uses, translated into one plain
    sentence instead of the operational breakdown table. Never invents a
    number: every figure quoted in the sentence comes straight from
    campaign_health()'s own output."""
    if campaign_id:
        campaign = await _require_owned_campaign(session, campaign_id, user.client_id)
        campaigns = [campaign]
    else:
        campaigns = [
            c for c in await _client_campaigns(session, user.client_id)
            if status_bucket(c.status) in ("active", "upcoming")
        ]

    items = []
    for c in campaigns:
        health = await campaign_predictor.campaign_health(session, c)
        coverage = health["breakdown"]["eligible_shoppers"]
        if health["risks"]:
            message = f"{c.name}: {' '.join(health['risks'])}"
        elif coverage >= 85:
            message = f"{c.name} is progressing well — {coverage}% of required shopper coverage has been achieved."
        elif coverage >= 50:
            message = f"{c.name} has {coverage}% shopper coverage so far — on track but worth monitoring."
        else:
            message = f"{c.name} currently has only {coverage}% shopper coverage — additional recruitment is recommended."
        items.append({
            "campaign_id": str(c.id),
            "campaign_name": c.name,
            "message": message,
            "readiness": health["readiness"],
        })
    return {"items": items, "total": len(items)}


@router.get("/reports")
async def reports(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    if campaign_id:
        campaigns = [await _require_owned_campaign(session, campaign_id, user.client_id)]
    else:
        campaigns = await _client_campaigns(session, user.client_id)

    items = []
    for c in campaigns:
        bucket = status_bucket(c.status)
        outreach = await _campaign_outreach(session, c.id)
        required = sum(s.required_shoppers for s in c.shops)
        entry = {
            "campaign_id": str(c.id),
            "campaign_name": c.name,
            "bucket": bucket,
            "campaign_summary": {
                "total_shops": c.total_shops,
                "completed_shops": c.completed_shops,
                "pending_shops": max(0, (c.total_shops or 0) - (c.completed_shops or 0)),
                "progress": round((c.completed_shops / c.total_shops) * 100) if c.total_shops else 0,
            },
            "recruitment_coverage": {
                "required": required,
                "confirmed": outreach["accepted"],
                "pending": max(0, required - outreach["accepted"]),
            },
            "completion_rate": round((c.completed_shops / c.total_shops) * 100) if c.total_shops else 0,
            "response_rate": round((outreach["accepted"] + outreach["declined"]) / outreach["sent"] * 100) if outreach["sent"] else 0,
            "outreach_summary": {
                "sent": outreach["sent"],
                "opened": outreach["opened"],
                "clicked": outreach["clicked"],
                "accepted": outreach["accepted"],
                "declined": outreach["declined"],
            },
        }
        if bucket == "completed":
            perf = await campaign_predictor.performance_summary(session, c)
            entry["ai_summary"] = perf["summary"]
        items.append(entry)
    return {"items": items, "total": len(items)}


@router.get("/reports/campaigns/{campaign_id}/export")
async def export_campaign_report(
    campaign_id: uuid.UUID,
    format: str = Query(default="pdf", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Client-safe export — reuses the exact same `build_campaign_report`
    the Admin export uses, with `admin=False` so no technical/internal
    section is ever assembled in the first place (not just hidden)."""
    campaign = await _require_owned_campaign(session, campaign_id, user.client_id)
    report = await reports_service.build_campaign_report(session, campaign, admin=False)
    content = exporters.EXPORTERS[format](report)
    filename = f"{campaign.name.replace(' ', '_')}_report.{format}"
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Connected social/portal accounts (conceptual/demo — see
# services/distribution.py). Client-level, shared across every campaign this
# client owns — connect once here, then it's available on every campaign's
# Distribution tab. "Connect" is a demo simulation (no real OAuth handshake
# exists), same pattern as the rest of this feature.
# --------------------------------------------------------------------------- #
@router.get("/social-accounts")
async def list_social_accounts(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    stmt = select(ClientSocialAccount).where(ClientSocialAccount.client_id == user.client_id)
    accounts = (await session.execute(stmt)).scalars().all()
    connected = {a.platform: a for a in accounts}
    items = [
        {
            "platform": ptype,
            "label": label,
            "connected": ptype in connected,
            "account_name": connected[ptype].account_name if ptype in connected else None,
            "connected_at": connected[ptype].connected_at.isoformat() if ptype in connected else None,
            # Only "facebook" can ever be a real OAuth connection today — see
            # services/facebook_oauth.py. Every other platform stays
            # simulated (status defaults to "connected" the moment the demo
            # "Connect" flow creates the row, with no token fields set).
            "status": connected[ptype].status if ptype in connected else None,
            "is_real_connection": bool(connected[ptype].access_token_encrypted) if ptype in connected else False,
            "needs_reconnect": (connected[ptype].status == "expired") if ptype in connected else False,
        }
        for ptype, label in DESTINATION_TYPES
    ]
    return {"items": items}


class ConnectSocialAccountRequest(BaseModel):
    platform: str
    account_name: str | None = None


@router.post("/social-accounts/connect")
async def connect_social_account(
    body: ConnectSocialAccountRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    valid_platforms = {p for p, _ in DESTINATION_TYPES}
    if body.platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {body.platform}")
    if body.platform == "facebook" and facebook_oauth.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Real Facebook OAuth is configured — use Connect Facebook (GET /api/social/facebook/connect) instead of the demo connect.",
        )

    client = await session.get(Client, user.client_id)
    existing_stmt = select(ClientSocialAccount).where(
        ClientSocialAccount.client_id == user.client_id, ClientSocialAccount.platform == body.platform
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    account_name = body.account_name or default_account_name(body.platform, client.company_name if client else "Client")
    if existing:
        existing.account_name = account_name
    else:
        session.add(
            ClientSocialAccount(
                client_id=user.client_id,
                platform=body.platform,
                account_name=account_name,
                connected_by=user.email,
            )
        )
    await record_audit(
        session,
        action="social_account.connected",
        actor=user.email,
        entity_type="client",
        entity_id=str(user.client_id),
        summary=f"Connected {body.platform} account: {account_name}",
        meta={"platform": body.platform, "account_name": account_name},
    )
    await session.commit()
    return {"platform": body.platform, "account_name": account_name, "connected": True}


@router.delete("/social-accounts/{platform}")
async def disconnect_social_account(
    platform: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    stmt = select(ClientSocialAccount).where(
        ClientSocialAccount.client_id == user.client_id, ClientSocialAccount.platform == platform
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Not connected")
    await session.delete(existing)
    await record_audit(
        session,
        action="social_account.disconnected",
        actor=user.email,
        entity_type="client",
        entity_id=str(user.client_id),
        summary=f"Disconnected {platform} account",
        meta={"platform": platform},
    )
    await session.commit()
    return {"platform": platform, "connected": False}
