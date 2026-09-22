"""One-off: assigns the 10 saved Call Contacts (see seed_call_contacts.py) as
the real phone numbers of 10 real Shopper rows already in an automation's
shopper list — so calling them goes through the SAME named, tracked flow
"Real AI Call" already uses (VoiceCallLog keyed by ShopperAutomationState,
shown against the shopper's actual name/transcript/outcome in the
automation table), instead of the anonymous Bulk Voice Call flow.

Picks the first automation for a campaign matching --campaign (default
"Dunkin' Chicago Store Audit #20") that actually has shoppers, takes its
first N shoppers in list order, and overwrites each one's `phone` with one
of the saved numbers (also labels the CallContact with that shopper's name
for clarity in the checklist). A Shopper's phone number is global — this
takes effect for every automation/campaign that shopper appears in, not
just this one.

Run:
    python -m app.scripts.assign_call_contacts_to_shoppers
    python -m app.scripts.assign_call_contacts_to_shoppers --campaign "Nike New York Metro Store Audit"
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..database import AsyncSessionLocal, init_models
from ..models import Campaign, CallContact, EmailAutomation, ShopperAutomationState


async def run(campaign_name: str) -> None:
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

        stmt = (
            select(EmailAutomation)
            .join(Campaign, EmailAutomation.campaign_id == Campaign.id)
            .where(Campaign.name == campaign_name)
            .options(
                selectinload(EmailAutomation.shopper_states).selectinload(ShopperAutomationState.shopper)
            )
        )
        automations = (await session.execute(stmt)).scalars().all()
        # Prefer whichever automation for this campaign has the MOST
        # shoppers — several near-duplicate drafts can exist from earlier
        # testing, and the one with the fullest shopper list is the one
        # actually worth wiring real numbers into.
        automation = max(automations, key=lambda a: len(a.shopper_states), default=None)
        if automation is None or not automation.shopper_states:
            print(f"No automation with shoppers found for campaign '{campaign_name}'.")
            return

        ordered_states = sorted(automation.shopper_states, key=lambda s: (s.shopper.name if s.shopper else ""))
        shoppers = [s.shopper for s in ordered_states if s.shopper][: len(contacts)]
        if not shoppers:
            print("That automation has no shoppers to assign numbers to.")
            return

        assigned = []
        for shopper, contact in zip(shoppers, contacts):
            old_phone = shopper.phone
            shopper.phone = contact.phone_number
            contact.label = shopper.name
            assigned.append((shopper.name, old_phone, contact.phone_number))

        await session.commit()

        print(f"Automation: {automation.name} (campaign: {campaign_name})")
        print(f"Assigned {len(assigned)} number(s):")
        for name, old, new in assigned:
            print(f"  {name}: {old} -> {new}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="Dunkin' Chicago Store Audit #20")
    args = parser.parse_args()
    asyncio.run(run(args.campaign))


if __name__ == "__main__":
    main()
