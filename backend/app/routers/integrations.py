"""Integration Management Hub: SASSIE, Email, SMS, Google Maps, AI.

Architecture:

    FastAPI Router -> IntegrationConfig (PostgreSQL) -> per-provider service/client -> external API

Every status shown to the UI is either a stored result of an explicit Test
Connection / Sync (network calls are never made just to render a list page)
or a live, local "is this even configured" check — never a hardcoded
"connected" string.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import require_admin
from ..models import IntegrationConfig, IntegrationStatus, SyncLog, User
from ..serializers import integration_out, sync_log_out
from ..services.audit import record_audit
from ..services.integrations.sassie import get_sassie_client, run_sync

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

DEFAULT_INTEGRATIONS = [
    {"provider": "sassie", "display_name": "SASSIE", "description": "Mystery shopping data synchronization"},
    {"provider": "email", "display_name": "Email", "description": "Email delivery and outreach"},
    {"provider": "sms", "display_name": "SMS", "description": "SMS notifications and outreach"},
    {"provider": "maps", "display_name": "Google Maps", "description": "Location and distance services"},
    {"provider": "ai", "display_name": "AI", "description": "AI-powered shopper matching"},
]


async def _ensure_defaults(session: AsyncSession) -> None:
    existing = {p for (p,) in (await session.execute(select(IntegrationConfig.provider))).all()}
    for item in DEFAULT_INTEGRATIONS:
        if item["provider"] in existing:
            continue
        session.add(
            IntegrationConfig(
                provider=item["provider"],
                display_name=item["display_name"],
                status=IntegrationStatus.CONFIGURATION_REQUIRED,
                configuration={"description": item["description"]},
            )
        )
    await session.commit()


async def _get_or_404(session: AsyncSession, provider: str) -> IntegrationConfig:
    cfg = (
        await session.execute(select(IntegrationConfig).where(IntegrationConfig.provider == provider))
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown integration '{provider}'")
    return cfg


def _live_status_override(cfg: IntegrationConfig) -> str:
    """Cheap, local, no-network check: if required config is plainly
    missing, always show CONFIGURATION_REQUIRED regardless of the last
    stored test result (config may have been cleared since)."""
    provider = cfg.provider
    conf = cfg.configuration or {}
    has_secret = bool(cfg.secret_config)

    if provider == "sassie":
        return cfg.status  # demo adapter always usable — never configuration_required
    if provider == "email":
        configured = settings.email_provider != "mock" or has_secret
        return cfg.status if configured else IntegrationStatus.CONFIGURATION_REQUIRED
    if provider == "ai":
        return cfg.status  # local engine is always usable
    if provider == "maps":
        configured = bool(settings.google_maps_api_key) or has_secret
        return cfg.status if configured else IntegrationStatus.CONFIGURATION_REQUIRED
    if provider == "sms":
        configured = bool(conf.get("sms_provider") or settings.sms_provider) and has_secret
        return cfg.status if configured else IntegrationStatus.CONFIGURATION_REQUIRED
    return cfg.status


@router.get("")
async def list_integrations(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    await _ensure_defaults(session)
    rows = (await session.execute(select(IntegrationConfig).order_by(IntegrationConfig.provider))).scalars().all()
    out = []
    for cfg in rows:
        data = integration_out(cfg)
        data["status"] = _live_status_override(cfg)
        out.append(data)
    return {"items": out, "total": len(out)}


@router.get("/sync-logs")
async def list_sync_logs(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    rows = (
        await session.execute(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(50))
    ).scalars().all()
    return {"items": [sync_log_out(r) for r in rows], "total": len(rows)}


@router.get("/{provider}")
async def get_integration(
    provider: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    await _ensure_defaults(session)
    cfg = await _get_or_404(session, provider)
    data = integration_out(cfg)
    data["status"] = _live_status_override(cfg)
    return data


class ConfigureRequest(BaseModel):
    configuration: dict = {}
    secrets: dict = {}  # write-only; never echoed back
    enabled: bool | None = None


@router.put("/{provider}/config")
async def update_integration_config(
    provider: str,
    body: ConfigureRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    await _ensure_defaults(session)
    cfg = await _get_or_404(session, provider)

    cfg.configuration = {**(cfg.configuration or {}), **body.configuration}
    if body.secrets:
        cfg.secret_config = {**(cfg.secret_config or {}), **{k: v for k, v in body.secrets.items() if v}}
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if cfg.status == IntegrationStatus.CONFIGURATION_REQUIRED and (cfg.configuration or cfg.secret_config):
        cfg.status = IntegrationStatus.DISCONNECTED  # configured, but not yet tested

    await record_audit(
        session,
        action=f"integration.{provider}.configured",
        actor=user.email,
        entity_type="integration",
        entity_id=provider,
        summary=f"{cfg.display_name} configuration updated",
        meta={"fields": list(body.configuration.keys()), "secrets_updated": list(body.secrets.keys())},
    )
    await session.commit()

    data = integration_out(cfg)
    data["status"] = _live_status_override(cfg)
    return data


# --------------------------------------------------------------------------- #
# Test connection — one handler per provider, each doing a REAL check.
# --------------------------------------------------------------------------- #
@router.post("/{provider}/test")
async def test_integration(
    provider: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    await _ensure_defaults(session)
    cfg = await _get_or_404(session, provider)

    if provider == "sassie":
        client = get_sassie_client({**cfg.configuration, "_secret_api_key": cfg.secret_config.get("api_key")})
        result = await client.test_connection()
        using_demo = not (cfg.configuration.get("api_base_url") or settings.sassie_api_base_url)
        cfg.status = IntegrationStatus.DEMO if (result["connected"] and using_demo) else (
            IntegrationStatus.CONNECTED if result["connected"] else IntegrationStatus.ERROR
        )
        cfg.last_error = None if result["connected"] else result.get("detail")

    elif provider == "email":
        if settings.email_provider == "sendgrid" and settings.sendgrid_api_key:
            import httpx

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://api.sendgrid.com/v3/scopes",
                        headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                    )
                result = {"connected": resp.status_code == 200, "detail": "SendGrid API key is valid." if resp.status_code == 200 else resp.text[:300]}
            except Exception as exc:  # noqa: BLE001
                result = {"connected": False, "detail": f"Could not reach SendGrid: {exc}"}
            cfg.status = IntegrationStatus.CONNECTED if result["connected"] else IntegrationStatus.ERROR
        elif settings.email_provider == "mock":
            result = {"connected": False, "detail": "Email integration is not configured (EMAIL_PROVIDER=mock)."}
            cfg.status = IntegrationStatus.CONFIGURATION_REQUIRED
        else:
            result = {"connected": True, "detail": f"Provider '{settings.email_provider}' is configured (no live health-check implemented for it)."}
            cfg.status = IntegrationStatus.CONNECTED
        cfg.last_error = None if result["connected"] else result.get("detail")

    elif provider == "ai":
        from ..services.semantic_matching import embed

        vec = embed("connection self-test")
        ok = len(vec) > 0
        result = {
            "connected": ok,
            "detail": "Local semantic matching engine responding. This app's recommendation engine is rule-based + local, not an external AI API call.",
        }
        cfg.status = IntegrationStatus.DEMO if ok else IntegrationStatus.ERROR
        cfg.last_error = None if ok else "Local matching engine failed to produce an embedding."

    elif provider == "maps":
        key = cfg.secret_config.get("api_key") or settings.google_maps_api_key
        if not key:
            result = {"connected": False, "detail": "Google Maps API key is not configured."}
            cfg.status = IntegrationStatus.CONFIGURATION_REQUIRED
        else:
            import httpx

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://maps.googleapis.com/maps/api/geocode/json",
                        params={"address": "Mumbai, India", "key": key},
                    )
                body = resp.json() if resp.status_code == 200 else {}
                ok = body.get("status") == "OK"
                result = {"connected": ok, "detail": "Geocoding API key is valid." if ok else f"Google Maps responded: {body.get('status', resp.status_code)}"}
            except Exception as exc:  # noqa: BLE001
                result = {"connected": False, "detail": f"Could not reach Google Maps: {exc}"}
            cfg.status = IntegrationStatus.CONNECTED if result["connected"] else IntegrationStatus.ERROR
        cfg.last_error = None if result["connected"] else result.get("detail")

    elif provider == "sms":
        result = {"connected": False, "detail": "No SMS provider is implemented in this project yet — configure one to enable this integration."}
        cfg.status = IntegrationStatus.CONFIGURATION_REQUIRED
        cfg.last_error = result["detail"]

    else:
        raise HTTPException(status_code=404, detail=f"Unknown integration '{provider}'")

    cfg.last_tested_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        action=f"integration.{provider}.tested",
        actor=user.email,
        entity_type="integration",
        entity_id=provider,
        summary=f"{cfg.display_name} connection tested: {cfg.status}",
        meta={"connected": result["connected"], "detail": result.get("detail")},
    )
    await session.commit()

    return {"connected": result["connected"], "status": cfg.status, "message": result.get("detail")}


class SendTestEmailRequest(BaseModel):
    test_email: EmailStr


@router.post("/email/test-send")
async def send_test_email(
    body: SendTestEmailRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    from ..services.email import send_email

    message = {
        "from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "to": str(body.test_email),
        "subject": "ShopperMatch.AI — Email integration test",
        "html": "<p>This is a test email from the ShopperMatch.AI Integration Management Hub.</p>",
        "text": "This is a test email from the ShopperMatch.AI Integration Management Hub.",
    }
    result = await send_email(message)

    await record_audit(
        session,
        action="integration.email.test_send",
        actor=user.email,
        entity_type="integration",
        entity_id="email",
        summary=f"Email integration test send to {body.test_email}",
        meta={"provider": result.get("provider"), "delivered": result.get("delivered")},
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# SASSIE synchronization
# --------------------------------------------------------------------------- #
@router.post("/sassie/sync")
async def start_sassie_sync(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    await _ensure_defaults(session)
    cfg = await _get_or_404(session, "sassie")

    log = SyncLog(provider="sassie", status="running")
    session.add(log)
    await session.flush()

    await record_audit(
        session,
        action="integration.sassie.sync_started",
        actor=user.email,
        entity_type="sync_log",
        entity_id=str(log.id),
        summary="SASSIE synchronization started",
        meta={},
    )
    await session.commit()

    client = get_sassie_client({**cfg.configuration, "_secret_api_key": cfg.secret_config.get("api_key")})
    try:
        await run_sync(session, client, log)
        log.status = "partial" if log.errors else "success"
    except Exception as exc:  # noqa: BLE001 — never fail silently, record it
        log.status = "failed"
        log.error_message = str(exc)[:1000]

    log.completed_at = datetime.now(timezone.utc)
    cfg.last_sync_at = log.completed_at
    if log.status == "failed":
        cfg.last_error = log.error_message

    await record_audit(
        session,
        action=f"integration.sassie.sync_{log.status}",
        actor=user.email,
        entity_type="sync_log",
        entity_id=str(log.id),
        summary=(
            f"SASSIE synchronization {log.status}: "
            f"{log.campaigns_created + log.campaigns_updated} campaigns, "
            f"{log.shops_created + log.shops_updated} shops, "
            f"{log.shoppers_created + log.shoppers_updated} shoppers"
        ),
        meta={"sync_id": str(log.id), "status": log.status},
    )
    await session.commit()

    return sync_log_out(log)
