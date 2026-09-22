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
from .voice_call import create_call
from .voice_call_ai import opening_line

MAX_BULK_CALL_TARGETS = 100
# Pace calls through the single configured number instead of firing all of
# them at once — a single Plivo number has a limited concurrent-call
# capacity, and hammering it risks calls silently failing to connect.
CALL_PACING_SECONDS = 3


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
        await asyncio.sleep(CALL_PACING_SECONDS)

    async with AsyncSessionLocal() as session:
        b = await session.get(BulkCallBatch, batch_id)
        if b is not None:
            b.status = "completed"
            await session.commit()
