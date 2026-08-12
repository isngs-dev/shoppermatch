"""Convenience recommendations endpoint for the Recommendations page.

Picks a shop (explicit ?shop_id or the first open shop) and returns explainable
match scores for every active shopper.
"""
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

router = APIRouter(prefix="/api/recommendations", tags=["Recommendations"])


@router.get("")
async def recommendations(
    shop_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    if shop_id is not None:
        shop = await session.get(Shop, shop_id)
    else:
        shop = (
            await session.execute(select(Shop).where(Shop.status == "open").limit(1))
        ).scalar_one_or_none()
        if shop is None:
            shop = (await session.execute(select(Shop).limit(1))).scalar_one_or_none()

    if shop is None:
        raise HTTPException(status_code=404, detail="No shops available")

    shoppers = (await session.execute(select(Shopper))).scalars().all()
    return {
        "shop": shop_out(shop),
        "recommendations": recommend_for_shop(list(shoppers), shop, limit=limit),
    }
