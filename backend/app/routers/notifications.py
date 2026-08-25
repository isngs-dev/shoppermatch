"""Notification feed — computed entirely from existing data (invitation
events, campaign deadlines, shop coverage, email jobs). There is no separate
notifications table: each notification is derived on read from the same
records already driving Tracking/Campaigns/Audit Logs, so it can never drift
out of sync with them. A stable, content-derived `id` lets the frontend track
read/unread locally (see NotificationsBell.tsx) without needing server-side
read-state.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_admin
from ..models import Campaign, EmailJob, Invitation, Shop, User
from ..serializers import iso
from .campaigns import status_bucket

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

DEADLINE_WARNING_DAYS = 7


def _nid(*parts: str) -> str:
    """Deterministic id: same underlying event always produces the same
    notification id, so client-side read-state survives refetches."""
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


@router.get("")
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    now = datetime.now(timezone.utc)
    notifications: list[dict] = []

    # ---- Shopper acceptance / decline (outreach response) ----
    inv_stmt = (
        select(Invitation)
        .where(Invitation.responded_at.isnot(None))
        .order_by(Invitation.responded_at.desc())
        .limit(200)
        .options(selectinload(Invitation.campaign), selectinload(Invitation.shopper))
    )
    responded = (await session.execute(inv_stmt)).scalars().all()
    for inv in responded:
        shopper_name = inv.shopper.name if inv.shopper else inv.email
        campaign_name = inv.campaign.name if inv.campaign else "a campaign"
        if inv.response == "accepted":
            notifications.append(
                {
                    "id": _nid("accept", str(inv.id)),
                    "type": "shopper_acceptance",
                    "severity": "success",
                    "title": "New shopper acceptance",
                    "message": f"{shopper_name} accepted the assignment for {campaign_name}.",
                    "timestamp": iso(inv.responded_at),
                    "meta": {"invitation_id": str(inv.id), "reference": inv.reference, "via": "email"},
                }
            )
        elif inv.response == "declined":
            notifications.append(
                {
                    "id": _nid("decline", str(inv.id)),
                    "type": "outreach_response",
                    "severity": "info",
                    "title": "Outreach response",
                    "message": f"{shopper_name} declined the assignment for {campaign_name}.",
                    "timestamp": iso(inv.responded_at),
                    "meta": {"invitation_id": str(inv.id), "reference": inv.reference},
                }
            )

    # Latest accepted-response timestamp per campaign, reused below so
    # "campaign completion" notifications are timestamped by when the
    # campaign actually filled up, not by a possibly-future deadline.
    last_accepted_at: dict = {}
    for inv in responded:
        if inv.response != "accepted":
            continue
        current = last_accepted_at.get(inv.campaign_id)
        if current is None or inv.responded_at > current:
            last_accepted_at[inv.campaign_id] = inv.responded_at

    # ---- Email delivery ("sync") completion ----
    job_stmt = (
        select(EmailJob)
        .where(EmailJob.status == "sent", EmailJob.completed_at.isnot(None))
        .order_by(EmailJob.completed_at.desc())
        .limit(100)
        .options(
            selectinload(EmailJob.invitation).selectinload(Invitation.campaign),
            selectinload(EmailJob.invitation).selectinload(Invitation.shopper),
        )
    )
    jobs = (await session.execute(job_stmt)).scalars().all()
    for job in jobs:
        inv = job.invitation
        if inv is None:
            continue
        shopper_name = inv.shopper.name if inv.shopper else inv.email
        campaign_name = inv.campaign.name if inv.campaign else "a campaign"
        notifications.append(
            {
                "id": _nid("sync", str(job.id)),
                "type": "sync_completion",
                "severity": "info",
                "title": "Sync completion",
                "message": f"Invitation email delivered to {shopper_name} for {campaign_name} via {job.provider}.",
                "timestamp": iso(job.completed_at),
                "meta": {"invitation_id": str(inv.id), "provider": job.provider},
            }
        )

    # ---- Campaign deadline / completion / low coverage ----
    campaigns = (
        await session.execute(select(Campaign).options(selectinload(Campaign.shops)))
    ).scalars().all()
    for c in campaigns:
        bucket = status_bucket(c.status)

        if bucket == "active" and c.deadline:
            deadline = c.deadline if c.deadline.tzinfo else c.deadline.replace(tzinfo=timezone.utc)
            days_left = (deadline - now).total_seconds() / 86400
            if 0 <= days_left <= DEADLINE_WARNING_DAYS:
                notifications.append(
                    {
                        "id": _nid("deadline", str(c.id), c.deadline.isoformat()),
                        "type": "deadline_approaching",
                        "severity": "warning",
                        "title": "Campaign approaching deadline",
                        "message": f"{c.name} deadline is in {max(0, round(days_left))} day(s).",
                        "timestamp": iso(now),
                        "meta": {"campaign_id": str(c.id), "deadline": iso(c.deadline)},
                    }
                )

        if bucket == "completed" or (c.total_shops and c.completed_shops >= c.total_shops and c.total_shops > 0):
            # Timestamp this by when completion actually happened (latest
            # accepted response for the campaign), never by `deadline` —
            # for still-"active" campaigns that filled early, the deadline
            # is still in the future and would render as a nonsensical
            # negative "time ago".
            last_accept = last_accepted_at.get(c.id)
            notifications.append(
                {
                    "id": _nid("campaign_complete", str(c.id)),
                    "type": "campaign_completion",
                    "severity": "success",
                    "title": "Campaign completion",
                    "message": f"{c.name} reached {c.completed_shops}/{c.total_shops} shops completed.",
                    "timestamp": iso(last_accept) if last_accept else iso(c.created_at),
                    "meta": {"campaign_id": str(c.id)},
                }
            )

    # Low shopper coverage (batched, avoids N+1): count invitations per shop
    # for active campaigns' shops only.
    shop_stmt = select(Shop).where(
        Shop.campaign_id.in_([c.id for c in campaigns if status_bucket(c.status) == "active"])
    )
    active_shops = (await session.execute(shop_stmt)).scalars().all()
    if active_shops:
        counts_stmt = (
            select(Invitation.shop_id, Invitation.id)
            .where(Invitation.shop_id.in_([s.id for s in active_shops]))
        )
        rows = (await session.execute(counts_stmt)).all()
        invited_by_shop: dict = {}
        for shop_id, _inv_id in rows:
            invited_by_shop[shop_id] = invited_by_shop.get(shop_id, 0) + 1
        campaign_by_id = {c.id: c for c in campaigns}
        for shop in active_shops:
            invited = invited_by_shop.get(shop.id, 0)
            if shop.required_shoppers and invited / shop.required_shoppers < 0.5:
                campaign = campaign_by_id.get(shop.campaign_id)
                notifications.append(
                    {
                        "id": _nid("coverage", str(shop.id)),
                        "type": "low_coverage",
                        "severity": "warning",
                        "title": "Low shopper coverage",
                        "message": (
                            f"{shop.shop_name} has {invited} of {shop.required_shoppers} required "
                            f"shoppers invited"
                            + (f" ({campaign.name})" if campaign else "") + "."
                        ),
                        "timestamp": iso(now),
                        "meta": {"shop_id": str(shop.id), "campaign_id": str(shop.campaign_id)},
                    }
                )

    notifications.sort(key=lambda n: n["timestamp"] or "", reverse=True)
    notifications = notifications[:limit]

    return {"items": notifications, "total": len(notifications)}
