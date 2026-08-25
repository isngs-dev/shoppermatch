"""Shopper endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_operator
from ..models import Campaign, Invitation, Shopper, User
from ..serializers import iso, shopper_out

router = APIRouter(prefix="/api/shoppers", tags=["Shoppers"])


@router.get("")
async def list_shoppers(
    q: str | None = Query(default=None, description="Search by name / email / city"),
    availability: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    stmt = select(Shopper).order_by(Shopper.rating.desc())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func_lower(Shopper.name).like(like),
                func_lower(Shopper.email).like(like),
                func_lower(Shopper.city).like(like),
            )
        )
    if availability:
        stmt = stmt.where(Shopper.availability_status == availability)
    shoppers = (await session.execute(stmt)).scalars().all()
    return {"items": [shopper_out(s) for s in shoppers], "total": len(shoppers)}


@router.get("/{shopper_id}")
async def get_shopper(
    shopper_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    shopper = await session.get(Shopper, shopper_id)
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")
    return shopper_out(shopper)


def _history_status(inv: Invitation) -> str:
    """Human status label for one campaign-history row, derived entirely
    from the invitation's real response/status fields."""
    if inv.response == "accepted":
        return "Completed" if inv.status == "accepted" else "Accepted"
    if inv.response == "declined":
        return "Declined"
    if inv.clicked_at:
        return "Clicked"
    if inv.opened_at:
        return "Opened"
    if inv.sent_at:
        return "Sent"
    return "Pending"


@router.get("/{shopper_id}/campaign-history")
async def shopper_campaign_history(
    shopper_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Every campaign/shop this shopper has ever been invited to, with the
    real outcome — used by the Shopper detail drawer's Campaign History list.
    A client-role caller only ever sees the slice of that history belonging
    to their own campaigns — the shopper pool is shared, but one client
    must never see which *other* brands the same shopper has worked with."""
    shopper = await session.get(Shopper, shopper_id)
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")

    stmt = (
        select(Invitation)
        .where(Invitation.shopper_id == shopper_id)
        .order_by(Invitation.created_at.desc())
        .options(selectinload(Invitation.campaign), selectinload(Invitation.shop))
    )
    if user.role == "client":
        stmt = stmt.join(Campaign, Invitation.campaign_id == Campaign.id).where(Campaign.client_id == user.client_id)
    invitations = (await session.execute(stmt)).scalars().all()

    items = [
        {
            "invitation_id": str(inv.id),
            "reference": inv.reference,
            "campaign_id": str(inv.campaign_id),
            "campaign_name": inv.campaign.name if inv.campaign else None,
            "client_name": inv.campaign.client_name if inv.campaign else None,
            "shop_name": inv.shop.shop_name if inv.shop else None,
            "status": _history_status(inv),
            "response": inv.response,
            "created_at": iso(inv.created_at),
            "responded_at": iso(inv.responded_at),
        }
        for inv in invitations
    ]
    counts = {
        "completed": sum(1 for i in items if i["status"] in ("Completed", "Accepted")),
        "declined": sum(1 for i in items if i["status"] == "Declined"),
        "pending": sum(1 for i in items if i["status"] not in ("Completed", "Accepted", "Declined")),
    }
    return {"shopper_id": str(shopper_id), "items": items, "total": len(items), "counts": counts}


# Small helper so search works case-insensitively on both SQLite and Postgres.
from sqlalchemy import func  # noqa: E402


def func_lower(column):
    return func.lower(column)
