"""Invitation generation, listing, detail, email preview and demo simulation.

Creating an invitation generates the unique UUID tracking token + human
reference, writes the ``invitation_created`` event and (optionally) 'sends' the
email via the configured provider (mock by default), recording ``email_sent``
and ``email_delivered`` events.
"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_session
from ..deps import require_operator
from ..models import Campaign, EmailComposition, EventType, Invitation, Shop, Shopper, User
from ..schemas import BulkInvitationCreateRequest, InvitationCreateRequest, SendTestRequest, SimulateRequest
from ..serializers import invitation_detail, invitation_row
from ..services.audit import record_audit
from ..services.email import load_composition, render_invitation_email, send_email
from ..services.outbox import enqueue_email
from ..services.selection import enforce_over_selection
from ..services.tenancy import enforce_campaign_access
from ..services.tracking import (
    add_event,
    mark_clicked,
    mark_delivered,
    mark_opened,
    mark_response,
    mark_sent,
)

router = APIRouter(prefix="/api/invitations", tags=["Invitations"])


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _subject_for(template: str, campaign: Campaign) -> str:
    if template == "reminder":
        return f"Reminder — {campaign.name}: your invitation is waiting"
    if template == "premium":
        return f"Priority invitation: {campaign.name}"
    return f"You're invited: {campaign.name}"


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id")


async def load_full(session: AsyncSession, invitation_id: uuid.UUID) -> Invitation | None:
    stmt = (
        select(Invitation)
        .where(Invitation.id == invitation_id)
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
            selectinload(Invitation.email_job),
            selectinload(Invitation.events),
            selectinload(Invitation.automation),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def next_reference(session: AsyncSession) -> str:
    count = await session.scalar(select(func.count(Invitation.id)))
    return f"INV-{(count or 0) + 1:04d}"


# --------------------------------------------------------------------------- #
@router.post("")
async def create_invitation(
    body: InvitationCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = await session.get(Campaign, _parse_uuid(body.campaign_id, "campaign"))
    shop = await session.get(Shop, _parse_uuid(body.shop_id, "shop"))
    shopper = await session.get(Shopper, _parse_uuid(body.shopper_id, "shopper"))

    campaign = enforce_campaign_access(campaign, user)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")
    if shop.campaign_id != campaign.id:
        raise HTTPException(status_code=400, detail="Shop does not belong to campaign")
    await enforce_over_selection(session, shop, 1)

    reference = await next_reference(session)
    subject = body.subject or _subject_for(body.template, campaign)

    inv = Invitation(
        tracking_token=uuid.uuid4(),
        reference=reference,
        campaign_id=campaign.id,
        shop_id=shop.id,
        shopper_id=shopper.id,
        # This override is invitation-specific; it does not change the shopper profile.
        email=str(body.recipient_email) if body.recipient_email else shopper.email,
        subject=subject,
        status="created",
        source="ISN Outreach",
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign or _slug(campaign.name),
        utm_content=body.utm_content,
    )
    # Assign the already-loaded relations so rendering never lazy-loads.
    inv.campaign = campaign
    inv.shop = shop
    inv.shopper = shopper
    session.add(inv)
    await session.flush()  # populate inv.id

    await add_event(
        session,
        inv,
        EventType.INVITATION_CREATED,
        {"source": "ISN", "campaign": campaign.name, "template": body.template},
    )

    if body.custom_subject and body.custom_html:
        session.add(
            EmailComposition(
                invitation_id=inv.id,
                subject_template=body.custom_subject,
                html_template=body.custom_html,
            )
        )

    provider_result = None

    await record_audit(
        session,
        action="invitation.created",
        actor=user.email,
        entity_type="invitation",
        entity_id=reference,
        summary=f"Invitation {reference} generated for {shopper.name}",
        meta={"campaign": campaign.name, "auto_send": body.auto_send},
    )
    if body.auto_send:
        job = await enqueue_email(session, inv)
        provider_result = {
            "provider": job.provider,
            "queued": True,
            "delivered": False,
            "detail": "Queued in the ShopperMatch outbox for background delivery.",
        }
    await session.commit()

    inv = await load_full(session, inv.id)
    detail = invitation_detail(inv)
    detail["email_preview"] = await render_invitation_email(session, inv, preview=True)
    detail["provider_result"] = provider_result
    return detail


# --------------------------------------------------------------------------- #
@router.post("/bulk")
async def create_bulk_invitations(
    body: BulkInvitationCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """One batch of a bulk send (spec: batch size / iterations). Reuses the
    exact same per-invitation creation path as `POST /api/invitations` in a
    loop — same reference numbering, same event/audit logging, same outbox
    enqueue — so a bulk send is never a second code path, just this one
    called N times. Actual send pacing (batch delay / daily cap) is enforced
    once, globally, by the outbox worker (services/outbox.py), not here."""
    campaign = await session.get(Campaign, _parse_uuid(body.campaign_id, "campaign"))
    shop = await session.get(Shop, _parse_uuid(body.shop_id, "shop"))
    campaign = enforce_campaign_access(campaign, user)
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    if shop.campaign_id != campaign.id:
        raise HTTPException(status_code=400, detail="Shop does not belong to campaign")
    await enforce_over_selection(session, shop, len(body.shopper_ids))

    created: list[dict] = []
    failed: list[dict] = []

    for raw_id in body.shopper_ids:
        try:
            shopper = await session.get(Shopper, _parse_uuid(raw_id, "shopper"))
        except HTTPException:
            failed.append({"shopper_id": raw_id, "error": "Invalid shopper id"})
            continue
        if shopper is None:
            failed.append({"shopper_id": raw_id, "error": "Shopper not found"})
            continue

        reference = await next_reference(session)
        inv = Invitation(
            tracking_token=uuid.uuid4(),
            reference=reference,
            campaign_id=campaign.id,
            shop_id=shop.id,
            shopper_id=shopper.id,
            email=shopper.email,
            subject=body.custom_subject or _subject_for("standard", campaign),
            status="created",
            source="ISN Outreach",
            utm_source="isn",
            utm_medium="email",
            utm_campaign=_slug(campaign.name),
            utm_content="bulk_invitation",
        )
        inv.campaign = campaign
        inv.shop = shop
        inv.shopper = shopper
        session.add(inv)
        await session.flush()

        await add_event(
            session,
            inv,
            EventType.INVITATION_CREATED,
            {"source": "ISN", "campaign": campaign.name, "bulk": True},
        )

        if body.custom_subject and body.custom_html:
            session.add(
                EmailComposition(
                    invitation_id=inv.id,
                    subject_template=body.custom_subject,
                    html_template=body.custom_html,
                )
            )

        if body.auto_send:
            await enqueue_email(session, inv)

        created.append({"shopper_id": str(shopper.id), "shopper_name": shopper.name, "reference": reference, "invitation_id": str(inv.id)})

    await record_audit(
        session,
        action="invitation.bulk_created",
        actor=user.email,
        entity_type="campaign",
        entity_id=str(campaign.id),
        summary=f"Bulk-created {len(created)} invitation(s) for {shop.shop_name} ({len(failed)} failed)",
        meta={"shop_id": str(shop.id), "created": len(created), "failed": len(failed)},
    )
    await session.commit()

    return {"created": created, "failed": failed, "total_created": len(created), "total_failed": len(failed)}


@router.get("")
async def list_invitations(
    campaign_id: uuid.UUID | None = Query(default=None),
    shop_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    automation_only: bool = Query(default=False, description="Only invitations sent by an Email Automation sequence"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    stmt = (
        select(Invitation)
        .order_by(Invitation.created_at.desc())
        .limit(limit)
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
            selectinload(Invitation.email_job),
            selectinload(Invitation.automation),
        )
    )
    if campaign_id is not None:
        campaign = await session.get(Campaign, campaign_id)
        enforce_campaign_access(campaign, user)
        stmt = stmt.where(Invitation.campaign_id == campaign_id)
    elif user.role == "client":
        stmt = stmt.join(Campaign, Invitation.campaign_id == Campaign.id).where(Campaign.client_id == user.client_id)
    if shop_id is not None:
        stmt = stmt.where(Invitation.shop_id == shop_id)
    if automation_only:
        stmt = stmt.where(Invitation.automation_id.is_not(None))
    if status:
        stmt = stmt.where(Invitation.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Invitation.email).like(like), func.lower(Invitation.reference).like(like))
        )
    invitations = (await session.execute(stmt)).scalars().all()
    return {"items": [invitation_row(i) for i in invitations], "total": len(invitations)}


@router.get("/{invitation_id}")
async def get_invitation(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    inv = await load_full(session, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(inv.campaign, user)
    return invitation_detail(inv)


@router.get("/{invitation_id}/email")
async def preview_email(
    invitation_id: uuid.UUID,
    preview: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    inv = await load_full(session, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(inv.campaign, user)
    return await render_invitation_email(session, inv, preview=preview)


@router.post("/{invitation_id}/simulate")
async def simulate(
    invitation_id: uuid.UUID,
    body: SimulateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    """Demo helper. Writes REAL events/timestamps via the same tracking service
    that the public endpoints use — nothing is faked in the frontend."""
    inv = await load_full(session, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(inv.campaign, user)

    meta = {"source": "simulation", "actor": user.email}
    recorded = True
    if body.action == "send":
        await mark_sent(session, inv, meta)
    elif body.action == "deliver":
        await mark_delivered(session, inv, meta)
    elif body.action == "open":
        recorded = await mark_opened(session, inv, meta)
    elif body.action == "click":
        recorded = await mark_clicked(session, inv, meta)
    elif body.action == "accept":
        recorded = await mark_response(session, inv, "accepted", meta)
    elif body.action == "decline":
        recorded = await mark_response(session, inv, "declined", meta)

    await session.commit()
    inv = await load_full(session, invitation_id)
    detail = invitation_detail(inv)
    detail["simulation"] = {"action": body.action, "newly_recorded": recorded}
    return detail


# --------------------------------------------------------------------------- #
# Explicit send step. Generate Invitation only creates the tracked record;
# this is the action that actually calls the email provider.
# --------------------------------------------------------------------------- #
class SendInvitationRequest(BaseModel):
    # Optional — these invitations (e.g. approved straight from AI
    # Recommendations) are created with a generic default subject/body and
    # no saved composition, so without this a client's edits in the Send
    # Invitation compose box would have no effect on them at all. When both
    # are given, they're saved as this invitation's composition right before
    # sending, so what gets delivered actually matches what was edited.
    custom_subject: str | None = None
    custom_html: str | None = None


@router.post("/{invitation_id}/send")
async def send_invitation(
    invitation_id: uuid.UUID,
    body: SendInvitationRequest = Body(default_factory=SendInvitationRequest),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    inv = await load_full(session, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(inv.campaign, user)

    # Idempotency: never silently double-send on a double-click, browser
    # retry, or re-render. sent_at is the durable guard — it's only ever set
    # once, by mark_sent().
    if inv.sent_at is not None:
        raise HTTPException(
            status_code=409,
            detail="This invitation has already been sent. Use Send Follow-Up to send another message.",
        )

    if inv.email_job is not None and inv.email_job.status in ("queued", "sending", "retrying"):
        raise HTTPException(status_code=409, detail="This invitation is already queued for delivery.")

    if body.custom_subject and body.custom_html:
        existing = await load_composition(session, inv.id)
        if existing is not None:
            existing.subject_template = body.custom_subject
            existing.html_template = body.custom_html
        else:
            session.add(
                EmailComposition(
                    invitation_id=inv.id,
                    subject_template=body.custom_subject,
                    html_template=body.custom_html,
                )
            )
        inv.subject = body.custom_subject

    job = await enqueue_email(session, inv)
    await add_event(session, inv, EventType.EMAIL_QUEUED, {"provider": job.provider, "actor": user.email})
    await record_audit(
        session,
        action="invitation.send_requested",
        actor=user.email,
        entity_type="invitation",
        entity_id=inv.reference,
        summary=f"Send requested for invitation {inv.reference} ({inv.email})",
        meta={"campaign": inv.campaign.name if inv.campaign else None, "provider": job.provider},
    )
    await session.commit()

    return {
        "queued": True,
        "provider": job.provider,
        "detail": "Queued in the ShopperMatch outbox for background delivery.",
    }


# --------------------------------------------------------------------------- #
# Test send: verifies formatting/deliverability without touching campaign
# metrics — no Invitation row is created or mutated, no sent_at/email_job is
# set. The rendered content reuses this invitation's real tracking link, so a
# click on it WILL be recorded against the real invitation (there is only one
# tracking token per invitation) — the UI must say so next to the button.
# --------------------------------------------------------------------------- #
@router.post("/{invitation_id}/send-test")
async def send_test_invitation(
    invitation_id: uuid.UUID,
    body: SendTestRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    inv = await load_full(session, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(inv.campaign, user)

    message = await render_invitation_email(session, inv, preview=True)
    message = {**message, "to": str(body.test_email), "subject": f"[TEST] {message['subject']}"}
    result = await send_email(message)

    await record_audit(
        session,
        action="invitation.test_sent",
        actor=user.email,
        entity_type="invitation",
        entity_id=inv.reference,
        summary=f"Test email sent for invitation {inv.reference} to {body.test_email}",
        meta={"provider": result.get("provider"), "delivered": result.get("delivered"), "test": True},
    )
    await session.commit()
    return {"test": True, "provider_result": result}


# --------------------------------------------------------------------------- #
# Follow-up: a fresh, separately-trackable invitation to the same
# shopper/shop/campaign. Requires the original to already be sent, so
# "Send Follow-Up" can't be used to sidestep the duplicate-send guard above.
# --------------------------------------------------------------------------- #
@router.post("/{invitation_id}/follow-up")
async def create_follow_up(
    invitation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    original = await load_full(session, invitation_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    enforce_campaign_access(original.campaign, user)
    if original.sent_at is None:
        raise HTTPException(status_code=400, detail="Original invitation has not been sent yet.")

    reference = await next_reference(session)
    inv = Invitation(
        tracking_token=uuid.uuid4(),
        reference=reference,
        campaign_id=original.campaign_id,
        shop_id=original.shop_id,
        shopper_id=original.shopper_id,
        email=original.email,
        subject=f"Follow-up: {original.subject}",
        status="created",
        source="ISN Follow-up",
        utm_source="isn",
        utm_medium="email",
        utm_campaign=original.utm_campaign,
        utm_content="follow_up",
    )
    inv.campaign = original.campaign
    inv.shop = original.shop
    inv.shopper = original.shopper
    session.add(inv)
    await session.flush()

    await add_event(
        session,
        inv,
        EventType.INVITATION_CREATED,
        {"source": "ISN", "campaign": original.campaign.name if original.campaign else None, "follow_up_of": original.reference},
    )
    await record_audit(
        session,
        action="invitation.follow_up_created",
        actor=user.email,
        entity_type="invitation",
        entity_id=reference,
        summary=f"Follow-up {reference} created for {original.shopper.name if original.shopper else original.email}, following {original.reference}",
        meta={"original_invitation": original.reference},
    )
    await session.commit()

    inv = await load_full(session, inv.id)
    detail = invitation_detail(inv)
    detail["email_preview"] = await render_invitation_email(session, inv, preview=True)
    return detail
