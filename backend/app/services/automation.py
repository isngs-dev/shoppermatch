"""Email automation engine.

A client configures a 3-step sequence (Initial Invitation -> Reminder ->
Final Reminder) for a set of shoppers against one campaign+shop. Each step's
actual send is a normal `Invitation` row tagged with `automation_id` /
`automation_step`, so delivery, tracking, the SendGrid outbox, and the
Event Webhook are all reused completely unchanged (see models.py). This
module owns only the sequencing/state machine:

  * which shoppers are due for their next step (`next_action_at <= now`)
  * whether the previous step's outcome means STOP or CONTINUE
  * advancing `ShopperAutomationState` independently per shopper

`process_due_automations()` is called on a poll loop from `run_automation_scheduler`
(started in main.py's lifespan, same pattern as the email outbox worker) —
it does not depend on any browser staying open.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import (
    AutomationStatus,
    Campaign,
    EmailAutomation,
    EmailComposition,
    EmailTemplate,
    EventType,
    Invitation,
    InvitationEvent,
    Shop,
    Shopper,
    ShopperAutomationState,
    ShopperAutomationStatus,
    User,
)
from ..services.audit import record_audit
from ..services.email import render_composed_email
from ..services.outbox import enqueue_email
from ..services.tracking import add_event, now

# --------------------------------------------------------------------------- #
# Default templates (spec section 5). Seeded once, idempotently, on startup —
# automations fall back to these when a client doesn't pick their own.
# --------------------------------------------------------------------------- #
DEFAULT_TEMPLATES = [
    (
        "Initial Invitation",
        "Mystery Shopping Opportunity — {{shop_name}}",
        (
            "<p>Hi {{shopper_name}},</p>"
            "<p>We have a new mystery shopping opportunity for you.</p>"
            "<p><strong>Campaign:</strong><br/>{{campaign_name}}</p>"
            "<p><strong>Shop:</strong><br/>{{shop_name}}</p>"
            "<p><strong>Location:</strong><br/>{{location}}</p>"
            "<p><strong>Compensation:</strong><br/>{{compensation}}</p>"
            "<p><strong>Deadline:</strong><br/>{{deadline}}</p>"
            '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
            'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
            "VIEW ASSIGNMENT</a></p>"
            "<p>Thank you,<br/>ShopperMatch.AI Team</p>"
        ),
    ),
    (
        "Reminder",
        "Reminder — {{shop_name}}: your invitation is waiting",
        (
            "<p>Hi {{shopper_name}},</p>"
            "<p>Just a reminder — this mystery shopping opportunity is still open for you.</p>"
            "<p><strong>Campaign:</strong><br/>{{campaign_name}}</p>"
            "<p><strong>Shop:</strong><br/>{{shop_name}}</p>"
            "<p><strong>Location:</strong><br/>{{location}}</p>"
            "<p><strong>Compensation:</strong><br/>{{compensation}}</p>"
            "<p><strong>Deadline:</strong><br/>{{deadline}}</p>"
            '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
            'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
            "VIEW ASSIGNMENT</a></p>"
            "<p>Thank you,<br/>ShopperMatch.AI Team</p>"
        ),
    ),
    (
        "Final Reminder",
        "Final Reminder — {{shop_name}}: this invitation is closing soon",
        (
            "<p>Hi {{shopper_name}},</p>"
            "<p>This is the final reminder for this mystery shopping opportunity — after this we won't follow up again.</p>"
            "<p><strong>Campaign:</strong><br/>{{campaign_name}}</p>"
            "<p><strong>Shop:</strong><br/>{{shop_name}}</p>"
            "<p><strong>Location:</strong><br/>{{location}}</p>"
            "<p><strong>Compensation:</strong><br/>{{compensation}}</p>"
            "<p><strong>Deadline:</strong><br/>{{deadline}}</p>"
            '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
            'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
            "VIEW ASSIGNMENT</a></p>"
            "<p>Thank you,<br/>ShopperMatch.AI Team</p>"
        ),
    ),
]


async def ensure_default_templates(session: AsyncSession) -> dict[str, EmailTemplate]:
    """Idempotent: create the 3 default templates by name if missing. Returns
    a {name: EmailTemplate} map (existing or newly created)."""
    out: dict[str, EmailTemplate] = {}
    for name, subject, html_body in DEFAULT_TEMPLATES:
        existing = (
            await session.execute(select(EmailTemplate).where(EmailTemplate.name == name))
        ).scalar_one_or_none()
        if existing is None:
            existing = EmailTemplate(name=name, subject=subject, html_body=html_body, active=True)
            session.add(existing)
            await session.flush()
        out[name] = existing
    return out


# --------------------------------------------------------------------------- #
# Loading helpers
# --------------------------------------------------------------------------- #
async def load_automation(session: AsyncSession, automation_id: uuid.UUID) -> EmailAutomation | None:
    stmt = (
        select(EmailAutomation)
        .where(EmailAutomation.id == automation_id)
        .options(
            selectinload(EmailAutomation.campaign),
            selectinload(EmailAutomation.shop),
            selectinload(EmailAutomation.step1_template),
            selectinload(EmailAutomation.step2_template),
            selectinload(EmailAutomation.step3_template),
            selectinload(EmailAutomation.shopper_states).selectinload(ShopperAutomationState.shopper),
            selectinload(EmailAutomation.shopper_states).selectinload(ShopperAutomationState.shop),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def step_template(session: AsyncSession, automation: EmailAutomation, step: int) -> EmailTemplate | None:
    """Prefers the ordered step_template_ids array (any number of steps);
    falls back to the fixed step1/2/3 columns for automations created
    before that array existed."""
    if automation.step_template_ids:
        if not (1 <= step <= len(automation.step_template_ids)):
            return None
        tid = automation.step_template_ids[step - 1]
        return await session.get(EmailTemplate, uuid.UUID(tid)) if tid else None
    return {1: automation.step1_template, 2: automation.step2_template, 3: automation.step3_template}.get(step)


# --------------------------------------------------------------------------- #
# Lifecycle: create / add shoppers / start / pause / resume / stop
# --------------------------------------------------------------------------- #
def _default_step_template(defaults: dict[str, EmailTemplate], step: int, total: int) -> EmailTemplate:
    """Step 1 defaults to Initial Invitation, the last step to Final
    Reminder, everything in between to Reminder — scales the same 3-role
    pattern to however many steps a batch-emailing wave setup asks for."""
    if step == 1:
        return defaults["Initial Invitation"]
    if step == total and total > 1:
        return defaults["Final Reminder"]
    return defaults["Reminder"]


async def create_automation(
    session: AsyncSession,
    user: User,
    campaign: Campaign,
    shop: Shop | None,
    name: str,
    step_template_ids: list[uuid.UUID | None],
    wait_days: int,
    scheduled_start_at: datetime | None,
    batch_size: int | None = None,
    total_iterations: int = 1,
    voice_call_enabled: bool = False,
    voice_call_delay_days: int = 2,
    voice_call_retry_gap_days: int = 3,
    voice_call_max_attempts: int = 2,
) -> EmailAutomation:
    """`shop=None` creates a campaign-wide automation — it spans every shop
    in the campaign at once; each shopper's actual shop then comes from
    their own ShopperAutomationState.shop_id (see add_shoppers).

    `step_template_ids` is ordered (index 0 = step 1); its length becomes
    max_steps. A None entry falls back to the role-appropriate default
    template (see _default_step_template)."""
    defaults = await ensure_default_templates(session)
    total_steps = max(1, len(step_template_ids))
    resolved_ids = [
        str(tid) if tid else str(_default_step_template(defaults, i + 1, total_steps).id)
        for i, tid in enumerate(step_template_ids)
    ]

    automation = EmailAutomation(
        campaign_id=campaign.id,
        shop_id=shop.id if shop else None,
        name=name,
        status=AutomationStatus.DRAFT,
        wait_days=max(1, wait_days),
        max_steps=total_steps,
        batch_size=batch_size,
        total_iterations=max(1, total_iterations),
        scheduled_start_at=scheduled_start_at,
        created_by=user.email,
        step_template_ids=resolved_ids,
        voice_call_enabled=voice_call_enabled,
        voice_call_delay_days=max(0, voice_call_delay_days),
        voice_call_retry_gap_days=max(1, voice_call_retry_gap_days),
        voice_call_max_attempts=max(1, voice_call_max_attempts),
        # First 3 slots are mirrored into the legacy fixed columns too —
        # cheap backward compatibility for any code still reading them.
        step1_template_id=uuid.UUID(resolved_ids[0]) if len(resolved_ids) > 0 else None,
        step2_template_id=uuid.UUID(resolved_ids[1]) if len(resolved_ids) > 1 else None,
        step3_template_id=uuid.UUID(resolved_ids[2]) if len(resolved_ids) > 2 else None,
    )
    session.add(automation)
    await session.flush()

    scope_label = f"{campaign.name} / {shop.shop_name}" if shop else f"{campaign.name} (all shops)"
    await record_audit(
        session,
        action="automation.created",
        actor=user.email,
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"Email automation '{name}' created for {scope_label}",
        meta={"campaign": campaign.name, "shop": shop.shop_name if shop else None, "wait_days": wait_days},
    )
    return automation


async def add_shoppers(
    session: AsyncSession,
    automation: EmailAutomation,
    user: User,
    shopper_ids: list[uuid.UUID],
    shop_ids: list[uuid.UUID | None] | None = None,
) -> list[ShopperAutomationState]:
    """`shop_ids`, when given, is positional with `shopper_ids` — each
    shopper's own shop for this automation. Required (per-shopper) when the
    automation itself is campaign-wide (automation.shop_id is None);
    otherwise every shopper just falls back to automation.shop_id."""
    if shop_ids is not None and len(shop_ids) != len(shopper_ids):
        raise ValueError("shop_ids must be the same length as shopper_ids")
    if automation.shop_id is None and shop_ids is None:
        raise ValueError("A shop is required per shopper for a campaign-wide automation")

    # Queried directly rather than via `automation.shopper_states` — the
    # caller may be holding a freshly-created, not-yet-eager-loaded
    # automation (e.g. bulk_start), and accessing an unloaded relationship
    # on an AsyncSession raises MissingGreenlet instead of lazy-loading.
    existing_stmt = select(ShopperAutomationState.shopper_id).where(
        ShopperAutomationState.automation_id == automation.id
    )
    existing_ids = set((await session.execute(existing_stmt)).scalars().all())
    created: list[ShopperAutomationState] = []
    for i, sid in enumerate(shopper_ids):
        if sid in existing_ids:
            continue
        shopper = await session.get(Shopper, sid)
        if shopper is None:
            continue
        shopper_shop_id = shop_ids[i] if shop_ids is not None else automation.shop_id
        if shopper_shop_id is None:
            raise ValueError(f"No shop resolved for shopper {sid} in a campaign-wide automation")
        state = ShopperAutomationState(
            automation_id=automation.id, shopper_id=sid, shop_id=shopper_shop_id, status=ShopperAutomationStatus.PENDING
        )
        session.add(state)
        created.append(state)
        existing_ids.add(sid)
    if created:
        await session.flush()
        await record_audit(
            session,
            action="automation.shoppers_added",
            actor=user.email,
            entity_type="email_automation",
            entity_id=str(automation.id),
            summary=f"{len(created)} shopper(s) added to automation '{automation.name}'",
            meta={"count": len(created)},
        )
    return created


async def start_automation(session: AsyncSession, automation: EmailAutomation, user: User) -> EmailAutomation:
    if not automation.shopper_states:
        raise ValueError("Add at least one shopper before starting the automation.")
    if automation.status not in (AutomationStatus.DRAFT, AutomationStatus.PAUSED, AutomationStatus.STOPPED):
        raise ValueError(f"Cannot start an automation in status '{automation.status}'.")

    future_start = automation.scheduled_start_at is not None and automation.scheduled_start_at > now()
    automation.status = AutomationStatus.SCHEDULED if future_start else AutomationStatus.ACTIVE
    base_start = automation.scheduled_start_at if future_start else now()

    pending = [s for s in automation.shopper_states if s.status == ShopperAutomationStatus.PENDING]

    if automation.batch_size:
        # Release shoppers in waves of `batch_size`, `wait_days` apart (the
        # same cadence already used for per-shopper step advancement),
        # capped at `total_iterations` waves. Anyone beyond that many
        # shoppers stays pending with no next_action_at — queued, never
        # sent — rather than silently falling back to "send to everyone".
        max_release = automation.batch_size * automation.total_iterations
        for i, state in enumerate(pending):
            if i >= max_release:
                continue
            wave = i // automation.batch_size
            state.next_action_at = base_start + timedelta(days=automation.wait_days * wave)
    else:
        for state in pending:
            state.next_action_at = base_start

    await record_audit(
        session,
        action="automation.started",
        actor=user.email,
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"Automation '{automation.name}' started ({automation.status})",
        meta={
            "scheduled_start_at": automation.scheduled_start_at.isoformat() if automation.scheduled_start_at else None,
            "batch_size": automation.batch_size,
            "total_iterations": automation.total_iterations,
        },
    )
    return automation


async def pause_automation(session: AsyncSession, automation: EmailAutomation, user: User) -> EmailAutomation:
    if automation.status not in (AutomationStatus.ACTIVE, AutomationStatus.SCHEDULED):
        raise ValueError(f"Cannot pause an automation in status '{automation.status}'.")
    automation.status = AutomationStatus.PAUSED
    await record_audit(
        session,
        action="automation.paused",
        actor=user.email,
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"Automation '{automation.name}' paused",
    )
    return automation


async def resume_automation(session: AsyncSession, automation: EmailAutomation, user: User) -> EmailAutomation:
    if automation.status != AutomationStatus.PAUSED:
        raise ValueError(f"Cannot resume an automation in status '{automation.status}'.")
    future_start = automation.scheduled_start_at is not None and automation.scheduled_start_at > now()
    automation.status = AutomationStatus.SCHEDULED if future_start else AutomationStatus.ACTIVE
    # Catch up any state whose wait period already fully elapsed while
    # paused — it sends on the next scheduler tick, not instantly/duplicated.
    await record_audit(
        session,
        action="automation.resumed",
        actor=user.email,
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"Automation '{automation.name}' resumed",
    )
    return automation


async def stop_automation(session: AsyncSession, automation: EmailAutomation, user: User) -> EmailAutomation:
    automation.status = AutomationStatus.STOPPED
    for state in automation.shopper_states:
        if state.status in (ShopperAutomationStatus.PENDING, ShopperAutomationStatus.ACTIVE):
            state.status = ShopperAutomationStatus.STOPPED
            state.last_event = "automation_stopped"
            state.last_event_at = now()
    await record_audit(
        session,
        action="automation.stopped",
        actor=user.email,
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"Automation '{automation.name}' stopped",
    )
    return automation


# --------------------------------------------------------------------------- #
# Preview (no DB writes) — reuses the exact same render pipeline as a real
# send by constructing a transient, unsaved Invitation with a throwaway
# tracking token.
# --------------------------------------------------------------------------- #
async def preview_step(session: AsyncSession, automation: EmailAutomation, shopper: Shopper, step: int, shop: Shop) -> dict:
    tmpl = await step_template(session, automation, step)
    if tmpl is None:
        raise ValueError(f"No template configured for step {step}.")
    transient = Invitation(
        id=uuid.uuid4(),
        tracking_token=uuid.uuid4(),
        reference=f"PREVIEW-{step}",
        campaign_id=automation.campaign_id,
        shop_id=shop.id,
        shopper_id=shopper.id,
        email=shopper.email,
        subject=tmpl.subject,
        status="created",
    )
    transient.campaign = automation.campaign
    transient.shop = shop
    transient.shopper = shopper
    return render_composed_email(transient, tmpl.subject, tmpl.html_body, preview=True)


# --------------------------------------------------------------------------- #
# Scheduler tick
# --------------------------------------------------------------------------- #
async def next_reference(session: AsyncSession) -> str:
    from sqlalchemy import func

    count = await session.scalar(select(func.count(Invitation.id)))
    return f"INV-{(count or 0) + 1:04d}"


async def _send_step(session: AsyncSession, automation: EmailAutomation, state: ShopperAutomationState, step: int) -> None:
    tmpl = await step_template(session, automation, step)
    if tmpl is None:
        state.status = ShopperAutomationStatus.COMPLETED_FAILED
        state.last_event = "no_template_configured"
        state.last_event_at = now()
        return

    shopper = state.shopper
    campaign = automation.campaign
    # A campaign-wide automation has no shop of its own — every shopper's
    # own state carries theirs. A shop-scoped automation's states never set
    # shop_id (add_shoppers falls back to automation.shop_id), so this
    # naturally resolves to automation.shop for the original, unchanged case.
    shop = state.shop or automation.shop
    if shop is None:
        state.status = ShopperAutomationStatus.COMPLETED_FAILED
        state.last_event = "no_shop_resolved"
        state.last_event_at = now()
        return

    reference = await next_reference(session)
    inv = Invitation(
        tracking_token=uuid.uuid4(),
        reference=reference,
        campaign_id=campaign.id,
        shop_id=shop.id,
        shopper_id=shopper.id,
        automation_id=automation.id,
        automation_step=step,
        email=shopper.email,
        subject=tmpl.subject,
        status="created",
        source="Client Email Automation",
        utm_source="isn",
        utm_medium="email",
        utm_campaign=campaign.name.lower().replace(" ", "_"),
        utm_content=f"automation_step_{step}",
    )
    inv.campaign = campaign
    inv.shop = shop
    inv.shopper = shopper
    session.add(inv)
    try:
        await session.flush()
    except IntegrityError:
        # Another tick already created this exact step for this shopper —
        # the DB-level uniqueness guard did its job; skip silently.
        await session.rollback()
        return

    session.add(EmailComposition(invitation_id=inv.id, subject_template=tmpl.subject, html_template=tmpl.html_body))
    await add_event(
        session, inv, EventType.INVITATION_CREATED,
        {"source": "automation", "automation_id": str(automation.id), "automation_name": automation.name, "step": step},
    )
    await enqueue_email(session, inv)

    step_label = {1: "Initial Invitation", 2: "Reminder", 3: "Final Reminder"}.get(step, f"Step {step}")
    await record_audit(
        session,
        action="automation.step_sent" if step == 1 else ("automation.reminder_sent" if step == 2 else "automation.final_reminder_sent"),
        actor="system",
        entity_type="email_automation",
        entity_id=str(automation.id),
        summary=f"{step_label} queued for {shopper.name} ({automation.name})",
        meta={"shopper_id": str(shopper.id), "step": step, "invitation_reference": reference},
    )

    state.current_step = step
    state.status = ShopperAutomationStatus.ACTIVE
    state.attempt_count += 1
    state.last_email_sent_at = now()
    state.last_event = step_label.lower().replace(" ", "_") + "_sent"
    state.last_event_at = now()
    state.next_action_at = now() + timedelta(days=automation.wait_days)


async def _evaluate_and_advance(session: AsyncSession, automation: EmailAutomation, state: ShopperAutomationState) -> None:
    """Called when a shopper's wait period for their current step has
    elapsed. Checks the outcome of that step's invitation and either stops
    the sequence or sends the next step."""
    stmt = (
        select(Invitation)
        .where(
            Invitation.automation_id == automation.id,
            Invitation.shopper_id == state.shopper_id,
            Invitation.automation_step == state.current_step,
        )
        .options(selectinload(Invitation.email_job))
    )
    inv = (await session.execute(stmt)).scalar_one_or_none()
    if inv is None:
        # Nothing was actually recorded for the step this state claims to be
        # on — treat as failed rather than looping forever.
        state.status = ShopperAutomationStatus.COMPLETED_FAILED
        state.next_action_at = None
        state.last_event = "missing_invitation_record"
        state.last_event_at = now()
        return

    # Permanent send failure (outbox exhausted retries) or a bounce/drop —
    # never keep messaging an address that can't be reached.
    bounced = (
        await session.execute(
            select(InvitationEvent).where(
                InvitationEvent.invitation_id == inv.id, InvitationEvent.event_type == EventType.EMAIL_BOUNCED
            )
        )
    ).scalar_one_or_none()
    if bounced is not None:
        state.status = ShopperAutomationStatus.COMPLETED_BOUNCED
        state.next_action_at = None
        state.last_event = "bounced"
        state.last_event_at = now()
        await record_audit(
            session, action="automation.stopped", actor="system", entity_type="email_automation",
            entity_id=str(automation.id),
            summary=f"Automation stopped for {inv.shopper.name if inv.shopper else inv.email}: email bounced",
            meta={"shopper_id": str(state.shopper_id), "reason": "bounced"},
        )
        return

    if inv.email_job is not None and inv.email_job.status == "failed" and inv.sent_at is None:
        state.status = ShopperAutomationStatus.COMPLETED_FAILED
        state.next_action_at = None
        state.last_event = "send_failed"
        state.last_event_at = now()
        await record_audit(
            session, action="automation.send_failed", actor="system", entity_type="email_automation",
            entity_id=str(automation.id),
            summary=f"Automation stopped for {inv.shopper.name if inv.shopper else inv.email}: provider failed to send",
            meta={"shopper_id": str(state.shopper_id), "error": inv.email_job.last_error},
        )
        return

    if inv.response is not None:
        state.status = ShopperAutomationStatus.COMPLETED_RESPONSE
        state.next_action_at = None
        state.last_event = inv.response
        state.last_event_at = inv.responded_at or now()
        return

    if inv.clicked_at is not None or inv.visited_at is not None:
        state.status = ShopperAutomationStatus.COMPLETED_INTERACTION
        state.next_action_at = None
        state.last_event = "visited" if inv.visited_at else "clicked"
        state.last_event_at = inv.visited_at or inv.clicked_at or now()
        return

    # Opened-only, or no interaction at all -> continue the sequence.
    next_step = state.current_step + 1
    if next_step > automation.max_steps:
        state.status = ShopperAutomationStatus.COMPLETED_NO_RESPONSE
        state.next_action_at = None
        state.last_event = "no_response"
        state.last_event_at = now()
        await record_audit(
            session, action="automation.completed_no_response", actor="system", entity_type="email_automation",
            entity_id=str(automation.id),
            summary=f"Automation completed for {inv.shopper.name if inv.shopper else inv.email}: no response after {automation.max_steps} emails",
            meta={"shopper_id": str(state.shopper_id)},
        )
        return

    await _send_step(session, automation, state, next_step)


async def process_due_automations() -> int:
    """One scheduler tick. Returns the number of shopper-states processed."""
    processed = 0
    due = now()
    async with AsyncSessionLocal() as session:
        # 1) Flip any scheduled automation whose start time has arrived.
        # Every pending shopper's next_action_at was already set correctly
        # (per-wave, for batch_size automations) back in start_automation() —
        # this only needs to flip the status, not touch next_action_at again,
        # or a later wave's timing would collapse back to "now".
        scheduled_stmt = select(EmailAutomation).where(
            EmailAutomation.status == AutomationStatus.SCHEDULED,
            EmailAutomation.scheduled_start_at <= due,
        )
        for automation in (await session.execute(scheduled_stmt)).scalars().all():
            automation.status = AutomationStatus.ACTIVE
        await session.commit()

        # 2) Process every due shopper-state under an active automation.
        due_stmt = (
            select(ShopperAutomationState)
            .join(EmailAutomation, ShopperAutomationState.automation_id == EmailAutomation.id)
            .where(
                EmailAutomation.status == AutomationStatus.ACTIVE,
                ShopperAutomationState.status.in_([ShopperAutomationStatus.PENDING, ShopperAutomationStatus.ACTIVE]),
                ShopperAutomationState.next_action_at.is_not(None),
                ShopperAutomationState.next_action_at <= due,
            )
            .options(
                selectinload(ShopperAutomationState.shopper),
                selectinload(ShopperAutomationState.shop),
                selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.campaign),
                selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.shop),
                selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.step1_template),
                selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.step2_template),
                selectinload(ShopperAutomationState.automation).selectinload(EmailAutomation.step3_template),
            )
        )
        states = (await session.execute(due_stmt)).scalars().all()
        for state in states:
            automation = state.automation
            try:
                if state.current_step == 0:
                    await _send_step(session, automation, state, 1)
                else:
                    await _evaluate_and_advance(session, automation, state)
                processed += 1
            except Exception as exc:  # noqa: BLE001 — one shopper's failure must never break the others
                state.status = ShopperAutomationStatus.COMPLETED_FAILED
                state.last_event = f"engine_error: {exc}"[:60]
                state.last_event_at = now()
            await session.commit()

        # 3) Roll an automation up to COMPLETED once every shopper is terminal.
        active_automations = (
            await session.execute(select(EmailAutomation).where(EmailAutomation.status == AutomationStatus.ACTIVE).options(selectinload(EmailAutomation.shopper_states)))
        ).scalars().all()
        terminal = {
            ShopperAutomationStatus.STOPPED,
            ShopperAutomationStatus.COMPLETED_RESPONSE,
            ShopperAutomationStatus.COMPLETED_INTERACTION,
            ShopperAutomationStatus.COMPLETED_NO_RESPONSE,
            ShopperAutomationStatus.COMPLETED_BOUNCED,
            ShopperAutomationStatus.COMPLETED_FAILED,
        }
        for automation in active_automations:
            if automation.shopper_states and all(s.status in terminal for s in automation.shopper_states):
                automation.status = AutomationStatus.COMPLETED
        await session.commit()

    return processed


async def run_automation_scheduler() -> None:
    """Runs for the FastAPI process lifetime — background, browser-independent."""
    import asyncio

    while True:
        try:
            await process_due_automations()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"WARNING: ShopperMatch automation scheduler error: {exc}")
        await asyncio.sleep(settings.automation_poll_seconds)
