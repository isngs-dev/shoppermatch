"""Seed realistic (but clearly synthetic) demo data.

Run directly:
    python -m app.seed            # seed only if the database is empty
    python -m app.seed --force    # drop everything and reseed

Creates: 1 admin user, 10 shoppers, 3 campaigns, 8 shops, 24 invitations and
110+ invitation events with a realistic outreach funnel.
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .config import settings
from .database import AsyncSessionLocal, Base, engine, init_models
from .models import (
    Campaign,
    Client,
    EventType,
    Invitation,
    InvitationEvent,
    InvitationStatus,
    Shop,
    Shopper,
    User,
)
from .security import hash_password

rnd = random.Random(42)

CITY_COORDS = {
    "Mumbai": (19.0760, 72.8777),
    "Pune": (18.5204, 73.8567),
    "Nashik": (19.9975, 73.7898),
}


def jitter(coord: tuple[float, float]) -> tuple[float, float]:
    return (coord[0] + rnd.uniform(-0.03, 0.03), coord[1] + rnd.uniform(-0.03, 0.03))


# (name, email, city, categories, availability, source, rating, completion, prev, code)
SHOPPERS = [
    ("Sarah Johnson", "sarah.johnson@shoppermail.example", "Mumbai", ["Footwear", "Apparel", "Retail"], "available", "SASSIE", 4.8, 0.97, 42, "SHP-1001"),
    ("John Smith", "john.smith@shoppermail.example", "Mumbai", ["Retail", "Electronics"], "available", "SASSIE", 4.2, 0.88, 15, "SHP-1002"),
    ("Priya Sharma", "priya.sharma@shoppermail.example", "Mumbai", ["Apparel", "Footwear", "Luxury"], "available", "SASSIE", 4.9, 0.95, 30, "SHP-1003"),
    ("Rahul Verma", "rahul.verma@shoppermail.example", "Pune", ["Retail", "Footwear", "Cafe"], "limited", "Referral", 4.5, 0.90, 22, "SHP-1004"),
    ("Ananya Iyer", "ananya.iyer@shoppermail.example", "Mumbai", ["Apparel", "Beauty", "Cafe"], "available", "SASSIE", 4.6, 0.92, 18, "SHP-1005"),
    ("Vikram Nair", "vikram.nair@shoppermail.example", "Nashik", ["Retail", "Grocery", "Footwear"], "available", "SASSIE", 4.1, 0.80, 9, "SHP-1006"),
    ("Meera Reddy", "meera.reddy@shoppermail.example", "Pune", ["Footwear", "Apparel", "Cafe"], "busy", "SASSIE", 4.7, 0.93, 27, "SHP-1007"),
    ("Arjun Kapoor", "arjun.kapoor@shoppermail.example", "Mumbai", ["Electronics", "Retail"], "available", "Web Signup", 3.9, 0.78, 6, "SHP-1008"),
    ("Neha Gupta", "neha.gupta@shoppermail.example", "Nashik", ["Apparel", "Beauty"], "available", "SASSIE", 4.4, 0.85, 12, "SHP-1009"),
    ("David Lee", "david.lee@shoppermail.example", "Pune", ["Retail", "Footwear", "Electronics"], "unavailable", "Referral", 4.0, 0.82, 8, "SHP-1010"),
]


async def _build(session) -> None:
    now = datetime.now(timezone.utc)

    # ---------------- Admin user ----------------
    admin = User(
        name=settings.demo_admin_name,
        email=settings.demo_admin_email.lower(),
        role="admin",
        password_hash=hash_password(settings.demo_admin_password),
    )
    session.add(admin)

    # ---------------- Clients (Client Portal) ----------------
    # One Client row per brand, each with a company matching a campaign's
    # client_name below. Nike also gets a demo client-portal login so the
    # Client Portal has something to sign into out of the box — this used to
    # be a one-time Alembic migration backfill, but that only ever ran
    # against a pre-existing SQLite dev database; a fresh deploy (Render/
    # Railway, migrations never invoked) needs it created here instead.
    # Explicit ids (rather than relying on Campaign.client_id, which has no
    # ORM relationship attribute defined) so they're known immediately for
    # wiring into the campaigns below, without an extra flush round-trip.
    client_nike = Client(id=uuid.uuid4(), company_name="Nike", status="active")
    client_starbucks = Client(id=uuid.uuid4(), company_name="Starbucks", status="active")
    client_croma = Client(id=uuid.uuid4(), company_name="Croma (Tata)", status="active")
    session.add_all([client_nike, client_starbucks, client_croma])

    demo_client_user = User(
        name="Nike Brand Team",
        email="client@nike-demo.example",
        role="client",
        password_hash=hash_password("client-demo-2026"),
        client=client_nike,
    )
    session.add(demo_client_user)

    # ---------------- Shoppers ----------------
    shoppers: list[Shopper] = []
    for name, email, city, cats, avail, source, rating, completion, prev, code in SHOPPERS:
        lat, lon = jitter(CITY_COORDS[city])
        s = Shopper(
            shopper_code=code,
            name=name,
            email=email.lower(),
            phone=f"+91 98{rnd.randint(1000000, 9999999)}",
            city=city,
            state="Maharashtra",
            zip_code=str(rnd.randint(400001, 422999)),
            latitude=lat,
            longitude=lon,
            categories=cats,
            availability_status=avail,
            source=source,
            rating=rating,
            completion_rate=completion,
            previous_assignments=prev,
            active=(avail != "unavailable"),
        )
        shoppers.append(s)
        session.add(s)

    # ---------------- Campaigns + Shops ----------------
    nike = Campaign(
        name="Nike Mumbai Store Audit",
        client_name="Nike",
        client_id=client_nike.id,
        description="Retail experience & compliance audit across Nike stores in Maharashtra.",
        status="active",
        deadline=datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc),
    )
    starbucks = Campaign(
        name="Starbucks Pune Experience Audit",
        client_name="Starbucks",
        client_id=client_starbucks.id,
        description="Service quality and store experience audit for Pune cafes.",
        status="active",
        deadline=datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc),
    )
    croma = Campaign(
        name="Croma Electronics Mystery Shop",
        client_name="Croma (Tata)",
        client_id=client_croma.id,
        description="Electronics retail mystery shopping across metro stores.",
        status="active",
        deadline=datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc),
    )
    session.add_all([nike, starbucks, croma])

    def make_shop(campaign, name, city, category, comp, visit):
        lat, lon = jitter(CITY_COORDS[city])
        return Shop(
            campaign=campaign,
            shop_name=name,
            address=f"{rnd.randint(1, 200)} {city} High Street",
            city=city,
            state="Maharashtra",
            latitude=lat,
            longitude=lon,
            required_shoppers=rnd.randint(1, 3),
            compensation=comp,
            currency="INR",
            category=category,
            visit_start=visit[0],
            visit_end=visit[1],
            status="open",
        )

    nike_window = (datetime(2026, 8, 20, tzinfo=timezone.utc), datetime(2026, 8, 25, tzinfo=timezone.utc))
    sbux_window = (datetime(2026, 8, 28, tzinfo=timezone.utc), datetime(2026, 9, 4, tzinfo=timezone.utc))
    croma_window = (datetime(2026, 9, 2, tzinfo=timezone.utc), datetime(2026, 9, 11, tzinfo=timezone.utc))

    nike_shops = [
        make_shop(nike, "Nike Mumbai — Bandra", "Mumbai", "Footwear", 1500, nike_window),
        make_shop(nike, "Nike Pune — Koregaon Park", "Pune", "Footwear", 1400, nike_window),
        make_shop(nike, "Nike Nashik — College Road", "Nashik", "Footwear", 1300, nike_window),
        make_shop(nike, "Nike Mumbai — Andheri", "Mumbai", "Footwear", 1500, nike_window),
    ]
    sbux_shops = [
        make_shop(starbucks, "Starbucks Pune — FC Road", "Pune", "Cafe", 1200, sbux_window),
        make_shop(starbucks, "Starbucks Mumbai — Colaba", "Mumbai", "Cafe", 1250, sbux_window),
    ]
    croma_shops = [
        make_shop(croma, "Croma Mumbai — Vashi", "Mumbai", "Electronics", 1600, croma_window),
        make_shop(croma, "Croma Pune — Baner", "Pune", "Electronics", 1550, croma_window),
    ]
    all_shops = nike_shops + sbux_shops + croma_shops
    session.add_all(all_shops)

    # Flush so PK ids are assigned before we build invitations/events.
    await session.flush()

    for c, shops in ((nike, nike_shops), (starbucks, sbux_shops), (croma, croma_shops)):
        c.total_shops = len(shops)

    # ---------------- Invitations + events ----------------
    # (shopper_idx, campaign, shop, stage)
    A, D, O, C, S = "accepted", "declined", "opened", "clicked", "sent"
    DEL = "delivered"
    plan = [
        (0, nike, nike_shops[0], A),
        (2, nike, nike_shops[0], C),
        (1, nike, nike_shops[3], O),
        (4, nike, nike_shops[3], A),
        (7, nike, nike_shops[0], DEL),
        (3, nike, nike_shops[1], A),
        (6, nike, nike_shops[1], C),
        (9, nike, nike_shops[1], D),
        (5, nike, nike_shops[2], O),
        (8, nike, nike_shops[2], S),
        (2, nike, nike_shops[1], O),
        (1, nike, nike_shops[0], C),
        (4, nike, nike_shops[2], DEL),
        (0, nike, nike_shops[1], D),
        (6, starbucks, sbux_shops[0], A),
        (3, starbucks, sbux_shops[0], O),
        (4, starbucks, sbux_shops[1], C),
        (2, starbucks, sbux_shops[1], A),
        (5, starbucks, sbux_shops[0], S),
        (1, croma, croma_shops[0], A),
        (7, croma, croma_shops[0], C),
        (9, croma, croma_shops[1], O),
        (8, croma, croma_shops[1], DEL),
        (0, croma, croma_shops[0], C),
    ]

    rank = {S: 1, DEL: 2, O: 3, C: 4, A: 5, D: 5}
    slug = {
        "Nike Mumbai Store Audit": "nike_mumbai_audit",
        "Starbucks Pune Experience Audit": "starbucks_pune_audit",
        "Croma Electronics Mystery Shop": "croma_electronics_shop",
    }

    accepted_shop_ids: set = set()
    for n, (sidx, campaign, shop, stage) in enumerate(plan, start=1):
        shopper = shoppers[sidx]
        base = now - timedelta(days=rnd.randint(1, 7), hours=rnd.randint(0, 10))
        r = rank[stage]

        inv = Invitation(
            reference=f"INV-{n:04d}",
            campaign=campaign,
            shop=shop,
            shopper=shopper,
            email=shopper.email,
            subject=f"You're invited: {campaign.name}",
            status=stage if stage in (A, D) else stage,
            source="ISN Outreach",
            utm_source="isn",
            utm_medium="email",
            utm_campaign=slug.get(campaign.name, "campaign"),
            utm_content="invitation",
            created_at=base,
        )

        events: list[InvitationEvent] = [
            InvitationEvent(
                invitation=inv,
                event_type=EventType.INVITATION_CREATED,
                event_timestamp=base,
                event_metadata={"source": "ISN", "campaign": campaign.name},
            )
        ]

        sent_at = base + timedelta(minutes=2)
        inv.sent_at = sent_at
        events.append(InvitationEvent(invitation=inv, event_type=EventType.EMAIL_SENT, event_timestamp=sent_at, event_metadata={"provider": "mock"}))

        if r >= 2:
            delivered_at = base + timedelta(minutes=6)
            inv.delivered_at = delivered_at
            events.append(InvitationEvent(invitation=inv, event_type=EventType.EMAIL_DELIVERED, event_timestamp=delivered_at, event_metadata={"provider": "mock"}))
        if r >= 3:
            opened_at = base + timedelta(hours=rnd.randint(1, 6), minutes=rnd.randint(0, 59))
            inv.opened_at = opened_at
            events.append(InvitationEvent(invitation=inv, event_type=EventType.EMAIL_OPENED, event_timestamp=opened_at, event_metadata={"page": "email_open_pixel", "user_agent_summary": "Chrome on Android"}))
        if r >= 4:
            clicked_at = inv.opened_at + timedelta(minutes=rnd.randint(1, 25))
            inv.clicked_at = clicked_at
            events.append(InvitationEvent(invitation=inv, event_type=EventType.LINK_CLICKED, event_timestamp=clicked_at, event_metadata={"page": "email_cta", "utm": {"utm_source": "isn", "utm_medium": "email"}}))
        if r >= 5:
            responded_at = inv.clicked_at + timedelta(minutes=rnd.randint(10, 180))
            inv.responded_at = responded_at
            if stage == A:
                inv.response = "accepted"
                inv.status = InvitationStatus.ACCEPTED
                events.append(InvitationEvent(invitation=inv, event_type=EventType.ASSIGNMENT_ACCEPTED, event_timestamp=responded_at, event_metadata={"page": "shopper_landing"}))
                accepted_shop_ids.add(shop.id)
            else:
                inv.response = "declined"
                inv.status = InvitationStatus.DECLINED
                events.append(InvitationEvent(invitation=inv, event_type=EventType.ASSIGNMENT_DECLINED, event_timestamp=responded_at, event_metadata={"page": "shopper_landing"}))

        session.add(inv)
        session.add_all(events)

    # Update campaign completion counts from accepted invitations.
    for c, shops in ((nike, nike_shops), (starbucks, sbux_shops), (croma, croma_shops)):
        completed = sum(1 for sh in shops if sh.id in accepted_shop_ids)
        c.completed_shops = completed
        c.remaining_shops = c.total_shops - completed

    await session.commit()


async def is_empty(session) -> bool:
    count = await session.scalar(select(func.count(User.id)))
    return (count or 0) == 0


async def maybe_seed() -> bool:
    """Seed only if the DB has no users. Returns True if seeding ran."""
    async with AsyncSessionLocal() as session:
        if not await is_empty(session):
            return False
        await _build(session)
        return True


async def _reset() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    force = "--force" in sys.argv
    await init_models()
    if force:
        print("Dropping and recreating all tables …")
        await _reset()
    async with AsyncSessionLocal() as session:
        if not force and not await is_empty(session):
            print("Database already contains data — skipping seed (use --force to reseed).")
            return
        await _build(session)
    print("✅ Seed complete: 1 admin, 10 shoppers, 3 campaigns, 8 shops, 24 invitations.")
    print(f"   Admin login: {settings.demo_admin_email} / {settings.demo_admin_password}")


if __name__ == "__main__":
    asyncio.run(main())
