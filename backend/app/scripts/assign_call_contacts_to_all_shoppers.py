"""One-off: cycles the 10 saved Call Contacts across EVERY Shopper in the
database (round-robin — shopper 11 gets contact #1 again, shopper 12 gets
contact #2, etc.) so "Real AI Call" and any voice-call automation actually
dials a real, working number no matter which shopper/campaign you're
testing from. A stand-in until the real SASSIE integration supplies one
real number per shopper — safe to re-run (always reassigns deterministically
in shopper_code order) and safe to discard once real numbers land.

Run:
    python -m app.scripts.assign_call_contacts_to_all_shoppers
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..database import AsyncSessionLocal, init_models
from ..models import CallContact, Shopper


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        contacts = (
            (await session.execute(select(CallContact).order_by(CallContact.created_at)))
            .scalars()
            .all()
        )
        if not contacts:
            print("No saved Call Contacts found — run app.scripts.seed_call_contacts first.")
            return

        shoppers = (
            (await session.execute(select(Shopper).order_by(Shopper.shopper_code)))
            .scalars()
            .all()
        )
        if not shoppers:
            print("No shoppers found.")
            return

        numbers = [c.phone_number for c in contacts]
        for i, shopper in enumerate(shoppers):
            shopper.phone = numbers[i % len(numbers)]

        await session.commit()
        print(f"Assigned {len(numbers)} real number(s) across all {len(shoppers)} shopper(s), cycling round-robin.")


if __name__ == "__main__":
    asyncio.run(run())
