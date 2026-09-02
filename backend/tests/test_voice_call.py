"""AI Voice Call Follow-Up tests — Twilio call initiation, webhook signature
verification, TwiML conversation turns, retry/threshold logic, daily cap,
and permission isolation.

Every Twilio/OpenAI call is mocked (monkeypatched at the function boundary
services.voice_call.create_call / services.voice_call_ai.next_turn) — this
suite makes zero real network calls to Twilio or OpenAI.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    EmailAutomation,
    Shopper,
    ShopperAutomationState,
    ShopperAutomationStatus,
    VoiceCallLog,
)
from app.seed import maybe_seed
from app.services import voice_call
from app.services.tracking import now
from app.services.voice_call_scheduler import process_due_voice_calls


async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await maybe_seed()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", follow_redirects=False)


async def _admin_auth() -> dict:
    async with _client() as client:
        r = await client.post("/api/auth/login", json={"email": "admin@isn.com", "password": "isn-demo-2026"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _nike_campaign_and_shop(auth: dict) -> tuple[dict, dict]:
    async with _client() as client:
        nike = next(c for c in (await client.get("/api/campaigns", headers=auth)).json()["items"] if "Nike" in c["name"])
        shop = (await client.get("/api/shops", params={"campaign_id": nike["id"]}, headers=auth)).json()["items"][0]
        return nike, shop


async def _make_shopper(phone: str | None = "+15551234567") -> str:
    async with AsyncSessionLocal() as session:
        shopper = Shopper(
            shopper_code=f"SHP-{uuid.uuid4().hex[:8]}",
            name="Test Shopper",
            email=f"test-{uuid.uuid4().hex[:8]}@example.com",
            phone=phone,
        )
        session.add(shopper)
        await session.commit()
        return str(shopper.id)


def _enable_twilio(monkeypatch):
    monkeypatch.setattr(settings, "twilio_account_sid", "AC_test")
    monkeypatch.setattr(settings, "twilio_auth_token", "test_auth_token")
    monkeypatch.setattr(settings, "twilio_phone_number", "+15550000000")


async def _create_automation_with_no_response_state(
    auth: dict, campaign: dict, shop: dict, shopper_id: str, *, delay_days: int = 0, max_attempts: int = 2, retry_gap_days: int = 1
) -> tuple[str, str]:
    """Creates a real automation (via the API) + a real ShopperAutomationState,
    then jumps that state straight to COMPLETED_NO_RESPONSE (bypassing the
    multi-day email engine — legitimate here since the voice-call scheduler
    only ever reads that field, never how it got there). Returns (automation_id, state_id)."""
    async with _client() as client:
        created = await client.post(
            "/api/automations",
            headers=auth,
            json={
                "campaign_id": campaign["id"],
                "shop_id": shop["id"],
                "name": f"Voice call test {uuid.uuid4().hex[:6]}",
                "voice_call_enabled": True,
                "voice_call_delay_days": delay_days,
                "voice_call_retry_gap_days": retry_gap_days,
                "voice_call_max_attempts": max_attempts,
            },
        )
        assert created.status_code == 200, created.text
        automation_id = created.json()["id"]

        added = await client.post(
            f"/api/automations/{automation_id}/shoppers", headers=auth, json={"shopper_ids": [shopper_id]}
        )
        assert added.status_code == 200, added.text

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        stmt = select(ShopperAutomationState).where(
            ShopperAutomationState.automation_id == uuid.UUID(automation_id),
            ShopperAutomationState.shopper_id == uuid.UUID(shopper_id),
        )
        state = (await session.execute(stmt)).scalar_one()
        state.status = ShopperAutomationStatus.COMPLETED_NO_RESPONSE
        state.last_event_at = now() - timedelta(days=delay_days)
        state_id = str(state.id)
        await session.commit()
    return automation_id, state_id


# --------------------------------------------------------------------------- #
# Scheduler: eligibility, placing calls, retries, caps
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_scheduler_does_nothing_when_twilio_not_configured():
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    placed = await process_due_voice_calls()
    assert placed == 0


@pytest.mark.asyncio
async def test_scheduler_places_call_when_due_and_configured(monkeypatch):
    await _fresh_db()
    _enable_twilio(monkeypatch)
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id, delay_days=0)

    async def fake_create_call(to_number, twiml_url, status_url):
        assert to_number == "+15551234567"
        return "CA_fake_sid"

    monkeypatch.setattr("app.services.voice_call_scheduler.create_call", fake_create_call)

    placed = await process_due_voice_calls()
    assert placed == 1

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "calling"
        assert state.voice_call_attempts == 1

    async with _client() as client:
        logs = await client.get(f"/api/voice-calls/automations/{automation_id}", headers=auth)
        assert logs.status_code == 200
        items = logs.json()["items"]
        assert len(items) == 1
        assert items[0]["automation_state_id"] == state_id


@pytest.mark.asyncio
async def test_scheduler_skips_state_before_delay_elapses(monkeypatch):
    await _fresh_db()
    _enable_twilio(monkeypatch)
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    # delay_days=5 but last_event_at backdated only by the (delay_days=0)
    # helper default — simulate "just went terminal" by NOT backdating.
    automation_id, state_id = await _create_automation_with_no_response_state(
        auth, campaign, shop, shopper_id, delay_days=0
    )
    # Force the automation's delay to 5 days after the fact and reset the
    # anchor to "now" so it's clearly not due yet.
    async with AsyncSessionLocal() as session:
        automation = await session.get(EmailAutomation, uuid.UUID(automation_id))
        automation.voice_call_delay_days = 5
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.last_event_at = now()
        await session.commit()

    placed = await process_due_voice_calls()
    assert placed == 0


@pytest.mark.asyncio
async def test_missing_phone_number_fails_without_retry(monkeypatch):
    await _fresh_db()
    _enable_twilio(monkeypatch)
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper(phone=None)
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    placed = await process_due_voice_calls()
    assert placed == 0
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "failed"
        # A missing phone number is permanently unfixable — attempts jump
        # straight to max_attempts instead of retrying pointlessly.
        automation = await session.get(EmailAutomation, uuid.UUID(automation_id))
        assert state.voice_call_attempts == automation.voice_call_max_attempts


@pytest.mark.asyncio
async def test_daily_call_cap_is_enforced(monkeypatch):
    await _fresh_db()
    _enable_twilio(monkeypatch)
    monkeypatch.setattr(settings, "voice_call_daily_limit", 1)
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)

    shopper_a = await _make_shopper()
    shopper_b = await _make_shopper()
    await _create_automation_with_no_response_state(auth, campaign, shop, shopper_a)
    await _create_automation_with_no_response_state(auth, campaign, shop, shopper_b)

    async def fake_create_call(to_number, twiml_url, status_url):
        return "CA_fake_sid"

    monkeypatch.setattr("app.services.voice_call_scheduler.create_call", fake_create_call)

    placed = await process_due_voice_calls()
    assert placed == 1  # capped at 1 even though 2 were eligible

    # A second tick within the same 24h window still respects the cap.
    placed_again = await process_due_voice_calls()
    assert placed_again == 0


@pytest.mark.asyncio
async def test_call_initiation_failure_schedules_retry_then_fails(monkeypatch):
    await _fresh_db()
    _enable_twilio(monkeypatch)
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(
        auth, campaign, shop, shopper_id, max_attempts=2, retry_gap_days=3
    )

    async def always_fails(to_number, twiml_url, status_url):
        raise RuntimeError("Twilio API unreachable")

    monkeypatch.setattr("app.services.voice_call_scheduler.create_call", always_fails)

    await process_due_voice_calls()
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "no_answer"
        assert state.voice_call_attempts == 1
        assert state.voice_call_next_at is not None
        # Force the retry due now instead of sleeping 3 real days.
        state.voice_call_next_at = now() - timedelta(minutes=1)
        await session.commit()

    await process_due_voice_calls()
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "failed"
        assert state.voice_call_attempts == 2


# --------------------------------------------------------------------------- #
# TwiML webhooks
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_twiml_endpoint_returns_greeting(monkeypatch):
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    async with _client() as client:
        r = await client.post(f"/api/voice-calls/twiml/{state_id}", data={"CallSid": "CA123"})
        assert r.status_code == 200
        assert "<Gather" in r.text
        assert "Test Shopper" in r.text or "Hi Test" in r.text


@pytest.mark.asyncio
async def test_twiml_rejects_bad_signature_when_configured(monkeypatch):
    await _fresh_db()
    monkeypatch.setattr(settings, "twilio_auth_token", "real-secret")
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    _, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    async with _client() as client:
        r = await client.post(
            f"/api/voice-calls/twiml/{state_id}", data={"CallSid": "CA123"}, headers={"X-Twilio-Signature": "wrong"}
        )
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_gather_endpoint_concludes_call_on_outcome(monkeypatch):
    # No _enable_twilio here on purpose: no TWILIO_AUTH_TOKEN configured
    # means signature verification auto-passes (see verify_twilio_signature),
    # matching how Twilio wouldn't be "configured" but the webhook itself
    # doesn't gate on is_configured() — only the scheduler does.
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.voice_call_status = "calling"
        session.add(VoiceCallLog(automation_state_id=state.id, attempted_at=now(), status="in-progress", transcript=[]))
        await session.commit()

    async def fake_next_turn(**kwargs):
        return {"say": "Great, thanks for letting us know — goodbye!", "outcome": "interested"}

    monkeypatch.setattr("app.routers.voice_calls.next_turn", fake_next_turn)

    async with _client() as client:
        r = await client.post(
            f"/api/voice-calls/gather/{state_id}",
            data={"SpeechResult": "Yes, I'm interested!", "CallSid": "CA123"},
        )
        assert r.status_code == 200
        assert "<Hangup/>" in r.text
        assert "Great, thanks" in r.text

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_outcome == "interested"
        assert state.voice_call_status == "completed"


@pytest.mark.asyncio
async def test_gather_endpoint_continues_conversation_without_outcome(monkeypatch):
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.voice_call_status = "calling"
        session.add(VoiceCallLog(automation_state_id=state.id, attempted_at=now(), status="in-progress", transcript=[]))
        await session.commit()

    async def fake_next_turn(**kwargs):
        return {"say": "Sorry, could you tell me more?", "outcome": None}

    monkeypatch.setattr("app.routers.voice_calls.next_turn", fake_next_turn)

    async with _client() as client:
        r = await client.post(f"/api/voice-calls/gather/{state_id}", data={"SpeechResult": "hmm", "CallSid": "CA123"})
        assert r.status_code == 200
        # Still mid-conversation: another <Gather> is offered (the trailing
        # fallback <Say>+<Hangup/> is always present too — it only fires if
        # THIS Gather itself times out with no speech, not a sign the call
        # already ended).
        assert "<Gather" in r.text
        assert "Sorry, could you tell me more?" in r.text

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_outcome is None
        assert state.voice_call_status == "calling"


@pytest.mark.asyncio
async def test_status_callback_no_answer_schedules_retry():
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(
        auth, campaign, shop, shopper_id, max_attempts=2, retry_gap_days=3
    )
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.voice_call_status = "calling"
        state.voice_call_attempts = 1
        session.add(VoiceCallLog(automation_state_id=state.id, attempted_at=now(), status="ringing", transcript=[]))
        await session.commit()

    async with _client() as client:
        r = await client.post(f"/api/voice-calls/status/{state_id}", data={"CallStatus": "no-answer", "CallSid": "CA123"})
        assert r.status_code == 204

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "no_answer"
        assert state.voice_call_next_at is not None


@pytest.mark.asyncio
async def test_status_callback_never_overwrites_a_concluded_outcome():
    """A late status callback for a call that already got a real outcome via
    /gather must never clobber it back to no_answer/undecided."""
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _nike_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    automation_id, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.voice_call_status = "completed"
        state.voice_call_outcome = "interested"
        await session.commit()

    async with _client() as client:
        r = await client.post(f"/api/voice-calls/status/{state_id}", data={"CallStatus": "completed", "CallSid": "CA123"})
        assert r.status_code == 204

    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_outcome == "interested"
        assert state.voice_call_status == "completed"


# --------------------------------------------------------------------------- #
# Permission isolation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_voice_call_signature_helper_accepts_valid_and_rejects_tampered():
    settings.twilio_auth_token = "shh"
    try:
        url = "https://example.com/api/voice-calls/twiml/abc"
        params = {"CallSid": "CA1", "From": "+15551234567"}
        import base64
        import hashlib
        import hmac

        data = url
        for k in sorted(params.keys()):
            data += k + params[k]
        valid_sig = base64.b64encode(hmac.new(b"shh", data.encode(), hashlib.sha1).digest()).decode()
        assert voice_call.verify_twilio_signature(url, params, valid_sig) is True
        assert voice_call.verify_twilio_signature(url, params, "tampered") is False
        assert voice_call.verify_twilio_signature(url, params, None) is False
    finally:
        settings.twilio_auth_token = None
