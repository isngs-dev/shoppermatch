"""Voice calls must not be cut off mid-conversation, and bulk numbers are dialled one at a time.

Regression tests for: "the 1st bulk call had a full AI conversation but from the 2nd call on the AI
cut the call halfway". Causes covered: (1) the batch runner dialled the next number every 3s without
waiting for the previous call, so several conversations ran at once on one Plivo number; (2) silence
made the call hang up instead of asking again; (3) a slow/failed AI turn 500'd the webhook, which makes
Plivo drop the call. Every Plivo/OpenAI call is mocked.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import BulkCallBatch, BulkCallTarget, ShopperAutomationState, VoiceCallLog
from app.routers import voice_calls as vc_router
from app.services import bulk_voice_call, voice_call
from app.services.tracking import now

from test_voice_call import (  # noqa: E402  (tests/ is on sys.path in pytest's default import mode)
    _admin_auth,
    _client,
    _create_automation_with_no_response_state,
    _fresh_db,
    _make_shopper,
    _ms_campaign_and_shop,
)


def test_silence_redirects_back_instead_of_hanging_up():
    xml = voice_call.plxml_say_gather("Hello there", "https://x.test/api/voice-calls/bulk-gather/1")
    assert "<GetInput" in xml and 'executionTimeout="30"' in xml
    # No speech heard -> back to our endpoint (which re-prompts), NOT an immediate goodbye + hangup.
    assert '<Redirect method="POST">https://x.test/api/voice-calls/bulk-gather/1?silence=1</Redirect>' in xml
    assert "<Hangup/>" not in xml
    # The counter keeps climbing, and survives an existing query string (the AI-failure counter).
    again = voice_call.plxml_say_gather("Hi", "https://x.test/g?err=1", silence=2)
    assert "https://x.test/g?err=1&amp;silence=3</Redirect>" in again
    # An explicit closing line still hangs up.
    assert "<Hangup/>" in voice_call.plxml_say_gather("Bye", "", hang_up_after=True)


async def _bulk_target(status: str = "calling") -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        batch = BulkCallBatch(created_by="t@x", message=None, total_count=1, status="running")
        session.add(batch)
        await session.flush()
        target = BulkCallTarget(
            batch_id=batch.id, phone_number="+15550001111", status=status,
            transcript=[{"role": "assistant", "text": "Hello!"}],
        )
        session.add(target)
        await session.commit()
        return target.id


async def _target(target_id):
    async with AsyncSessionLocal() as session:
        return await session.get(BulkCallTarget, target_id)


@pytest.mark.asyncio
async def test_bulk_silence_is_reprompted_then_ends_politely(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    await _fresh_db()
    tid = await _bulk_target()
    async with _client() as client:
        # 1st quiet window: ask again, keep the call open, schedule the next silence check.
        r = await client.post(f"/api/voice-calls/bulk-gather/{tid}", data={"CallUUID": "c"})
        assert r.status_code == 200 and "Are you still there" in r.text and "<GetInput" in r.text
        assert "silence=1" in r.text and "<Hangup/>" not in r.text
        r2 = await client.post(f"/api/voice-calls/bulk-gather/{tid}?silence=2", data={"CallUUID": "c"})
        assert "Are you still there" in r2.text and "silence=3" in r2.text and "<Hangup/>" not in r2.text
        assert (await _target(tid)).status == "calling"  # still alive
        # Still nothing after the allowed re-prompts: goodbye, and the target is closed cleanly.
        r3 = await client.post(f"/api/voice-calls/bulk-gather/{tid}?silence=3", data={"CallUUID": "c"})
        assert "<Hangup/>" in r3.text and "goodbye" in r3.text
    t = await _target(tid)
    assert t.status == "completed" and t.outcome == "undecided" and t.ended_at is not None


@pytest.mark.asyncio
async def test_bulk_speech_continues_a_normal_turn_after_silence(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    await _fresh_db()
    tid = await _bulk_target()

    async def fake_next_turn(**kwargs):
        assert kwargs["history"][-1] == {"role": "user", "content": "yes please"}
        return {"say": "Great, tell me more?", "outcome": None}

    monkeypatch.setattr("app.routers.voice_calls.next_turn", fake_next_turn)
    async with _client() as client:
        # Even deep into silence re-prompts, real speech continues the conversation normally.
        r = await client.post(f"/api/voice-calls/bulk-gather/{tid}?silence=2", data={"Speech": "yes please"})
    assert "Great, tell me more?" in r.text
    assert "silence=" not in r.text.split("</GetInput>")[0]  # the listening action URL is clean again


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "too_slow"])
async def test_bulk_ai_failure_keeps_the_call_alive(monkeypatch, failure):
    """An OpenAI error/timeout used to 500 the webhook, which makes Plivo drop the call mid-conversation."""
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    monkeypatch.setattr(vc_router, "AI_TURN_TIMEOUT_SECONDS", 0.05)
    await _fresh_db()
    tid = await _bulk_target()

    async def broken(**kwargs):
        if failure == "raises":
            raise RuntimeError("openai down")
        await asyncio.sleep(1)
        return {"say": "late", "outcome": None}

    monkeypatch.setattr("app.routers.voice_calls.next_turn", broken)
    async with _client() as client:
        r = await client.post(f"/api/voice-calls/bulk-gather/{tid}", data={"Speech": "hello?"})
        assert r.status_code == 200 and "say that again" in r.text and "<GetInput" in r.text
        assert "err=1" in r.text and "<Hangup/>" not in r.text
        r2 = await client.post(f"/api/voice-calls/bulk-gather/{tid}?err=1", data={"Speech": "hello??"})
        assert r2.status_code == 200 and "err=2" in r2.text and "<Hangup/>" not in r2.text
        # Persistent failure: a polite goodbye after a few tries (not an endless loop, not a 500).
        r3 = await client.post(f"/api/voice-calls/bulk-gather/{tid}?err=2", data={"Speech": "anyone?"})
        assert r3.status_code == 200 and "<Hangup/>" in r3.text
    t = await _target(tid)
    assert [x["text"] for x in t.transcript if x["role"] == "user"] == ["hello?", "hello??", "anyone?"]  # nothing lost
    assert t.status == "completed"


@pytest.mark.asyncio
async def test_shopper_call_gather_also_survives_silence_and_ai_failure(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    monkeypatch.setattr(vc_router, "AI_TURN_TIMEOUT_SECONDS", 0.05)
    await _fresh_db()
    auth = await _admin_auth()
    campaign, shop = await _ms_campaign_and_shop(auth)
    shopper_id = await _make_shopper()
    _, state_id = await _create_automation_with_no_response_state(auth, campaign, shop, shopper_id)
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        state.voice_call_status = "calling"
        session.add(VoiceCallLog(automation_state_id=state.id, attempted_at=now(), status="in-progress", transcript=[]))
        await session.commit()

    async def broken(**kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr("app.routers.voice_calls.next_turn", broken)
    async with _client() as client:
        silent = await client.post(f"/api/voice-calls/gather/{state_id}", data={"CallUUID": "c"})
        assert "Are you still there" in silent.text and "<Hangup/>" not in silent.text
        failed = await client.post(f"/api/voice-calls/gather/{state_id}", data={"Speech": "hi"})
        assert failed.status_code == 200 and "say that again" in failed.text and "<Hangup/>" not in failed.text
        done = await client.post(f"/api/voice-calls/gather/{state_id}?silence=3", data={"CallUUID": "c"})
        assert "<Hangup/>" in done.text
    async with AsyncSessionLocal() as session:
        state = await session.get(ShopperAutomationState, uuid.UUID(state_id))
        assert state.voice_call_status == "completed" and state.voice_call_outcome == "undecided"


async def _two_target_batch() -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with AsyncSessionLocal() as session:
        batch = BulkCallBatch(created_by="t@x", message=None, total_count=2, status="running")
        session.add(batch)
        await session.flush()
        targets = [
            BulkCallTarget(batch_id=batch.id, phone_number=n, status="queued") for n in ("+15550001111", "+15550002222")
        ]
        session.add_all(targets)
        await session.commit()
        return batch.id, [t.id for t in targets]


@pytest.mark.asyncio
async def test_bulk_batch_dials_one_number_at_a_time(monkeypatch):
    await _fresh_db()
    monkeypatch.setattr(bulk_voice_call, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(bulk_voice_call, "CALL_PACING_SECONDS", 0)
    batch_id, (first, second) = await _two_target_batch()
    placed: list[str] = []

    async def fake_create_call(to_number, answer_url, hangup_url):
        placed.append(to_number)
        return f"sid-{len(placed)}"

    monkeypatch.setattr(bulk_voice_call, "create_call", fake_create_call)
    task = asyncio.create_task(bulk_voice_call.run_bulk_call_batch(batch_id))
    await asyncio.sleep(0.4)
    # The first call is still in progress: the second number must NOT have been dialled yet.
    assert placed == ["+15550001111"] and (await _target(second)).status == "queued"
    bulk_voice_call.mark_answered(first)
    async with AsyncSessionLocal() as session:  # Plivo's hangup webhook for call 1
        t = await session.get(BulkCallTarget, first)
        t.status = "completed"
        await session.commit()
    # Only now (call 1 over) does the runner dial number 2; finish that call too so the batch can end.
    for _ in range(200):
        if len(placed) == 2:
            break
        await asyncio.sleep(0.01)
    assert placed == ["+15550001111", "+15550002222"]
    async with AsyncSessionLocal() as session:  # Plivo's hangup webhook for call 2
        t = await session.get(BulkCallTarget, second)
        t.status = "completed"
        await session.commit()
    await asyncio.wait_for(task, timeout=5)
    async with AsyncSessionLocal() as session:
        assert (await session.get(BulkCallBatch, batch_id)).status == "completed"


@pytest.mark.asyncio
async def test_bulk_batch_moves_on_when_a_hangup_webhook_never_arrives(monkeypatch):
    await _fresh_db()
    monkeypatch.setattr(bulk_voice_call, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(bulk_voice_call, "CALL_PACING_SECONDS", 0)
    monkeypatch.setattr(bulk_voice_call, "RING_WAIT_SECONDS", 0.1)  # never answered
    monkeypatch.setattr(bulk_voice_call, "CALL_MAX_SECONDS", 0.1)
    batch_id, (first, second) = await _two_target_batch()
    placed: list[str] = []

    async def fake_create_call(to_number, answer_url, hangup_url):
        placed.append(to_number)
        if len(placed) == 2:
            bulk_voice_call.mark_answered(second)  # picked up, but its hangup webhook is lost
        return "sid"

    monkeypatch.setattr(bulk_voice_call, "create_call", fake_create_call)
    await asyncio.wait_for(bulk_voice_call.run_bulk_call_batch(batch_id), timeout=5)
    assert placed == ["+15550001111", "+15550002222"]
    one, two = await _target(first), await _target(second)
    assert one.status == "no-answer" and one.ended_at is not None  # never picked up
    assert two.status == "completed" and two.outcome == "undecided"  # picked up, webhook lost


@pytest.mark.asyncio
async def test_bulk_answer_marks_the_call_as_picked_up(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    await _fresh_db()
    tid = await _bulk_target()
    bulk_voice_call._answered.discard(tid)
    async with _client() as client:
        r = await client.post(f"/api/voice-calls/bulk-answer/{tid}", data={"CallUUID": "c"})
    assert r.status_code == 200 and tid in bulk_voice_call._answered
    bulk_voice_call._answered.discard(tid)


@pytest.mark.asyncio
async def test_create_call_cancels_unanswered_rings_quickly(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_id", "MA_test")
    monkeypatch.setattr(settings, "plivo_auth_token", "tok")
    monkeypatch.setattr(settings, "plivo_phone_number", "+15550009999")
    seen = {}

    class FakeCalls:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"request_uuid": "uuid-1"})()

    class FakeClient:
        def __init__(self, *a):
            self.calls = FakeCalls()

    monkeypatch.setattr("plivo.RestClient", FakeClient)
    assert await voice_call.create_call("+15550001111", "https://a", "https://h") == "uuid-1"
    assert seen["ring_timeout"] == 45 and seen["time_limit"] == 600


@pytest.mark.asyncio
async def test_caller_id_endpoint_reports_the_plivo_number(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from tests.test_bulk_invitations import _login

    monkeypatch.setattr(settings, "plivo_phone_number", "+18888477090")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        auth = await _login(client)
        body = (await client.get("/api/voice-calls/caller-id", headers=auth)).json()
    assert body["from_number"] == "+18888477090"


@pytest.mark.asyncio
async def test_bulk_hangup_keeps_plivos_reason_for_a_cut_call(monkeypatch):
    """A call Plivo/the callee ends early must say why (cause, who, how long), not just read 'completed'."""
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    await _fresh_db()
    tid = await _bulk_target()
    async with _client() as client:
        r = await client.post(
            f"/api/voice-calls/bulk-status/{tid}",
            data={"CallStatus": "completed", "HangupCauseName": "Normal Hangup", "HangupSource": "Callee", "Duration": "12"},
        )
    assert r.status_code == 204
    t = await _target(tid)
    assert t.status == "completed" and t.ended_at is not None
    assert "Callee" in t.error_message and "Normal Hangup" in t.error_message and "12s" in t.error_message
    assert "0 reply" in t.error_message


@pytest.mark.asyncio
async def test_bulk_hangup_after_our_own_goodbye_adds_no_error(monkeypatch):
    monkeypatch.setattr(settings, "plivo_auth_token", None)
    await _fresh_db()
    tid = await _bulk_target(status="completed")
    async with _client() as client:
        await client.post(f"/api/voice-calls/bulk-status/{tid}", data={"CallStatus": "completed", "HangupCauseName": "Normal Hangup"})
    assert (await _target(tid)).error_message is None
