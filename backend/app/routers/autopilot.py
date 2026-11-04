"""AI Autopilot endpoints — configure it (per campaign, or as a default for every campaign of a client), preview
what it would do, and run it. The work itself lives in services/autopilot.py."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import require_operator
from ..models import AutopilotSetting, Campaign, Client, User
from ..serializers import iso
from ..services.audit import record_audit
from ..services.autopilot import MODES, load_scopes, resolve_guardrails, run_autopilot
from ..services.tenancy import enforce_campaign_access

router = APIRouter(prefix="/api/autopilot", tags=["AI Autopilot"])

_CONFIG_FIELDS = (
    "mode",
    "max_radius_km",
    "max_bonus_multiplier",
    "min_match_score",
    "max_invitations_per_run",
    "fill_every_shop",
    "max_shops_per_shopper",
)


class AutopilotConfigIn(BaseModel):
    """Only the fields present in the request are changed; a field sent as null goes back to inheriting."""

    mode: str | None = Field(default=None, description="off | review | auto")
    max_radius_km: float | None = Field(default=None, gt=0, le=500)
    max_bonus_multiplier: float | None = Field(default=None, ge=0, le=5)
    min_match_score: int | None = Field(default=None, ge=0, le=100)
    max_invitations_per_run: int | None = Field(default=None, ge=1, le=1000)
    fill_every_shop: bool | None = Field(default=None, description="Keep going past the limits until every shop is full")
    max_shops_per_shopper: int | None = Field(default=None, ge=1, le=20)


class RunIn(BaseModel):
    dry_run: bool = True
    mode: str | None = Field(default=None, description="Run once in this mode instead of the configured one")


def _row_json(row: AutopilotSetting | None) -> dict | None:
    if row is None:
        return None
    return {name: getattr(row, name) for name in _CONFIG_FIELDS} | {
        "updated_by": row.updated_by,
        "updated_at": iso(row.updated_at),
    }


def _validate(body: AutopilotConfigIn) -> None:
    if "mode" in body.model_fields_set and body.mode is not None and body.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")


def _apply(row: AutopilotSetting, body: AutopilotConfigIn, user: User) -> None:
    for name in body.model_fields_set:
        if name in _CONFIG_FIELDS:
            setattr(row, name, getattr(body, name))
    row.updated_by = user.email


async def _campaign(session: AsyncSession, campaign_id: uuid.UUID, user: User) -> Campaign:
    return enforce_campaign_access(await session.get(Campaign, campaign_id), user)


@router.get("/campaigns/{campaign_id}", summary="Get a campaign's AI Autopilot settings and last run report")
async def get_campaign_autopilot(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = await _campaign(session, campaign_id, user)
    camp, client, glob = await load_scopes(session, campaign)
    guard = await resolve_guardrails(session, campaign)
    return {
        "campaign_id": str(campaign.id),
        "effective": guard.as_dict(),
        "campaign_override": _row_json(camp),
        "client_default": _row_json(client),
        "global_default": _row_json(glob),
        "last_run_at": iso(camp.last_run_at) if camp else None,
        "last_report": camp.last_report if camp else None,
    }


@router.put("/campaigns/{campaign_id}", summary="Set a campaign's AI Autopilot mode and limits (off, review or auto)")
async def set_campaign_autopilot(
    campaign_id: uuid.UUID,
    body: AutopilotConfigIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = await _campaign(session, campaign_id, user)
    _validate(body)
    row = await session.scalar(select(AutopilotSetting).where(AutopilotSetting.campaign_id == campaign.id))
    if row is None:
        row = AutopilotSetting(campaign_id=campaign.id, client_id=campaign.client_id)
        session.add(row)
    _apply(row, body, user)
    await session.flush()
    guard = await resolve_guardrails(session, campaign)
    await record_audit(
        session,
        action="autopilot.configured",
        actor=user.email,
        entity_type="campaign",
        entity_id=str(campaign.id),
        summary=f"{user.email} set AI Autopilot for {campaign.name} to {guard.mode}",
        meta={k: v for k, v in body.model_dump(exclude_unset=True).items()},
    )
    await session.commit()
    return {"effective": guard.as_dict(), "campaign_override": _row_json(row)}


async def _default_row(session: AsyncSession, user: User, client_id: uuid.UUID | None) -> tuple[AutopilotSetting | None, uuid.UUID | None]:
    """The default-settings row a user edits: a client user edits their own client's; an admin edits a given
    client's, or the global one when no client is given."""
    scope_client = user.client_id if user.role == "client" else client_id
    if user.role == "client" and scope_client is None:
        raise HTTPException(status_code=403, detail="This account is not linked to a client.")
    if scope_client is not None and user.role != "client":
        if await session.get(Client, scope_client) is None:
            raise HTTPException(status_code=404, detail="Client not found")
    stmt = select(AutopilotSetting).where(AutopilotSetting.campaign_id.is_(None))
    stmt = stmt.where(AutopilotSetting.client_id == scope_client) if scope_client else stmt.where(AutopilotSetting.client_id.is_(None))
    return await session.scalar(stmt), scope_client


@router.get("/defaults", summary="Get the account-wide AI Autopilot default")
async def get_defaults(
    client_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    row, scope = await _default_row(session, user, client_id)
    return {"client_id": str(scope) if scope else None, "default": _row_json(row)}


@router.put("/defaults", summary="Set the AI Autopilot default for all campaigns of the account, including new ones")
async def set_defaults(
    body: AutopilotConfigIn,
    client_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """A default for every campaign of the client — campaigns that already exist and ones added later (including
    those synced in through the API) — unless a campaign has its own override."""
    _validate(body)
    row, scope = await _default_row(session, user, client_id)
    if row is None:
        row = AutopilotSetting(client_id=scope, campaign_id=None)
        session.add(row)
    _apply(row, body, user)
    await record_audit(
        session,
        action="autopilot.defaults_configured",
        actor=user.email,
        entity_type="client",
        entity_id=str(scope) if scope else "global",
        summary=f"{user.email} set the AI Autopilot default to {row.mode or 'inherit'} for {'a client' if scope else 'all clients'}",
        meta={k: v for k, v in body.model_dump(exclude_unset=True).items()},
    )
    await session.commit()
    return {"client_id": str(scope) if scope else None, "default": _row_json(row)}


@router.post("/campaigns/{campaign_id}/run", summary="Preview (dry_run true) or run AI Autopilot for a campaign now")
async def run_campaign_autopilot(
    campaign_id: uuid.UUID,
    body: RunIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Preview (dry run, the default: nothing is written or sent) or run the autopilot for this campaign now."""
    campaign = await _campaign(session, campaign_id, user)
    if body.mode is not None and body.mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(MODES)}")
    report = await run_autopilot(
        session, campaign, actor=user.email, dry_run=body.dry_run, mode=body.mode, trigger="manual"
    )
    if not body.dry_run:
        await session.commit()
    return report
