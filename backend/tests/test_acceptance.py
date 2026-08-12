"""End-to-end acceptance test — the exact flow from the scope's section 29.

Runs entirely in-process against the ASGI app (no server, no network) using a
fresh disposable SQLite database, so it verifies the real backend logic:

    login -> create invitation for Sarah Johnson -> click /r/{token}
    -> accept -> open pixel -> confirm every event + timestamp persisted,
    attribution is correct, redirect works, and state survives a new session.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app
from app.seed import maybe_seed


async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await maybe_seed()


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_full_acceptance_flow():
    await _fresh_db()

    async with _client() as client:
        # --- Step 0: admin login ---
        r = await client.post(
            "/api/auth/login",
            json={"email": "admin@isn.com", "password": "isn-demo-2026"},
        )
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # --- Find Sarah Johnson + a Nike shop ---
        r = await client.get("/api/shoppers", params={"q": "Sarah"}, headers=auth)
        assert r.status_code == 200
        sarah = next(s for s in r.json()["items"] if s["name"] == "Sarah Johnson")

        r = await client.get("/api/campaigns", headers=auth)
        nike = next(c for c in r.json()["items"] if "Nike" in c["name"])

        r = await client.get("/api/shops", params={"campaign_id": nike["id"]}, headers=auth)
        shop = r.json()["items"][0]

        # Baseline clicked count for the "dashboard updates" assertion.
        summary_before = (await client.get("/api/tracking/summary", headers=auth)).json()

        # --- Step 1-4: create invitation (generates UUID token) ---
        r = await client.post(
            "/api/invitations",
            headers=auth,
            json={
                "campaign_id": nike["id"],
                "shop_id": shop["id"],
                "shopper_id": sarah["id"],
                "auto_send": True,
            },
        )
        assert r.status_code == 200, r.text
        inv = r.json()
        invitation_id = inv["id"]

        # 1. invitation exists  2. has UUID token  4/5. campaign + shopper associated
        assert inv["reference"].startswith("INV-")
        tracking_url = inv["urls"]["tracking_url"]
        assert "/r/" in tracking_url
        tracking_token = tracking_url.split("/r/")[-1]
        assert len(tracking_token) == 36  # canonical UUID string
        assert inv["campaign_id"] == nike["id"]
        assert inv["shopper_id"] == sarah["id"]
        assert inv["attribution"]["source"] == "ISN Outreach"  # 6. source is ISN
        # auto_send recorded sent + delivered
        assert inv["sent_at"] is not None
        assert inv["delivered_at"] is not None

        # Token maps to exactly one invitation (public landing resolves it).
        r = await client.get(f"/api/public/invitations/{tracking_token}")
        assert r.status_code == 200
        assert r.json()["reference"] == inv["reference"]

        # --- Step: open the tracking URL /r/{token} ---
        r = await client.get(f"/r/{tracking_token}")
        assert r.status_code == 302                              # 7. redirect works
        assert r.headers["location"] == f"/shop/{tracking_token}"

        # 2/3. click event + timestamp persisted
        detail = (await client.get(f"/api/invitations/{invitation_id}", headers=auth)).json()
        assert detail["clicked_at"] is not None
        assert detail["status"] == "clicked"
        event_types = [e["event_type"] for e in detail["events"]]
        assert "link_clicked" in event_types

        # 8. dashboard updates (clicked count increased by 1)
        summary_after = (await client.get("/api/tracking/summary", headers=auth)).json()
        assert summary_after["clicked"] == summary_before["clicked"] + 1

        # --- Step: accept assignment ---  9/10. accept works, accepted event appears
        r = await client.post(
            f"/api/invitations/{tracking_token}/respond",
            json={"response": "accepted"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["recorded"] is True

        detail = (await client.get(f"/api/invitations/{invitation_id}", headers=auth)).json()
        assert detail["response"] == "accepted"
        assert detail["responded_at"] is not None
        assert "assignment_accepted" in [e["event_type"] for e in detail["events"]]

        # --- Email pixel: /track/open/{token}.gif records email_opened ---
        r = await client.get(f"/track/open/{tracking_token}.gif")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/gif"
        assert r.content[:6] == b"GIF89a"          # a real transparent GIF

        detail = (await client.get(f"/api/invitations/{invitation_id}", headers=auth)).json()
        assert detail["opened_at"] is not None
        assert "email_opened" in [e["event_type"] for e in detail["events"]]

    # --- 11. state survives a brand-new session (fresh client) ---
    async with _client() as client2:
        r = await client2.post(
            "/api/auth/login",
            json={"email": "admin@isn.com", "password": "isn-demo-2026"},
        )
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        detail = (await client2.get(f"/api/invitations/{invitation_id}", headers=auth)).json()
        assert detail["response"] == "accepted"
        assert detail["clicked_at"] is not None
        assert detail["opened_at"] is not None


@pytest.mark.asyncio
async def test_open_pixel_preview_does_not_record():
    """Previewing an email (?preview=1) must NOT create an email_opened event."""
    await _fresh_db()
    async with _client() as client:
        r = await client.post(
            "/api/auth/login",
            json={"email": "admin@isn.com", "password": "isn-demo-2026"},
        )
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        shoppers = (await client.get("/api/shoppers", headers=auth)).json()["items"]
        nike = next(c for c in (await client.get("/api/campaigns", headers=auth)).json()["items"] if "Nike" in c["name"])
        shop = (await client.get("/api/shops", params={"campaign_id": nike["id"]}, headers=auth)).json()["items"][0]

        inv = (await client.post("/api/invitations", headers=auth, json={
            "campaign_id": nike["id"], "shop_id": shop["id"], "shopper_id": shoppers[0]["id"], "auto_send": True,
        })).json()
        token = inv["urls"]["tracking_url"].split("/r/")[-1]

        # Preview pixel — should return a GIF but not record an open.
        r = await client.get(f"/track/open/{token}.gif", params={"preview": 1})
        assert r.status_code == 200
        detail = (await client.get(f"/api/invitations/{inv['id']}", headers=auth)).json()
        assert detail["opened_at"] is None
        assert "email_opened" not in [e["event_type"] for e in detail["events"]]
