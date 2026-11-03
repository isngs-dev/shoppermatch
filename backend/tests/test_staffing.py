"""Staffing status (filled / ready / short) and the bonus recommendation that goes with a shortfall.

The rule is shared by the AI Recommendations page and Auto Assign, so it is checked in one place here and
through both endpoints. The seed's invitations vary, so API assertions are relative to each shop's own state."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.staffing import (
    FILLED,
    KM_PER_BONUS_DOLLAR,
    READY,
    SHORT,
    assess_staffing,
    bonus_ceiling,
    effective_radius,
    suggest_bonus,
)
from tests.test_acceptance import _fresh_db
from tests.test_bulk_invitations import _login


def _shop(required=2, compensation=30):
    return SimpleNamespace(required_shoppers=required, compensation=compensation, currency="USD")


def _assess(shop, **kw):
    args = dict(already_selected=0, recommended=0, eligible_count=0, outside_radius=0, radius_km=25.0, bonus=None)
    return assess_staffing(shop, **{**args, **kw})


def test_filled_when_every_slot_is_taken():
    s = _assess(_shop(2), already_selected=2)
    assert s["state"] == FILLED and s["slots_open"] == 0 and not s["bonus_recommended"]


def test_ready_when_the_ai_found_enough():
    s = _assess(_shop(2), already_selected=1, recommended=1, eligible_count=4)
    assert s["state"] == READY and s["shortfall"] == 0 and not s["bonus_recommended"]


def test_short_recommends_a_bonus_whatever_the_reason():
    # Nobody eligible at all, and nobody further out either: widening the radius is pointless.
    s = _assess(_shop(2), recommended=0, eligible_count=0, outside_radius=0)
    assert s["state"] == SHORT and s["shortfall"] == 2
    assert s["bonus_recommended"] and s["suggested_bonus"]["amount"] > 0
    assert s["can_expand_radius"] is False and "no eligible" in s["reason"].lower()

    # Partly filled, with more shoppers just outside the radius: expanding can still help, bonus still offered.
    s = _assess(_shop(3), recommended=1, eligible_count=1, outside_radius=5, outside_distances=[40, 55, 60, 70, 90])
    assert s["state"] == SHORT and s["shortfall"] == 2 and s["recommended"] == 1
    assert s["can_expand_radius"] is True and s["bonus_recommended"]


def test_widening_jumps_straight_to_the_radius_that_reaches_enough_shoppers():
    # Two shoppers are missing; the 2nd-nearest outside is 80 km away, so one click goes to 100 km (not +25).
    s = _assess(_shop(2), radius_km=25.0, recommended=0, outside_radius=3, outside_distances=[60, 80, 140])
    assert s["can_expand_radius"] and s["next_radius_km"] == 100.0 and not s["recruit_locally"] and not s["far"]
    # Only one shopper is outside: go as far as that one.
    s = _assess(_shop(2), radius_km=25.0, recommended=0, outside_radius=1, outside_distances=[60])
    assert s["next_radius_km"] == 75.0


def test_a_far_away_pool_can_still_be_reached_but_is_flagged_and_paired_with_local_recruiting():
    # Portland-style: the nearest shopper is ~1,300 km away. Widening does reach them (so shoppers get
    # recommended), but it is flagged as a long trip and local recruiting is suggested alongside.
    far = [1336.3, 1500.0, 2800.0]
    s = _assess(_shop(2), recommended=0, eligible_count=0, outside_radius=3, outside_distances=far)
    assert s["state"] == SHORT and s["can_expand_radius"] is True and s["far"] is True
    assert s["next_radius_km"] == 1500.0 and s["nearest_outside_km"] == 1336.3
    assert s["recruit_locally"] is True and "long trip" in s["reason"]
    assert s["bonus_recommended"] is True and s["suggested_bonus"]["fills_gap"] is False
    # An existing bonus is not raised again and again when it wouldn't reach anyone.
    s = _assess(_shop(2), recommended=0, eligible_count=0, outside_radius=3, outside_distances=far, bonus=SimpleNamespace(amount=70))
    assert s["bonus_recommended"] is False and s["recruit_locally"] is True


def test_a_bonus_extends_how_far_the_matching_looks():
    assert effective_radius(25, 20) == 25 + 20 * KM_PER_BONUS_DOLLAR and effective_radius(None, 50) is None
    # The nearest missing shopper is 300 km out: the suggested bonus is big enough that its reach gets there.
    b = suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=2, eligible=0, base_radius=25.0, needed_km=300.0)
    assert b["fills_gap"] is True and 25 + b["reach_km"] >= 300 and b["amount"] <= bonus_ceiling(30)
    # Further than any allowed bonus can reach: still a suggestion, but it says it won't fill the gap alone.
    b = suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=2, eligible=0, base_radius=25.0, needed_km=5000.0)
    assert b["fills_gap"] is False and b["amount"] <= bonus_ceiling(30)
    # With a bonus already set, the shop's own reach is what is left to cover by widening.
    s = _assess(_shop(2), radius_km=25.0, recommended=0, outside_radius=1, outside_distances=[400.0], bonus=SimpleNamespace(amount=20))
    assert s["bonus_reach_km"] == 200 and s["next_radius_km"] == 200.0


def test_a_bonus_is_never_raised_past_the_ceiling():
    assert bonus_ceiling(30) == 90
    capped = suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=2, eligible=1, existing_amount=70)
    assert capped["amount"] == 90
    assert suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=2, eligible=1, existing_amount=90) is None
    s = _assess(_shop(2, 30), recommended=0, eligible_count=1, outside_radius=0, bonus=SimpleNamespace(amount=95))
    assert s["bonus_maxed"] is True and s["bonus_recommended"] is False


def test_bonus_scales_with_pay_and_gap_and_raises_an_existing_one():
    small = suggest_bonus(compensation=30, currency="USD", slots_open=4, shortfall=1, eligible=3)
    large = suggest_bonus(compensation=30, currency="USD", slots_open=4, shortfall=4, eligible=0)
    assert 10 <= small["amount"] < large["amount"] <= 30
    assert small["amount"] % 5 == 0 and large["amount"] % 5 == 0
    # A pay of 0 still gets a sensible suggestion, and a bonus that is already set is raised, not repeated.
    assert suggest_bonus(compensation=0, currency="USD", slots_open=1, shortfall=1, eligible=0)["amount"] >= 10
    raised = suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=2, eligible=0, existing_amount=25)
    assert raised["raises_existing"] and raised["amount"] > 25
    assert suggest_bonus(compensation=30, currency="USD", slots_open=2, shortfall=0, eligible=2) is None


async def _first_open_shop(client: AsyncClient, auth: dict) -> tuple[dict, dict]:
    for campaign in (await client.get("/api/campaigns", headers=auth)).json()["items"]:
        shops = (await client.get(f"/api/campaigns/{campaign['id']}/shops", headers=auth)).json()["items"]
        for shop in shops:
            if shop["open_slots"] >= 1:
                return campaign, shop
    pytest.skip("seed has no shop with an open slot")


@pytest.mark.asyncio
async def test_recommendations_report_staffing_and_bonus_when_short():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _first_open_shop(client, auth)
        url = f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/recommendations"

        # A tiny radius leaves nobody to recommend, so the shop is short and a bonus is recommended.
        tight = (await client.get(url, params={"limit": 20, "radius": 0.1}, headers=auth)).json()
        staffing = tight["staffing"]
        assert staffing["state"] == SHORT
        assert staffing["shortfall"] == staffing["slots_open"] - staffing["recommended"] > 0
        assert staffing["bonus_recommended"] and staffing["suggested_bonus"]["amount"] > 0
        assert staffing["reason"]

        # The shops list carries the same open-slot count the picker shows.
        listed = next(s for s in (await client.get(f"/api/campaigns/{campaign['id']}/shops", headers=auth)).json()["items"] if s["id"] == shop["id"])
        assert listed["open_slots"] == staffing["slots_open"]


@pytest.mark.asyncio
async def test_a_staffed_shop_reports_filled_and_no_bonus_recommendation():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        for campaign in (await client.get("/api/campaigns", headers=auth)).json()["items"]:
            for shop in (await client.get(f"/api/campaigns/{campaign['id']}/shops", headers=auth)).json()["items"]:
                url = f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/recommendations"
                body = (await client.get(url, params={"limit": 20}, headers=auth)).json()
                fresh = [r["shopper_id"] for r in body["recommendations"] if r["recommended"]]
                if body["slots_remaining"] >= 1 and len(fresh) == body["slots_remaining"]:
                    assert body["staffing"]["state"] == READY and not body["staffing"]["bonus_recommended"]
                    ok = await client.post(f"{url}/approve", headers=auth, json={"shopper_ids": fresh})
                    assert ok.status_code == 200, ok.text
                    after = (await client.get(url, params={"limit": 20}, headers=auth)).json()["staffing"]
                    assert after["state"] == FILLED and not after["bonus_recommended"] and after["slots_open"] == 0
                    return
        pytest.skip("seed has no shop the AI can fully staff")


@pytest.mark.asyncio
async def test_auto_assign_recommends_a_bonus_for_shops_it_cannot_fill():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, _ = await _first_open_shop(client, auth)
        plan = (
            await client.post(
                f"/api/ai/campaigns/{campaign['id']}/optimize-assignments", params={"radius_km": 0.1}, headers=auth
            )
        ).json()
        assert plan["unfilled"], "a 0.1 km radius should leave shops unfilled"
        for u in plan["unfilled"]:
            assert u["suggested_bonus"] and u["suggested_bonus"]["amount"] > 0


async def _untouched_open_shop(client: AsyncClient, auth: dict) -> tuple[dict, dict]:
    """A shop nobody has been selected for yet, so every shopper that becomes eligible counts as new."""
    for campaign in (await client.get("/api/campaigns", headers=auth)).json()["items"]:
        for shop in (await client.get(f"/api/campaigns/{campaign['id']}/shops", headers=auth)).json()["items"]:
            if shop["selected_shoppers"] == 0 and shop["open_slots"] >= 1:
                return campaign, shop
    pytest.skip("seed has no untouched shop")


@pytest.mark.asyncio
async def test_widening_the_radius_makes_the_ai_recommend_shoppers():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _untouched_open_shop(client, auth)
        url = f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/recommendations"
        tight = (await client.get(url, params={"limit": 20, "radius": 0.1}, headers=auth)).json()
        st = tight["staffing"]
        assert st["state"] == SHORT and st["can_expand_radius"] and st["next_radius_km"] > 0.1

        wider = (await client.get(url, params={"limit": 20, "radius": st["next_radius_km"]}, headers=auth)).json()
        assert wider["staffing"]["state"] == READY
        assert sum(1 for r in wider["recommendations"] if r["recommended"]) == wider["slots_remaining"]


@pytest.mark.asyncio
async def test_adding_the_suggested_bonus_makes_the_ai_recommend_shoppers():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _untouched_open_shop(client, auth)
        url = f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/recommendations"
        tight = (await client.get(url, params={"limit": 20, "radius": 0.1}, headers=auth)).json()
        suggestion = tight["staffing"]["suggested_bonus"]
        assert suggestion and suggestion["fills_gap"], "a nearby pool should be reachable with a bonus"

        saved = await client.post(
            f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/bonus", headers=auth, json={"amount": suggestion["amount"]}
        )
        assert saved.status_code in (200, 201), saved.text

        after = (await client.get(url, params={"limit": 20, "radius": 0.1}, headers=auth)).json()
        assert after["staffing"]["state"] == READY and after["staffing"]["bonus_reach_km"] == suggestion["reach_km"]
        assert after["eligible_count"] > tight["eligible_count"]


@pytest.mark.asyncio
async def test_auto_assign_fills_a_shop_once_its_radius_is_widened():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _untouched_open_shop(client, auth)
        endpoint = f"/api/ai/campaigns/{campaign['id']}/optimize-assignments"
        plan = (await client.post(endpoint, params={"radius_km": 0.1}, headers=auth)).json()
        entry = next(u for u in plan["unfilled"] if u["shop_id"] == shop["id"])
        assert entry["can_expand_radius"] and entry["next_radius_km"] > 0.1 and entry["suggested_bonus"]
        assert not [p for p in plan["proposals"] if p["shop_id"] == shop["id"]]

        # Only this shop is widened; the rest of the campaign keeps the tight radius.
        widened = (
            await client.post(
                endpoint,
                params={"radius_km": 0.1},
                headers=auth,
                json={"shop_radii": {shop["id"]: entry["next_radius_km"]}},
            )
        ).json()
        assert [p for p in widened["proposals"] if p["shop_id"] == shop["id"]]
        assert {p["shop_id"] for p in widened["proposals"]} == {shop["id"]}
