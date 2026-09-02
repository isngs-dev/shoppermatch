"""AI Voice Call Follow-Up webhooks — /api/voice-calls/*.

Public routes Twilio itself calls (no bearer auth possible — Twilio is an
external server, not a logged-in browser), verified instead via Twilio's own
request-signature scheme (services/voice_call.py::verify_twilio_signature),
same "public but signature-verified" posture as routers/webhooks.py's
SendGrid endpoint.

Client-facing (authenticated) endpoints for viewing call outcomes/transcripts
live at the bottom.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_operator
from ..models import EmailAutomation, ShopperAutomationState, User, VoiceCallLog
from ..serializers import iso
from ..services.tenancy import enforce_campaign_access
from ..services.tracking import now
from ..services.voice_call import twiml_say_gather, verify_twilio_signature
from ..services.voice_call_ai import next_turn, opening_line

router = APIRouter(prefix="/api/voice-calls", tags=["AI Voice Call Follow-Up"])


async def _verify_request(request: Request) -> dict:
    form = await request.form()
    params = dict(form)
    signature = request.headers.get("x-twilio-signature")
    if not verify_twilio_signature(str(request.url), params, signature):
        raise HTTPException(status_code=401, detail="Invalid Twilio webhook signature")
    return params


async def _latest_call_log(session: AsyncSession, state_id: uuid.UUID) -> VoiceCallLog | None:
    stmt = (
        select(VoiceCallLog)
        .where(VoiceCallLog.automation_state_id == state_id)
        .order_by(VoiceCallLog.attempted_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _xml(body: str) -> Response:
    return Response(content=body, media_type="text/xml")


# --------------------------------------------------------------------------- #
# Twilio webhooks (public, signature-verified)
# --------------------------------------------------------------------------- #
@router.post("/twiml/{state_id}", include_in_schema=False)
async def call_connected(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Twilio fetches this the instant the call connects — the opening line."""
    await _verify_request(request)
    stmt = (
        select(ShopperAutomationState)
        .where(ShopperAutomationState.id == state_id)
        .options(
            selectinload(ShopperAutomationState.shopper),
            selectinload(ShopperAutomationState.shop),
            selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.campaign),
        )
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is None:
        return _xml('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')

    shop = state.shop or state.automation.shop
    greeting = opening_line(
        state.shopper.name if state.shopper else "there",
        shop.shop_name if shop else "this opportunity",
        state.automation.campaign.name if state.automation.campaign else "",
    )
    gather_url = f"{request.url.scheme}://{request.url.netloc}/api/voice-calls/gather/{state_id}"
    return _xml(twiml_say_gather(greeting, gather_url))


@router.post("/gather/{state_id}", include_in_schema=False)
async def call_gather(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Twilio POSTs here after each <Gather> completes, with SpeechResult
    holding what it transcribed. One GPT turn, then either another Gather or
    a Hangup once conclude_call fires."""
    params = await _verify_request(request)
    stmt = (
        select(ShopperAutomationState)
        .where(ShopperAutomationState.id == state_id)
        .options(
            selectinload(ShopperAutomationState.shopper),
            selectinload(ShopperAutomationState.shop),
            selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.campaign),
            selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.shop),
        )
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is None:
        return _xml('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')

    log = await _latest_call_log(session, state_id)
    speech = (params.get("SpeechResult") or "").strip()
    shop = state.shop or state.automation.shop
    campaign = state.automation.campaign

    history: list[dict[str, str]] = []
    if log and log.transcript:
        history = [{"role": t["role"], "content": t["text"]} for t in log.transcript]
    if speech:
        history.append({"role": "user", "content": speech})
        if log:
            log.transcript = [*(log.transcript or []), {"role": "user", "text": speech}]

    turn = await next_turn(
        history=history,
        shopper_name=state.shopper.name if state.shopper else "there",
        shop_name=shop.shop_name if shop else "this opportunity",
        campaign_name=campaign.name if campaign else "",
        compensation=(f"{shop.currency} {shop.compensation}" if shop and shop.compensation else "detailed in your email"),
    )

    if log:
        log.transcript = [*(log.transcript or []), {"role": "assistant", "text": turn["say"]}]

    if turn["outcome"]:
        state.voice_call_outcome = turn["outcome"]
        state.voice_call_status = "completed"
        if log:
            log.status = "completed"
            log.outcome = turn["outcome"]
            log.ended_at = now()
        await session.commit()
        return _xml(twiml_say_gather(turn["say"], "", hang_up_after=True))

    await session.commit()
    gather_url = f"{request.url.scheme}://{request.url.netloc}/api/voice-calls/gather/{state_id}"
    return _xml(twiml_say_gather(turn["say"], gather_url))


@router.post("/status/{state_id}", include_in_schema=False)
async def call_status(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Twilio's call-completed status callback — the only reliable signal
    for calls that never connected at all (no-answer/busy/failed), which
    /gather never sees since no <Gather> ever ran."""
    params = await _verify_request(request)
    call_status_value = params.get("CallStatus", "")
    duration = params.get("CallDuration")

    stmt = (
        select(ShopperAutomationState)
        .where(ShopperAutomationState.id == state_id)
        .options(selectinload(ShopperAutomationState.automation))
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is None:
        return Response(status_code=204)

    log = await _latest_call_log(session, state_id)
    if log:
        log.status = call_status_value or log.status
        log.ended_at = now()
        if duration:
            try:
                log.duration_seconds = int(duration)
            except ValueError:
                pass

    # Only overwrite state if the conversation itself hasn't already
    # concluded (voice_call_status == "completed", set in /gather) — a
    # late-arriving status callback for a call that already got a real
    # outcome must never clobber it back to "no_answer".
    if state.voice_call_status == "calling":
        if call_status_value == "completed":
            # Connected, ended, but /gather never got a conclude_call — the
            # shopper likely just hung up. Not a failure, just inconclusive.
            state.voice_call_status = "completed"
            state.voice_call_outcome = state.voice_call_outcome or "undecided"
        else:
            # no-answer | busy | failed | canceled
            if state.voice_call_attempts >= state.automation.voice_call_max_attempts:
                state.voice_call_status = "failed"
            else:
                state.voice_call_status = "no_answer"
                state.voice_call_next_at = now() + timedelta(days=state.automation.voice_call_retry_gap_days)
    await session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Client-facing: view call outcomes/transcripts for one automation
# --------------------------------------------------------------------------- #
@router.get("/automations/{automation_id}")
async def list_voice_calls_for_automation(
    automation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    from ..services import automation as engine

    automation = await engine.load_automation(session, automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    enforce_campaign_access(automation.campaign, user)

    stmt = (
        select(VoiceCallLog)
        .join(ShopperAutomationState, VoiceCallLog.automation_state_id == ShopperAutomationState.id)
        .where(ShopperAutomationState.automation_id == automation_id)
        .order_by(VoiceCallLog.attempted_at.desc())
        .options(selectinload(VoiceCallLog.automation_state).selectinload(ShopperAutomationState.shopper))
    )
    logs = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(l.id),
                "automation_state_id": str(l.automation_state_id),
                "shopper_name": l.automation_state.shopper.name if l.automation_state and l.automation_state.shopper else None,
                "status": l.status,
                "outcome": l.outcome,
                "attempted_at": iso(l.attempted_at),
                "ended_at": iso(l.ended_at),
                "duration_seconds": l.duration_seconds,
                "transcript": l.transcript or [],
                "error_message": l.error_message,
            }
            for l in logs
        ]
    }
