"""Shop endpoints + per-shop recommendations."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_admin, require_operator
from ..models import Campaign, EventType, Invitation, InvitationStatus, Shop, ShopBonus, Shopper, User, utcnow
from ..serializers import shop_bonus_out, shop_out
from ..services.audit import record_audit
from ..services.email import send_email
from ..services.recommendation import recommend_for_shop
from ..services.selection import active_invitation_count
from ..services.tenancy import enforce_campaign_access
from ..services.tracking import add_event, advance_status

router = APIRouter(prefix="/api/shops", tags=["Shops"])


async def _require_shop(session: AsyncSession, shop_id: uuid.UUID, user: User) -> Shop:
    stmt = select(Shop).where(Shop.id == shop_id).options(selectinload(Shop.campaign))
    shop = (await session.execute(stmt)).scalar_one_or_none()
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    enforce_campaign_access(shop.campaign, user)
    return shop


@router.get("")
async def list_shops(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = select(Shop)
    if campaign_id is not None:
        campaign = await session.get(Campaign, campaign_id)
        enforce_campaign_access(campaign, user)
        stmt = stmt.where(Shop.campaign_id == campaign_id)
    elif user.role == "client":
        stmt = stmt.join(Campaign, Shop.campaign_id == Campaign.id).where(Campaign.client_id == user.client_id)
    shops = (await session.execute(stmt)).scalars().all()
    shop_ids = [s.id for s in shops]
    bonus_by_shop = {}
    if shop_ids:
        bonus_rows = (
            await session.execute(select(ShopBonus).where(ShopBonus.shop_id.in_(shop_ids)))
        ).scalars().all()
        bonus_by_shop = {b.shop_id: b for b in bonus_rows}
    return {
        "items": [shop_out(s, bonus=bonus_by_shop.get(s.id)) for s in shops],
        "total": len(shops),
    }


@router.get("/{shop_id}")
async def get_shop(
    shop_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    shop = await _require_shop(session, shop_id, user)
    bonus = (
        await session.execute(select(ShopBonus).where(ShopBonus.shop_id == shop_id))
    ).scalar_one_or_none()
    data = shop_out(shop, bonus=bonus)
    data["active_selected_count"] = await active_invitation_count(session, shop.id)
    return data


class OverSelectionRequest(BaseModel):
    allow: bool


@router.patch("/{shop_id}/over-selection")
async def set_over_selection(
    shop_id: uuid.UUID,
    body: OverSelectionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Explicit, auditable per-shop override of the over-selection rule —
    the only way a shop is allowed to carry more active invitations than
    required_shoppers (see services/selection.py)."""
    shop = await _require_shop(session, shop_id, user)
    shop.allow_over_selection = body.allow
    await record_audit(
        session,
        action="shop.over_selection_changed",
        actor=user.email,
        entity_type="shop",
        entity_id=str(shop.id),
        summary=f"Over-selection {'enabled' if body.allow else 'disabled'} for {shop.shop_name}",
        meta={"allow_over_selection": body.allow},
    )
    await session.commit()
    return shop_out(shop)


@router.get("/{shop_id}/recommendations")
async def shop_recommendations(
    shop_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    shop = await _require_shop(session, shop_id, user)
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    recommendations = recommend_for_shop(list(shoppers), shop, limit=limit)
    return {
        "shop": shop_out(shop),
        "recommendations": recommendations,
        "count": len(recommendations),
    }


@router.post("/{shop_id}/complete")
async def complete_shop(
    shop_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """ISN-ops-only: confirm a shop visit actually happened (e.g. from SASSIE
    data). Advances the earliest accepted invitation for this shop to
    "completed" and, if the client pledged a bonus for this shop (see
    routers/campaigns.py::set_shop_bonus), awards it to that shopper and
    emails the client a reminder — ShopperMatch never processes the payment
    itself, only tracks the pledge and notifies who it's due to."""
    shop = await _require_shop(session, shop_id, user)
    if shop.status == "completed":
        raise HTTPException(status_code=400, detail="This shop is already marked completed.")

    stmt = (
        select(Invitation)
        .where(Invitation.shop_id == shop_id, Invitation.response == "accepted")
        .order_by(Invitation.responded_at.asc())
        .options(selectinload(Invitation.shopper))
    )
    accepted = (await session.execute(stmt)).scalars().first()
    if accepted is None:
        raise HTTPException(
            status_code=400,
            detail="No shopper has accepted this shop yet — nothing to mark as completed.",
        )

    shop.status = "completed"
    advance_status(accepted, InvitationStatus.COMPLETED)
    await add_event(
        session,
        accepted,
        EventType.ASSIGNMENT_COMPLETED,
        {"shop": shop.shop_name, "actor": user.email},
    )

    bonus = (
        await session.execute(select(ShopBonus).where(ShopBonus.shop_id == shop_id))
    ).scalar_one_or_none()
    reminder_sent = False
    if bonus is not None and bonus.completed_at is None:
        bonus.completed_at = utcnow()
        bonus.awarded_invitation_id = accepted.id
        bonus.awarded_shopper_name = accepted.shopper.name if accepted.shopper else None

        recipients = (
            await session.execute(
                select(User.email).where(User.role == "client", User.client_id == shop.campaign.client_id)
            )
        ).scalars().all()
        shopper_name = bonus.awarded_shopper_name or "The shopper"
        subject = f"Bonus due — {shop.shop_name} ({shop.campaign.name})"
        text = (
            f"{shopper_name} has completed the mystery shop at {shop.shop_name} ({shop.campaign.name}). "
            f"A bonus of {bonus.currency} {bonus.amount} was pledged for this shop and is now due. "
            "ShopperMatch.AI does not process this payment — please arrange it directly with the shopper "
            "outside the platform."
        )
        html = (
            f"<p>{shopper_name} has completed the mystery shop at <strong>{shop.shop_name}</strong> "
            f"({shop.campaign.name}).</p>"
            f"<p>A bonus of <strong>{bonus.currency} {bonus.amount}</strong> was pledged for this shop and "
            "is now due.</p>"
            "<p>ShopperMatch.AI does not process this payment — please arrange it directly with the "
            "shopper outside the platform.</p>"
        )
        for email in recipients:
            await send_email({"to": email, "subject": subject, "text": text, "html": html})
        if recipients:
            reminder_sent = True
            bonus.reminder_sent_at = utcnow()
        await add_event(
            session,
            accepted,
            EventType.BONUS_REMINDER_SENT,
            {"amount": bonus.amount, "currency": bonus.currency, "recipients": recipients},
        )

    await record_audit(
        session,
        action="shop.completed",
        actor=user.email,
        entity_type="shop",
        entity_id=str(shop.id),
        summary=(
            f"{user.email} marked {shop.shop_name} completed"
            + (f" — bonus reminder sent for {bonus.currency} {bonus.amount}" if reminder_sent else "")
        ),
        meta={"shop": shop.shop_name, "invitation_id": str(accepted.id)},
    )
    await session.commit()
    return {
        "shop": shop_out(shop, bonus=bonus),
        "invitation_id": str(accepted.id),
        "bonus_reminder_sent": reminder_sent,
    }
