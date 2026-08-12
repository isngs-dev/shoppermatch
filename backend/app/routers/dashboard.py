"""Dashboard metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Campaign, Shop, Shopper, User
from ..services.analytics import compute_summary, recent_activity

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/metrics")
async def dashboard_metrics(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    summary = await compute_summary(session)

    total_campaigns = await session.scalar(select(func.count(Campaign.id)))
    active_campaigns = await session.scalar(
        select(func.count(Campaign.id)).where(Campaign.status == "active")
    )
    total_shoppers = await session.scalar(select(func.count(Shopper.id)))
    active_shoppers = await session.scalar(
        select(func.count(Shopper.id)).where(Shopper.active.is_(True))
    )
    total_shops = await session.scalar(select(func.count(Shop.id)))
    open_shops = await session.scalar(
        select(func.count(Shop.id)).where(Shop.status == "open")
    )

    return {
        "outreach": summary,
        "counts": {
            "campaigns": int(total_campaigns or 0),
            "active_campaigns": int(active_campaigns or 0),
            "shoppers": int(total_shoppers or 0),
            "active_shoppers": int(active_shoppers or 0),
            "shops": int(total_shops or 0),
            "open_shops": int(open_shops or 0),
        },
        "recent_activity": await recent_activity(session, limit=12),
    }
