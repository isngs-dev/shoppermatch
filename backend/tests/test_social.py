"""Social Media Automation tests — OAuth, token handling, post lifecycle,
scheduling, publishing, retries, idempotency, manual Facebook Groups
workflow, and tenant isolation.

Every Meta Graph API call is mocked (monkeypatched at the function boundary
services.facebook_oauth.exchange_code_for_pages / services.facebook_graph.
publish_to_page) — this suite makes zero real network calls to Facebook.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import Client, ClientSocialAccount, DistributionPost, SocialPublishingLog, User
from app.security import create_access_token, hash_password
from app.seed import maybe_seed
from app.services import facebook_oauth
from app.services.crypto import decrypt_token, encrypt_token
from app.services.facebook_graph import FacebookPublishError
from app.services.social_publisher import _claim_for_publishing, attempt_publish, process_due_social_posts
from app.services.tracking import now


async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await maybe_seed()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", follow_redirects=False)


async def _nike_client_auth() -> dict:
    async with _client() as client:
        r = await client.post(
            "/api/auth/login", json={"email": "client@nike-demo.example", "password": "client-demo-2026"}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _second_client_auth() -> dict:
    """Creates an independent client+user directly (no dependence on seeded
    demo credentials for a second tenant), for tenant-isolation checks."""
    async with AsyncSessionLocal() as session:
        client_row = Client(company_name=f"Other Co {uuid.uuid4().hex[:6]}")
        session.add(client_row)
        await session.flush()
        user = User(
            name="Other User",
            email=f"other-{uuid.uuid4().hex[:8]}@example.com",
            role="client",
            password_hash=hash_password("irrelevant-not-used"),
            client_id=client_row.id,
        )
        session.add(user)
        await session.commit()
        token = create_access_token(str(user.id))
        return {"Authorization": f"Bearer {token}"}


async def _nike_campaign(auth: dict) -> dict:
    async with _client() as client:
        r = await client.get("/api/campaigns", headers=auth)
        return next(c for c in r.json()["items"] if "Nike" in c["name"])


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_facebook_status_reports_not_configured_by_default():
    await _fresh_db()
    auth = await _nike_client_auth()
    async with _client() as client:
        r = await client.get("/api/social/facebook/status", headers=auth)
        assert r.status_code == 200
        assert r.json() == {"configured": False}


@pytest.mark.asyncio
async def test_facebook_connect_requires_configuration():
    await _fresh_db()
    auth = await _nike_client_auth()
    async with _client() as client:
        r = await client.get("/api/social/facebook/connect", headers=auth)
        assert r.status_code == 503


@pytest.mark.asyncio
async def test_facebook_oauth_full_flow_with_mocked_graph_api(monkeypatch):
    """connect -> (mocked) callback -> pending pages -> select-page, ending
    with a real ClientSocialAccount row whose token round-trips through
    encryption. No real HTTP call to Facebook happens anywhere here."""
    await _fresh_db()
    monkeypatch.setattr(settings, "facebook_app_id", "test-app-id")
    monkeypatch.setattr(settings, "facebook_app_secret", "test-app-secret")
    monkeypatch.setattr(settings, "facebook_redirect_uri", "http://testserver/api/social/facebook/callback")

    auth = await _nike_client_auth()
    async with _client() as client:
        me = await client.get("/api/auth/me", headers=auth)
        client_id = me.json()["client_id"]

        connect = await client.get("/api/social/facebook/connect", headers=auth)
        assert connect.status_code == 200
        authorize_url = connect.json()["authorize_url"]
        assert "test-app-id" in authorize_url
        state = authorize_url.split("state=")[1].split("&")[0]
        from urllib.parse import unquote

        state = unquote(state)

        async def fake_exchange(code: str):
            assert code == "fake-code"
            return [{"id": "1234567890", "name": "Nike Test Page", "access_token": "fake-page-token", "category": "Retail"}]

        monkeypatch.setattr(facebook_oauth, "exchange_code_for_pages", fake_exchange)

        callback = await client.get("/api/social/facebook/callback", params={"code": "fake-code", "state": state})
        assert callback.status_code in (302, 307)
        location = callback.headers["location"]
        assert "fb_pending=" in location
        pending_id = location.split("fb_pending=")[1]

        pending = await client.get(f"/api/social/facebook/pending/{pending_id}", headers=auth)
        assert pending.status_code == 200
        pages = pending.json()["pages"]
        assert pages == [{"id": "1234567890", "name": "Nike Test Page", "category": "Retail"}]

        selected = await client.post(
            "/api/social/facebook/select-page",
            headers=auth,
            json={"pending_id": pending_id, "page_id": "1234567890"},
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["account_name"] == "Nike Test Page"

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        stmt = select(ClientSocialAccount).where(
            ClientSocialAccount.client_id == uuid.UUID(client_id), ClientSocialAccount.platform == "facebook"
        )
        account = (await session.execute(stmt)).scalar_one()
        assert account.external_account_id == "1234567890"
        assert account.status == "connected"
        # The stored value must never be the plaintext token, and must
        # decrypt back to exactly what Meta returned.
        assert account.access_token_encrypted != "fake-page-token"
        assert decrypt_token(account.access_token_encrypted) == "fake-page-token"


@pytest.mark.asyncio
async def test_facebook_callback_rejects_tampered_state():
    await _fresh_db()
    async with _client() as client:
        r = await client.get("/api/social/facebook/callback", params={"code": "x", "state": "not-a-valid-signed-state"})
        assert r.status_code in (302, 307)
        assert "fb_error=" in r.headers["location"]


# --------------------------------------------------------------------------- #
# Post lifecycle: draft, scheduling, permissions
# --------------------------------------------------------------------------- #
async def _connected_facebook_account(client_id: str, *, with_token: bool = True) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            ClientSocialAccount(
                client_id=uuid.UUID(client_id),
                platform="facebook",
                account_name="Test Page",
                connected_by="test@example.com",
                external_account_id="page-1",
                access_token_encrypted=encrypt_token("real-token") if with_token else None,
                status="connected",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_create_draft_and_permission_isolation():
    await _fresh_db()
    auth = await _nike_client_auth()
    other_auth = await _second_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={
                "campaign_id": campaign["id"],
                "source_type": "campaign",
                "destination_type": "facebook",
                "target_kind": "page",
                "message": "Draft post",
            },
        )
        assert create.status_code == 200, create.text
        post = create.json()
        assert post["status"] == "draft"

        # The owning client can read it.
        own_read = await client.get(f"/api/social/posts/{post['id']}", headers=auth)
        assert own_read.status_code == 200

        # A different client gets 404, never 403 (never confirms it exists).
        other_read = await client.get(f"/api/social/posts/{post['id']}", headers=other_auth)
        assert other_read.status_code == 404

        # A different client can't even create a post against this campaign.
        cross_create = await client.post(
            "/api/social/posts",
            headers=other_auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        assert cross_create.status_code == 404


@pytest.mark.asyncio
async def test_scheduling_requires_a_connected_account_with_a_token():
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        post_id = create.json()["id"]

        # No account connected yet -> rejected.
        r = await client.post(f"/api/social/posts/{post_id}/schedule", headers=auth, json={"scheduled_at": "2027-01-01T00:00:00Z"})
        assert r.status_code == 400

        me = (await client.get("/api/auth/me", headers=auth)).json()
        await _connected_facebook_account(me["client_id"])

        r = await client.post(f"/api/social/posts/{post_id}/schedule", headers=auth, json={"scheduled_at": "2027-01-01T00:00:00Z"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "scheduled"


@pytest.mark.asyncio
async def test_group_target_never_schedulable_and_uses_manual_workflow():
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={
                "campaign_id": campaign["id"],
                "source_type": "campaign",
                "destination_type": "facebook",
                "target_kind": "group",
                "target_ref": "https://facebook.com/groups/test",
                "message": "Group post",
            },
        )
        post = create.json()
        assert post["status"] == "manual_required"
        assert post["requires_manual_posting"] is True

        # Cannot be scheduled for automatic publishing under any circumstances.
        schedule_attempt = await client.post(
            f"/api/social/posts/{post['id']}/schedule", headers=auth, json={"scheduled_at": "2027-01-01T00:00:00Z"}
        )
        assert schedule_attempt.status_code == 400

        # Cannot be published automatically either.
        publish_attempt = await client.post(f"/api/social/posts/{post['id']}/publish", headers=auth)
        assert publish_attempt.status_code == 400

        marked = await client.post(f"/api/social/posts/{post['id']}/mark-posted", headers=auth)
        assert marked.status_code == 200
        assert marked.json()["status"] == "posted_manual"


# --------------------------------------------------------------------------- #
# Publishing: success, failure/retry, idempotency
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_publish_now_success_records_external_post_id_and_log(monkeypatch):
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)
    me_client_id = None

    async with _client() as client:
        me = (await client.get("/api/auth/me", headers=auth)).json()
        me_client_id = me["client_id"]
        await _connected_facebook_account(me_client_id)

        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "Publish me"},
        )
        post_id = create.json()["id"]

        async def fake_publish(page_id, token, message, image_url):
            assert token == "real-token"
            return "page-1_998877"

        monkeypatch.setattr("app.services.social_publisher.publish_to_page", fake_publish)

        r = await client.post(f"/api/social/posts/{post_id}/publish", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "posted"
        assert body["external_post_id"] == "page-1_998877"

    async with AsyncSessionLocal() as session:
        logs = (
            await session.execute(
                select(SocialPublishingLog).where(SocialPublishingLog.post_id == uuid.UUID(post_id))
            )
        ).scalars().all()
        assert len(logs) == 1
        assert logs[0].status == "success"
        assert logs[0].external_post_id == "page-1_998877"


@pytest.mark.asyncio
async def test_scheduled_publish_retries_then_fails_after_max_attempts(monkeypatch):
    """Simulates several scheduler ticks against a persistently-failing
    Graph API call — retry_count must climb and the post must land on
    'failed' once social_publisher_max_attempts is reached, never stuck
    retrying forever and never silently marked posted."""
    await _fresh_db()
    monkeypatch.setattr(settings, "social_publisher_max_attempts", 2)
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        me = (await client.get("/api/auth/me", headers=auth)).json()
        await _connected_facebook_account(me["client_id"])
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        post_id = create.json()["id"]
        await client.post(f"/api/social/posts/{post_id}/schedule", headers=auth, json={"scheduled_at": "2020-01-01T00:00:00Z"})

    async def always_fails(*args, **kwargs):
        raise FacebookPublishError("Simulated transient Graph API error")

    import app.services.social_publisher as sp

    monkeypatch.setattr(sp, "publish_to_page", always_fails)

    # Tick 1: fails, retry_count=1, backoff pushes scheduled_at into the
    # future so a second immediate tick correctly does NOT pick it up again.
    processed = await process_due_social_posts()
    assert processed == 1
    async with AsyncSessionLocal() as session:
        post = await session.get(DistributionPost, uuid.UUID(post_id))
        assert post.status == "scheduled"
        assert post.retry_count == 1
        # Force it due again to simulate time passing, rather than sleeping.
        post.scheduled_at = post.scheduled_at.replace(year=2020)
        await session.commit()

    # Tick 2: second failure reaches max_attempts -> terminal 'failed'.
    processed = await process_due_social_posts()
    assert processed == 1
    async with AsyncSessionLocal() as session:
        post = await session.get(DistributionPost, uuid.UUID(post_id))
        assert post.status == "failed"
        assert post.retry_count == 2
        assert post.error_message

    async with AsyncSessionLocal() as session:
        logs = (
            await session.execute(
                select(SocialPublishingLog).where(SocialPublishingLog.post_id == uuid.UUID(post_id))
            )
        ).scalars().all()
        assert len(logs) == 2


@pytest.mark.asyncio
async def test_auth_error_flips_account_to_expired_instead_of_retrying(monkeypatch):
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        me = (await client.get("/api/auth/me", headers=auth)).json()
        await _connected_facebook_account(me["client_id"])
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        post_id = create.json()["id"]

        async def fake_publish(*a, **k):
            raise FacebookPublishError("token invalid", is_auth_error=True)

        monkeypatch.setattr("app.services.social_publisher.publish_to_page", fake_publish)
        r = await client.post(f"/api/social/posts/{post_id}/publish", headers=auth)
        assert r.status_code == 502

        accounts = await client.get("/api/client/social-accounts", headers=auth)
        fb = next(a for a in accounts.json()["items"] if a["platform"] == "facebook")
        assert fb["needs_reconnect"] is True


@pytest.mark.asyncio
async def test_idempotent_claim_prevents_double_publish():
    """The actual double-publish guard: two concurrent attempts to claim the
    same post for publishing must never both succeed."""
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        me = (await client.get("/api/auth/me", headers=auth)).json()
        await _connected_facebook_account(me["client_id"])
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        post_id = create.json()["id"]
        await client.post(f"/api/social/posts/{post_id}/schedule", headers=auth, json={"scheduled_at": "2020-01-01T00:00:00Z"})

    async with AsyncSessionLocal() as session_a, AsyncSessionLocal() as session_b:
        first = await _claim_for_publishing(session_a, uuid.UUID(post_id))
        second = await _claim_for_publishing(session_b, uuid.UUID(post_id))
        assert first is True
        assert second is False  # already claimed — must not also succeed


@pytest.mark.asyncio
async def test_publish_fails_cleanly_with_no_connected_account():
    await _fresh_db()
    auth = await _nike_client_auth()
    campaign = await _nike_campaign(auth)

    async with _client() as client:
        create = await client.post(
            "/api/social/posts",
            headers=auth,
            json={"campaign_id": campaign["id"], "source_type": "campaign", "destination_type": "facebook", "target_kind": "page", "message": "x"},
        )
        post_id = create.json()["id"]
        r = await client.post(f"/api/social/posts/{post_id}/publish", headers=auth)
        assert r.status_code == 400
        # Never left in a half-published/"publishing" limbo state.
        check = await client.get(f"/api/social/posts/{post_id}", headers=auth)
        assert check.json()["status"] == "draft"


