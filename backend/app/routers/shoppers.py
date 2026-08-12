"""Shopper endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import get_current_user
from ..models import Shopper, User
from ..serializers import shopper_out

router = APIRouter(prefix="/api/shoppers", tags=["Shoppers"])


@router.get("")
async def list_shoppers(
    q: str | None = Query(default=None, description="Search by name / email / city"),
    availability: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
):
    shopper = await session.get(Shopper, shopper_id)
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")
    return shopper_out(shopper)


# Small helper so search works case-insensitively on both SQLite and Postgres.
from sqlalchemy import func  # noqa: E402


def func_lower(column):
    return func.lower(column)
