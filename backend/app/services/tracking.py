"""Core tracking logic: append immutable events and advance invitation state.

This is the heart of the attribution layer. Every meaningful interaction with an
invitation (sent, delivered, opened, clicked, accepted, declined) is written as
an `invitation_events` row *and* reflected on the parent invitation's status +
timestamp columns so the dashboard can render both aggregates and timelines.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EventType, Invitation, InvitationEvent, InvitationStatus


def now() -> datetime:
    return datetime.now(timezone.utc)


def advance_status(inv: Invitation, new_status: str) -> None:
    """Move the status forward only — never regress (e.g. clicked -> opened)."""
    current_rank = InvitationStatus.ORDER.get(inv.status, 0)
    next_rank = InvitationStatus.ORDER.get(new_status, 0)
    if next_rank >= current_rank:
        inv.status = new_status


async def add_event(
    session: AsyncSession,
    invitation: Invitation,
    event_type: str,
    metadata: dict | None = None,
) -> InvitationEvent:
    """Persist a single event. `invitation.id` must already exist (flush first)."""
    event = InvitationEvent(
        invitation_id=invitation.id,
        event_type=event_type,
        event_timestamp=now(),
        event_metadata=metadata or {},
    )
    session.add(event)
    return event


async def mark_sent(session: AsyncSession, inv: Invitation, metadata: dict | None = None) -> bool:
    if inv.sent_at is None:
        inv.sent_at = now()
    advance_status(inv, InvitationStatus.SENT)
    await add_event(session, inv, EventType.EMAIL_SENT, metadata)
    return True


async def mark_delivered(session: AsyncSession, inv: Invitation, metadata: dict | None = None) -> bool:
    if inv.delivered_at is None:
        inv.delivered_at = now()
    advance_status(inv, InvitationStatus.DELIVERED)
    await add_event(session, inv, EventType.EMAIL_DELIVERED, metadata)
    return True


async def mark_opened(session: AsyncSession, inv: Invitation, metadata: dict | None = None) -> bool:
    """Record an email-open. Deduplicated: only the first open is stored.

    Returns True if this call recorded a *new* open, False if already opened.
    """
    if inv.opened_at is not None:
        return False
    inv.opened_at = now()
    advance_status(inv, InvitationStatus.OPENED)
    await add_event(session, inv, EventType.EMAIL_OPENED, metadata)
    return True


async def mark_clicked(session: AsyncSession, inv: Invitation, metadata: dict | None = None) -> bool:
    """Record a link click. Deduplicated to the first click for a clean timeline.

    Returns True if this call recorded a *new* click, False if already clicked.
    """
    if inv.clicked_at is not None:
        return False
    inv.clicked_at = now()
    advance_status(inv, InvitationStatus.CLICKED)
    await add_event(session, inv, EventType.LINK_CLICKED, metadata)
    return True


async def mark_response(
    session: AsyncSession, inv: Invitation, response: str, metadata: dict | None = None
) -> bool:
    """Record accept/decline. Returns False if a response was already recorded."""
    if inv.responded_at is not None:
        return False
    inv.responded_at = now()
    inv.response = response
    if response == "accepted":
        advance_status(inv, InvitationStatus.ACCEPTED)
        event_type = EventType.ASSIGNMENT_ACCEPTED
    else:
        advance_status(inv, InvitationStatus.DECLINED)
        event_type = EventType.ASSIGNMENT_DECLINED
    await add_event(session, inv, event_type, metadata)
    return True
