"""One-off: seeds the Call Contacts checklist with the numbers the client
gave directly (a stand-in for a future SASSIE export) so they show up as a
selectable checklist in Bulk Voice Call instead of being re-typed by hand.
Safe to run multiple times — skips any number already saved.

Run:
    python -m app.scripts.seed_call_contacts
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..database import AsyncSessionLocal, init_models
from ..models import CallContact

NUMBERS = [
    "+918691969772",
    "+919890068591",
    "+919653491090",
    "+918291471944",
    "+919136768287",
    "+918828393252",
    "+919833956595",
    "+917506183223",
    "+919920616857",
    "+918454921315",
]


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        existing = set((await session.execute(select(CallContact.phone_number))).scalars().all())
        added = 0
        for n in NUMBERS:
            if n in existing:
                continue
            session.add(CallContact(phone_number=n, label=None, source="manual"))
            added += 1
        await session.commit()
        print(f"Added {added} new contact(s), {len(NUMBERS) - added} already existed.")


if __name__ == "__main__":
    asyncio.run(run())
