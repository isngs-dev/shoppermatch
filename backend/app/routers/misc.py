"""Audit logs, insights, integrations and settings endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import require_admin
from ..models import AuditLog, Shopper, User
from ..serializers import audit_out
from ..services.analytics import compute_summary
from ..services.insights import generate_insights
from ..services.outbox import sent_count_last_24h

router = APIRouter(prefix="/api", tags=["Insights & Admin"])


@router.get("/audit-logs")
async def audit_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    logs = (await session.execute(stmt)).scalars().all()
    return {"items": [audit_out(a) for a in logs], "total": len(logs)}


@router.get("/insights")
async def insights(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    summary = await compute_summary(session)
    rows = (
        await session.execute(
            select(Shopper.city, func.count(Shopper.id))
            .where(Shopper.active.is_(True))
            .group_by(Shopper.city)
        )
    ).all()
    city_coverage = {(city or "Unknown"): int(count) for city, count in rows}
    return {
        "insights": generate_insights(summary, city_coverage),
        "city_coverage": city_coverage,
        "summary": summary,
    }


# Integration management (SASSIE, Email, SMS, Google Maps, AI) moved to
# routers/integrations.py — real DB-backed config/status/test/sync, not this
# hardcoded list.


@router.get("/settings")
async def get_settings_endpoint(_: User = Depends(require_admin)):
    """Non-secret configuration surfaced to the admin UI."""
    return {
        "app_name": settings.app_name,
        "tagline": settings.app_tagline,
        "environment": settings.environment,
        "public_base_url": settings.public_base_url,
        "email_provider": settings.email_provider,
        "email_from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "database": "postgresql" if not settings.is_sqlite else "sqlite (local fallback)",
        "tracking_rate_limit_per_minute": settings.tracking_rate_limit_per_minute,
        "cors_origins": settings.cors_origin_list,
        "bulk_email_batch_size": settings.bulk_email_batch_size,
        "bulk_email_daily_limit": settings.bulk_email_daily_limit,
        "bulk_email_batch_delay_seconds": settings.bulk_email_batch_delay_seconds,
        "emails_sent_last_24h": await sent_count_last_24h(),
    }
