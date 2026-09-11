"""One-off bulk data extension: adds 60 more US-based campaigns — 20 active,
20 upcoming, 20 completed — spread across 20 real US brands and 18 real US
metro areas, 20 shops each (1,200 shops total), on top of whatever app.seed
already created. Does NOT touch or delete any existing row.

Run:
    python -m app.scripts.add_bulk_us_campaigns

Not idempotent by design — it always appends another batch. Run it once.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..database import AsyncSessionLocal, init_models
from ..models import (
    Campaign,
    Client,
    EventType,
    Invitation,
    InvitationEvent,
    InvitationStatus,
    Shop,
    Shopper,
)
from ..seed import CHI_LOCALITIES, LA_LOCALITIES, NYC_LOCALITIES, jitter, zip_for

rnd = random.Random(7)

# ---------------- Extra US metros (center-jittered, not per-locality exact — ---
# ---------------- same fidelity tradeoff the shopper rows already use) ------ #
METROS: dict[str, dict] = {
    "Houston": {"state": "TX", "center": (29.7604, -95.3698), "localities": ["Downtown Houston", "Sugar Land", "The Woodlands", "Katy", "Pearland", "Pasadena", "Spring", "Cypress"]},
    "Phoenix": {"state": "AZ", "center": (33.4484, -112.0740), "localities": ["Scottsdale", "Tempe", "Mesa", "Chandler", "Glendale", "Gilbert", "Peoria", "Surprise"]},
    "Philadelphia": {"state": "PA", "center": (39.9526, -75.1652), "localities": ["Center City", "Fishtown", "Manayunk", "Camden", "Cherry Hill", "King of Prussia", "Norristown", "Bensalem"]},
    "San Antonio": {"state": "TX", "center": (29.4241, -98.4936), "localities": ["Downtown San Antonio", "Alamo Heights", "Stone Oak", "Schertz", "New Braunfels", "Boerne", "Converse", "Leon Valley"]},
    "San Diego": {"state": "CA", "center": (32.7157, -117.1611), "localities": ["Gaslamp Quarter", "La Jolla", "Chula Vista", "Carlsbad", "Escondido", "Oceanside", "El Cajon", "National City"]},
    "Dallas": {"state": "TX", "center": (32.7767, -96.7970), "localities": ["Downtown Dallas", "Plano", "Frisco", "Irving", "Arlington", "Grapevine", "McKinney", "Denton"]},
    "Austin": {"state": "TX", "center": (30.2672, -97.7431), "localities": ["Downtown Austin", "Round Rock", "Cedar Park", "Georgetown", "Pflugerville", "San Marcos", "Kyle", "Leander"]},
    "Seattle": {"state": "WA", "center": (47.6062, -122.3321), "localities": ["Downtown Seattle", "Bellevue", "Redmond", "Tacoma", "Everett", "Kirkland", "Renton", "Kent"]},
    "Denver": {"state": "CO", "center": (39.7392, -104.9903), "localities": ["Downtown Denver", "Aurora", "Boulder", "Lakewood", "Littleton", "Centennial", "Westminster", "Arvada"]},
    "Boston": {"state": "MA", "center": (42.3601, -71.0589), "localities": ["Back Bay", "Cambridge", "Somerville", "Quincy", "Brookline", "Newton", "Waltham", "Medford"]},
    "Miami": {"state": "FL", "center": (25.7617, -80.1918), "localities": ["Downtown Miami", "South Beach", "Coral Gables", "Hialeah", "Kendall", "Doral", "Aventura", "Hollywood"]},
    "Atlanta": {"state": "GA", "center": (33.7490, -84.3880), "localities": ["Downtown Atlanta", "Midtown", "Decatur", "Marietta", "Alpharetta", "Sandy Springs", "Roswell", "Smyrna"]},
    "Detroit": {"state": "MI", "center": (42.3314, -83.0458), "localities": ["Downtown Detroit", "Dearborn", "Royal Oak", "Ann Arbor", "Troy", "Southfield", "Warren", "Livonia"]},
    "Minneapolis": {"state": "MN", "center": (44.9778, -93.2650), "localities": ["Downtown Minneapolis", "St. Paul", "Bloomington", "Edina", "Eden Prairie", "Minnetonka", "Plymouth", "Maple Grove"]},
    "Portland": {"state": "OR", "center": (45.5152, -122.6784), "localities": ["Downtown Portland", "Beaverton", "Hillsboro", "Gresham", "Lake Oswego", "Tigard", "Vancouver", "Milwaukie"]},
}

# The 3 flagship metros already have real per-locality coordinates in
# app.seed — reuse them here too so a bulk campaign in New York/Chicago/LA
# looks exactly as tight/precise on the map as Nike's own campaigns do.
FLAGSHIP_METROS = {
    "New York": {"state": "NY", "localities": [(n, s, lat, lng) for n, s, lat, lng in NYC_LOCALITIES]},
    "Chicago": {"state": "IL", "localities": [(n, s, lat, lng) for n, s, lat, lng in CHI_LOCALITIES]},
    "Los Angeles": {"state": "CA", "localities": [(n, s, lat, lng) for n, s, lat, lng in LA_LOCALITIES]},
}
METRO_NAMES = list(FLAGSHIP_METROS.keys()) + list(METROS.keys())

# (brand, category)
BRANDS = [
    ("Target", "Retail"),
    ("Walmart", "Retail"),
    ("Adidas", "Footwear"),
    ("Apple", "Electronics"),
    ("McDonald's", "Food & Beverage"),
    ("Chipotle", "Food & Beverage"),
    ("Home Depot", "Retail"),
    ("Lowe's", "Retail"),
    ("CVS Pharmacy", "Healthcare"),
    ("Walgreens", "Healthcare"),
    ("Kroger", "Grocery"),
    ("Whole Foods", "Grocery"),
    ("GameStop", "Electronics"),
    ("Foot Locker", "Footwear"),
    ("Macy's", "Apparel"),
    ("Dick's Sporting Goods", "Footwear"),
    ("T-Mobile", "Telecom"),
    ("Verizon", "Telecom"),
    ("Panera Bread", "Food & Beverage"),
    ("Dunkin'", "Food & Beverage"),
]

SHOPS_PER_CAMPAIGN = 20


def shop_location(metro_name: str, i: int) -> tuple[str, str, float, float]:
    """Returns (locality_name, state, lat, lng) for the i-th shop in a metro,
    cycling its locality list and jittering coordinates — flagship metros
    jitter a real per-locality coordinate tightly; the rest jitter a wider
    spread around the metro's own center (same fidelity the shopper rows in
    app.seed already use)."""
    if metro_name in FLAGSHIP_METROS:
        localities = FLAGSHIP_METROS[metro_name]["localities"]
        name, state, lat, lng = localities[i % len(localities)]
        lat, lng = jitter((lat, lng), spread=0.006)
        return name, state, lat, lng
    m = METROS[metro_name]
    localities = m["localities"]
    base_name = localities[i % len(localities)]
    suffix = f" #{i // len(localities) + 1}" if i >= len(localities) else ""
    lat, lng = jitter(m["center"], spread=0.08)
    return base_name + suffix, m["state"], lat, lng


async def get_or_create_client(session, cache: dict[str, Client], name: str) -> Client:
    if name in cache:
        return cache[name]
    existing = (await session.execute(select(Client).where(Client.company_name == name))).scalar_one_or_none()
    if existing:
        cache[name] = existing
        return existing
    c = Client(company_name=name, status="active")
    session.add(c)
    await session.flush()
    cache[name] = c
    return c


A, D, O, C, S, DEL = "accepted", "declined", "opened", "clicked", "sent", "delivered"
OTHER_STAGES = [O, C, S, DEL, D]
RANK = {S: 1, DEL: 2, O: 3, C: 4, A: 5, D: 5}


async def build_invitations(session, campaign: Campaign, shops: list[Shop], shopper_pool: list[Shopper], accepted_n: int, other_n: int, ref_start: int, now: datetime) -> tuple[int, int]:
    """Same funnel-building logic as app.seed._build, trimmed to a reusable
    function — creates accepted_n + other_n invitations (with a full event
    cascade each) touching a random subset of this campaign's shops. Returns
    (next_ref_counter, completed_shop_count)."""
    pool = shopper_pool * 3
    shuffled = shops[:]
    rnd.shuffle(shuffled)
    plan: list[tuple[Shopper, Shop, str]] = []
    idx = 0
    for shop in shuffled[:accepted_n]:
        plan.append((pool[idx % len(pool)], shop, A))
        idx += 1
    for j, shop in enumerate(shuffled[accepted_n : accepted_n + other_n]):
        plan.append((pool[idx % len(pool)], shop, OTHER_STAGES[j % len(OTHER_STAGES)]))
        idx += 1

    ref = ref_start
    accepted_shop_ids: set = set()
    for shopper, shop, stage in plan:
        base = now - timedelta(days=rnd.randint(1, 40), hours=rnd.randint(0, 10))
        r = RANK[stage]
        inv = Invitation(
            reference=f"INV-B{ref:05d}",
            campaign=campaign,
            shop=shop,
            shopper=shopper,
            email=shopper.email,
            subject=f"You're invited: {campaign.name}",
            status=stage,
            source="ISN Outreach",
            utm_source="isn",
            utm_medium="email",
            utm_campaign="bulk_demo",
            utm_content="invitation",
            created_at=base,
        )
        ref += 1
        events = [InvitationEvent(invitation=inv, event_type=EventType.INVITATION_CREATED, event_timestamp=base, event_metadata={"source": "ISN", "campaign": campaign.name})]
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
            events.append(InvitationEvent(invitation=inv, event_type=EventType.EMAIL_OPENED, event_timestamp=opened_at, event_metadata={"page": "email_open_pixel"}))
        if r >= 4:
            clicked_at = inv.opened_at + timedelta(minutes=rnd.randint(1, 25))
            inv.clicked_at = clicked_at
            events.append(InvitationEvent(invitation=inv, event_type=EventType.LINK_CLICKED, event_timestamp=clicked_at, event_metadata={"page": "email_cta"}))
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

    return ref, len(accepted_shop_ids)


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        shoppers = (await session.execute(select(Shopper))).scalars().all()
        if not shoppers:
            raise RuntimeError("No shoppers found — run app.seed first.")

        client_cache: dict[str, Client] = {}
        now = datetime.now(timezone.utc)
        ref_counter = 1
        campaigns_created = 0
        shops_created = 0

        # 20 of each bucket, cycling brand and metro for variety.
        plan = [("active", i) for i in range(20)] + [("upcoming", i) for i in range(20)] + [("completed", i) for i in range(20)]

        for n, (status, i) in enumerate(plan):
            brand, category = BRANDS[n % len(BRANDS)]
            metro_name = METRO_NAMES[n % len(METRO_NAMES)]
            client = await get_or_create_client(session, client_cache, brand)

            if status == "active":
                visit_start = now - timedelta(days=rnd.randint(0, 5))
                visit_end = now + timedelta(days=rnd.randint(5, 20))
                name_suffix = "Store Audit"
            elif status == "upcoming":
                visit_start = now + timedelta(days=rnd.randint(20, 60))
                visit_end = visit_start + timedelta(days=rnd.randint(10, 20))
                name_suffix = "Launch Recruitment"
            else:
                visit_end = now - timedelta(days=rnd.randint(5, 40))
                visit_start = visit_end - timedelta(days=rnd.randint(10, 20))
                name_suffix = "Store Audit"

            campaign = Campaign(
                name=f"{brand} {metro_name} {name_suffix} #{i + 1}",
                client_name=brand,
                client_id=client.id,
                description=f"{'Recruiting shoppers ahead of' if status == 'upcoming' else 'Retail experience & compliance audit across'} {brand} stores in the {metro_name} area.",
                status=status,
                deadline=visit_end,
            )
            session.add(campaign)
            await session.flush()

            shops: list[Shop] = []
            for si in range(SHOPS_PER_CAMPAIGN):
                loc_name, state, lat, lng = shop_location(metro_name, si)
                shops.append(
                    Shop(
                        campaign=campaign,
                        shop_name=f"{brand} — {loc_name}",
                        address=f"{rnd.randint(100, 999)} Main St, {loc_name}, {state}",
                        city=loc_name,
                        state=state,
                        latitude=lat,
                        longitude=lng,
                        required_shoppers=rnd.randint(1, 3),
                        compensation=rnd.randint(15, 45),
                        currency="USD",
                        category=category,
                        visit_start=visit_start,
                        visit_end=visit_end,
                        status="open",
                    )
                )
            session.add_all(shops)
            await session.flush()
            campaign.total_shops = len(shops)

            if status == "active":
                accepted_n, other_n = rnd.randint(4, 8), rnd.randint(6, 10)
            elif status == "upcoming":
                accepted_n, other_n = 0, rnd.randint(4, 8)
            else:
                accepted_n, other_n = rnd.randint(15, 19), rnd.randint(0, 2)

            ref_counter, completed = await build_invitations(session, campaign, shops, list(shoppers), accepted_n, other_n, ref_counter, now)
            campaign.completed_shops = completed
            campaign.remaining_shops = campaign.total_shops - completed

            campaigns_created += 1
            shops_created += len(shops)

        await session.commit()
        print(f"Added {campaigns_created} campaigns ({shops_created} shops) across {len(client_cache)} brands.")


if __name__ == "__main__":
    asyncio.run(run())
