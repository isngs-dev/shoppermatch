"""Shop endpoints + per-shop recommendations."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Shop, Shopper, User
from ..serializers import shop_out
from ..services.recommendation import recommend_for_shop

router = APIRouter(prefix="/api/shops", tags=["Shops"])


@router.get("")
async def list_shops(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(Shop)
    if campaign_id is not None:
        stmt = stmt.where(Shop.campaign_id == campaign_id)
    shops = (await session.execute(stmt)).scalars().all()
    return {"items": [shop_out(s) for s in shops], "total": len(shops)}


@router.get("/{shop_id}")
async def get_shop(
    shop_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    shop = await session.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop_out(shop)


@router.get("/{shop_id}/recommendations")
async def shop_recommendations(
    shop_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    shop = await session.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    recommendations = recommend_for_shop(list(shoppers), shop, limit=limit)
    return {
        "shop": shop_out(shop),
        "recommendations": recommendations,
        "count": len(recommendations),
    }
