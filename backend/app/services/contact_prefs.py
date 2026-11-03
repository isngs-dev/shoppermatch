"""Contact opt-out checks shared by every outbound channel.

A shopper who tells the chatbot to stop (record_opt_out) is flagged on the
`shoppers` row; the email outbox, the voice-call scheduler, the bulk voice
call runner and chatbot follow-ups all consult this before contacting anyone.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Shopper


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


async def phone_opted_out(session: AsyncSession, phone: str | None) -> bool:
    """True if any shopper with this phone number (formatting ignored) opted out of calls."""
    target = _digits(phone)
    if not target:
        return False
    rows = (
        await session.execute(select(Shopper.phone).where(Shopper.opted_out_phone.is_(True), Shopper.phone.isnot(None)))
    ).scalars().all()
    return any(_digits(p) == target for p in rows)
