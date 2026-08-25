"""Email Automation API — client-portal (and admin) endpoints for building,
running and inspecting multi-step outreach sequences. See services/automation.py
for the engine itself; this router is thin: validate, call the service,
serialize, commit.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_operator
from ..models import Campaign, EmailAutomation, Shop, Shopper, ShopperAutomationState, User
from ..serializers import iso
from ..services import automation as engine
from ..services.semantic_matching import run_matching
from ..services.tenancy import enforce_campaign_access

router = APIRouter(prefix="/api/automations", tags=["Email Automation"])


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class AutomationCreate(BaseModel):
    campaign_id: str
    shop_id: str
    name: str = Field(min_length=1, max_length=255)
    step1_template_id: str | None = None
    step2_template_id: str | None = None
    step3_template_id: str | None = None
    wait_days: int = Field(default=2, ge=1, le=14)
    scheduled_start_at: datetime | None = None


class ShoppersIn(BaseModel):
    shopper_ids: list[str] = Field(min_length=1)


class BulkStartRequest(BaseModel):
    campaign_ids: list[str] = Field(min_length=1)
    shoppers_per_shop: int = Field(default=3, ge=1, le=10)
    # When true, automations for ACTIVE campaigns are started immediately
    # (real emails go out). UPCOMING campaigns are always created as drafts
    # only, never auto-started — matches the standing rule that nothing
    # sends before a campaign's configured start.
    start_immediately: bool = True


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def _state_out(s: ShopperAutomationState) -> dict:
    return {
        "id": str(s.id),
        "shopper_id": str(s.shopper_id),
        "shopper_name": s.shopper.name if s.shopper else None,
        "shopper_email": s.shopper.email if s.shopper else None,
        "current_step": s.current_step,
        "status": s.status,
        "attempt_count": s.attempt_count,
        "next_action_at": iso(s.next_action_at),
        "last_event": s.last_event,
        "last_event_at": iso(s.last_event_at),
        "last_email_sent_at": iso(s.last_email_sent_at),
    }


_ACTIVE_STATES = {"pending", "active"}
_BOUNCED = {"completed_bounced"}
_FAILED = {"completed_failed"}


def _automation_out(a: EmailAutomation, with_states: bool = True) -> dict:
    states = a.shopper_states or []
    dashboard = {
        "total_shoppers": len(states),
        "pending": sum(1 for s in states if s.status == "pending"),
        "active": sum(1 for s in states if s.status == "active"),
        "sent": sum(1 for s in states if s.current_step > 0),
        "accepted_or_declined": sum(1 for s in states if s.status == "completed_response"),
        "interacted": sum(1 for s in states if s.status == "completed_interaction"),
        "no_response": sum(1 for s in states if s.status == "completed_no_response"),
        "bounced": sum(1 for s in states if s.status in _BOUNCED),
        "failed": sum(1 for s in states if s.status in _FAILED),
        "stopped": sum(1 for s in states if s.status == "stopped"),
    }
    out = {
        "id": str(a.id),
        "campaign_id": str(a.campaign_id),
        "campaign_name": a.campaign.name if a.campaign else None,
        "shop_id": str(a.shop_id),
        "shop_name": a.shop.shop_name if a.shop else None,
        "name": a.name,
        "status": a.status,
        "wait_days": a.wait_days,
        "max_steps": a.max_steps,
        "scheduled_start_at": iso(a.scheduled_start_at),
        "step1_template_id": str(a.step1_template_id) if a.step1_template_id else None,
        "step2_template_id": str(a.step2_template_id) if a.step2_template_id else None,
        "step3_template_id": str(a.step3_template_id) if a.step3_template_id else None,
        "step1_template_name": a.step1_template.name if a.step1_template else None,
        "step2_template_name": a.step2_template.name if a.step2_template else None,
        "step3_template_name": a.step3_template.name if a.step3_template else None,
        "created_by": a.created_by,
        "created_at": iso(a.created_at),
        "dashboard": dashboard,
    }
    if with_states:
        out["shoppers"] = [_state_out(s) for s in states]
    return out


async def _load(session: AsyncSession, automation_id: uuid.UUID) -> EmailAutomation:
    a = await engine.load_automation(session, automation_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id")


# --------------------------------------------------------------------------- #
@router.post("")
async def create_automation(
    body: AutomationCreate,
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

    step_ids = {}
    for step, raw in ((1, body.step1_template_id), (2, body.step2_template_id), (3, body.step3_template_id)):
        step_ids[step] = _parse_uuid(raw, f"step{step}_template") if raw else None

    automation = await engine.create_automation(
        session, user, campaign, shop, body.name.strip(), step_ids, body.wait_days, body.scheduled_start_at
    )
    await session.commit()
    automation = await _load(session, automation.id)
    return _automation_out(automation)


@router.post("/bulk-start")
async def bulk_start(
    body: BulkStartRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Client Portal multi-select 'Bulk-start Email Automation'. For every
    selected campaign's shops, runs the existing AI matching engine, takes
    the top N candidates, and creates (+ starts, for active campaigns) one
    automation per shop. Upcoming campaigns get draft automations only —
    never auto-started. Completed/cancelled campaigns are skipped."""
    from .campaigns import status_bucket

    results: list[dict] = []
    for raw_id in body.campaign_ids:
        try:
            campaign_id = uuid.UUID(raw_id)
        except ValueError:
            results.append({"campaign_id": raw_id, "error": "Invalid campaign id"})
            continue
        campaign = await session.get(Campaign, campaign_id)
        try:
            campaign = enforce_campaign_access(campaign, user)
        except HTTPException as exc:
            results.append({"campaign_id": raw_id, "error": exc.detail})
            continue

        bucket = status_bucket(campaign.status)
        if bucket not in ("active", "upcoming"):
            results.append({
                "campaign_id": raw_id, "campaign_name": campaign.name,
                "skipped": True, "reason": f"Campaign is {bucket}, not active or upcoming",
            })
            continue

        shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
        shopper_pool = (await session.execute(select(Shopper))).scalars().all()

        automations_out = []
        for shop in shops:
            match = run_matching(list(shopper_pool), shop, campaign)
            top = [r for r in match["recommendations"] if r["match_score"] > 0][: body.shoppers_per_shop]
            if not top:
                automations_out.append({"shop_name": shop.shop_name, "skipped": True, "reason": "No eligible shoppers found"})
                continue
            automation = await engine.create_automation(
                session, user, campaign, shop, f"{shop.shop_name} — Bulk Automation", {}, 2, None
            )
            shopper_ids = [uuid.UUID(r["shopper_id"]) for r in top]
            await engine.add_shoppers(session, automation, user, shopper_ids)
            started = False
            if body.start_immediately and bucket == "active":
                automation = await _load(session, automation.id)
                await engine.start_automation(session, automation, user)
                started = True
            automations_out.append({
                "automation_id": str(automation.id), "shop_name": shop.shop_name,
                "shopper_count": len(shopper_ids), "started": started,
            })
        await session.commit()
        results.append({"campaign_id": raw_id, "campaign_name": campaign.name, "automations": automations_out})

    return {"results": results}


