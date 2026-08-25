"""Batch (wave) automation engine.

Deliberately separate from `services/automation.py` (the 3-step reminder
sequence engine) — different shape of problem entirely. That engine
re-messages the SAME shoppers over up to 3 steps. This one expands reach:
every `wait_days`, it emails the NEXT `batch_size` shoppers from an AI-ranked
candidate pool computed once at creation, for `total_iterations` waves,
never repeating a shopper. `process_due_batch_automations()` runs on the same
poll-loop pattern as the outbox/reminder schedulers (started in main.py's
lifespan) — background, browser-independent.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import (
    BatchAutomation,
    BatchAutomationStatus,
    Campaign,
    EmailComposition,
    EmailTemplate,
    EventType,
    Invitation,
    Shop,
    Shopper,
    User,
)
from ..services.audit import record_audit
from ..services.email import render_composed_email, render_email
from ..services.outbox import enqueue_email
from ..services.semantic_matching import run_matching
from ..services.tracking import add_event, now


async def load_batch_automation(session: AsyncSession, automation_id: uuid.UUID) -> BatchAutomation | None:
    stmt = (
        select(BatchAutomation)
        .where(BatchAutomation.id == automation_id)
        .options(
            selectinload(BatchAutomation.campaign),
            selectinload(BatchAutomation.shop),
            selectinload(BatchAutomation.template),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def next_reference(session: AsyncSession) -> str:
    count = await session.scalar(select(func.count(Invitation.id)))
    return f"INV-{(count or 0) + 1:04d}"


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def create_batch_automation(
    session: AsyncSession,
    user: User,
    campaign: Campaign,
    shop: Shop,
    name: str,
    template_id: uuid.UUID | None,
    batch_size: int,
    wait_days: int,
    total_iterations: int,
    scheduled_start_at,
) -> BatchAutomation:
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    result = run_matching(list(shoppers), shop, campaign)
    candidate_ids = [r["shopper_id"] for r in result["recommendations"]]

    automation = BatchAutomation(
        campaign_id=campaign.id,
        shop_id=shop.id,
        name=name,
        status=BatchAutomationStatus.DRAFT,
        template_id=template_id,
        batch_size=max(1, batch_size),
        wait_days=max(1, wait_days),
        total_iterations=max(1, total_iterations),
        candidate_shopper_ids=candidate_ids,
        sent_shopper_ids=[],
        scheduled_start_at=scheduled_start_at,
        created_by=user.email,
    )
    session.add(automation)
    await session.flush()

    await record_audit(
        session,
        action="batch_automation.created",
        actor=user.email,
        entity_type="batch_automation",
        entity_id=str(automation.id),
        summary=f"Batch automation '{name}' created for {campaign.name} / {shop.shop_name} — {len(candidate_ids)} candidate(s)",
        meta={"campaign": campaign.name, "shop": shop.shop_name, "batch_size": batch_size, "wait_days": wait_days, "total_iterations": total_iterations},
    )
    return automation


async def start_batch_automation(session: AsyncSession, automation: BatchAutomation, user: User) -> BatchAutomation:
    if automation.status not in (BatchAutomationStatus.DRAFT, BatchAutomationStatus.PAUSED, BatchAutomationStatus.STOPPED):
        raise ValueError(f"Cannot start a batch automation in status '{automation.status}'.")
    if not automation.candidate_shopper_ids:
        raise ValueError("No eligible shoppers found for this shop — nothing to send.")

    future_start = automation.scheduled_start_at is not None and automation.scheduled_start_at > now()
    automation.status = BatchAutomationStatus.SCHEDULED if future_start else BatchAutomationStatus.ACTIVE
    automation.next_run_at = automation.scheduled_start_at if future_start else now()
    if automation.started_at is None:
        automation.started_at = now()

    await record_audit(
        session,
        action="batch_automation.started",
        actor=user.email,
        entity_type="batch_automation",
        entity_id=str(automation.id),
        summary=f"Batch automation '{automation.name}' started ({automation.status})",
        meta={"scheduled_start_at": automation.scheduled_start_at.isoformat() if automation.scheduled_start_at else None},
    )
    return automation


async def pause_batch_automation(session: AsyncSession, automation: BatchAutomation, user: User) -> BatchAutomation:
    if automation.status not in (BatchAutomationStatus.ACTIVE, BatchAutomationStatus.SCHEDULED):
        raise ValueError(f"Cannot pause a batch automation in status '{automation.status}'.")
    automation.status = BatchAutomationStatus.PAUSED
    await record_audit(
        session, action="batch_automation.paused", actor=user.email, entity_type="batch_automation",
        entity_id=str(automation.id), summary=f"Batch automation '{automation.name}' paused",
    )
    return automation


async def resume_batch_automation(session: AsyncSession, automation: BatchAutomation, user: User) -> BatchAutomation:
    if automation.status != BatchAutomationStatus.PAUSED:
        raise ValueError(f"Cannot resume a batch automation in status '{automation.status}'.")
    future_start = automation.scheduled_start_at is not None and automation.scheduled_start_at > now()
    automation.status = BatchAutomationStatus.SCHEDULED if future_start else BatchAutomationStatus.ACTIVE
    if automation.next_run_at is None or automation.next_run_at < now():
        automation.next_run_at = now()
    await record_audit(
        session, action="batch_automation.resumed", actor=user.email, entity_type="batch_automation",
        entity_id=str(automation.id), summary=f"Batch automation '{automation.name}' resumed",
    )
    return automation


async def stop_batch_automation(session: AsyncSession, automation: BatchAutomation, user: User) -> BatchAutomation:
    automation.status = BatchAutomationStatus.STOPPED
    automation.next_run_at = None
    await record_audit(
        session, action="batch_automation.stopped", actor=user.email, entity_type="batch_automation",
        entity_id=str(automation.id), summary=f"Batch automation '{automation.name}' stopped",
    )
    return automation


# --------------------------------------------------------------------------- #
# Preview (no DB writes) — uses the first candidate shopper as a stand-in.
# --------------------------------------------------------------------------- #
async def preview_batch_email(session: AsyncSession, automation: BatchAutomation) -> dict:
    if not automation.candidate_shopper_ids:
        raise ValueError("No candidate shoppers to preview.")
    shopper = await session.get(Shopper, uuid.UUID(automation.candidate_shopper_ids[0]))
    if shopper is None:
        raise ValueError("Preview shopper no longer exists.")
    tmpl = automation.template
    subject = tmpl.subject if tmpl else f"Mystery Shopping Opportunity — {automation.shop.shop_name}"
    transient = Invitation(
        id=uuid.uuid4(), tracking_token=uuid.uuid4(), reference="PREVIEW",
        campaign_id=automation.campaign_id, shop_id=automation.shop_id, shopper_id=shopper.id,
        email=shopper.email, subject=subject, status="created",
    )
    transient.campaign = automation.campaign
    transient.shop = automation.shop
    transient.shopper = shopper
    if tmpl:
        return render_composed_email(transient, tmpl.subject, tmpl.html_body, preview=True)
    return render_email(transient, preview=True)


# --------------------------------------------------------------------------- #
# Scheduler tick
# --------------------------------------------------------------------------- #
async def _run_wave(session: AsyncSession, automation: BatchAutomation) -> None:
    sent_set = set(automation.sent_shopper_ids)
    remaining = [sid for sid in automation.candidate_shopper_ids if sid not in sent_set]
    batch = remaining[: automation.batch_size]

    if not batch:
        automation.status = BatchAutomationStatus.COMPLETED
        automation.completed_at = now()
        automation.next_run_at = None
        return

    campaign = automation.campaign
    shop = automation.shop
    tmpl = automation.template
    newly_sent: list[str] = []

    for sid in batch:
        try:
            shopper = await session.get(Shopper, uuid.UUID(sid))
        except (ValueError, TypeError):
            continue
        if shopper is None:
            continue

        reference = await next_reference(session)
        subject = tmpl.subject if tmpl else f"Mystery Shopping Opportunity — {shop.shop_name}"
        inv = Invitation(
            tracking_token=uuid.uuid4(),
            reference=reference,
            campaign_id=campaign.id,
            shop_id=shop.id,
            shopper_id=shopper.id,
            email=shopper.email,
            subject=subject,
            status="created",
            source="Batch Automation",
            utm_source="isn",
            utm_medium="email",
            utm_campaign=campaign.name.lower().replace(" ", "_"),
            utm_content=f"batch_wave_{automation.current_iteration + 1}",
        )
        inv.campaign = campaign
        inv.shop = shop
        inv.shopper = shopper
        session.add(inv)
        await session.flush()

        if tmpl:
            session.add(EmailComposition(invitation_id=inv.id, subject_template=tmpl.subject, html_template=tmpl.html_body))
        await add_event(
            session, inv, EventType.INVITATION_CREATED,
            {"source": "batch_automation", "automation_id": str(automation.id), "wave": automation.current_iteration + 1},
        )
        await enqueue_email(session, inv)
        newly_sent.append(sid)

    # Reassign (not mutate in place) so SQLAlchemy detects the JSON column change.
    automation.sent_shopper_ids = automation.sent_shopper_ids + newly_sent
    automation.current_iteration += 1

    await record_audit(
        session,
        action="batch_automation.wave_sent",
        actor="system",
        entity_type="batch_automation",
        entity_id=str(automation.id),
        summary=f"Wave {automation.current_iteration} of '{automation.name}' sent to {len(newly_sent)} shopper(s)",
        meta={"wave": automation.current_iteration, "count": len(newly_sent)},
    )

    exhausted = len(automation.sent_shopper_ids) >= len(automation.candidate_shopper_ids)
    if automation.current_iteration >= automation.total_iterations or exhausted:
        automation.status = BatchAutomationStatus.COMPLETED
        automation.completed_at = now()
        automation.next_run_at = None
    else:
        automation.next_run_at = now() + timedelta(days=automation.wait_days)


async def process_due_batch_automations() -> int:
    processed = 0
    due = now()
    async with AsyncSessionLocal() as session:
        scheduled_stmt = select(BatchAutomation).where(
            BatchAutomation.status == BatchAutomationStatus.SCHEDULED,
            BatchAutomation.scheduled_start_at <= due,
        )
        for automation in (await session.execute(scheduled_stmt)).scalars().all():
            automation.status = BatchAutomationStatus.ACTIVE
            automation.next_run_at = due
        await session.commit()

        due_stmt = (
            select(BatchAutomation)
            .where(
                BatchAutomation.status == BatchAutomationStatus.ACTIVE,
                BatchAutomation.next_run_at.is_not(None),
                BatchAutomation.next_run_at <= due,
            )
            .options(
                selectinload(BatchAutomation.campaign),
                selectinload(BatchAutomation.shop),
                selectinload(BatchAutomation.template),
            )
        )
        automations = (await session.execute(due_stmt)).scalars().all()
        for automation in automations:
            try:
                await _run_wave(session, automation)
                processed += 1
            except Exception as exc:  # noqa: BLE001 — one automation's failure must never break the others
                automation.status = BatchAutomationStatus.PAUSED
                automation.next_run_at = None
                await record_audit(
                    session, action="batch_automation.error", actor="system", entity_type="batch_automation",
                    entity_id=str(automation.id), summary=f"Batch automation '{automation.name}' paused after an error: {exc}"[:200],
                )
            await session.commit()

    return processed


async def run_batch_automation_scheduler() -> None:
    """Runs for the FastAPI process lifetime — background, browser-independent."""
    import asyncio

    while True:
        try:
            await process_due_batch_automations()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"WARNING: ShopperMatch batch automation scheduler error: {exc}")
        await asyncio.sleep(settings.automation_poll_seconds)
