"""AI recommendations fill exactly the slots a shop still needs; anything beyond that is the
over-selection flow, and Auto Assign never proposes more shoppers than a shop has room for.

The seed may already hold invitations for some shops, so every assertion is relative to the shop's own
`slots_remaining` rather than to a fixed count."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_acceptance import _fresh_db
from tests.test_bulk_invitations import _login


def _url(campaign: dict, shop: dict) -> str:
    return f"/api/campaigns/{campaign['id']}/shops/{shop['id']}/recommendations"


async def _recs(client: AsyncClient, auth: dict, campaign: dict, shop: dict) -> dict:
    return (await client.get(_url(campaign, shop), params={"limit": 20}, headers=auth)).json()


async def _pick_shop(client: AsyncClient, auth: dict, min_slots: int) -> tuple[dict, dict, dict]:
    """A shop that has at least `min_slots` open slots and a few more eligible shoppers than that."""
    for campaign in (await client.get("/api/campaigns", headers=auth)).json()["items"]:
        for shop in (await client.get("/api/shops", params={"campaign_id": campaign["id"]}, headers=auth)).json()["items"]:
            body = await _recs(client, auth, campaign, shop)
            if body["slots_remaining"] >= min_slots and body["eligible_count"] > shop["required_shoppers"] + 1:
                return campaign, shop, body
    pytest.skip("seed has no shop with enough open slots and eligible shoppers")


@pytest.mark.asyncio
async def test_recommends_exactly_the_open_slots():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        _, shop, body = await _pick_shop(client, auth, 1)

        recommended = [r for r in body["recommendations"] if r["recommended"]]
        assert body["slots_remaining"] == max(0, shop["required_shoppers"] - body["already_selected"])
        assert len(recommended) == body["slots_remaining"]
        # The recommended shoppers are the best-ranked ones that aren't invited yet; the rest are optional extras.
        fresh = [r["shopper_id"] for r in body["recommendations"] if not r["already_invited"]]
        assert [r["shopper_id"] for r in recommended] == fresh[: len(recommended)]
        assert body["allow_over_selection"] is False


@pytest.mark.asyncio
async def test_recommendation_shrinks_as_shoppers_get_selected():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop, before = await _pick_shop(client, auth, 2)
        first = next(r for r in before["recommendations"] if r["recommended"])

        r = await client.post(f"{_url(campaign, shop)}/approve", headers=auth, json={"shopper_ids": [first["shopper_id"]]})
        assert r.status_code == 200, r.text

        after = await _recs(client, auth, campaign, shop)
        assert after["already_selected"] == before["already_selected"] + 1
        assert after["slots_remaining"] == before["slots_remaining"] - 1
        assert sum(1 for x in after["recommendations"] if x["recommended"]) == after["slots_remaining"]
        picked = next(x for x in after["recommendations"] if x["shopper_id"] == first["shopper_id"])
        assert picked["already_invited"] and not picked["recommended"]


@pytest.mark.asyncio
async def test_full_shop_recommends_nobody_until_over_selection():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop, body = await _pick_shop(client, auth, 1)
        fill = [r["shopper_id"] for r in body["recommendations"] if r["recommended"]]
        ok = await client.post(f"{_url(campaign, shop)}/approve", headers=auth, json={"shopper_ids": fill})
        assert ok.status_code == 200, ok.text

        full = await _recs(client, auth, campaign, shop)
        assert full["slots_remaining"] == 0
        assert not any(r["recommended"] for r in full["recommendations"])

        extra = next(r for r in full["recommendations"] if not r["already_invited"])
        blocked = await client.post(f"{_url(campaign, shop)}/approve", headers=auth, json={"shopper_ids": [extra["shopper_id"]]})
        assert blocked.status_code == 409

        assert (await client.patch(f"/api/shops/{shop['id']}/over-selection", headers=auth, json={"allow": True})).status_code == 200
        allowed = await client.post(f"{_url(campaign, shop)}/approve", headers=auth, json={"shopper_ids": [extra["shopper_id"]]})
        assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_auto_assign_only_fills_open_slots():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop, body = await _pick_shop(client, auth, 1)
        fill = [r["shopper_id"] for r in body["recommendations"] if r["recommended"]]
        ok = await client.post(f"{_url(campaign, shop)}/approve", headers=auth, json={"shopper_ids": fill})
        assert ok.status_code == 200, ok.text

        plan = (await client.post(f"/api/ai/campaigns/{campaign['id']}/optimize-assignments", headers=auth)).json()
        assert not [p for p in plan["proposals"] if p["shop_id"] == shop["id"]]
        assert not [u for u in plan["unfilled"] if u["shop_id"] == shop["id"]]
        # No proposal may exceed what its shop can still take, so approving the plan can never 409.
        per_shop: dict[str, int] = {}
        for p in plan["proposals"]:
            per_shop[p["shop_id"]] = per_shop.get(p["shop_id"], 0) + 1
        for shop_id, count in per_shop.items():
            other = next(s for s in (await client.get("/api/shops", params={"campaign_id": campaign["id"]}, headers=auth)).json()["items"] if s["id"] == shop_id)
            room = (await client.get(f"/api/shops/{shop_id}", headers=auth)).json()
            assert count <= max(0, other["required_shoppers"] - room["active_selected_count"])
