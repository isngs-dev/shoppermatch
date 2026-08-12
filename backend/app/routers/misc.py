"""Audit logs, insights, integrations and settings endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import get_current_user
from ..models import AuditLog, Shopper, User
from ..serializers import audit_out
from ..services.analytics import compute_summary
from ..services.insights import generate_insights

router = APIRouter(prefix="/api", tags=["Insights & Admin"])


@router.get("/audit-logs")
async def audit_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    logs = (await session.execute(stmt)).scalars().all()
    return {"items": [audit_out(a) for a in logs], "total": len(logs)}


@router.get("/insights")
async def insights(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
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


@router.get("/integrations")
async def integrations(_: User = Depends(get_current_user)):
    return {
        "items": [
            {
                "key": "sassie",
                "name": "SASSIE",
                "category": "Data Source",
                "status": "connected",
                "detail": "Shopper roster & shop definitions (synthetic demo feed).",
            },
            {
                "key": "postgres",
                "name": "PostgreSQL",
                "category": "Database",
                "status": "connected" if not settings.is_sqlite else "fallback",
                "detail": "Primary datastore"
                + (" (SQLite fallback active for local demo)." if settings.is_sqlite else "."),
            },
            {
                "key": "email",
                "name": "SendGrid" if settings.email_provider == "sendgrid" else "Mock Email Provider",
                "category": "Email Delivery",
                "status": "connected"
                if settings.email_provider == "sendgrid" and settings.sendgrid_api_key
                else "demo",
                "detail": "Set EMAIL_PROVIDER=sendgrid + SENDGRID_API_KEY to send real email.",
            },
            {
                "key": "redis",
                "name": "Redis",
                "category": "Queue / Cache",
                "status": "optional",
                "detail": "Optional background/event processing. Not required for the demo.",
            },
            {
                "key": "neo4j",
                "name": "Neo4j",
                "category": "Graph",
                "status": "planned",
                "detail": "Future-ready: SHOPPER/SHOP/CAMPAIGN relationships map cleanly to a graph.",
            },
        ]
    }


@router.get("/settings")
async def get_settings_endpoint(_: User = Depends(get_current_user)):
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
    }
