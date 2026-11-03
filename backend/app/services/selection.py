"""Over-selection guard — shared by every path that creates invitations for a
shop (AI recommendation approval, single invitation, bulk invitations), so
the rule can never be bypassed by going through a different entry point.

Default: a shop cannot have more active (non-declined) invitations than its
required_shoppers. A decline frees the slot back up. An admin/client can
explicitly allow over-selection per shop for backup candidates.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Invitation, Shop


async def active_invitation_count(session: AsyncSession, shop_id) -> int:
    """Invitations still 'in play' for a shop — everything except a decline."""
    return (
        await session.scalar(
            select(func.count(Invitation.id)).where(
                Invitation.shop_id == shop_id,
                func.coalesce(Invitation.response, "") != "declined",
            )
        )
        or 0
    )


async def active_shopper_ids(session: AsyncSession, shop_id) -> set:
    """Shoppers who already hold a live (non-declined) invitation for this shop."""
    rows = await session.execute(
        select(Invitation.shopper_id).where(
            Invitation.shop_id == shop_id,
            func.coalesce(Invitation.response, "") != "declined",
        )
    )
    return {r[0] for r in rows}


def mark_recommended(recs: list[dict], invited_ids: set, slots: int) -> list[dict]:
    """Flags exactly `slots` candidates as the AI's recommendation for a shop: the best-ranked ones that
    aren't already invited. Everyone else stays in the list as an optional extra (over-selection)."""
    left = max(0, slots)
    invited = {str(i) for i in invited_ids}
    for r in recs:
        already = r["shopper_id"] in invited
        r["already_invited"] = already
        r["recommended"] = bool(left) and not already
        if r["recommended"]:
            left -= 1
    return recs


async def enforce_over_selection(session: AsyncSession, shop: Shop, additional: int) -> None:
    """Raises 409 if adding `additional` more invitations would exceed
    shop.required_shoppers and the shop hasn't opted into over-selection."""
    if shop.allow_over_selection or additional <= 0:
        return
    current = await active_invitation_count(session, shop.id)
    if current + additional > shop.required_shoppers:
        remaining = max(0, shop.required_shoppers - current)
        raise HTTPException(
            status_code=409,
            detail=(
                f"{shop.shop_name} requires {shop.required_shoppers} shopper(s) — "
                f"{current} already selected, so only {remaining} more can be added "
                f"(you tried to add {additional}). Enable over-selection for this shop "
                "if you intentionally want backup candidates."
            ),
        )
