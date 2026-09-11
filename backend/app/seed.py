"""Seed realistic (but clearly synthetic) demo data — US-based, so a US
client sees their own cities/shops/shoppers rather than a foreign market.

Run directly:
    python -m app.seed            # seed only if the database is empty
    python -m app.seed --force    # drop everything and reseed

Creates: 1 admin user, 24 shoppers, 3 campaigns (one active — 35 shops, one
upcoming — 20 shops, one completed — 20 shops; 75 shops total), and a
realistic outreach funnel of invitations/events across three real US metro
areas (New York, Chicago, Los Angeles).
"""
from __future__ import annotations

import asyncio
import random
import sys
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

# ---------------- US metro geography ---------------- #
# Each campaign is clustered around one real US metro area — real
# neighborhood/suburb names with real approximate coordinates — so the map
# view zooms into a believable, tight metro cluster per campaign instead of
# scattering pins across the whole country.

METRO_CENTER = {
    "New York": (40.7128, -74.0060),
    "Chicago": (41.8781, -87.6298),
    "Los Angeles": (34.0522, -118.2437),
}

# (locality, state, lat, lng)
NYC_LOCALITIES = [
    ("Manhattan", "NY", 40.7831, -73.9712),
    ("Brooklyn", "NY", 40.6782, -73.9442),
    ("Queens", "NY", 40.7282, -73.7949),
    ("The Bronx", "NY", 40.8448, -73.8648),
    ("Staten Island", "NY", 40.5795, -74.1502),
    ("Jersey City", "NJ", 40.7178, -74.0431),
    ("Hoboken", "NJ", 40.7439, -74.0324),
    ("Newark", "NJ", 40.7357, -74.1724),
    ("Yonkers", "NY", 40.9312, -73.8987),
    ("White Plains", "NY", 41.0340, -73.7629),
    ("New Rochelle", "NY", 40.9115, -73.7823),
    ("Stamford", "CT", 41.0534, -73.5387),
    ("Hartford", "CT", 41.7658, -72.6734),
    ("New Haven", "CT", 41.3083, -72.9279),
    ("Trenton", "NJ", 40.2171, -74.7429),
    ("Elizabeth", "NJ", 40.6640, -74.2107),
    ("Paramus", "NJ", 40.9445, -74.0754),
    ("Edison", "NJ", 40.5187, -74.4121),
    ("Long Island City", "NY", 40.7447, -73.9485),
    ("Flushing", "NY", 40.7654, -73.8318),
    ("Astoria", "NY", 40.7644, -73.9235),
    ("Williamsburg", "NY", 40.7081, -73.9571),
    ("Park Slope", "NY", 40.6710, -73.9814),
    ("Forest Hills", "NY", 40.7196, -73.8448),
    ("Bayonne", "NJ", 40.6687, -74.1143),
    ("Union City", "NJ", 40.7795, -74.0238),
    ("Fort Lee", "NJ", 40.8509, -73.9701),
    ("Englewood", "NJ", 40.8929, -73.9723),
    ("Mount Vernon", "NY", 40.9126, -73.8371),
    ("Scarsdale", "NY", 40.9884, -73.7787),
    ("Bridgeport", "CT", 41.1792, -73.1894),
    ("Norwalk", "CT", 41.1177, -73.4082),
    ("Danbury", "CT", 41.3948, -73.4540),
    ("Perth Amboy", "NJ", 40.5068, -74.2654),
    ("New Brunswick", "NJ", 40.4862, -74.4518),
]

