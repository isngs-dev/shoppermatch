"""AI Voice Call Follow-Up webhooks — /api/voice-calls/*.

Public routes Plivo itself calls (no bearer auth possible — Plivo is an
external server, not a logged-in browser), verified instead via Plivo's own
V3 request-signature scheme (services/voice_call.py::verify_plivo_signature),
same "public but signature-verified" posture as routers/webhooks.py's
SendGrid endpoint.

Client-facing (authenticated) endpoints for viewing call outcomes/transcripts
live at the bottom.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_session
from ..deps import require_operator
from ..models import BulkCallBatch, BulkCallTarget, EmailAutomation, ShopperAutomationState, User, VoiceCallLog
from ..serializers import iso
from ..services.audit import record_audit
from ..services.bulk_voice_call import MAX_BULK_CALL_TARGETS, run_bulk_call_batch
from ..services.tenancy import enforce_campaign_access
from ..services.tracking import now
from ..services.voice_call import create_call, is_configured, plxml_say_gather, verify_plivo_signature
from ..services.voice_call_ai import next_turn, opening_line

router = APIRouter(prefix="/api/voice-calls", tags=["AI Voice Call Follow-Up"])

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


async def _verify_request(request: Request) -> dict:
    form = await request.form()
    params = dict(form)
    signature = request.headers.get("x-plivo-signature-v3")
    nonce = request.headers.get("x-plivo-signature-v3-nonce")
    if not verify_plivo_signature("POST", str(request.url), nonce, signature, params):
        raise HTTPException(status_code=401, detail="Invalid Plivo webhook signature")
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
# Ad-hoc test call — admin-triggered, NOT tied to a shopper/automation record.
# Same "manually verify the integration actually works" purpose as
# routers/integrations.py's POST /email/test-send; places one real outbound
# Plivo call that speaks a message once and hangs up (no AI conversation —
# this checks connectivity/audio, not the GPT turn-taking).
# --------------------------------------------------------------------------- #
class TestCallRequest(BaseModel):
    to_number: str = Field(min_length=8, max_length=20)
    # Falls back to that automation's configured recorded message when given;
    # an explicit `message` always wins over `automation_id`.
    automation_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=1000)


@router.post("/test-call")
async def send_test_call(
    body: TestCallRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    to_number = re.sub(r"[\s\-().]", "", body.to_number)
    # A client that types just digits (no leading "+") is a plain, common
    # slip, not a genuinely malformed number — auto-prepend it rather than
    # bouncing the request back for a one-character fix.
    if to_number and not to_number.startswith("+"):
        to_number = "+" + to_number
    if not _E164.match(to_number):
        raise HTTPException(status_code=400, detail="to_number must be in E.164 format, e.g. +918691969772")

    message = body.message
    if not message and body.automation_id:
        from ..services import automation as engine

        automation = await engine.load_automation(session, body.automation_id)
        if automation is None:
            raise HTTPException(status_code=404, detail="Automation not found")
        enforce_campaign_access(automation.campaign, user)
        message = automation.voice_call_message
    greeting = opening_line("there", "this opportunity", "", message)

    base = settings.public_base_url.rstrip("/")
    answer_url = f"{base}/api/voice-calls/test-answer?message={quote(greeting)}"
    hangup_url = f"{base}/api/voice-calls/test-status"
    call_sid = await create_call(to_number, answer_url, hangup_url)

    await record_audit(
        session,
        action="voice_call.test_call",
        actor=user.email,
        entity_type="voice_call",
        entity_id=call_sid,
        summary=f"Test call placed to {to_number}",
        meta={"to_number": to_number, "message": greeting},
    )
    await session.commit()
    return {"call_sid": call_sid, "to_number": to_number, "message": greeting}


@router.post("/real-test-call/{state_id}")
async def send_real_test_call(
    state_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Places a real call through the exact same webhook flow a scheduled
    voice-call follow-up uses (services/voice_call_scheduler.py::_place_call)
    — it listens for the shopper's spoken reply and has GPT actually respond,
    turn after turn, instead of /test-call's speak-once-and-hang-up. Lets a
    client hear/test the real back-and-forth for one of this automation's
    shoppers right now, without waiting for the email sequence to exhaust
    and the configured delay window to pass."""
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
        raise HTTPException(status_code=404, detail="Shopper not found in this automation")
    enforce_campaign_access(state.automation.campaign, user)
    if not state.automation.voice_call_enabled:
        raise HTTPException(status_code=400, detail="AI Voice Call Follow-Up is not enabled for this automation")
    shopper = state.shopper
    if not shopper or not shopper.phone:
        raise HTTPException(status_code=400, detail="This shopper has no phone number on file")

    base = settings.public_base_url.rstrip("/")
    answer_url = f"{base}/api/voice-calls/answer/{state.id}"
    hangup_url = f"{base}/api/voice-calls/status/{state.id}"
    call_sid = await create_call(shopper.phone, answer_url, hangup_url)

    shop = state.shop or state.automation.shop
    greeting = opening_line(
        shopper.name,
        shop.shop_name if shop else "this opportunity",
        state.automation.campaign.name if state.automation.campaign else "",
        state.automation.voice_call_message,
    )
    log = VoiceCallLog(
        automation_state_id=state.id,
        attempted_at=now(),
        status="queued",
        external_call_sid=call_sid,
        transcript=[{"role": "assistant", "text": greeting}],
    )
    state.voice_call_status = "calling"
    session.add(log)
    await record_audit(
        session,
        action="voice_call.manual_real_test",
        actor=user.email,
        entity_type="shopper_automation_state",
        entity_id=str(state.id),
        summary=f"Manual real (full-conversation) test call placed to {shopper.name} ({shopper.phone})",
        meta={"call_sid": call_sid, "automation_id": str(state.automation_id)},
    )
    await session.commit()
    return {"call_sid": call_sid, "to_number": shopper.phone}


