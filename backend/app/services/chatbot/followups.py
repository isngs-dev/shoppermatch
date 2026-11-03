"""Sends the reminders shoppers asked the chatbot for (ShopperFollowup rows).

Email reminders go through the app's normal email provider (mock by default,
so nothing leaves the machine unless EMAIL_PROVIDER is configured). A shopper
who opted out since scheduling is skipped, never contacted. Phone follow-ups
are NOT auto-dialled: they become a coordinator task, because a chat message
is not consent for an AI-initiated call.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...config import settings
from ...database import AsyncSessionLocal
from ...models import ChatEscalation, Invitation, ShopperFollowup
from ..email import send_email
from ..tracking import add_event

log = logging.getLogger(__name__)

_SUBJECTS = {
    "visit_reminder": "Reminder: your upcoming mystery shopping visit",
    "form_deadline": "Reminder: your mystery shopping report is due soon",
    "incomplete_response": "Reminder: please respond to your ISN invitation",
}
_BODIES = {
    "visit_reminder": "This is the reminder you asked for about your upcoming mystery shopping visit.",
    "form_deadline": "This is the reminder you asked for about submitting your mystery shopping report.",
    "incomplete_response": "This is the reminder you asked for to respond to your mystery shopping invitation.",
}


def _message(inv: Invitation, purpose: str) -> dict:
    link = f"{settings.public_base_url.rstrip('/')}/shop/{inv.tracking_token}"
    campaign = inv.campaign.name if inv.campaign else "your campaign"
    first = inv.shopper.name.split(" ")[0] if inv.shopper else "there"
    text = (
        f"Hi {first},\n\n{_BODIES[purpose]}\n\nCampaign: {campaign}\nYour personal page (assignment details and chat):\n"
        f"{link}\n\nIf you'd rather not get reminders, open the chat on that page and say \"stop messages\".\n"
    )
    return {
        "from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "to": inv.email or inv.shopper.email,
        "subject": _SUBJECTS[purpose],
        "text": text,
        "html": "<p>" + text.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>",
    }


async def process_due_followups() -> int:
    """Handle every pending follow-up whose time has come; returns how many."""
    handled = 0
    async with AsyncSessionLocal() as session:
        due = (
            await session.execute(
                select(ShopperFollowup)
                .where(ShopperFollowup.status == "pending", ShopperFollowup.send_at <= datetime.now(timezone.utc))
                .order_by(ShopperFollowup.send_at)
                .limit(20)
            )
        ).scalars().all()
        for f in due:
            inv = (
                await session.execute(
                    select(Invitation)
                    .where(Invitation.id == f.invitation_id)
                    .options(selectinload(Invitation.shopper), selectinload(Invitation.campaign))
                )
            ).scalar_one_or_none()
            shopper = inv.shopper if inv else None
            handled += 1
            if inv is None or shopper is None:
                f.status, f.detail = "failed", "Invitation or shopper no longer exists."
                continue
            if (f.channel == "email" and shopper.opted_out_email) or (f.channel == "phone" and shopper.opted_out_phone):
                f.status, f.detail = "skipped_opt_out", "Shopper opted out."
                continue
            if f.channel == "phone":
                session.add(
                    ChatEscalation(
                        shopper_id=shopper.id, campaign_id=f.campaign_id, kind="escalation", reason="other", priority="low",
                        summary=f"Call {shopper.name} ({shopper.phone}) — {f.purpose.replace('_', ' ')} requested via chatbot.",
                    )
                )
                f.status, f.detail = "handed_to_coordinator", "Added to the coordinator task list."
                continue
            try:
                result = await asyncio.wait_for(send_email(_message(inv, f.purpose)), timeout=25)
            except Exception as exc:  # noqa: BLE001 — one failure must not block the rest
                result = {"delivered": False, "detail": f"{type(exc).__name__}"}
            if result.get("delivered"):
                f.status, f.sent_at = "sent", datetime.now(timezone.utc)
                f.detail = result.get("provider")
                await add_event(session, inv, "followup_sent", {"purpose": f.purpose, "provider": result.get("provider")})
            else:
                f.status, f.detail = "failed", str(result.get("detail", "provider did not accept"))[:500]
        await session.commit()
    return handled


async def run_followup_worker() -> None:
    """Runs for the FastAPI process lifetime, like the other schedulers."""
    while True:
        try:
            await process_due_followups()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep the app alive
            log.warning("chatbot follow-up worker error: %s", exc)
        await asyncio.sleep(settings.chatbot_followup_poll_seconds)
