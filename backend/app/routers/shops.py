"""Shop endpoints + per-shop recommendations."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_operator
from ..models import Campaign, Shop, Shopper, User
from ..serializers import shop_out
from ..services.audit import record_audit
from ..services.recommendation import recommend_for_shop
from ..services.selection import active_invitation_count
from ..services.tenancy import enforce_campaign_access

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
    return {"items": [shop_out(s) for s in shops], "total": len(shops)}


@router.get("/{shop_id}")
async def get_shop(
    shop_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    shop = await _require_shop(session, shop_id, user)
    data = shop_out(shop)
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