@router.post("/test-answer", include_in_schema=False)
async def test_call_connected(request: Request):
    """Plivo fetches this the instant a test call (POST /test-call) connects."""
    await _verify_request(request)
    message = request.query_params.get("message") or "This is a test call from ShopperMatch A I. Thanks, goodbye."
    return _xml(plxml_say_gather(message, "", hang_up_after=True))


@router.post("/test-status", include_in_schema=False)
async def test_call_status(request: Request):
    """Plivo's hangup callback for a test call — nothing to persist, just
    needs to exist and return 2xx so Plivo doesn't retry/alert."""
    await _verify_request(request)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Plivo webhooks (public, signature-verified)
# --------------------------------------------------------------------------- #
@router.post("/answer/{state_id}", include_in_schema=False)
async def call_connected(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Plivo fetches this the instant the call connects — the opening line."""
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
        state.automation.voice_call_message,
    )
    gather_url = f"{settings.public_base_url.rstrip('/')}/api/voice-calls/gather/{state_id}"
    return _xml(plxml_say_gather(greeting, gather_url))


@router.post("/gather/{state_id}", include_in_schema=False)
async def call_gather(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Plivo POSTs here after each <GetInput> completes, with Speech holding
    what it transcribed. One GPT turn, then either another GetInput or a
    Hangup once conclude_call fires."""
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
    speech = (params.get("Speech") or "").strip()
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
        return _xml(plxml_say_gather(turn["say"], "", hang_up_after=True))

    await session.commit()
    gather_url = f"{settings.public_base_url.rstrip('/')}/api/voice-calls/gather/{state_id}"
    return _xml(plxml_say_gather(turn["say"], gather_url))


@router.post("/status/{state_id}", include_in_schema=False)
async def call_status(state_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    """Plivo's hangup_url callback — the only reliable signal for calls that
    never connected at all (no-answer/busy/failed), which /gather never sees
    since no <GetInput> ever ran."""
    params = await _verify_request(request)
    call_status_value = params.get("CallStatus", "")
    # Plivo's hangup callback gives AnswerTime/EndTime timestamps rather than
    # a ready-made duration figure — compute it from those when both are
    # present; best-effort only, this is a reporting figure, not core logic.
    duration: int | None = None
    answer_time, end_time = params.get("AnswerTime"), params.get("EndTime")
    if answer_time and end_time:
        try:
            duration = int((datetime.fromisoformat(end_time) - datetime.fromisoformat(answer_time)).total_seconds())
        except ValueError:
            duration = None

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
        if duration is not None:
            log.duration_seconds = duration

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
# Bulk Voice Call webhooks — same shape as /answer, /gather, /status above,
# just keyed on BulkCallTarget instead of ShopperAutomationState since these
# numbers have no automation/shopper record backing them.
# --------------------------------------------------------------------------- #
@router.post("/bulk-answer/{target_id}", include_in_schema=False)
async def bulk_call_connected(target_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    await _verify_request(request)
    stmt = select(BulkCallTarget).where(BulkCallTarget.id == target_id).options(selectinload(BulkCallTarget.batch))
    target = (await session.execute(stmt)).scalar_one_or_none()
    if target is None:
        return _xml('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')

    greeting = opening_line("there", "this opportunity", "", target.batch.message)
    gather_url = f"{settings.public_base_url.rstrip('/')}/api/voice-calls/bulk-gather/{target_id}"
    return _xml(plxml_say_gather(greeting, gather_url))


@router.post("/bulk-gather/{target_id}", include_in_schema=False)
async def bulk_call_gather(target_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    params = await _verify_request(request)
    target = await session.get(BulkCallTarget, target_id)
    if target is None:
        return _xml('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>')

    speech = (params.get("Speech") or "").strip()
    history: list[dict[str, str]] = [{"role": t["role"], "content": t["text"]} for t in (target.transcript or [])]
    if speech:
        history.append({"role": "user", "content": speech})
        target.transcript = [*(target.transcript or []), {"role": "user", "text": speech}]

    turn = await next_turn(
        history=history,
        shopper_name="there",
        shop_name="this opportunity",
        campaign_name="",
        compensation="detailed on the call",
    )
    target.transcript = [*(target.transcript or []), {"role": "assistant", "text": turn["say"]}]

    if turn["outcome"]:
        target.outcome = turn["outcome"]
        target.status = "completed"
        target.ended_at = now()
        await session.commit()
        return _xml(plxml_say_gather(turn["say"], "", hang_up_after=True))

    await session.commit()
    gather_url = f"{settings.public_base_url.rstrip('/')}/api/voice-calls/bulk-gather/{target_id}"
    return _xml(plxml_say_gather(turn["say"], gather_url))


@router.post("/bulk-status/{target_id}", include_in_schema=False)
async def bulk_call_status(target_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    params = await _verify_request(request)
    call_status_value = params.get("CallStatus", "")
    target = await session.get(BulkCallTarget, target_id)
    if target is None:
        return Response(status_code=204)

    if target.status == "calling":
        target.status = "completed" if call_status_value == "completed" else "no-answer"
        target.outcome = target.outcome or ("undecided" if call_status_value == "completed" else None)
        target.ended_at = now()
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


# --------------------------------------------------------------------------- #
# Bulk Voice Call — client-facing: create a batch, list recent batches, poll
# one batch's progress.
# --------------------------------------------------------------------------- #
def _bulk_target_out(t: BulkCallTarget) -> dict:
    return {
        "id": str(t.id),
        "phone_number": t.phone_number,
        "status": t.status,
        "outcome": t.outcome,
        "transcript": t.transcript or [],
        "error_message": t.error_message,
        "attempted_at": iso(t.attempted_at),
        "ended_at": iso(t.ended_at),
    }


def _bulk_batch_out(b: BulkCallBatch, with_targets: bool = True) -> dict:
    data = {
        "id": str(b.id),
        "created_by": b.created_by,
        "message": b.message,
        "total_count": b.total_count,
        "status": b.status,
        "created_at": iso(b.created_at),
        "automation_id": str(b.automation_id) if b.automation_id else None,
    }
    if with_targets:
        targets = b.targets
        data["targets"] = [_bulk_target_out(t) for t in targets]
        data["placed"] = sum(1 for t in targets if t.status != "queued")
        data["completed"] = sum(1 for t in targets if t.status == "completed")
        data["failed"] = sum(1 for t in targets if t.status in ("failed", "no-answer"))
    return data


class BulkCallCreate(BaseModel):
    # Raw phone numbers — E.164 preferred but a bare-digits number is
    # auto-prepended with "+", same leniency as /test-call.
    numbers: list[str] = Field(min_length=1, max_length=MAX_BULK_CALL_TARGETS)
    message: str | None = Field(default=None, max_length=1000)
    # Launched from one automation's own AI Voice Call Follow-Up card — when
    # given and `message` is left blank, falls back to that automation's own
    # configured script (same "explicit message always wins" rule /test-call
    # already uses), and the batch is filterable back to that automation.
    automation_id: uuid.UUID | None = None


@router.post("/bulk")
async def create_bulk_call_batch(
    body: BulkCallCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Voice Call Follow-Up is not configured — set PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN and PLIVO_PHONE_NUMBER.",
        )

    message = body.message
    if not message and body.automation_id:
        from ..services import automation as engine

        automation = await engine.load_automation(session, body.automation_id)
        if automation is None:
            raise HTTPException(status_code=404, detail="Automation not found")
        enforce_campaign_access(automation.campaign, user)
        message = automation.voice_call_message

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in body.numbers:
        n = re.sub(r"[\s\-().]", "", raw)
        if n and not n.startswith("+"):
            n = "+" + n
        if not _E164.match(n):
            raise HTTPException(status_code=400, detail=f"'{raw}' is not a valid phone number (E.164, e.g. +918691969772)")
        if n not in seen:
            seen.add(n)
            cleaned.append(n)

    batch = BulkCallBatch(
        created_by=user.email,
        message=message,
        total_count=len(cleaned),
        status="running",
        automation_id=body.automation_id,
    )
    session.add(batch)
    await session.flush()
    session.add_all([BulkCallTarget(batch_id=batch.id, phone_number=n) for n in cleaned])
    await record_audit(
        session,
        action="voice_call.bulk_batch_created",
        actor=user.email,
        entity_type="bulk_call_batch",
        entity_id=str(batch.id),
        summary=f"Started a bulk voice call batch to {len(cleaned)} number(s)",
        meta={"count": len(cleaned)},
    )
    await session.commit()

    # Fire-and-forget: paces calls out one at a time over the batch's
    # lifetime (see CALL_PACING_SECONDS) — the request returns immediately
    # rather than blocking for however long the whole batch takes.
    asyncio.create_task(run_bulk_call_batch(batch.id))

    # Re-select (not session.get()) — the batch is already in this session's
    # identity map from the insert above, so get()'s eager-load option would
    # be silently skipped and `targets` would stay a lazy attribute, which
    # fails outside the session's own await context when serialized below.
    stmt = select(BulkCallBatch).where(BulkCallBatch.id == batch.id).options(selectinload(BulkCallBatch.targets))
    batch = (await session.execute(stmt)).scalar_one()
    return _bulk_batch_out(batch)


@router.get("/bulk")
async def list_bulk_call_batches(
    automation_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = (
        select(BulkCallBatch)
        .order_by(BulkCallBatch.created_at.desc())
        .limit(20)
        .options(selectinload(BulkCallBatch.targets))
    )
    if automation_id:
        stmt = stmt.where(BulkCallBatch.automation_id == automation_id)
    batches = (await session.execute(stmt)).scalars().all()
    return {"items": [_bulk_batch_out(b) for b in batches]}


@router.get("/bulk/{batch_id}")
async def get_bulk_call_batch(
    batch_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = select(BulkCallBatch).where(BulkCallBatch.id == batch_id).options(selectinload(BulkCallBatch.targets))
    batch = (await session.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _bulk_batch_out(batch)
