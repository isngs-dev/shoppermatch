"""ShopperMatch-owned transactional email outbox.

The queue records every provider attempt independently from invitation tracking.
It gives operators SendGrid-style queued/retrying/sent/failed visibility while
keeping SMTP or another configured provider as the final delivery transport.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import EmailJob, Invitation
from .email import render_invitation_email, send_email
from .tracking import mark_delivered, mark_sent, now


class EmailJobStatus:
    QUEUED = "queued"
    SENDING = "sending"
    RETRYING = "retrying"
    SENT = "sent"
    FAILED = "failed"


async def enqueue_email(session, invitation: Invitation) -> EmailJob:
    """Put an invitation into the durable outbox in the current transaction."""
    job = EmailJob(
        invitation_id=invitation.id,
        provider=settings.email_provider.lower(),
        status=EmailJobStatus.QUEUED,
        next_attempt_at=now(),
    )
    session.add(job)
    await session.flush()
    return job


async def reset_stuck_jobs() -> int:
    """Requeue jobs left in 'sending' by a process that died/restarted mid-send."""
    async with AsyncSessionLocal() as session:
        stmt = select(EmailJob).where(EmailJob.status == EmailJobStatus.SENDING)
        stuck = (await session.execute(stmt)).scalars().all()
        for job in stuck:
            job.status = EmailJobStatus.RETRYING
            job.next_attempt_at = now()
        if stuck:
            await session.commit()
        return len(stuck)


async def _claim_next_job() -> uuid.UUID | None:
    async with AsyncSessionLocal() as session:
        due = now()
        stmt = (
            select(EmailJob)
            .where(
                EmailJob.status.in_((EmailJobStatus.QUEUED, EmailJobStatus.RETRYING)),
                EmailJob.next_attempt_at <= due,
            )
            .order_by(EmailJob.queued_at)
            .limit(1)
        )
        job = (await session.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None
        job.status = EmailJobStatus.SENDING
        job.attempts += 1
        job.attempted_at = due
        await session.commit()
        return job.id


async def _complete_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(EmailJob)
            .where(EmailJob.id == job_id)
            .options(
                selectinload(EmailJob.invitation).selectinload(Invitation.campaign),
                selectinload(EmailJob.invitation).selectinload(Invitation.shop),
                selectinload(EmailJob.invitation).selectinload(Invitation.shopper),
            )
        )
        job = (await session.execute(stmt)).scalar_one_or_none()
        if job is None or job.status != EmailJobStatus.SENDING or job.invitation is None:
            return

        try:
            message = await render_invitation_email(session, job.invitation)
            result = await asyncio.wait_for(send_email(message), timeout=25)
        except asyncio.TimeoutError:
            result = {
                "provider": job.provider,
                "delivered": False,
                "detail": "Timed out waiting for the email provider (25s).",
            }
        job.provider = result.get("provider", job.provider)
        if result.get("delivered"):
            job.status = EmailJobStatus.SENT
            job.completed_at = now()
            job.last_error = None
            await mark_sent(session, job.invitation, {"provider": job.provider, "outbox_job_id": str(job.id)})
            # SendGrid's API accepting the request only means it was queued
            # for delivery, not that a mailbox received it — DELIVERED is set
            # later by the SendGrid Event Webhook (routers/webhooks.py). Every
            # other provider here has no webhook, so it's the closest signal
            # we have and is marked delivered immediately, same as before.
            if job.provider != "sendgrid":
                await mark_delivered(session, job.invitation, {"provider": job.provider, "outbox_job_id": str(job.id)})
        else:
            job.last_error = str(result.get("detail", "Provider did not accept the message."))[:1000]
            if job.attempts >= settings.email_max_attempts:
                job.status = EmailJobStatus.FAILED
                job.completed_at = now()
            else:
                job.status = EmailJobStatus.RETRYING
                # Bounded exponential backoff: 6, 12 seconds by default.
                job.next_attempt_at = now() + timedelta(seconds=min(60, 3 * (2 ** job.attempts)))
        await session.commit()


async def process_one_email_job() -> bool:
    """Process one due job; useful for the worker and in-process verification."""
    job_id = await _claim_next_job()
    if job_id is None:
        return False
    await _complete_job(job_id)
    return True


async def run_outbox_worker() -> None:
    """Run for the FastAPI process lifetime. One job at a time keeps this demo
    predictable; production can run a separate worker fleet with DB locking."""
    while True:
        try:
            processed = await process_one_email_job()
            if not processed:
                await asyncio.sleep(settings.email_worker_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the operator app alive
            print(f"WARNING: ShopperMatch outbox worker error: {exc}")
            await asyncio.sleep(settings.email_worker_poll_seconds)
