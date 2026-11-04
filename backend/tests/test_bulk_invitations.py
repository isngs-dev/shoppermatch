"""Bulk invitations: the send path must queue emails without a server error, and the
over-selection guard must answer with a readable JSON 409 (never a bare 500)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import EmailJob
from tests.test_acceptance import _fresh_db


async def _login(client: AsyncClient) -> dict:
    r = await client.post("/api/auth/login", json={"email": "admin@isn.com", "password": "isn-demo-2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _shop_with_room(client: AsyncClient, auth: dict) -> tuple[dict, dict]:
    campaigns = (await client.get("/api/campaigns", headers=auth)).json()["items"]
    for campaign in campaigns:
        # The seed's order is random and some shops already hold an invitation, so go by the slots actually open.
        shops = (await client.get(f"/api/campaigns/{campaign['id']}/shops", headers=auth)).json()["items"]
        for shop in shops:
            if shop["open_slots"] >= 2:
                return campaign, shop
    pytest.skip("seed has no shop with 2+ open slots")


@pytest.mark.asyncio
async def test_bulk_send_queues_every_invitation():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _shop_with_room(client, auth)
        shoppers = (await client.get("/api/shoppers", headers=auth)).json()["items"][:2]

        r = await client.post(
            "/api/invitations/bulk",
            headers=auth,
            json={
                "campaign_id": campaign["id"],
                "shop_id": shop["id"],
                "shopper_ids": [s["id"] for s in shoppers],
                "auto_send": True,
                "custom_subject": "Hello",
                "custom_html": "<p>Hi</p>",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_created"] == 2 and body["total_failed"] == 0

    async with AsyncSessionLocal() as session:
        assert await session.scalar(select(func.count(EmailJob.id)).where(EmailJob.status == "queued")) == 2


@pytest.mark.asyncio
async def test_over_selection_is_a_json_409():
    await _fresh_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        campaign, shop = await _shop_with_room(client, auth)
        too_many = (await client.get("/api/shoppers", params={"limit": shop["required_shoppers"] + 2}, headers=auth)).json()["items"]

        r = await client.post(
            "/api/invitations/bulk",
            headers=auth,
            json={
                "campaign_id": campaign["id"],
                "shop_id": shop["id"],
                "shopper_ids": [s["id"] for s in too_many],
                "auto_send": False,
            },
        )
        assert r.status_code == 409
        assert "over-selection" in r.json()["detail"]