CHI_LOCALITIES = [
    ("The Loop", "IL", 41.8786, -87.6251),
    ("Lincoln Park", "IL", 41.9214, -87.6513),
    ("Wicker Park", "IL", 41.9088, -87.6796),
    ("Naperville", "IL", 41.7508, -88.1535),
    ("Evanston", "IL", 42.0451, -87.6877),
    ("Oak Park", "IL", 41.8850, -87.7845),
    ("Schaumburg", "IL", 42.0334, -88.0834),
    ("Skokie", "IL", 42.0324, -87.7416),
    ("Cicero", "IL", 41.8456, -87.7539),
    ("Aurora", "IL", 41.7606, -88.3201),
    ("Elgin", "IL", 42.0354, -88.2826),
    ("Joliet", "IL", 41.5250, -88.0817),
    ("Waukegan", "IL", 42.3636, -87.8448),
    ("Berwyn", "IL", 41.8506, -87.7909),
    ("Orland Park", "IL", 41.6303, -87.8531),
    ("Tinley Park", "IL", 41.5732, -87.7898),
    ("Downers Grove", "IL", 41.8089, -88.0117),
    ("Arlington Heights", "IL", 42.0884, -87.9806),
    ("Palatine", "IL", 42.1103, -88.0342),
    ("Bolingbrook", "IL", 41.6987, -88.0684),
]

LA_LOCALITIES = [
    ("Downtown LA", "CA", 34.0407, -118.2468),
    ("Hollywood", "CA", 34.0928, -118.3287),
    ("Santa Monica", "CA", 34.0195, -118.4912),
    ("Pasadena", "CA", 34.1478, -118.1445),
    ("Long Beach", "CA", 33.7701, -118.1937),
    ("Burbank", "CA", 34.1808, -118.3090),
    ("Glendale", "CA", 34.1425, -118.2551),
    ("Anaheim", "CA", 33.8366, -117.9143),
    ("Irvine", "CA", 33.6846, -117.8265),
    ("Santa Ana", "CA", 33.7455, -117.8677),
    ("Pomona", "CA", 34.0551, -117.7500),
    ("Torrance", "CA", 33.8358, -118.3406),
    ("Inglewood", "CA", 33.9617, -118.3531),
    ("Compton", "CA", 33.8958, -118.2201),
    ("Van Nuys", "CA", 34.1867, -118.4487),
    ("Beverly Hills", "CA", 34.0736, -118.4004),
    ("West Hollywood", "CA", 34.0900, -118.3617),
    ("Culver City", "CA", 34.0211, -118.3965),
    ("Manhattan Beach", "CA", 33.8847, -118.4109),
    ("Costa Mesa", "CA", 33.6411, -117.9187),
]

ZIP_RANGE = {"NY": (10001, 14925), "NJ": (7001, 8989), "CT": (6001, 6928), "IL": (60001, 62999), "CA": (90001, 96162)}


def jitter(coord: tuple[float, float], spread: float = 0.02) -> tuple[float, float]:
    return (coord[0] + rnd.uniform(-spread, spread), coord[1] + rnd.uniform(-spread, spread))


def zip_for(state: str) -> str:
    lo, hi = ZIP_RANGE.get(state, (10001, 14925))
    return str(rnd.randint(lo, hi))


