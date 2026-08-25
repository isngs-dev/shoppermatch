"""One-off idempotent data script: adds more Nike campaigns spanning
active/upcoming/completed buckets so the Client Portal's multi-select bulk
actions (start automation / change status / export report) have real data
to operate on in every tab. Safe to re-run — skipped if a campaign with the
same name already exists.

Run:
    cd backend
    .venv/Scripts/python.exe -m app.scripts.add_nike_campaigns
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import (
    Campaign,
    Client,
    EventType,
    Invitation,
    InvitationEvent,
    Shop,
    Shopper,
)

rnd = random.Random(7)

CITY_COORDS = {
    "Mumbai": (19.0760, 72.8777),
    "Pune": (18.5204, 73.8567),
    "Nashik": (19.9975, 73.7898),
    "Bangalore": (12.9716, 77.5946),
    "Delhi": (28.7041, 77.1025),
}


def jitter(coord: tuple[float, float]) -> tuple[float, float]:
    return (coord[0] + rnd.uniform(-0.03, 0.03), coord[1] + rnd.uniform(-0.03, 0.03))


def make_shop(campaign, name, city, comp, visit):
    lat, lon = jitter(CITY_COORDS[city])
    return Shop(
        campaign=campaign,
        shop_name=name,
        address=f"{rnd.randint(1, 200)} {city} High Street",
        city=city,
        state="Maharashtra" if city in ("Mumbai", "Pune", "Nashik") else ("Karnataka" if city == "Bangalore" else "Delhi"),
        latitude=lat,
        longitude=lon,
        required_shoppers=rnd.randint(1, 3),
        compensation=comp,
        currency="INR",
        category="Footwear",
        visit_start=visit[0],
        visit_end=visit[1],
        status="open",
    )


NOW = datetime.now(timezone.utc)

CAMPAIGN_DEFS = [
    # (name, status, description, deadline_offset_days, shop city list, completed_ratio)
    (
        "Nike Delhi Flagship Audit",
        "active",
        "Retail experience & compliance audit across Nike flagship stores in Delhi NCR.",
        20,
        ["Delhi", "Delhi"],
        0.5,
    ),
    (
        "Nike Bangalore Launch Audit",
        "upcoming",
        "New-store launch readiness audit for Nike's Bangalore expansion.",
        35,
        ["Bangalore", "Bangalore"],
        0.0,
    ),
    (
        "Nike Winter Collection Preview",
        "upcoming",
        "Pre-launch mystery shop of the winter collection rollout across Maharashtra stores.",
        45,
        ["Mumbai", "Pune"],
        0.0,
    ),
    (
        "Nike Republic Day Sale Audit",
        "completed",
        "Post-event audit of the Republic Day promotional sale execution.",
        -10,
        ["Mumbai", "Pune", "Nashik"],
        1.0,
    ),
    (
        "Nike Diwali Footfall Audit",
        "completed",
        "Customer experience audit during the Diwali shopping season.",
        -30,
        ["Mumbai", "Delhi"],
        1.0,
    ),
]


async def _build() -> int:
    async with AsyncSessionLocal() as session:
        nike = (await session.execute(select(Client).where(Client.company_name == "Nike"))).scalar_one_or_none()
        if nike is None:
            print("Nike client not found — aborting.")
            return 0

        created = 0
        for name, status, description, deadline_offset, cities, completed_ratio in CAMPAIGN_DEFS:
            existing = (await session.execute(select(Campaign).where(Campaign.name == name))).scalar_one_or_none()
            if existing is not None:
                print(f"Skipping (already exists): {name}")
                continue

            campaign = Campaign(
                name=name,
                client_name="Nike",
                client_id=nike.id,
                description=description,
                status=status,
                deadline=NOW + timedelta(days=deadline_offset),
                created_at=NOW - timedelta(days=max(1, -deadline_offset) if deadline_offset < 0 else rnd.randint(3, 10)),
                source="demo",
            )
            session.add(campaign)

            visit_start = NOW + timedelta(days=deadline_offset - 5)
            visit_end = NOW + timedelta(days=deadline_offset)
            shops = [
                make_shop(campaign, f"Nike {city} — Store #{i + 1}", city, rnd.choice([1300, 1400, 1500, 1600]), (visit_start, visit_end))
                for i, city in enumerate(cities)
            ]
            session.add_all(shops)
            await session.flush()

            campaign.total_shops = len(shops)
            completed_shops = round(len(shops) * completed_ratio)
            campaign.completed_shops = completed_shops
            campaign.remaining_shops = len(shops) - completed_shops

            # For completed campaigns, seed a small real outreach history so
            # KPIs/report export have non-zero, realistic numbers.
            if status == "completed":
                shoppers = (await session.execute(select(Shopper).limit(10))).scalars().all()
                n = 1
                for i, shop in enumerate(shops):
                    for j in range(2):
                        shopper = shoppers[(i * 2 + j) % len(shoppers)]
                        base = NOW + timedelta(days=deadline_offset - rnd.randint(1, 4))
                        accepted = rnd.random() < 0.75
                        inv = Invitation(
                            reference=f"INV-NKX-{name[:3].upper()}-{n:03d}",
                            campaign=campaign,
                            shop=shop,
                            shopper=shopper,
                            email=shopper.email,
                            subject=f"You're invited: {campaign.name}",
                            status="accepted" if accepted else "declined",
                            source="ISN Outreach",
                            sent_at=base,
                            delivered_at=base + timedelta(minutes=5),
                            opened_at=base + timedelta(hours=1),
                            clicked_at=base + timedelta(hours=2),
                            responded_at=base + timedelta(hours=3),
                            response="accepted" if accepted else "declined",
                            created_at=base,
                        )
                        session.add(inv)
                        await session.flush()
                        session.add(InvitationEvent(
                            invitation_id=inv.id,
                            event_type=EventType.ASSIGNMENT_ACCEPTED if accepted else EventType.ASSIGNMENT_DECLINED,
                            event_timestamp=inv.responded_at,
                            event_metadata={"source": "demo_seed"},
                        ))
                        n += 1

            created += 1
            print(f"Created: {name} ({status}) — {len(shops)} shop(s)")

        await session.commit()
        return created


async def main() -> None:
    count = await _build()
    print(f"Done. {count} campaign(s) created.")


if __name__ == "__main__":
    asyncio.run(main())