@router.get("")
async def list_automations(
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = (
        select(EmailAutomation)
        .order_by(EmailAutomation.created_at.desc())
        .options(
            selectinload(EmailAutomation.campaign),
            selectinload(EmailAutomation.shop),
            selectinload(EmailAutomation.step1_template),
            selectinload(EmailAutomation.step2_template),
            selectinload(EmailAutomation.step3_template),
            selectinload(EmailAutomation.shopper_states),
        )
    )
    if campaign_id is not None:
        campaign = await session.get(Campaign, campaign_id)
        enforce_campaign_access(campaign, user)
        stmt = stmt.where(EmailAutomation.campaign_id == campaign_id)
    elif user.role == "client":
        stmt = stmt.join(Campaign, EmailAutomation.campaign_id == Campaign.id).where(Campaign.client_id == user.client_id)

    items = (await session.execute(stmt)).scalars().all()
    return {"items": [_automation_out(a, with_states=False) for a in items], "total": len(items)}


@router.get("/{automation_id}")
async def get_automation(
    automation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    return _automation_out(a)


@router.post("/{automation_id}/shoppers")
async def add_shoppers(
    automation_id: uuid.UUID,
    body: ShoppersIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    if a.status not in ("draft", "paused"):
        raise HTTPException(status_code=409, detail="Shoppers can only be added while the automation is draft or paused.")
    ids = [_parse_uuid(s, "shopper") for s in body.shopper_ids]
    await engine.add_shoppers(session, a, user, ids)
    await session.commit()
    a = await _load(session, automation_id)
    return _automation_out(a)


@router.delete("/{automation_id}/shoppers/{shopper_id}")
async def remove_shopper(
    automation_id: uuid.UUID,
    shopper_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    state = next((s for s in a.shopper_states if s.shopper_id == shopper_id), None)
    if state is None:
        raise HTTPException(status_code=404, detail="Shopper not in this automation")
    if state.current_step > 0:
        raise HTTPException(status_code=409, detail="Cannot remove a shopper who has already been sent an email — stop the automation instead.")
    await session.delete(state)
    await session.commit()
    return {"removed": True}


@router.get("/{automation_id}/preview")
async def preview(
    automation_id: uuid.UUID,
    shopper_id: uuid.UUID,
    step: int = Query(default=1, ge=1, le=3),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    a = await _load(session, automation_id)
    enforce_campaign_access(a.campaign, user)
    shopper = await session.get(Shopper, shopper_id)
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")
    try:
        return await engine.preview_step(a, shopper, step)
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
    return _automation_out(a)


@router.post("/{automation_id}/start")
async def start(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.start_automation)


@router.post("/{automation_id}/pause")
async def pause(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.pause_automation)


@router.post("/{automation_id}/resume")
async def resume(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.resume_automation)


@router.post("/{automation_id}/stop")
async def stop(automation_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_operator)):
    return await _run_action(session, automation_id, user, engine.stop_automation)
