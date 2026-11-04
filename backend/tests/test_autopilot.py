"""AI Autopilot: it recruits for every open shop inside guardrails, and does nothing until switched on.

Seed data varies, so assertions are relative to what each shop actually needs."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import Campaign, EmailComposition, EmailJob, Invitation, Shop, ShopBonus
from app.services.autopilot import resolve_guardrails, run_autopilot_cycle
from tests.test_acceptance import _fresh_db
from tests.test_bulk_invitations import _login


async def _count(model, *where) -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count(model.id)).where(*where)) or 0


async def _recruitable_campaign(client: AsyncClient, auth: dict) -> dict:
    """A campaign where a (dry-run) autopilot pass would actually invite someone."""
    for campaign in (await client.get("/api/campaigns", headers=auth)).json()["items"]:
        r = await client.post(f"/api/autopilot/campaigns/{campaign['id']}/run", headers=auth, json={"dry_run": True, "mode": "review"})
        if r.json()["totals"].get("invited", 0) >= 2:
            return campaign
    pytest.skip("seed has no campaign the autopilot can recruit for")


def _run(client, auth, campaign, **body):
    return client.post(f"/api/autopilot/campaigns/{campaign['id']}/run", headers=auth, json=body)


@pytest.mark.asyncio
async def test_autopilot_is_off_by_default_and_does_nothing():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = (await client.get("/api/campaigns", headers=auth)).json()["items"][0]
        cfg = (await client.get(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth)).json()
        assert cfg["effective"]["mode"] == "off"

        before = await _count(Invitation)
        report = (await _run(client, auth, campaign, dry_run=False)).json()
        assert report.get("skipped") and not report["shops"]
        assert await _count(Invitation) == before


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        before = (await _count(Invitation), await _count(ShopBonus), await _count(EmailJob))
        report = (await _run(client, auth, campaign, dry_run=True, mode="auto")).json()
        assert report["dry_run"] and report["totals"]["invited"] >= 2
        assert (await _count(Invitation), await _count(ShopBonus), await _count(EmailJob)) == before


@pytest.mark.asyncio
async def test_review_mode_invites_exactly_what_each_shop_needs_and_sends_nothing():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        cid = campaign["id"]
        shops = (await client.get(f"/api/campaigns/{cid}/shops", headers=auth)).json()["items"]
        open_before = {s["id"]: s["open_slots"] for s in shops}

        report = (await _run(client, auth, campaign, dry_run=False, mode="review")).json()
        assert report["mode"] == "review" and report["totals"]["emailed"] == 0
        assert await _count(EmailJob) == 0

        after = (await client.get(f"/api/campaigns/{cid}/shops", headers=auth)).json()["items"]
        for s in after:
            # Never more than the shop needed, so nothing is over-selected.
            assert s["selected_shoppers"] <= s["required_shoppers"]
            assert s["open_slots"] <= open_before[s["id"]]
        async with AsyncSessionLocal() as session:
            created = (await session.execute(select(Invitation).where(Invitation.source == "AI Autopilot"))).scalars().all()
            assert created and all(i.status == "created" and i.sent_at is None for i in created)

        # A second pass finds nothing left that it can still fill: no duplicate invitations.
        invites = await _count(Invitation)
        again = (await _run(client, auth, campaign, dry_run=False, mode="review")).json()
        assert again["totals"]["invited"] == 0 or await _count(Invitation) == invites + again["totals"]["invited"]
        assert (await client.get(f"/api/autopilot/campaigns/{cid}", headers=auth)).json()["last_report"]


@pytest.mark.asyncio
async def test_auto_mode_queues_a_personalised_email_per_invitation():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        report = (await _run(client, auth, campaign, dry_run=False, mode="auto")).json()
        invited = report["totals"]["invited"]
        assert invited >= 2 and report["totals"]["emailed"] == invited
        assert await _count(EmailJob, EmailJob.status == "queued") == invited
        async with AsyncSessionLocal() as session:
            comps = (await session.execute(select(EmailComposition))).scalars().all()
            assert len(comps) == invited
            assert all("{{assignment_link}}" in c.html_template and "Hi " in c.html_template for c in comps)


@pytest.mark.asyncio
async def test_guardrails_stop_it_instead_of_forcing_a_fill():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        # A tiny radius and no bonus allowed: nothing can be reached, so shops are flagged, not filled.
        r = await client.put(
            f"/api/autopilot/campaigns/{campaign['id']}",
            headers=auth,
            json={"mode": "review", "max_radius_km": 0.1, "max_bonus_multiplier": 0, "fill_every_shop": False},
        )
        assert r.status_code == 200, r.text
        report = (await _run(client, auth, campaign, dry_run=False)).json()
        assert report["totals"]["invited"] == 0 and report["totals"]["needs_attention"] > 0
        assert await _count(ShopBonus, ShopBonus.created_by == "AI Autopilot") == 0
        flagged = [s for s in report["shops"] if s["state"] == "needs_attention"]
        assert flagged and all("limit" in s["reason"] or "bonus" in s["reason"] for s in flagged)


@pytest.mark.asyncio
async def test_it_raises_a_bonus_within_the_ceiling_when_the_radius_is_capped():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        # The radius can't grow, but a bonus pays for the trip — so the autopilot spends one, within 3x the pay.
        await client.put(
            f"/api/autopilot/campaigns/{campaign['id']}",
            headers=auth,
            json={"mode": "review", "max_radius_km": 0.1, "max_bonus_multiplier": 3, "fill_every_shop": False},
        )
        report = (await _run(client, auth, campaign, dry_run=False)).json()
        bonuses = [s for s in report["shops"] if s["bonus"]]
        assert bonuses and report["totals"]["invited"] > 0
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(ShopBonus).where(ShopBonus.created_by == "AI Autopilot"))).scalars().all()
            assert rows
            for b in rows:
                shop = await session.get(Shop, b.shop_id)
                assert 0 < b.amount <= max(10, round(3 * (shop.compensation or 40) / 5) * 5)


@pytest.mark.asyncio
async def test_a_shopper_who_declined_is_never_asked_again():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        first = (await _run(client, auth, campaign, dry_run=False, mode="review")).json()
        shop_entry = next(s for s in first["shops"] if s["invited"])
        declined_id = uuid.UUID(shop_entry["invited"][0]["shopper_id"])
        async with AsyncSessionLocal() as session:
            inv = await session.scalar(
                select(Invitation).where(Invitation.shop_id == uuid.UUID(shop_entry["shop_id"]), Invitation.shopper_id == declined_id)
            )
            inv.response = "declined"
            await session.commit()

        again = (await _run(client, auth, campaign, dry_run=False, mode="review")).json()
        replaced = next(s for s in again["shops"] if s["shop_id"] == shop_entry["shop_id"])
        ids = {p["shopper_id"] for p in replaced["invited"]}
        assert str(declined_id) not in ids and len(ids) <= 1  # one slot reopened, filled by someone else


@pytest.mark.asyncio
async def test_the_scheduler_covers_new_campaigns_through_the_client_default():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        template = await _recruitable_campaign(client, auth)

    async with AsyncSessionLocal() as session:
        source = await session.get(Campaign, uuid.UUID(template["id"]))
        shop = (await session.execute(select(Shop).where(Shop.campaign_id == source.id).limit(1))).scalar_one()
        # A campaign that arrives later (as if synced through the API) for the same client.
        new = Campaign(name="Synced later", client_name=source.client_name, client_id=source.client_id, status="active")
        session.add(new)
        await session.flush()
        session.add(
            Shop(
                campaign_id=new.id, shop_name="Synced shop", city=shop.city, state=shop.state, latitude=shop.latitude,
                longitude=shop.longitude, required_shoppers=2, compensation=30, currency="USD", category=shop.category,
            )
        )
        await session.commit()
        new_id, client_id = new.id, source.client_id
        assert client_id is not None

    # Nothing is on yet: a cycle touches nothing.
    assert (await run_autopilot_cycle())["ran"] == 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        r = await client.put(f"/api/autopilot/defaults?client_id={client_id}", headers=auth, json={"mode": "review"})
        assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as session:
        assert (await resolve_guardrails(session, await session.get(Campaign, new_id))).sources["mode"] == "client"

    result = await run_autopilot_cycle()
    assert result["ran"] >= 1 and result["failed"] == 0
    assert await _count(Invitation, Invitation.campaign_id == new_id, Invitation.source == "AI Autopilot") >= 1
    # Within the minimum interval a second cycle leaves everything alone.
    assert (await run_autopilot_cycle())["ran"] == 0


@pytest.mark.asyncio
async def test_a_campaign_override_beats_the_client_default():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = (await client.get("/api/campaigns", headers=auth)).json()["items"][0]
        async with AsyncSessionLocal() as session:
            client_id = (await session.get(Campaign, uuid.UUID(campaign["id"]))).client_id
        assert client_id is not None
        await client.put(f"/api/autopilot/defaults?client_id={client_id}", headers=auth, json={"mode": "auto"})
        await client.put(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth, json={"mode": "off"})
        eff = (await client.get(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth)).json()["effective"]
        assert eff["mode"] == "off" and eff["sources"]["mode"] == "campaign"
        # Clearing the override goes back to inheriting.
        await client.put(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth, json={"mode": None})
        eff = (await client.get(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth)).json()["effective"]
        assert eff["mode"] == "auto" and eff["sources"]["mode"] == "client"


@pytest.mark.asyncio
async def test_invalid_settings_are_rejected():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = (await client.get("/api/campaigns", headers=auth)).json()["items"][0]
        url = f"/api/autopilot/campaigns/{campaign['id']}"
        assert (await client.put(url, headers=auth, json={"mode": "yolo"})).status_code == 400
        assert (await client.put(url, headers=auth, json={"max_radius_km": -5})).status_code == 422
        assert (await client.put(url, headers=auth, json={"min_match_score": 500})).status_code == 422


@pytest.mark.asyncio
async def test_one_shopper_is_never_lined_up_for_two_shops_in_a_run():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        await client.put(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth, json={"fill_every_shop": False})
        report = (await _run(client, auth, campaign, dry_run=True, mode="review")).json()
        ids = [p["shopper_id"] for s in report["shops"] for p in s["invited"]]
        assert ids and len(ids) == len(set(ids))


# ---------------------------------------------------------------------------------------------------------------
# "Fill every shop": it goes past the comfortable limits instead of stopping, and never reports an error state.
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fill_every_shop_leaves_nothing_that_needs_attention():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        strict = (
            await client.put(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth, json={"fill_every_shop": False})
        ).json()
        assert strict["effective"]["fill_every_shop"] is False
        before = (await _run(client, auth, campaign, dry_run=True, mode="review")).json()["totals"]

        await client.put(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth, json={"fill_every_shop": None})
        eff = (await client.get(f"/api/autopilot/campaigns/{campaign['id']}", headers=auth)).json()["effective"]
        assert eff["fill_every_shop"] is True  # the default
        after = (await _run(client, auth, campaign, dry_run=True, mode="review")).json()
        t = after["totals"]
        assert t["needs_attention"] == 0 and t["partial"] == 0
        assert t["invited"] >= before["invited"]
        assert t["staffed"] + t["searching"] + t["already_filled"] == t["shops_checked"]
        # Nobody is lined up for more shops than the limit allows.
        per_shopper: dict[str, int] = {}
        for shop in after["shops"]:
            for p in shop["invited"]:
                per_shopper[p["shopper_id"]] = per_shopper.get(p["shopper_id"], 0) + 1
        assert per_shopper and max(per_shopper.values()) <= eff["max_shops_per_shopper"]


@pytest.mark.asyncio
async def test_it_stretches_past_the_radius_limit_and_pays_for_the_trip():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign = await _recruitable_campaign(client, auth)
        await client.put(
            f"/api/autopilot/campaigns/{campaign['id']}",
            headers=auth,
            json={"mode": "review", "max_radius_km": 0.1, "max_bonus_multiplier": 3, "fill_every_shop": True},
        )
        report = (await _run(client, auth, campaign, dry_run=False)).json()
        assert report["totals"]["needs_attention"] == 0 and report["totals"]["invited"] > 0
        stretched = [s for s in report["shops"] if any(a.get("stretch") for a in s["actions"])]
        assert stretched
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(ShopBonus).where(ShopBonus.created_by == "AI Autopilot"))).scalars().all()
            for b in rows:  # the travel bonus never passes the ceiling
                shop = await session.get(Shop, b.shop_id)
                assert b.amount <= max(10, round(3 * (shop.compensation or 40) / 5) * 5)


@pytest.mark.asyncio
async def test_a_shop_nobody_can_fill_is_searched_for_not_flagged_as_an_error():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        template = await _recruitable_campaign(client, auth)
        async with AsyncSessionLocal() as session:
            source = await session.get(Campaign, uuid.UUID(template["id"]))
            shop = (await session.execute(select(Shop).where(Shop.campaign_id == source.id).limit(1))).scalar_one()
            big = Campaign(name="Huge need", client_name=source.client_name, client_id=source.client_id, status="active")
            session.add(big)
            await session.flush()
            session.add(
                Shop(
                    campaign_id=big.id, shop_name="Needs everyone", city=shop.city, state=shop.state, latitude=shop.latitude,
                    longitude=shop.longitude, required_shoppers=500, compensation=30, currency="USD", category=shop.category,
                    allow_over_selection=True,
                )
            )
            await session.commit()
            big_id = str(big.id)

        report = (await _run(client, auth, {"id": big_id}, dry_run=True, mode="review")).json()
        shop_report = next(s for s in report["shops"] if s["shop_name"] == "Needs everyone")
        assert shop_report["state"] == "searching" and "keeps trying" in shop_report["reason"]
        assert report["totals"]["needs_attention"] == 0 and report["totals"]["searching"] == 1
        assert shop_report["invited"], "everyone eligible is still lined up, the rest is searched for"


@pytest.mark.asyncio
async def test_no_shopper_is_buried_under_invitations_across_campaigns(monkeypatch):
    from app.config import settings

    await _fresh_db()
    monkeypatch.setattr(settings, "autopilot_max_open_per_shopper", 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaigns = (await client.get("/api/campaigns", headers=auth)).json()["items"]
        # Run several campaigns for real (review mode): the cap is global, not per campaign.
        for campaign in campaigns[:6]:
            r = await _run(client, auth, campaign, dry_run=False, mode="review")
            assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as session:
        autopilot = dict(
            (
                await session.execute(
                    select(Invitation.shopper_id, func.count(Invitation.id))
                    .where(Invitation.source == "AI Autopilot")
                    .group_by(Invitation.shopper_id)
                )
            ).all()
        )
    assert autopilot, "the autopilot should still have invited people"
    # Whoever the autopilot picked got at most one new invitation, however many campaigns and shops it ran for.
    assert max(autopilot.values()) <= 1
