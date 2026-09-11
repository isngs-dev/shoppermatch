"""One-off: re-owns every campaign that isn't already Nike's under the Nike
client (client_id), so the ONE client portal login this demo has
(client@nike-demo.example) actually sees the full 20 active / 20 upcoming /
20 completed multi-brand spread from add_bulk_us_campaigns.py, instead of
those 60 campaigns only being visible from the Admin portal.

Each campaign keeps its own brand identity (client_name, shop names) — only
the access-control client_id changes, so "Client Activity" in Admin still
shows the real brand per campaign; only who can log in and see it changes.

Run:
    python -m app.scripts.assign_bulk_campaigns_to_nike_client
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..database import AsyncSessionLocal, init_models
from ..models import Campaign, Client


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        nike = (await session.execute(select(Client).where(Client.company_name == "Nike"))).scalar_one_or_none()
        if nike is None:
            raise RuntimeError("Nike client not found — run app.seed first.")

        campaigns = (await session.execute(select(Campaign).where(Campaign.client_id != nike.id))).scalars().all()
        for c in campaigns:
            c.client_id = nike.id
        await session.commit()
        print(f"Re-owned {len(campaigns)} campaign(s) under the Nike client portal login.")


if __name__ == "__main__":
    asyncio.run(run())
