"""Idempotent seed extension: populates the Upcoming and Completed campaign
portals using the SAME database/schema the Active portal already uses.

This does NOT touch or delete any existing campaign, shop, shopper,
invitation or event — it only adds campaigns that don't already exist (by
name) and, for completed campaigns, realistic historical invitations/events
anchored before each campaign's completion date.

Run:
    python -m app.seed_demo_data

Safe to run multiple times: every campaign is looked up by name first, and
is skipped entirely if already present.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .database import AsyncSessionLocal, init_models
from .models import Campaign, EventType, Invitation, InvitationEvent, InvitationStatus, Shop, Shopper

rnd = random.Random(7)

MUMBAI = {
    "Andheri": (19.1197, 72.8468),
    "Bandra": (19.0596, 72.8295),
    "Powai": (19.1176, 72.9060),
    "Lower Parel": (18.9958, 72.8258),
    "Borivali": (19.2307, 72.8567),
    "Thane": (19.2183, 72.9781),
    "Navi Mumbai": (19.0330, 73.0297),
    "Malad": (19.1874, 72.8484),
    "Vashi": (19.0771, 73.0000),
    "Ghatkopar": (19.0857, 72.9081),
    "Worli": (19.0176, 72.8163),
    "Juhu": (19.1075, 72.8263),
    "Colaba": (18.9067, 72.8147),
}
PUNE = {
    "FC Road": (18.5236, 73.8478),
    "Baner": (18.5590, 73.7868),
    "Koregaon Park": (18.5362, 73.8940),
    "Viman Nagar": (18.5679, 73.9143),
    "Hinjewadi": (18.5908, 73.7389),
    "Kothrud": (18.5074, 73.8077),
    "Wakad": (18.5978, 73.7649),
}
NASHIK = {
    "College Road": (19.9975, 73.7898),
    "Gangapur Road": (20.0059, 73.7519),
    "Panchavati": (20.0112, 73.7903),
}
STATE_FOR_CITY = {"Mumbai": "Maharashtra", "Pune": "Maharashtra", "Nashik": "Maharashtra"}


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in text).strip("_")


def make_shop(
    campaign: Campaign,
    client: str,
    city: str,
    locality: str,
    coords: tuple[float, float],
    category: str,
    compensation: int,
    required: int,
    visit_start: datetime,
    visit_end: datetime,
    status: str = "open",
) -> Shop:
    lat, lon = coords
    return Shop(
        campaign=campaign,
        shop_name=f"{client} {city} — {locality}",
        address=f"{rnd.randint(1, 200)} {locality} Road",
        city=city,
        state=STATE_FOR_CITY[city],
        latitude=lat + rnd.uniform(-0.003, 0.003),
        longitude=lon + rnd.uniform(-0.003, 0.003),
        required_shoppers=required,
        compensation=compensation,
        currency="INR",
        category=category,
        visit_start=visit_start,
        visit_end=visit_end,
        status=status,
    )


async def _existing_campaign_names(session) -> set[str]:
    rows = (await session.execute(select(Campaign.name))).scalars().all()
    return set(rows)


async def _next_ref_start(session) -> int:
    count = await session.scalar(select(func.count(Invitation.id)))
    return int(count or 0) + 1


def _add_invitation_with_events(
    session,
    ref_n: int,
    campaign: Campaign,
    shop: Shop,
    shopper: Shopper,
    stage: str,
    anchor: datetime,
) -> None:
    """Mirrors app/seed.py's funnel-event builder, anchored to `anchor`
    (a past completion date) instead of "now" — every timestamp lands
    strictly before `anchor`, which itself is in the past."""
    A, D, O, C, S, DEL = "accepted", "declined", "opened", "clicked", "sent", "delivered"
    rank = {S: 1, DEL: 2, O: 3, C: 4, A: 5, D: 5}
    r = rank[stage]

    base = anchor - timedelta(days=rnd.randint(4, 26), hours=rnd.randint(0, 10))
    inv = Invitation(
        reference=f"INV-{ref_n:04d}",
        campaign=campaign,
        shop=shop,
        shopper=shopper,
        email=shopper.email,
        subject=f"You're invited: {campaign.name}",
        status=stage,
        source="ISN Outreach",
        utm_source="isn",
        utm_medium="email",
        utm_campaign=_slug(campaign.name),
        utm_content="invitation",
        created_at=base,
    )
    events = [
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
        else:
            inv.response = "declined"
            inv.status = InvitationStatus.DECLINED
            events.append(InvitationEvent(invitation=inv, event_type=EventType.ASSIGNMENT_DECLINED, event_timestamp=responded_at, event_metadata={"page": "shopper_landing"}))

    # Ensure the invitation is never dated after its own campaign's completion.
    assert base < anchor

    session.add(inv)
    session.add_all(events)


async def _build_upcoming(session, existing: set[str]) -> list[Campaign]:
    created: list[Campaign] = []

    def add(name, client, description, deadline):
        if name in existing:
            return None
        c = Campaign(name=name, client_name=client, description=description, status="upcoming", deadline=deadline)
        session.add(c)
        created.append(c)
        return c

    adidas = add(
        "Adidas Mumbai Customer Experience Audit",
        "Adidas",
        "Retail experience & product knowledge audit across Adidas stores in Mumbai.",
        datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc),
    )
    if adidas:
        window = (datetime(2026, 9, 20, tzinfo=timezone.utc), datetime(2026, 9, 30, tzinfo=timezone.utc))
        localities = ["Andheri", "Bandra", "Powai", "Lower Parel", "Borivali", "Thane", "Navi Mumbai", "Malad"]
        shops = [
            make_shop(adidas, "Adidas", "Mumbai", loc, MUMBAI[loc], "Footwear", 1400, 2, *window)
            for loc in localities
        ]
        session.add_all(shops)
        adidas.total_shops = len(shops)
        adidas.remaining_shops = len(shops)

    reliance = add(
        "Reliance Digital Pune Retail Audit",
        "Reliance Digital",
        "Electronics retail experience and staff product-knowledge audit across Pune stores.",
        datetime(2026, 10, 5, 18, 0, tzinfo=timezone.utc),
    )
    if reliance:
        window = (datetime(2026, 9, 25, tzinfo=timezone.utc), datetime(2026, 10, 5, tzinfo=timezone.utc))
        localities = ["FC Road", "Baner", "Koregaon Park", "Viman Nagar", "Hinjewadi"]
        shops = [
            make_shop(reliance, "Reliance Digital", "Pune", loc, PUNE[loc], "Electronics", 1500, 2, *window)
            for loc in localities
        ]
        session.add_all(shops)
        reliance.total_shops = len(shops)
        reliance.remaining_shops = len(shops)

    sbux_upcoming = add(
        "Starbucks Mumbai Service Quality Audit",
        "Starbucks",
        "Service quality and store experience audit across Mumbai cafes.",
        datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc),
    )
    if sbux_upcoming:
        window = (datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc))
        localities = ["Bandra", "Andheri", "Powai", "Worli", "Juhu", "Ghatkopar"]
        shops = [
            make_shop(sbux_upcoming, "Starbucks", "Mumbai", loc, MUMBAI[loc], "Cafe", 1250, 2, *window)
            for loc in localities
        ]
        session.add_all(shops)
        sbux_upcoming.total_shops = len(shops)
        sbux_upcoming.remaining_shops = len(shops)

    croma_upcoming = add(
        "Croma Maharashtra Electronics Audit",
        "Croma (Tata)",
        "Statewide electronics retail mystery shopping across Maharashtra.",
        datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc),
    )
    if croma_upcoming:
        window = (datetime(2026, 10, 10, tzinfo=timezone.utc), datetime(2026, 10, 20, tzinfo=timezone.utc))
        picks = [
            ("Mumbai", "Ghatkopar"), ("Mumbai", "Malad"), ("Mumbai", "Vashi"),
            ("Pune", "Kothrud"), ("Pune", "Wakad"),
            ("Nashik", "Gangapur Road"), ("Nashik", "Panchavati"),
        ]
        coords = {"Mumbai": MUMBAI, "Pune": PUNE, "Nashik": NASHIK}
        shops = [
            make_shop(croma_upcoming, "Croma", city, loc, coords[city][loc], "Electronics", 1550, 2, *window)
            for city, loc in picks
        ]
        session.add_all(shops)
        croma_upcoming.total_shops = len(shops)
        croma_upcoming.remaining_shops = len(shops)

    await session.flush()

    # A little early recruitment activity on one upcoming campaign only, so
    # the portal shows a mix of "Not Started" and "In Progress" recruitment
    # rather than every upcoming campaign looking identical.
    if reliance:
        shoppers = (await session.execute(select(Shopper).where(Shopper.city == "Pune"))).scalars().all()
        ref = await _next_ref_start(session)
        anchor = datetime.now(timezone.utc)
        reliance_shops = [s for s in (await session.execute(select(Shop).where(Shop.campaign_id == reliance.id))).scalars().all()]
        for i, shopper in enumerate(shoppers[:3]):
            stage = "opened" if i % 2 == 0 else "sent"
            _add_invitation_with_events(session, ref, reliance, reliance_shops[i % len(reliance_shops)], shopper, stage, anchor + timedelta(days=1))
            ref += 1

    return created


async def _build_completed(session, existing: set[str]) -> list[Campaign]:
    created: list[Campaign] = []

    def add(name, client, description, completion_date):
        if name in existing:
            return None
        c = Campaign(
            name=name,
            client_name=client,
            description=description,
            status="completed",
            deadline=completion_date,
        )
        session.add(c)
        created.append((c, completion_date))
        return c

    apple = add(
        "Apple Store Experience Audit",
        "Apple",
        "Retail experience and product-knowledge audit across Apple stores.",
        datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc),
    )
    amazon = add(
        "Amazon Delivery Experience Audit",
        "Amazon",
        "Delivery and customer-service experience audit across Amazon partner retail points.",
        datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc),
    )
    croma_done = add(
        "Tata Croma Retail Experience Audit",
        "Croma (Tata)",
        "Retail experience and staff knowledge audit across Croma electronics stores.",
        datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc),
    )
    mcdonalds = add(
        "McDonald's Customer Experience Audit",
        "McDonald's",
        "Customer experience, cleanliness and service speed audit across outlets.",
        datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc),
    )
    await session.flush()

    all_shoppers = (await session.execute(select(Shopper))).scalars().all()
    if not all_shoppers:
        return [c for c, _ in created]

    def cycle_shoppers():
        i = 0
        while True:
            yield all_shoppers[i % len(all_shoppers)]
            i += 1

    ref_counter = await _next_ref_start(session)

    async def build_campaign(campaign, completion_date, city_localities, client, category, comp, shop_count, funnel):
        nonlocal ref_counter
        if campaign is None:
            return
        visit_end = completion_date - timedelta(days=1)
        visit_start = visit_end - timedelta(days=6)
        shops = []
        for i in range(shop_count):
            city, loc, coords = city_localities[i % len(city_localities)]
            shops.append(
                make_shop(campaign, client, city, f"{loc} #{i // len(city_localities) + 1}" if shop_count > len(city_localities) else loc,
                          coords, category, comp, rnd.randint(1, 2), visit_start, visit_end, status="completed")
            )
        session.add_all(shops)
        campaign.total_shops = len(shops)
        await session.flush()

        gen = cycle_shoppers()
        stage_pool = funnel  # list of stage labels, one per invitation
        shop_i = 0
        accepted_shops: set = set()
        for stage in stage_pool:
            shopper = next(gen)
            shop = shops[shop_i % len(shops)]
            shop_i += 1
            _add_invitation_with_events(session, ref_counter, campaign, shop, shopper, stage, completion_date)
            ref_counter += 1
            if stage == "accepted":
                accepted_shops.add(shop.id)

        # Guarantee every shop has at least one accepted invitation (100%
        # shop completion for a *completed* campaign) without inflating the
        # funnel numbers already spent above.
        for shop in shops:
            if shop.id not in accepted_shops:
                shopper = next(gen)
                _add_invitation_with_events(session, ref_counter, campaign, shop, shopper, "accepted", completion_date)
                ref_counter += 1
                accepted_shops.add(shop.id)

        campaign.completed_shops = len(shops)
        campaign.remaining_shops = 0

    def funnel(sent, delivered, opened, clicked, accepted, declined):
        # Build a stage-per-invitation list matching the requested funnel
        # counts exactly (each stage below implies all prior stages too, per
        # the existing rank-based event builder).
        n_sent_only = sent - delivered
        n_delivered_only = delivered - opened
        n_opened_only = opened - clicked
        n_clicked_only = clicked - accepted - declined
        stages = (
            ["sent"] * max(0, n_sent_only)
            + ["delivered"] * max(0, n_delivered_only)
            + ["opened"] * max(0, n_opened_only)
            + ["clicked"] * max(0, n_clicked_only)
            + ["accepted"] * accepted
            + ["declined"] * declined
        )
        rnd.shuffle(stages)
        return stages

    await build_campaign(
        apple, datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc),
        [("Mumbai", "Bandra", MUMBAI["Bandra"]), ("Mumbai", "Powai", MUMBAI["Powai"]), ("Pune", "Koregaon Park", PUNE["Koregaon Park"]),
         ("Nashik", "College Road", NASHIK["College Road"])],
        "Apple", "Electronics", 1800, 10,
        funnel(30, 29, 24, 19, 14, 5),
    )
    await build_campaign(
        amazon, datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc),
        [("Mumbai", "Vashi", MUMBAI["Vashi"]), ("Mumbai", "Ghatkopar", MUMBAI["Ghatkopar"]), ("Pune", "Wakad", PUNE["Wakad"]),
         ("Pune", "Hinjewadi", PUNE["Hinjewadi"]), ("Nashik", "Gangapur Road", NASHIK["Gangapur Road"])],
        "Amazon", "Retail", 1300, 15,
        funnel(45, 44, 35, 27, 20, 7),
    )
    await build_campaign(
        croma_done, datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc),
        [("Mumbai", "Malad", MUMBAI["Malad"]), ("Mumbai", "Thane", MUMBAI["Thane"]), ("Pune", "Baner", PUNE["Baner"]),
         ("Nashik", "Panchavati", NASHIK["Panchavati"])],
        "Croma", "Electronics", 1600, 12,
        funnel(36, 35, 28, 21, 16, 5),
    )
    await build_campaign(
        mcdonalds, datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc),
        [("Mumbai", "Andheri", MUMBAI["Andheri"]), ("Mumbai", "Juhu", MUMBAI["Juhu"]), ("Pune", "FC Road", PUNE["FC Road"])],
        "McDonald's", "Food Service", 800, 8,
        funnel(24, 23, 18, 14, 10, 4),
    )

    return [c for c, _ in created]


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        existing = await _existing_campaign_names(session)
        upcoming_created = await _build_upcoming(session, existing)
        # Re-fetch names so the completed pass also skips anything the
        # upcoming pass just added (defensive; names don't overlap today).
        existing2 = await _existing_campaign_names(session)
        completed_created = await _build_completed(session, existing2)
        await session.commit()

    print(f"Upcoming campaigns created: {[c.name for c in upcoming_created] or 'none (already present)'}")
    print(f"Completed campaigns created: {[c.name for c in completed_created] or 'none (already present)'}")


if __name__ == "__main__":
    asyncio.run(run())