# (name, email, metro, categories, availability, source, rating, completion, prev, code)
SHOPPERS = [
    ("Sarah Johnson", "sarah.johnson@shoppermail.example", "New York", ["Footwear", "Apparel", "Retail"], "available", "SASSIE", 4.8, 0.97, 42, "SHP-1001"),
    ("Michael Johnson", "michael.johnson@shoppermail.example", "New York", ["Retail", "Electronics"], "available", "SASSIE", 4.2, 0.88, 15, "SHP-1002"),
    ("Jessica Martinez", "jessica.martinez@shoppermail.example", "New York", ["Apparel", "Footwear", "Luxury"], "available", "SASSIE", 4.9, 0.95, 30, "SHP-1003"),
    ("Daniel Kim", "daniel.kim@shoppermail.example", "New York", ["Retail", "Footwear", "Cafe"], "limited", "Referral", 4.5, 0.90, 22, "SHP-1004"),
    ("Ashley Brown", "ashley.brown@shoppermail.example", "New York", ["Apparel", "Beauty", "Cafe"], "available", "SASSIE", 4.6, 0.92, 18, "SHP-1005"),
    ("Christopher Davis", "christopher.davis@shoppermail.example", "New York", ["Retail", "Grocery", "Footwear"], "available", "SASSIE", 4.1, 0.80, 9, "SHP-1006"),
    ("Olivia Wilson", "olivia.wilson@shoppermail.example", "New York", ["Footwear", "Apparel", "Cafe"], "busy", "SASSIE", 4.7, 0.93, 27, "SHP-1007"),
    ("Brandon Lee", "brandon.lee@shoppermail.example", "New York", ["Electronics", "Retail"], "available", "Web Signup", 3.9, 0.78, 6, "SHP-1008"),
    ("Matthew Anderson", "matthew.anderson@shoppermail.example", "Chicago", ["Footwear", "Apparel", "Retail"], "available", "SASSIE", 4.6, 0.94, 31, "SHP-1009"),
    ("Sophia Thompson", "sophia.thompson@shoppermail.example", "Chicago", ["Retail", "Electronics"], "available", "SASSIE", 4.3, 0.86, 14, "SHP-1010"),
    ("Ryan Garcia", "ryan.garcia@shoppermail.example", "Chicago", ["Apparel", "Footwear"], "limited", "Referral", 4.4, 0.89, 19, "SHP-1011"),
    ("Hannah Robinson", "hannah.robinson@shoppermail.example", "Chicago", ["Cafe", "Apparel", "Beauty"], "available", "SASSIE", 4.8, 0.96, 35, "SHP-1012"),
    ("Tyler Walker", "tyler.walker@shoppermail.example", "Chicago", ["Retail", "Grocery"], "available", "Web Signup", 3.8, 0.75, 5, "SHP-1013"),
    ("Madison Clark", "madison.clark@shoppermail.example", "Chicago", ["Footwear", "Cafe"], "busy", "SASSIE", 4.5, 0.91, 21, "SHP-1014"),
    ("Justin Rodriguez", "justin.rodriguez@shoppermail.example", "Chicago", ["Electronics", "Retail"], "available", "SASSIE", 4.0, 0.83, 11, "SHP-1015"),
    ("Grace Lewis", "grace.lewis@shoppermail.example", "Chicago", ["Apparel", "Footwear", "Luxury"], "available", "Referral", 4.9, 0.98, 40, "SHP-1016"),
    ("Nathan Hall", "nathan.hall@shoppermail.example", "Los Angeles", ["Electronics", "Retail"], "available", "SASSIE", 4.3, 0.87, 16, "SHP-1017"),
    ("Victoria Young", "victoria.young@shoppermail.example", "Los Angeles", ["Apparel", "Footwear", "Beauty"], "available", "SASSIE", 4.7, 0.93, 26, "SHP-1018"),
    ("Kevin Allen", "kevin.allen@shoppermail.example", "Los Angeles", ["Retail", "Electronics"], "limited", "Web Signup", 3.7, 0.72, 4, "SHP-1019"),
    ("Samantha King", "samantha.king@shoppermail.example", "Los Angeles", ["Footwear", "Apparel", "Cafe"], "available", "SASSIE", 4.6, 0.92, 23, "SHP-1020"),
    ("Jordan Scott", "jordan.scott@shoppermail.example", "Los Angeles", ["Retail", "Grocery"], "unavailable", "Referral", 4.0, 0.81, 7, "SHP-1021"),
    ("Amanda Wright", "amanda.wright@shoppermail.example", "Los Angeles", ["Electronics", "Retail", "Luxury"], "available", "SASSIE", 4.8, 0.95, 33, "SHP-1022"),
    ("Ethan Baker", "ethan.baker@shoppermail.example", "Los Angeles", ["Footwear", "Apparel"], "available", "SASSIE", 4.2, 0.85, 13, "SHP-1023"),
    ("Chloe Nelson", "chloe.nelson@shoppermail.example", "Los Angeles", ["Cafe", "Beauty", "Apparel"], "busy", "SASSIE", 4.5, 0.90, 20, "SHP-1024"),
]

