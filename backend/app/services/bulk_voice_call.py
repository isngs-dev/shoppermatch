"""Bulk Voice Call — calls up to MAX_BULK_CALL_TARGETS raw phone numbers
(e.g. a SASSIE export, not necessarily existing Shopper rows) one after
another through the single configured Plivo number, each getting the exact
same full listen-then-GPT-responds conversation as a single shopper's Real
AI Call (routers/voice_calls.py's /answer + /gather flow, mirrored here as
/bulk-answer + /bulk-gather since these targets have no ShopperAutomationState
to key off of).

Runs as an in-process background task per batch (started by the router,
kicked off with `asyncio.create_task` — same "fire and forget, browser-
independent" posture as services/voice_call_scheduler.py's poller, just
triggered once per batch instead of polling).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import BulkCallBatch, BulkCallTarget
from .tracking import now
from .contact_prefs import phone_opted_out
from .voice_call import create_call
from .voice_call_ai import opening_line

MAX_BULK_CALL_TARGETS = 100
# Pace calls through the single configured number instead of firing all of
# them at once — a single Plivo number has a limited concurrent-call
# capacity, and hammering it risks calls silently failing to connect.
CALL_PACING_SECONDS = 3
POLL_SECONDS = 2
# Not answered within this long (ring_timeout is 45s) => give up and move to the next number.
RING_WAIT_SECONDS = 75
# Answered calls are capped by Plivo's time_limit (600s) plus a grace period for the hangup webhook.
CALL_MAX_SECONDS = 660

# Targets whose Plivo answer webhook has fired (set by the router, read by the runner: same process).
_answered: set = set()


def mark_answered(target_id) -> None:
    _answered.add(target_id)


async def _wait_for_call_to_finish(target_id) -> None:
    """Block until this call is over so numbers are dialled strictly ONE AT A TIME. Placing the next
    call while an earlier one was still talking ran several conversations at once on a single Plivo
    number, and the later ones were the ones that got cut off."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        await asyncio.sleep(POLL_SECONDS)
        async with AsyncSessionLocal() as session:
            target = await session.get(BulkCallTarget, target_id)
            if target is None or target.status != "calling":
                _answered.discard(target_id)
                return
            answered = target_id in _answered
            if loop.time() - started > (CALL_MAX_SECONDS if answered else RING_WAIT_SECONDS):
                # The hangup webhook never arrived: close the target ourselves so the batch can continue.
                target.status = "completed" if answered else "no-answer"
                target.outcome = target.outcome or ("undecided" if answered else None)
                target.ended_at = now()
                await session.commit()
                _answered.discard(target_id)
                return


async def run_bulk_call_batch(batch_id) -> None:
    async with AsyncSessionLocal() as session:
        batch = await session.get(BulkCallBatch, batch_id)
        if batch is None:
            return
        message = batch.message
        target_ids = (
            (
                await session.execute(
                    select(BulkCallTarget.id).where(
                        BulkCallTarget.batch_id == batch_id, BulkCallTarget.status == "queued"
                    )
                )
            )
            .scalars()
            .all()
        )

    base = settings.public_base_url.rstrip("/")
    for target_id in target_ids:
        async with AsyncSessionLocal() as session:
            target = await session.get(BulkCallTarget, target_id)
            if target is None or target.status != "queued":
                continue
            if await phone_opted_out(session, target.phone_number):
                target.status = "failed"
                target.error_message = "This number opted out of calls."
                await session.commit()
                continue
            target.status = "calling"
            target.attempted_at = now()
            try:
                answer_url = f"{base}/api/voice-calls/bulk-answer/{target.id}"
                hangup_url = f"{base}/api/voice-calls/bulk-status/{target.id}"
                call_sid = await create_call(target.phone_number, answer_url, hangup_url)
                target.external_call_sid = call_sid
                greeting = opening_line("there", "this opportunity", "", message)
                target.transcript = [{"role": "assistant", "text": greeting}]
            except Exception as exc:  # noqa: BLE001 — one number's failure can't stop the batch
                target.status = "failed"
                target.error_message = str(exc)[:500]
            await session.commit()
            placed = target.status == "calling"
        if placed:
            await _wait_for_call_to_finish(target_id)
        await asyncio.sleep(CALL_PACING_SECONDS)

    async with AsyncSessionLocal() as session:
        b = await session.get(BulkCallBatch, batch_id)
        if b is not None:
            b.status = "completed"
            await session.commit()
