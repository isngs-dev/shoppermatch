"""Batch (wave) Automation API — separate module from /api/automations (the
3-step reminder sequence engine). See services/batch_automation.py for the
engine; this router is thin: validate, call the service, serialize, commit.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import require_operator
from ..models import BatchAutomation, Campaign, Shop, User
from ..serializers import iso
from ..services import batch_automation as engine
from ..services.tenancy import enforce_campaign_access

router = APIRouter(prefix="/api/batch-automations", tags=["Batch Automation"])


class BatchAutomationCreate(BaseModel):
    campaign_id: str
    shop_id: str
    name: str = Field(min_length=1, max_length=255)
    template_id: str | None = None
    batch_size: int = Field(default=10, ge=1, le=200)
    wait_days: int = Field(default=2, ge=1, le=30)
    total_iterations: int = Field(default=3, ge=1, le=20)
    scheduled_start_at: datetime | None = None


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id")


def _out(a: BatchAutomation) -> dict:
    remaining = max(0, len(a.candidate_shopper_ids) - len(a.sent_shopper_ids))
    return {
        "id": str(a.id),
        "campaign_id": str(a.campaign_id),
        "campaign_name": a.campaign.name if a.campaign else None,
        "shop_id": str(a.shop_id),
        "shop_name": a.shop.shop_name if a.shop else None,
        "name": a.name,
        "status": a.status,
        "template_id": str(a.template_id) if a.template_id else None,
        "template_name": a.template.name if a.template else None,
        "batch_size": a.batch_size,
        "wait_days": a.wait_days,
        "total_iterations": a.total_iterations,
        "current_iteration": a.current_iteration,
        "candidate_count": len(a.candidate_shopper_ids),
        "sent_count": len(a.sent_shopper_ids),
        "remaining_count": remaining,
        "next_run_at": iso(a.next_run_at),
        "scheduled_start_at": iso(a.scheduled_start_at),
        "created_by": a.created_by,
        "created_at": iso(a.created_at),
        "started_at": iso(a.started_at),
        "completed_at": iso(a.completed_at),
    }


async def _load(session: AsyncSession, automation_id: uuid.UUID) -> BatchAutomation:
    a = await engine.load_batch_automation(session, automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Batch automation not found")
    return a


@router.post("")
async def create_batch_automation(
    body: BatchAutomationCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    from .campaigns import status_bucket

    campaign = await session.get(Campaign, _parse_uuid(body.campaign_id, "campaign"))
    campaign = enforce_campaign_access(campaign, user)
    if status_bucket(campaign.status) not in ("active", "upcoming"):
        raise HTTPException(status_code=400, detail="Outreach is closed for completed/cancelled campaigns")
    shop = await session.get(Shop, _parse_uuid(body.shop_id, "shop"))
    if shop is None or shop.campaign_id != campaign.id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")
    template_id = _parse_uuid(body.template_id, "template") if body.template_id else None

    automation = await engine.create_batch_automation(
        session, user, campaign, shop, body.name.strip(), template_id,
        body.batch_size, body.wait_days, body.total_iterations, body.scheduled_start_at,
    )
    await session.commit()
    automation = await _load(session, automation.id)
    return _out(automation)


@router.get("")
async def list_batch_automations(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    from sqlalchemy.orm import selectinload

    stmt = (
        select(BatchAutomation)
        .order_by(BatchAutomation.created_at.desc())
        .options(
            selectinload(BatchAutomation.campaign),
            selectinload(BatchAutomation.shop),
            selectinload(BatchAutomation.template),
        )
    )
    if campaign_id is not None:
        campaign = await session.get(Campaign, campaign_id)
        enforce_campaign_access(campaign, user)
        stmt = stmt.where(BatchAutomation.campaign_id == campaign_id)
    elif user.role == "client":
        stmt = stmt.join(Campaign, BatchAutomation.campaign_id == Campaign.id).where(Campaign.client_id == user.client_id)

    items = (await session.execute(stmt)).scalars().all()
    return {"items": [_out(a) for a in items], "total": len(items)}


@router.get("/{automation_id}")
async def get_batch_automation(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    return _out(a)


@router.get("/{automation_id}/preview")
async def preview_batch_automation(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    try:
        return await engine.preview_batch_email(session, a)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _run_action(session: AsyncSession, automation_id: uuid.UUID, user: User, fn):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    try:
        await fn(session, a, user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await session.commit()
    a = await _load(session, automation_id)
    return _out(a)


@router.post("/{automation_id}/start")
async def start(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.start_batch_automation)


@router.post("/{automation_id}/pause")
async def pause(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.pause_batch_automation)


@router.post("/{automation_id}/resume")
async def resume(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.resume_batch_automation)


@router.post("/{automation_id}/stop")
async def stop(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.stop_batch_automation)