METRO_AREA_CODE = {"New York": "212", "Chicago": "312", "Los Angeles": "213"}
METRO_STATE = {"New York": "NY", "Chicago": "IL", "Los Angeles": "CA"}


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
    client_nike = Client(company_name="Nike", status="active")
    client_starbucks = Client(company_name="Starbucks", status="active")
    client_bestbuy = Client(company_name="Best Buy", status="active")
    session.add_all([client_nike, client_starbucks, client_bestbuy])

    demo_client_user = User(
        name="Nike Brand Team",
        email="client@nike-demo.example",
        role="client",
        password_hash=hash_password("client-demo-2026"),
        client=client_nike,
    )
    session.add(demo_client_user)

    # Flush now so the clients are actually committed to the DB (and their
    # ids assigned) before Campaign rows reference them by client_id below.
    # Campaign.client_id is a plain FK column with no ORM relationship() to
    # Client, so SQLAlchemy's unit-of-work has no dependency graph telling it
    # to insert clients first — without this flush it may batch the Campaign
    # inserts ahead of the Client inserts. SQLite doesn't enforce FK
    # constraints by default so this went unnoticed there; Postgres does.
    await session.flush()

    # ---------------- Shoppers ----------------
    shoppers: list[Shopper] = []
    for name, email, metro, cats, avail, source, rating, completion, prev, code in SHOPPERS:
        lat, lon = jitter(METRO_CENTER[metro], spread=0.08)
        state = METRO_STATE[metro]
        s = Shopper(
            shopper_code=code,
            name=name,
            email=email.lower(),
            phone=f"+1 ({METRO_AREA_CODE[metro]}) 555-{rnd.randint(1000, 9999)}",
            city=metro,
            state=state,
            zip_code=zip_for(state),
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

    nyc_shoppers = shoppers[0:8]
    chi_shoppers = shoppers[8:16]
    la_shoppers = shoppers[16:24]

    # ---------------- Campaigns ----------------
    # All three belong to the one client with a portal login (Nike) — one of
    # each bucket, active/upcoming/completed, so signing in as that client
    # actually shows all three lifecycle stages (each with its own 20
    # shops) instead of only ever seeing "active". Starbucks and Best Buy
    # stay as separate Client rows purely for admin-side brand variety —
    # they just don't own any campaigns themselves in this seed.
    nike = Campaign(
        name="Nike New York Metro Store Audit",
        client_name="Nike",
        client_id=client_nike.id,
        description="Retail experience & compliance audit across Nike stores in the New York tri-state area.",
        status="active",
        deadline=now + timedelta(days=12),
    )
    starbucks = Campaign(
        name="Nike Chicago Store Launch Recruitment",
        client_name="Nike",
        client_id=client_nike.id,
        description="Recruiting shoppers ahead of a new-store audit across the Chicago metro area.",
        status="upcoming",
        deadline=now + timedelta(days=45),
    )
    bestbuy = Campaign(
        name="Nike Los Angeles Store Audit",
        client_name="Nike",
        client_id=client_nike.id,
        description="Retail experience & compliance audit wrapped up across the Los Angeles metro area.",
        status="completed",
        deadline=now - timedelta(days=20),
    )
    session.add_all([nike, starbucks, bestbuy])

    def make_shop(campaign, brand, loc, category, comp, visit):
        name, state, lat, lng = loc
        lat, lng = jitter((lat, lng), spread=0.006)
        return Shop(
            campaign=campaign,
            shop_name=f"{brand} — {name}",
            address=f"{rnd.randint(100, 999)} Main St, {name}, {state}",
            city=name,
            state=state,
            latitude=lat,
            longitude=lng,
            required_shoppers=rnd.randint(1, 3),
            compensation=comp,
            currency="USD",
            category=category,
            visit_start=visit[0],
            visit_end=visit[1],
            status="open",
        )

    nike_window = (now - timedelta(days=3), now + timedelta(days=12))
    sbux_window = (now + timedelta(days=30), now + timedelta(days=45))
    bestbuy_window = (now - timedelta(days=35), now - timedelta(days=20))

    nike_shops = [make_shop(nike, "Nike", loc, "Footwear", rnd.randint(25, 40), nike_window) for loc in NYC_LOCALITIES]
    sbux_shops = [make_shop(starbucks, "Nike", loc, "Footwear", rnd.randint(25, 40), sbux_window) for loc in CHI_LOCALITIES]
    bestbuy_shops = [make_shop(bestbuy, "Nike", loc, "Footwear", rnd.randint(25, 40), bestbuy_window) for loc in LA_LOCALITIES]
    all_shops = nike_shops + sbux_shops + bestbuy_shops
    session.add_all(all_shops)

    # Flush so PK ids are assigned before we build invitations/events.
    await session.flush()

    for c, shops in ((nike, nike_shops), (starbucks, sbux_shops), (bestbuy, bestbuy_shops)):
        c.total_shops = len(shops)

    # ---------------- Invitations + events ----------------
    # Built programmatically per campaign instead of a hand-written literal
    # list — with 20 shops per campaign a hardcoded plan would be unreadable.
    # `accepted_n` shops get an accepted invitation (drives completed_shops);
    # the next `other_n` shops get a mix of in-flight funnel stages; the rest
    # of the 20 stay untouched, which is realistic for an active/upcoming
    # campaign and fine for a wrapped-up one too (not every shop gets a
    # response before a campaign closes).
    A, D, O, C, S = "accepted", "declined", "opened", "clicked", "sent"
    DEL = "delivered"
    OTHER_STAGES = [O, C, S, DEL, D]

    def build_plan(shops: list[Shop], shopper_pool: list[Shopper], accepted_n: int, other_n: int):
        pool = shopper_pool * 3  # enough repeats to cover every shop touched
        shuffled = shops[:]
        rnd.shuffle(shuffled)
        plan: list[tuple[Shopper, Campaign, Shop, str]] = []
        idx = 0
        for shop in shuffled[:accepted_n]:
            plan.append((pool[idx % len(pool)], shop.campaign, shop, A))
            idx += 1
        for j, shop in enumerate(shuffled[accepted_n : accepted_n + other_n]):
            plan.append((pool[idx % len(pool)], shop.campaign, shop, OTHER_STAGES[j % len(OTHER_STAGES)]))
            idx += 1
        return plan

    plan = (
        build_plan(nike_shops, nyc_shoppers, accepted_n=10, other_n=14)
        + build_plan(sbux_shops, chi_shoppers, accepted_n=0, other_n=8)
        + build_plan(bestbuy_shops, la_shoppers, accepted_n=18, other_n=2)
    )

    rank = {S: 1, DEL: 2, O: 3, C: 4, A: 5, D: 5}
    slug = {
        "Nike New York Metro Store Audit": "nike_nyc_audit",
        "Nike Chicago Store Launch Recruitment": "nike_chicago_launch",
        "Nike Los Angeles Store Audit": "nike_la_audit",
    }

    accepted_shop_ids: set = set()
    for n, (shopper, campaign, shop, stage) in enumerate(plan, start=1):
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
    for c, shops in ((nike, nike_shops), (starbucks, sbux_shops), (bestbuy, bestbuy_shops)):
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
    print("✅ Seed complete: 1 admin, 24 shoppers, 3 campaigns (active 35 shops, upcoming 20, completed 20 — 75 total).")
    print(f"   Admin login: {settings.demo_admin_email} / {settings.demo_admin_password}")


if __name__ == "__main__":
    asyncio.run(main())
