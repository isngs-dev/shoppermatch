"""Background worker for AI Voice Call Follow-Up — same in-process asyncio
poller pattern as services/automation.py, services/social_publisher.py, and
services/social_automation.py (see main.py's lifespan). Finds shoppers whose
email sequence is fully exhausted (ShopperAutomationStatus.COMPLETED_NO_RESPONSE)
on an automation with voice calling enabled, and places (or retries) a real
Twilio call for each one that's actually due.

Pacing: a single global `voice_call_daily_limit` (real phone calls cost real
money) — once that many calls have been ATTEMPTED in the trailing 24h, this
tick stops claiming new ones and simply waits for the next tick, exactly
like the existing bulk-email daily governor.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import EmailAutomation, ShopperAutomationState, ShopperAutomationStatus, VoiceCallLog
from .audit import record_audit
from .tracking import now
from .voice_call import create_call, is_configured
from .voice_call_ai import opening_line


async def _calls_in_last_24h(session) -> int:
    since = now() - timedelta(hours=24)
    return (
        await session.scalar(select(func.count(VoiceCallLog.id)).where(VoiceCallLog.attempted_at >= since))
    ) or 0


async def _eligible_states(session) -> list[ShopperAutomationState]:
    due = now()
    stmt = (
        select(ShopperAutomationState)
        .join(EmailAutomation, ShopperAutomationState.automation_id == EmailAutomation.id)
        .where(
            ShopperAutomationState.status == ShopperAutomationStatus.COMPLETED_NO_RESPONSE,
            EmailAutomation.voice_call_enabled.is_(True),
            ShopperAutomationState.voice_call_attempts < EmailAutomation.voice_call_max_attempts,
            # .in_([None, ...]) does NOT match NULL rows in SQL — IN never
            # matches NULL, it has to be spelled out with an explicit OR.
            or_(
                ShopperAutomationState.voice_call_status.is_(None),
                ShopperAutomationState.voice_call_status.in_(["no_answer", "failed"]),
            ),
        )
        .options(
            selectinload(ShopperAutomationState.shopper),
            selectinload(ShopperAutomationState.shop),
            selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.campaign),
            selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.shop),
        )
    )
    candidates = (await session.execute(stmt)).scalars().all()

    eligible = []
    for state in candidates:
        automation = state.automation
        if state.voice_call_attempts == 0:
            # First attempt: due `voice_call_delay_days` after the sequence
            # went terminal (last_event_at was stamped exactly then).
            anchor = state.last_event_at or state.created_at
            if _aware(anchor) + timedelta(days=automation.voice_call_delay_days) <= due:
                eligible.append(state)
        else:
            # Retry: due at the explicit voice_call_next_at set after the
            # previous attempt (no-answer/failed-to-connect).
            if state.voice_call_next_at and _aware(state.voice_call_next_at) <= due:
                eligible.append(state)
    return eligible


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True)
    # columns — same fix applied elsewhere in this app (see
    # services/ai/outreach_priority.py) wherever a stored timestamp is
    # compared in Python rather than in the SQL WHERE clause itself.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _place_call(session, state: ShopperAutomationState) -> None:
    automation = state.automation
    shopper = state.shopper
    shop = state.shop or automation.shop
    campaign = automation.campaign

    log = VoiceCallLog(automation_state_id=state.id, attempted_at=now(), status="failed")

    if not shopper or not shopper.phone:
        # Permanently unfixable by retrying — exhaust attempts immediately
        # rather than burning `max_attempts` ticks re-discovering the same
        # missing phone number.
        state.voice_call_status = "failed"
        state.voice_call_attempts = automation.voice_call_max_attempts
        state.voice_call_last_at = now()
        log.error_message = "Shopper has no phone number on file."
        session.add(log)
        return

    state.voice_call_attempts += 1
    state.voice_call_last_at = now()

    try:
        base_url = settings.public_base_url.rstrip("/")
        twiml_url = f"{base_url}/api/voice-calls/twiml/{state.id}"
        status_url = f"{base_url}/api/voice-calls/status/{state.id}"
        call_sid = await create_call(shopper.phone, twiml_url, status_url)
        log.external_call_sid = call_sid
        log.status = "queued"
        log.transcript = [
            {"role": "assistant", "text": opening_line(shopper.name, shop.shop_name if shop else "this shop", campaign.name if campaign else "")}
        ]
        state.voice_call_status = "calling"
        session.add(log)
        await record_audit(
            session,
            action="voice_call.initiated",
            actor="system",
            entity_type="shopper_automation_state",
            entity_id=str(state.id),
            summary=f"Placed a voice call follow-up to {shopper.name} ({shopper.phone})",
            meta={"call_sid": call_sid, "automation_id": str(automation.id)},
        )
    except Exception as exc:  # noqa: BLE001 — one call's failure must never break the batch
        log.error_message = str(exc)[:500]
        session.add(log)
        if state.voice_call_attempts >= automation.voice_call_max_attempts:
            state.voice_call_status = "failed"
        else:
            state.voice_call_status = "no_answer"
            state.voice_call_next_at = now() + timedelta(days=automation.voice_call_retry_gap_days)


async def process_due_voice_calls() -> int:
    """One scheduler tick. Returns the number of calls actually placed."""
    if not is_configured():
        return 0  # inert until TWILIO_* env vars are set — never even queries

    placed = 0
    async with AsyncSessionLocal() as session:
        already_today = await _calls_in_last_24h(session)
        remaining = max(0, settings.voice_call_daily_limit - already_today)
        if remaining == 0:
            return 0

        for state in await _eligible_states(session):
            if placed >= remaining:
                break
            try:
                await _place_call(session, state)
                await session.commit()
                if state.voice_call_status == "calling":
                    placed += 1
            except Exception as exc:  # noqa: BLE001 — keep the tick alive
                await session.rollback()
                print(f"WARNING: ShopperMatch voice call scheduler error for state {state.id}: {exc!r}")
    return placed


async def run_voice_call_scheduler() -> None:
    """Runs for the FastAPI process lifetime — background, browser-independent."""
    import asyncio

    while True:
        try:
            await process_due_voice_calls()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"WARNING: ShopperMatch voice call scheduler error: {exc}")
        await asyncio.sleep(settings.voice_call_poll_seconds)
