"""Aggregate analytics shared by the dashboard + tracking screens.

Counts are derived from the invitation *timestamp* columns (not the current
status) because status only holds the furthest stage reached, whereas an opened
invitation has necessarily also been sent + delivered.
"""
from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Invitation, InvitationEvent
from ..serializers import iso


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


async def compute_summary(session: AsyncSession) -> dict:
    stmt = select(
        func.count(Invitation.id).label("total"),
        func.sum(case((Invitation.sent_at.isnot(None), 1), else_=0)).label("sent"),
        func.sum(case((Invitation.delivered_at.isnot(None), 1), else_=0)).label("delivered"),
        func.sum(case((Invitation.opened_at.isnot(None), 1), else_=0)).label("opened"),
        func.sum(case((Invitation.clicked_at.isnot(None), 1), else_=0)).label("clicked"),
        func.sum(case((Invitation.response == "accepted", 1), else_=0)).label("accepted"),
        func.sum(case((Invitation.response == "declined", 1), else_=0)).label("declined"),
    )
    row = (await session.execute(stmt)).one()

    total = int(row.total or 0)
    sent = int(row.sent or 0)
    delivered = int(row.delivered or 0)
    opened = int(row.opened or 0)
    clicked = int(row.clicked or 0)
    accepted = int(row.accepted or 0)
    declined = int(row.declined or 0)
    pending = total - accepted - declined

    return {
        "total_invitations": total,
        "sent": sent,
        "delivered": delivered,
        "opened": opened,
        "clicked": clicked,
        "accepted": accepted,
        "declined": declined,
        "pending": pending,
        # Rates (see module docstring for denominators)
        "delivery_rate": _rate(delivered, sent),
        "open_rate": _rate(opened, delivered),
        "click_rate": _rate(clicked, opened),
        "acceptance_rate": _rate(accepted, clicked),
        # Funnel ready for direct charting
        "funnel": [
            {"stage": "Sent", "value": sent},
            {"stage": "Delivered", "value": delivered},
            {"stage": "Opened", "value": opened},
            {"stage": "Clicked", "value": clicked},
            {"stage": "Accepted", "value": accepted},
        ],
    }


async def recent_activity(session: AsyncSession, limit: int = 12) -> list[dict]:
    stmt = (
        select(InvitationEvent)
        .order_by(InvitationEvent.event_timestamp.desc())
        .limit(limit)
        .options(
            selectinload(InvitationEvent.invitation).selectinload(Invitation.shopper),
            selectinload(InvitationEvent.invitation).selectinload(Invitation.campaign),
        )
    )
    events = (await session.execute(stmt)).scalars().all()
    out = []
    for e in events:
        inv = e.invitation
        out.append(
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "event_timestamp": iso(e.event_timestamp),
                "shopper_name": inv.shopper.name if inv and inv.shopper else None,
                "campaign_name": inv.campaign.name if inv and inv.campaign else None,
                "reference": inv.reference if inv else None,
                "metadata": e.event_metadata or {},
            }
        )
    return out
