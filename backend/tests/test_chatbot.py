"""Agentic chatbot tests — tenant isolation, shopper scope, the two-step
accept/decline guard, consent-gated callbacks, rate limiting and admin review.

OpenAI is never called: `services.chatbot.agent._chat_completion` (the single
seam) is monkeypatched with a scripted fake that returns tool calls / replies
in order and records what it was sent.
"""
from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    Campaign,
    ChatConversation,
    ChatEscalation,
    Client,
    EmailJob,
    Invitation,
    InvitationEvent,
    Shop,
    Shopper,
    ShopperFollowup,
    ShopperInterest,
    User,
)
from app.routers import chatbot as chatbot_router
from app.seed import maybe_seed
from app.services.chatbot import agent as chatbot_agent
from app.services.chatbot import knowledge
from app.services.chatbot.followups import process_due_followups
from app.services.chatbot.tools import ChatScope, run_tool, tool_specs
from app.services.contact_prefs import phone_opted_out


async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await maybe_seed()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", follow_redirects=False)


async def _login(email: str, password: str) -> dict:
    async with _client() as c:
        r = await c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _admin() -> dict:
    return await _login("admin@isn.com", "isn-demo-2026")


async def _ms_client() -> dict:
    return await _login("client@ms-demo.example", "ms-demo-2026")


def _call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
    }


def _say(text: str) -> dict:
    return {"role": "assistant", "content": text}


class FakeLLM:
    """Scripted stand-in for `_chat_completion`: pops one message per call."""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.seen: list[list[dict]] = []

    async def __call__(self, messages, tools, model=None):
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        assert self.script, "FakeLLM ran out of scripted messages"
        item = self.script.pop(0)
        return item(messages) if callable(item) else item


@pytest.fixture
def fake_llm(monkeypatch):
    def install(script: list[dict]) -> FakeLLM:
        fake = FakeLLM(script)
        monkeypatch.setattr(chatbot_agent, "_chat_completion", fake)
        return fake

    return install


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    chatbot_router._limiter._hits.clear()
    yield
    chatbot_router._limiter._hits.clear()


async def _make_invitation(campaign_name_contains: str = "MS") -> tuple[str, str]:
    """A fresh invitation (own shopper) → (tracking_token, invitation_id)."""
    async with AsyncSessionLocal() as session:
        camp = (
            await session.execute(select(Campaign).where(Campaign.name.ilike(f"%{campaign_name_contains}%")).limit(1))
        ).scalar_one()
        shop = (await session.execute(select(Shop).where(Shop.campaign_id == camp.id).limit(1))).scalar_one()
        shopper = Shopper(
            shopper_code=f"SHP-{uuid.uuid4().hex[:8]}",
            name="Chat Tester",
            email=f"chat-{uuid.uuid4().hex[:6]}@example.com",
            phone="+15551230000",
        )
        session.add(shopper)
        await session.flush()
        inv = Invitation(
            campaign_id=camp.id,
            shop_id=shop.id,
            shopper_id=shopper.id,
            reference=f"INV-T{uuid.uuid4().hex[:5]}",
            email=shopper.email,
            subject="Test invite",
        )
        session.add(inv)
        await session.commit()
        return str(inv.tracking_token), str(inv.id)



async def _make_rival_tenant() -> str:
    """A second tenant (client + campaign + shop + one invitation) the MS
    client must never be able to see. Returns the rival campaign's name."""
    async with AsyncSessionLocal() as session:
        rival = Client(company_name=f"Rival Co {uuid.uuid4().hex[:4]}", status="active")
        session.add(rival)
        await session.flush()
        camp = Campaign(name="Rival Secret Campaign", client_name=rival.company_name, client_id=rival.id, status="active")
        session.add(camp)
        await session.flush()
        shop = Shop(campaign_id=camp.id, shop_name="Rival Flagship", city="Gotham", state="NY", required_shoppers=3)
        shopper = Shopper(shopper_code=f"SHP-{uuid.uuid4().hex[:8]}", name="Rival Shopper", email="rival@example.com")
        session.add_all([shop, shopper])
        await session.flush()
        session.add(
            Invitation(
                campaign_id=camp.id, shop_id=shop.id, shopper_id=shopper.id,
                reference=f"INV-R{uuid.uuid4().hex[:5]}", email=shopper.email, subject="rival",
            )
        )
        await session.commit()
        return camp.name


async def _scope_for(audience: str, *, user_email: str | None = None, invitation_id: str | None = None):
    """Open a session and build a ChatScope (caller must close the session)."""
    session = AsyncSessionLocal()
    user = None
    if user_email:
        user = (await session.execute(select(User).where(User.email == user_email))).scalar_one()
    inv = None
    if invitation_id:
        inv = (
            await session.execute(
                select(Invitation).where(Invitation.id == uuid.UUID(invitation_id))
            )
        ).scalar_one()
        await session.refresh(inv, ["shopper", "shop", "campaign"])
    conv = ChatConversation(
        audience=audience, session_key="k" * 24, user_id=user.id if user else None, invitation_id=inv.id if inv else None
    )
    session.add(conv)
    await session.flush()
    return session, ChatScope(audience=audience, conversation=conv, user=user, invitation=inv)


# --------------------------------------------------------------------------- #
# Availability / failure behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_not_configured_fails_explicitly(monkeypatch):
    await _fresh_db()
    monkeypatch.setattr(settings, "openai_api_key", None)
    auth = await _admin()
    async with _client() as c:
        assert (await c.get("/api/chatbot/status")).json() == {"available": False}
        r = await c.post("/api/chatbot/staff/message", json={"message": "hi"}, headers=auth)
        assert r.status_code == 503  # never a fake answer


@pytest.mark.asyncio
async def test_staff_endpoint_requires_auth():
    await _fresh_db()
    async with _client() as c:
        assert (await c.post("/api/chatbot/staff/message", json={"message": "hi"})).status_code == 401


# --------------------------------------------------------------------------- #
# Staff: tenant isolation (the load-bearing constraint)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_client_only_sees_own_campaigns():
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    session, scope = await _scope_for("staff", user_email="client@ms-demo.example")
    try:
        names = {c["name"] for c in (await run_tool(session, scope, "list_campaigns", {}))["campaigns"]}
        assert names and rival_name not in names
        assert all("MS" in n for n in names)
        # The rival's campaign can't be reached by name, overview, shop gaps or funnel.
        assert "error" in await run_tool(session, scope, "campaign_overview", {"campaign_name": rival_name})
        assert "error" in await run_tool(session, scope, "outreach_funnel", {"campaign_name": rival_name})
        gaps = await run_tool(session, scope, "shops_needing_shoppers", {})
        assert all(s["campaign"] != rival_name for s in gaps["shops"])
        # Aggregate funnel counts only this tenant's invitations.
        total = (await run_tool(session, scope, "outreach_funnel", {}))["total"]
        ms_total = len(
            (
                await session.execute(
                    select(Invitation)
                    .join(Campaign, Campaign.id == Invitation.campaign_id)
                    .where(Campaign.client_id == scope.user.client_id)
                )
            ).scalars().all()
        )
        assert total == ms_total
        events = (await run_tool(session, scope, "recent_activity", {"limit": 15}))["events"]
        assert all(e["campaign"] != rival_name for e in events)
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_admin_sees_all_campaigns():
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    session, scope = await _scope_for("staff", user_email="admin@isn.com")
    try:
        res = await run_tool(session, scope, "list_campaigns", {})
        assert rival_name in {c["name"] for c in res["campaigns"]}
        assert "error" not in await run_tool(session, scope, "campaign_overview", {"campaign_name": rival_name})
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_list_campaigns_files_campaigns_the_way_the_app_does_and_finds_them_by_name():
    await _fresh_db()
    session, scope = await _scope_for("staff", user_email="admin@isn.com")
    try:
        a, b, c = (await session.execute(select(Campaign).order_by(Campaign.name).limit(3))).scalars().all()
        a.status, b.status, c.status = "draft", "in_progress", "completed"
        await session.flush()

        async def found(campaign, status):
            res = await run_tool(session, scope, "list_campaigns", {"status": status, "name": campaign.name})
            # A hit that only came from the "other statuses" fallback is not a match for that status.
            return campaign.name in {x["name"] for x in res["campaigns"]} and "note" not in res, res["total_matching"]

        # "draft" is upcoming and "in_progress" is active — not just the literal statuses "upcoming" / "active".
        assert (await found(a, "upcoming"))[0] and not (await found(a, "active"))[0]
        assert (await found(b, "active"))[0] and not (await found(b, "upcoming"))[0]
        assert (await found(c, "completed"))[0] and not (await found(c, "active"))[0]
        # A name alone finds it whatever its status, and the total says how many matched.
        by_name = await run_tool(session, scope, "list_campaigns", {"name": a.name})
        assert a.name in {x["name"] for x in by_name["campaigns"]} and by_name["total_matching"] >= 1
        # Asking for a campaign by name under the wrong status still finds it, and says so.
        wrong = await run_tool(session, scope, "list_campaigns", {"status": "active", "name": a.name})
        assert a.name in {x["name"] for x in wrong["campaigns"]} and "other statuses" in wrong["note"]
        # Without a name nothing is widened: the filter is honoured.
        assert "note" not in await run_tool(session, scope, "list_campaigns", {"status": "completed"})
    finally:
        await session.rollback()
        await session.close()


def test_the_staff_agent_is_reminded_of_the_ids_it_already_looked_up():
    from types import SimpleNamespace

    from app.services.chatbot.agent import _known_entities

    cid, sid = "54721e66-b0b1-404e-9ea1-96a2fcff20b4", "0d02ba33-03e3-4d25-b0b8-1dc4d34e6e4b"
    rows = [  # newest first, as the query returns them
        SimpleNamespace(meta={"name": "call_api"}, content='{"data": {"items": [{"id": "%s", "shop_name": "Dunkin\\u2019s \\u2014 Loop"}]}}' % sid),
        SimpleNamespace(
            meta={"name": "list_campaigns"},
            content='{"campaigns": [{"id": "%s", "name": "Dunkin\\u2019s Philadelphia Store Audit #20", "status": "completed"}, {"id": "%s", "name": "Cut off ca' % (cid, sid),
        ),
        SimpleNamespace(meta={"name": "shops_needing_shoppers"}, content='{"id": "%s", "name": "ignored"}' % cid),
    ]
    found = dict(_known_entities(rows))
    assert found[cid] == "Dunkin\u2019s Philadelphia Store Audit #20"  # decoded, and read from a truncated result
    assert found[sid] == "Dunkin\u2019s \u2014 Loop"  # the newest mention wins; no repeats
    assert len(found) == 2 and _known_entities([]) == []


@pytest.mark.asyncio
async def test_shopper_identities_are_admin_only():
    await _fresh_db()
    token, _ = await _make_invitation()
    # Client: no shopper tools, and activity rows carry no shopper names.
    session, scope = await _scope_for("staff", user_email="client@ms-demo.example")
    try:
        names = {s["function"]["name"] for s in tool_specs(scope)}
        assert "shopper_search" not in names and "shopper_history" not in names
        assert "error" in await run_tool(session, scope, "shopper_search", {"query": "a"})
        assert "error" in await run_tool(session, scope, "shopper_history", {"shopper": "a"})
        assert "error" in await run_tool(session, scope, "chat_escalations", {})
        events = (await run_tool(session, scope, "recent_activity", {"limit": 15}))["events"]
        assert all("shopper" not in e for e in events)
    finally:
        await session.rollback()
        await session.close()
    # Admin: can search shoppers.
    session, scope = await _scope_for("staff", user_email="admin@isn.com")
    try:
        assert {"shopper_search", "chat_escalations"} <= {s["function"]["name"] for s in tool_specs(scope)}
        res = await run_tool(session, scope, "shopper_search", {"query": "Chat Tester"})
        assert res["total_matching"] >= 1
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_staff_flow_end_to_end_persists_tool_calls(fake_llm):
    await _fresh_db()
    fake_llm([_call("outreach_funnel", {}), _say("Here is your funnel.")])
    auth = await _ms_client()
    async with _client() as c:
        r = await c.post("/api/chatbot/staff/message", json={"message": "How is outreach doing?"}, headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reply"] == "Here is your funnel."
        assert body["session_key"] is None  # staff are bearer-authenticated
        # Resuming with the same user keeps the conversation.
        fake_llm([_say("Sure.")])
        r2 = await c.post(
            "/api/chatbot/staff/message",
            json={"message": "thanks", "conversation_id": body["conversation_id"]},
            headers=auth,
        )
        assert r2.json()["conversation_id"] == body["conversation_id"]
        # A client can't read transcripts via the admin API.
        assert (await c.get("/api/chatbot/admin/conversations", headers=auth)).status_code == 403
        admin = await _admin()
        detail = (await c.get(f"/api/chatbot/admin/conversations/{body['conversation_id']}", headers=admin)).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles[:3] == ["user", "tool", "assistant"]
    assert detail["messages"][1]["meta"]["name"] == "outreach_funnel"


@pytest.mark.asyncio
async def test_other_users_conversation_is_not_resumed(fake_llm):
    await _fresh_db()
    fake_llm([_say("one"), _say("two")])
    ms = await _ms_client()
    admin = await _admin()
    async with _client() as c:
        first = (await c.post("/api/chatbot/staff/message", json={"message": "hi"}, headers=ms)).json()
        stolen = (
            await c.post(
                "/api/chatbot/staff/message",
                json={"message": "hi", "conversation_id": first["conversation_id"]},
                headers=admin,
            )
        ).json()
    assert stolen["conversation_id"] != first["conversation_id"]


@pytest.mark.asyncio
async def test_navigate_returns_ui_action(fake_llm):
    await _fresh_db()
    fake_llm([_call("navigate", {"page": "bulk_voice_call"}), _say("Opening it.")])
    auth = await _ms_client()
    async with _client() as c:
        r = await c.post("/api/chatbot/staff/message", json={"message": "take me to bulk calls"}, headers=auth)
    assert r.json()["actions"] == [
        {"type": "navigate", "path": "/client/email-automation?tab=bulk-call", "label": "Bulk Voice Call"}
    ]


# --------------------------------------------------------------------------- #
# Shopper: scope + the two-step accept/decline guard
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_shopper_cannot_use_another_shoppers_conversation(fake_llm):
    await _fresh_db()
    token_a, _ = await _make_invitation()
    token_b, _ = await _make_invitation()
    fake_llm([_say("a"), _say("b")])
    async with _client() as c:
        a = (await c.post(f"/api/chatbot/shopper/{token_a}/message", json={"message": "hi"})).json()
        b = (
            await c.post(
                f"/api/chatbot/shopper/{token_b}/message",
                json={"message": "hi", "conversation_id": a["conversation_id"], "session_key": a["session_key"]},
            )
        ).json()
    assert b["conversation_id"] != a["conversation_id"]


@pytest.mark.asyncio
async def test_shopper_wrong_session_key_starts_fresh(fake_llm):
    await _fresh_db()
    token, _ = await _make_invitation()
    fake_llm([_say("a"), _say("b")])
    async with _client() as c:
        a = (await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "hi"})).json()
        b = (
            await c.post(
                f"/api/chatbot/shopper/{token}/message",
                json={"message": "hi", "conversation_id": a["conversation_id"], "session_key": "wrong"},
            )
        ).json()
    assert b["conversation_id"] != a["conversation_id"]


@pytest.mark.asyncio
async def test_shopper_bad_token_is_404():
    await _fresh_db()
    async with _client() as c:
        assert (await c.post("/api/chatbot/shopper/not-a-token/message", json={"message": "hi"})).status_code == 404
        r = await c.post(f"/api/chatbot/shopper/{uuid.uuid4()}/message", json={"message": "hi"})
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Visitor: consent, resume protection, knowledge fallback
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_visitor_callback_requires_consent(fake_llm):
    await _fresh_db()
    # Model tries to store details without consent -> refused, nothing saved.
    fake_llm(
        [
            _call("request_callback", {"name": "Sam", "email": "sam@example.com", "consent_given": False}),
            _say("May we store your details?"),
        ]
    )
    async with _client() as c:
        r1 = (await c.post("/api/chatbot/visitor/message", json={"message": "call me, I'm sam@example.com"})).json()
        assert r1["escalated"] is False
        async with AsyncSessionLocal() as s:
            conv = await s.get(ChatConversation, uuid.UUID(r1["conversation_id"]))
            assert conv.contact_email is None and conv.contact_consent is False
        # With consent + valid details it is stored.
        fake_llm(
            [
                _call("request_callback", {"name": "Sam", "email": "sam@example.com", "consent_given": True, "reason": "wants to join"}),
                _say("Thanks Sam, we'll be in touch."),
            ]
        )
        r2 = (
            await c.post(
                "/api/chatbot/visitor/message",
                json={"message": "yes you may", "conversation_id": r1["conversation_id"], "session_key": r1["session_key"]},
            )
        ).json()
    assert r2["escalated"] is True
    async with AsyncSessionLocal() as s:
        conv = await s.get(ChatConversation, uuid.UUID(r2["conversation_id"]))
        assert conv.contact_email == "sam@example.com" and conv.contact_consent is True


@pytest.mark.asyncio
async def test_visitor_callback_validates_contact():
    await _fresh_db()
    session, scope = await _scope_for("visitor")
    try:
        bad = await run_tool(session, scope, "request_callback", {"name": "Sam", "email": "nope", "consent_given": True})
        assert bad["status"] == "invalid_email"
        none = await run_tool(session, scope, "request_callback", {"name": "Sam", "consent_given": True})
        assert none["status"] == "missing_details"
        assert scope.conversation.status == "open"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_visitor_has_no_database_tools():
    await _fresh_db()
    session, scope = await _scope_for("visitor")
    try:
        names = {s["function"]["name"] for s in tool_specs(scope)}
        assert names == {"open_opportunities", "request_callback", "search_knowledge"}
        # Aggregate counts only — no brand or client names leak.
        res = await run_tool(session, scope, "open_opportunities", {})
        flat = json.dumps(res).lower()
        assert "ms" not in flat and "starbucks" not in flat and "best buy" not in flat
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_unanswered_questions_trigger_callback_nudge(fake_llm):
    await _fresh_db()
    miss = _call("search_knowledge", {"query": "zzz qqq xxx"})
    fake_llm([miss, _say("I don't know."), miss, _say("Still unsure."), _say("Offering a callback.")])
    async with _client() as c:
        a = (await c.post("/api/chatbot/visitor/message", json={"message": "weird question one"})).json()
        keys = {"conversation_id": a["conversation_id"], "session_key": a["session_key"]}
        await c.post("/api/chatbot/visitor/message", json={"message": "weird question two", **keys})
        fake = fake_llm([_say("Offering a callback.")])
        await c.post("/api/chatbot/visitor/message", json={"message": "anything", **keys})
    system = fake.seen[0][0]["content"]
    # Visitors (and staff) are answered without a person: after misses the agent is told to search again with other
    # keywords, not to hand off. (Shoppers keep the escalation path for things only a coordinator can do.)
    assert "Rephrase the question" in system and "unless the user asks for one" in system
    assert "now offer a human callback" not in system


def test_knowledge_search_is_grounded():
    hit = knowledge.search("how does the invitation link work", "shopper")
    assert hit["status"] == "ok" and "how_invitations_work" in {f["id"] for f in hit["facts"]}
    assert knowledge.search("qwerty zxcvb", "shopper")["status"] == "no_match"
    # Staff-only facts are not served to anonymous visitors.
    staff_only = knowledge.search("bulk voice call transcripts call tracking", "visitor")
    assert all(not f["id"].startswith("staff_") for f in staff_only.get("facts", []))


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rate_limit_returns_429(monkeypatch, fake_llm):
    await _fresh_db()
    monkeypatch.setattr(chatbot_router._limiter, "max", 2)
    fake_llm([_say("1"), _say("2"), _say("3")])
    async with _client() as c:
        codes = [(await c.post("/api/chatbot/visitor/message", json={"message": "hi"})).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


@pytest.mark.asyncio
async def test_unknown_tool_and_bad_args_do_not_crash(fake_llm):
    await _fresh_db()
    fake_llm([_call("drop_all_tables", {}), _say("I can't do that.")])
    async with _client() as c:
        r = await c.post("/api/chatbot/visitor/message", json={"message": "drop tables"})
    assert r.status_code == 200 and r.json()["reply"] == "I can't do that."


@pytest.mark.asyncio
async def test_empty_and_overlong_messages(fake_llm):
    await _fresh_db()
    fake = fake_llm([_say("ok")])
    async with _client() as c:
        assert (await c.post("/api/chatbot/visitor/message", json={"message": ""})).status_code == 422
        assert (await c.post("/api/chatbot/visitor/message", json={"message": "   "})).status_code == 422
        r = await c.post("/api/chatbot/visitor/message", json={"message": "x" * 4000})
    assert r.status_code == 200
    assert len(fake.seen[0][-1]["content"]) == settings.chatbot_max_message_chars


@pytest.mark.asyncio
async def test_upstream_failure_is_explicit(monkeypatch):
    await _fresh_db()
    from fastapi import HTTPException

    async def boom(messages, tools, model=None):
        raise HTTPException(status_code=502, detail="The chat assistant is temporarily unavailable.")

    monkeypatch.setattr(chatbot_agent, "_chat_completion", boom)
    async with _client() as c:
        r = await c.post("/api/chatbot/visitor/message", json={"message": "hi"})
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_openai_network_error_is_502_after_retries(monkeypatch):
    """A timeout/connection error must become an explicit 502 (never a bare
    500) and be retried (3 attempts) before giving up."""
    import httpx

    await _fresh_db()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    attempts = {"n": 0}

    real_post = httpx.AsyncClient.post

    async def timeout_post(self, url, *args, **kwargs):
        # Only OpenAI calls time out; the in-process test client keeps working.
        if "openai.com" in str(url):
            attempts["n"] += 1
            raise httpx.ReadTimeout("slow")
        return await real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", timeout_post)
    async with _client() as c:
        r = await c.post("/api/chatbot/visitor/message", json={"message": "hi"})
    assert r.status_code == 502
    assert attempts["n"] == 3



# =========================================================================== #
# Shopper campaign assistant — spec tools and rules
# =========================================================================== #
from datetime import datetime, timedelta, timezone  # noqa: E402

from app.services.chatbot.shopper_tools import IST  # noqa: E402


def _today_ist():
    return datetime.now(IST).date()


async def _first_available_shop(session, scope) -> dict:
    res = await run_tool(session, scope, "list_available_shops", {})
    assert res["shops"], res
    return res["shops"][0]


def _valid_date_for(shop: dict) -> str:
    """A date inside the shop's visit window and not in the past (IST)."""
    start, end = shop["visit_window"].split(" to ")
    pick = max(_today_ist(), datetime.fromisoformat(start).date())
    assert pick <= datetime.fromisoformat(end).date()
    return pick.isoformat()


@pytest.mark.asyncio
async def test_update_response_requires_confirmation_on_a_later_turn(fake_llm):
    await _fresh_db()
    token, inv_id = await _make_invitation()

    async def response_now():
        async with AsyncSessionLocal() as s:
            return (await s.get(Invitation, uuid.UUID(inv_id))).response

    # Turn 1: the model tries to accept at once, even twice in the same turn.
    fake_llm(
        [
            _call("update_shopper_response", {"response": "accepted"}, "a"),
            _call("update_shopper_response", {"response": "accepted"}, "b"),
            _say("Shall I confirm that you accept?"),
        ]
    )
    async with _client() as c:
        r1 = (await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "accept it"})).json()
        assert await response_now() is None
        fake_llm([_call("update_shopper_response", {"response": "accepted"}), _say("Done.")])
        r2 = (
            await c.post(
                f"/api/chatbot/shopper/{token}/message",
                json={"message": "yes", "conversation_id": r1["conversation_id"], "session_key": r1["session_key"]},
            )
        ).json()
    assert r2["conversation_id"] == r1["conversation_id"]
    assert await response_now() == "accepted"


@pytest.mark.asyncio
async def test_changed_arguments_do_not_count_as_confirmation(fake_llm):
    await _fresh_db()
    token, inv_id = await _make_invitation()
    fake_llm([_call("update_shopper_response", {"response": "accepted"}), _say("Confirm accept?")])
    async with _client() as c:
        r1 = (await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "accept"})).json()
        fake_llm([_call("update_shopper_response", {"response": "declined"}), _say("Confirm decline?")])
        await c.post(
            f"/api/chatbot/shopper/{token}/message",
            json={"message": "no, decline", "conversation_id": r1["conversation_id"], "session_key": r1["session_key"]},
        )
    async with AsyncSessionLocal() as s:
        assert (await s.get(Invitation, uuid.UUID(inv_id))).response is None


@pytest.mark.asyncio
async def test_maybe_is_not_final():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        await run_tool(session, scope, "update_shopper_response", {"response": "maybe", "reason": "check schedule"})
        scope.conversation.turn_count = 1
        res = await run_tool(session, scope, "update_shopper_response", {"response": "maybe", "reason": "check schedule"})
        assert res["status"] == "noted"
        assert scope.invitation.response is None and scope.invitation.responded_at is None
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_record_interest_two_step_and_not_a_booking():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop = await _first_available_shop(session, scope)
        args = {"shop_id": shop["shop_id"], "preferred_date": _valid_date_for(shop), "preferred_time": "morning"}
        first = await run_tool(session, scope, "record_shopper_interest", args)
        assert first["status"] == "needs_confirmation"
        assert (await session.execute(select(ShopperInterest))).scalars().first() is None
        scope.conversation.turn_count += 1  # the shopper said yes on a later turn
        done = await run_tool(session, scope, "record_shopper_interest", args)
        assert done["status"] == "recorded" and done["shopper_status"] == "Shopper Responded / Pending Confirmation"
        assert "NOT a booking" in done["note"]
        await session.flush()
        row = (await session.execute(select(ShopperInterest))).scalars().one()
        assert row.status == "Shopper Responded / Pending Confirmation" and str(row.shop_id) == shop["shop_id"]
        # The activity trail got an event on the invitation.
        evs = (await session.execute(select(InvitationEvent.event_type).where(InvitationEvent.invitation_id == scope.invitation.id))).scalars().all()
        assert "shopper_interest_recorded" in evs
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_interest_rejects_bad_dates_and_foreign_shops():
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop = await _first_available_shop(session, scope)
        yesterday = (_today_ist() - timedelta(days=1)).isoformat()
        assert "past" in (await run_tool(session, scope, "record_shopper_interest", {"shop_id": shop["shop_id"], "preferred_date": yesterday}))["error"]
        assert "YYYY-MM-DD" in (await run_tool(session, scope, "record_shopper_interest", {"shop_id": shop["shop_id"], "preferred_date": "next sat"}))["error"]
        far = (_today_ist() + timedelta(days=900)).isoformat()
        assert "window" in (await run_tool(session, scope, "record_shopper_interest", {"shop_id": shop["shop_id"], "preferred_date": far}))["error"]
        # A shop from another tenant/campaign: same "no such shop" as a missing one.
        rival_shop = (await session.execute(select(Shop).join(Campaign, Campaign.id == Shop.campaign_id).where(Campaign.name == rival_name))).scalar_one()
        for tool, a in (
            ("record_shopper_interest", {"shop_id": str(rival_shop.id), "preferred_date": _today_ist().isoformat()}),
            ("get_shop_status", {"shop_id": str(rival_shop.id)}),
        ):
            assert (await run_tool(session, scope, tool, a))["error"] == "No such shop in this campaign."
        assert (await run_tool(session, scope, "get_shop_status", {"shop_id": str(uuid.uuid4())}))["error"] == "No such shop in this campaign."
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_multi_campaign_only_allows_campaigns_the_shopper_was_invited_to(monkeypatch):
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    _, inv_id = await _make_invitation()
    monkeypatch.setattr(settings, "chatbot_mode", "multi_campaign")
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        # Not invited to the rival campaign -> still unreachable, even in multi mode.
        err = await run_tool(session, scope, "get_campaign_details", {"campaign_name": "Rival Secret"})
        assert "error" in err
        ctx = await run_tool(session, scope, "get_shopper_context", {})
        assert rival_name not in ctx["campaigns_invited_to"]
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_list_shops_is_capped_at_five_and_filters():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        res = await run_tool(session, scope, "list_available_shops", {})
        assert len(res["shops"]) <= 5
        assert res["more_available"] == max(0, res["total_matching"] - len(res["shops"]))
        city = res["shops"][0]["city"]
        filtered = await run_tool(session, scope, "list_available_shops", {"city": city})
        assert all(city.lower() in (s["city"] or "").lower() or city.lower() in (s["state"] or "").lower() for s in filtered["shops"])
        none = await run_tool(session, scope, "list_available_shops", {"city": "Atlantis"})
        assert none["shops"] == [] and none["total_matching"] == 0
        # An over-narrow filter must not read as "no shops exist": the result names where shops ARE open.
        assert "does NOT mean there are none" in none["instruction"] and none["areas_with_open_shops"]
        assert "error" in await run_tool(session, scope, "list_available_shops", {"date": "tomorrow"})
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_shop_status_never_claims_scheduled_without_basis():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        invited_shop = str(scope.invitation.shop_id)
        res = await run_tool(session, scope, "get_shop_status", {"shop_id": invited_shop})
        assert res["status"] == "Contacted" and res["can_say_assigned"] is False
        # Accepting an invitation is a response, not a confirmed booking.
        scope.invitation.response, scope.invitation.responded_at = "accepted", datetime.now(timezone.utc)
        res2 = await run_tool(session, scope, "get_shop_status", {"shop_id": invited_shop})
        assert res2["status"] == "Responded" and res2["can_say_assigned"] is False
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_client_confidential_hides_brand():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        open_ = await run_tool(session, scope, "get_campaign_details", {})
        assert open_["client"] and open_["client_name_hidden"] is False
        scope.invitation.campaign.client_confidential = True
        hidden = await run_tool(session, scope, "get_campaign_details", {})
        assert hidden["client"] is None and hidden["client_name_hidden"] is True
        assert scope.invitation.campaign.client_name not in json.dumps(hidden)
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_eligibility_reports_criteria():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        res = await run_tool(session, scope, "check_eligibility", {})
        names = {c["criterion"] for c in res["criteria"]}
        assert "Account active and available" in names and "Within travel distance" in names
        assert all(c["met"] in (True, False, None) and c["detail"] for c in res["criteria"])
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_campaign_knowledge_grounded_and_no_match_counts():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop_name = scope.invitation.shop.shop_name
        hit = await run_tool(session, scope, "search_campaign_knowledge", {"query": f"where is {shop_name}"})
        assert hit["status"] == "ok" and any(f["source"] == "shop_info" for f in hit["facts"])
        miss = await run_tool(session, scope, "search_campaign_knowledge", {"query": "zzzz qqqq wwww"})
        assert miss["status"] == "no_match" and "escalate" in miss["instruction"]
        assert scope.conversation.unanswered_count == 1
        form = await run_tool(session, scope, "get_form_guide", {})
        assert form["status"] == "no_data" and "NEVER suggest answers" in form["reminders"]
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_escalation_records_summary_and_sla():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        bad = await run_tool(session, scope, "escalate_to_coordinator", {"summary": "x", "reason": "because", "priority": "high"})
        assert "error" in bad and scope.conversation.status == "open"
        ok = await run_tool(
            session, scope, "escalate_to_coordinator",
            {"summary": "Shopper: Chat\nIssue: payment missing", "reason": "payment_issue", "priority": "high"},
        )
        assert ok == {"status": "escalated", "coordinator_sla": settings.chatbot_coordinator_sla}
        await session.flush()
        row = (await session.execute(select(ChatEscalation))).scalars().one()
        assert row.reason == "payment_issue" and row.priority == "high" and row.kind == "escalation"
        assert scope.conversation.status == "escalated"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_reschedule_and_cancel_need_reason_date_and_confirmation():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        assert "reason" in (await run_tool(session, scope, "request_reschedule_or_cancel", {"action": "cancel", "reason": " "}))["error"]
        assert "new date" in (await run_tool(session, scope, "request_reschedule_or_cancel", {"action": "reschedule", "reason": "busy"}))["error"]
        args = {"action": "reschedule", "reason": "family event", "new_date": (_today_ist() + timedelta(days=3)).isoformat()}
        assert (await run_tool(session, scope, "request_reschedule_or_cancel", args))["status"] == "needs_confirmation"
        scope.conversation.turn_count += 1
        done = await run_tool(session, scope, "request_reschedule_or_cancel", args)
        assert done["status"] == "requested" and settings.chatbot_coordinator_sla in done["next_step"]
        await session.flush()
        row = (await session.execute(select(ChatEscalation))).scalars().one()
        assert row.kind == "reschedule" and row.new_date == args["new_date"]
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_followups_email_sent_phone_handed_off_and_opt_out_respected():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    when = (datetime.now(IST) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    try:
        assert "future" in (await run_tool(session, scope, "schedule_followup", {"channel": "email", "purpose": "visit_reminder", "send_at": "2020-01-01T09:00"}))["error"]
        assert "purpose" in (await run_tool(session, scope, "schedule_followup", {"channel": "email", "purpose": "spam", "send_at": when}))["error"]
        for ch in ("email", "phone"):
            a = {"channel": ch, "purpose": "visit_reminder", "send_at": when}
            assert (await run_tool(session, scope, "schedule_followup", a))["status"] == "needs_confirmation"
            scope.conversation.turn_count += 1
            assert (await run_tool(session, scope, "schedule_followup", a))["status"] == "scheduled"
        await session.commit()
        rows = (await session.execute(select(ShopperFollowup))).scalars().all()
        assert {r.channel for r in rows} == {"email", "phone"} and all(r.status == "pending" for r in rows)
        # Make them due and process: email is "sent" via the mock provider, phone goes to a coordinator.
        for r in rows:
            r.send_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()
        assert await process_due_followups() == 2
        async with AsyncSessionLocal() as check:
            by = {r.channel: r for r in (await check.execute(select(ShopperFollowup))).scalars().all()}
            assert by["email"].status == "sent" and by["phone"].status == "handed_to_coordinator"
            assert (await check.execute(select(ChatEscalation).where(ChatEscalation.priority == "low"))).scalars().first() is not None

        # Opt out of email, schedule is now refused, and a pending one is skipped, never sent.
        session.add(ShopperFollowup(shopper_id=scope.invitation.shopper_id, invitation_id=scope.invitation.id, channel="email",
                                    purpose="form_deadline", send_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await session.commit()
        out = await run_tool(session, scope, "record_opt_out", {"channel": "email"})
        assert out == {"status": "opted_out", "channel": "email"}  # immediate: no confirmation round
        await session.commit()
        assert "opted out" in (await run_tool(session, scope, "schedule_followup", {"channel": "email", "purpose": "visit_reminder", "send_at": when}))["error"]
        async with AsyncSessionLocal() as check:
            pend = (await check.execute(select(ShopperFollowup).where(ShopperFollowup.purpose == "form_deadline"))).scalars().one()
            assert pend.status == "skipped_opt_out"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_opt_out_blocks_email_outbox_and_phone_numbers():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    from app.services.outbox import process_one_email_job

    async with AsyncSessionLocal() as s:
        inv = await s.get(Invitation, uuid.UUID(inv_id))
        shopper = await s.get(Shopper, inv.shopper_id)
        shopper.opted_out_email = True
        shopper.opted_out_phone = True
        s.add(EmailJob(invitation_id=inv.id, provider="mock", status="queued", next_attempt_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        await s.commit()
        phone = shopper.phone
    assert await process_one_email_job() is True
    async with AsyncSessionLocal() as s:
        job = (await s.execute(select(EmailJob))).scalars().one()
        assert job.status == "failed" and "opted out" in job.last_error
        # Number matching ignores formatting, and non-opted-out numbers are fine.
        assert await phone_opted_out(s, "1 (555) 123-0000") is True
        assert await phone_opted_out(s, "+19998887777") is False


@pytest.mark.asyncio
async def test_shopper_prompt_follows_the_spec(fake_llm, monkeypatch):
    await _fresh_db()
    token, inv_id = await _make_invitation()
    monkeypatch.setattr(settings, "chatbot_assistant_name", "Maya")
    fake = fake_llm([_say("ok")])
    async with _client() as c:
        await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "hi"})
    system = fake.seen[0][0]["content"]
    assert "You are Maya" in system and "IST" in system
    assert "Chat" in system  # first name of the seeded shopper "Chat Tester"
    assert "Client confidentiality: false" in system
    assert "NEVER suggest answers" in system and "Shopper identified: true" in system
    names = {s["function"]["name"] for s in tool_specs(ChatScope(audience="shopper", conversation=ChatConversation(audience="shopper", session_key="k"), invitation=None))}
    assert names == {
        "get_campaign_details", "search_campaign_knowledge", "list_available_shops", "get_shop_status", "get_shopper_context",
        "check_eligibility", "get_form_guide", "record_shopper_interest", "update_shopper_response",
        "request_reschedule_or_cancel", "schedule_followup", "record_opt_out", "escalate_to_coordinator", "log_activity",
    }
    # No tool takes a shopper id or campaign id from the model.
    for s in tool_specs(ChatScope(audience="shopper", conversation=ChatConversation(audience="shopper", session_key="k"))):
        assert not {"shopper_id", "campaign_id"} & set(s["function"]["parameters"]["properties"])


@pytest.mark.asyncio
async def test_greeting_and_accessed_event():
    await _fresh_db()
    token, inv_id = await _make_invitation()
    async with _client() as c:
        g = (await c.get(f"/api/chatbot/shopper/{token}/greeting")).json()["greeting"]
        assert g.startswith("Hi Chat!") and "Maya" in g and "campaign" in g
        assert (await c.get(f"/api/chatbot/shopper/{uuid.uuid4()}/greeting")).status_code == 404
    # "Chatbot accessed" lands on the invitation timeline when a chat starts.
    chatbot_agent_fake = FakeLLM([_say("hi")])
    import pytest as _p  # noqa: F401
    original = chatbot_agent._chat_completion
    chatbot_agent._chat_completion = chatbot_agent_fake
    try:
        async with _client() as c:
            await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "hello"})
    finally:
        chatbot_agent._chat_completion = original
    async with AsyncSessionLocal() as s:
        evs = (await s.execute(select(InvitationEvent.event_type).where(InvitationEvent.invitation_id == uuid.UUID(inv_id)))).scalars().all()
    assert "chatbot_accessed" in evs


@pytest.mark.asyncio
async def test_log_activity_and_admin_escalation_views(fake_llm):
    await _fresh_db()
    token, inv_id = await _make_invitation()
    fake_llm([
        _call("log_activity", {"event_type": "chatbot_interaction", "details": "asked about pay"}, "a"),
        _call("escalate_to_coordinator", {"summary": "Shopper: Chat\nIssue: pay", "reason": "payment_issue", "priority": "high"}, "b"),
        _say("A coordinator has been informed."),
    ])
    admin = await _admin()
    async with _client() as c:
        r = (await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "I was not paid"})).json()
        assert r["escalated"] is True
        items = (await c.get("/api/chatbot/admin/escalations", headers=admin)).json()["items"]
        assert items[0]["reason"] == "payment_issue" and items[0]["shopper"] == "Chat Tester"
        ms = await _ms_client()
        assert (await c.get("/api/chatbot/admin/escalations", headers=ms)).status_code == 403
    async with AsyncSessionLocal() as s:
        evs = (await s.execute(select(InvitationEvent).where(InvitationEvent.invitation_id == uuid.UUID(inv_id)))).scalars().all()
        assert any(e.event_type == "chatbot_activity" and e.event_metadata["activity"] == "chatbot_interaction" for e in evs)
        assert any(e.event_type == "chatbot_escalated" for e in evs)
    # Staff assistant (admin) sees it through the tool too.
    session, scope = await _scope_for("staff", user_email="admin@isn.com")
    try:
        res = await run_tool(session, scope, "chat_escalations", {})
        assert res["shopper_requests"][0]["reason"] == "payment_issue"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_complex_model_routing(fake_llm, monkeypatch):
    await _fresh_db()
    token, _ = await _make_invitation()
    calls: list[str | None] = []

    class Rec(FakeLLM):
        async def __call__(self, messages, tools, model=None):
            calls.append(model)
            return await super().__call__(messages, tools, model)

    rec = Rec([_say("a"), _say("b")])
    monkeypatch.setattr(chatbot_agent, "_chat_completion", rec)
    monkeypatch.setattr(settings, "chatbot_complex_model", "gpt-big")
    async with _client() as c:
        await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "what is the visit window"})
        await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "this is unacceptable, I want a refund"})
    assert calls == [None, "gpt-big"]



@pytest.mark.asyncio
async def test_markdown_is_stripped_from_replies(fake_llm):
    await _fresh_db()
    fake_llm([_say("1. **Account active**: yes\n2. Use `this`")])
    async with _client() as c:
        r = (await c.post("/api/chatbot/visitor/message", json={"message": "hi"})).json()
    assert r["reply"] == "1. Account active: yes\n2. Use this"



@pytest.mark.asyncio
async def test_confirmation_ignores_free_text_extras_but_not_the_shop_or_date():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop = await _first_available_shop(session, scope)
        d = _valid_date_for(shop)
        first = {"shop_id": shop["shop_id"], "preferred_date": d, "preferred_time": "morning", "notes": "ok"}
        assert (await run_tool(session, scope, "record_shopper_interest", first))["status"] == "needs_confirmation"
        scope.conversation.turn_count += 1
        # Same shop + date, different wording of the optional extras -> confirmed.
        again = {"shop_id": shop["shop_id"], "preferred_date": d, "preferred_time": "subah", "notes": "different words"}
        assert (await run_tool(session, scope, "record_shopper_interest", again))["status"] == "recorded"
        await session.flush()
        row = (await session.execute(select(ShopperInterest))).scalars().one()
        assert row.preferred_time == "subah"  # the latest wording is what gets stored

        # A different DATE on the confirming turn is a new proposal, not a confirmation.
        other = (_today_ist() + timedelta(days=3)).isoformat()
        if shop["bookable_dates"].split(" to ")[1] >= other >= shop["bookable_dates"].split(" to ")[0] and other != d:
            scope.conversation.turn_count += 1
            res = await run_tool(session, scope, "record_shopper_interest", {"shop_id": shop["shop_id"], "preferred_date": other})
            assert res["status"] == "needs_confirmation"
    finally:
        await session.rollback()
        await session.close()



@pytest.mark.asyncio
async def test_shop_can_be_referenced_by_name_but_only_if_unambiguous_and_in_scope():
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop = await _first_available_shop(session, scope)
        by_name = shop["name"].upper().replace(" ", "_")  # model-style "MS_MANHATTAN"
        res = await run_tool(session, scope, "get_shop_status", {"shop_id": by_name})
        assert "error" not in res, res
        # A rival campaign's shop name resolves to nothing.
        assert "error" in await run_tool(session, scope, "get_shop_status", {"shop_id": "Rival Flagship"})
        assert "error" in await run_tool(session, scope, "get_shop_status", {"shop_id": "no such place"})
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_previously_listed_shops_are_given_back_to_the_model(fake_llm):
    """Tool results aren't replayed in history, so the prompt must re-supply the shop_ids it listed earlier."""
    await _fresh_db()
    token, _ = await _make_invitation()
    fake = fake_llm([_call("list_available_shops", {}), _say("Here are the shops."), _say("Noted.")])
    async with _client() as c:
        r1 = (await c.post(f"/api/chatbot/shopper/{token}/message", json={"message": "show shops"})).json()
        await c.post(
            f"/api/chatbot/shopper/{token}/message",
            json={"message": "the first one", "conversation_id": r1["conversation_id"], "session_key": r1["session_key"]},
        )
    first_turn_system = fake.seen[0][0]["content"]
    second_turn_system = fake.seen[-1][0]["content"]
    assert "Shops you already showed" not in first_turn_system
    assert "Shops you already showed" in second_turn_system and "shop_id" in second_turn_system



@pytest.mark.asyncio
async def test_two_writes_can_share_one_confirmation():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _scope_for("shopper", invitation_id=inv_id)
    try:
        shop = await _first_available_shop(session, scope)
        interest = {"shop_id": shop["shop_id"], "preferred_date": _valid_date_for(shop)}
        when = (datetime.now(IST) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        reminder = {"channel": "email", "purpose": "visit_reminder", "send_at": when}
        # Same turn: both are only proposed.
        assert (await run_tool(session, scope, "record_shopper_interest", interest))["status"] == "needs_confirmation"
        assert (await run_tool(session, scope, "schedule_followup", reminder))["status"] == "needs_confirmation"
        scope.conversation.turn_count += 1  # one "yes" from the shopper covers both
        assert (await run_tool(session, scope, "record_shopper_interest", interest))["status"] == "recorded"
        assert (await run_tool(session, scope, "schedule_followup", reminder))["status"] == "scheduled"
        # A confirmation is single-use: repeating it later needs a fresh yes.
        scope.conversation.turn_count += 1
        assert (await run_tool(session, scope, "schedule_followup", reminder))["status"] == "needs_confirmation"
    finally:
        await session.rollback()
        await session.close()



@pytest.mark.asyncio
async def test_staff_can_request_a_callback_and_admin_sees_it(fake_llm):
    await _fresh_db()
    fake_llm([
        _call("request_callback", {"reason": "Questions about our campaign results", "phone": "+1 555 010 2030", "preferred_time": "tomorrow 3pm"}),
        _say("Done — a team member will contact you."),
    ])
    ms = await _ms_client()
    async with _client() as c:
        r = (await c.post("/api/chatbot/staff/message", json={"message": "can someone call me back?"}, headers=ms)).json()
        assert r["escalated"] is True and "contact you" in r["reply"]
        admin = await _admin()
        items = (await c.get("/api/chatbot/admin/escalations", headers=admin)).json()["items"]
    cb = next(i for i in items if i["kind"] == "callback")
    assert "client@ms-demo.example" in cb["summary"] and "+1 555 010 2030" in cb["summary"] and "tomorrow 3pm" in cb["summary"]
    session, scope = await _scope_for("staff", user_email="admin@isn.com")
    try:
        listed = await run_tool(session, scope, "chat_escalations", {})
        assert any(e["kind"] == "callback" for e in listed["shopper_requests"])
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_staff_callback_validation_and_no_duplicates():
    await _fresh_db()
    session, scope = await _scope_for("staff", user_email="client@ms-demo.example")
    try:
        bad = await run_tool(session, scope, "request_callback", {"reason": "pricing", "phone": "call me maybe"})
        assert bad["status"] == "invalid_phone" and scope.conversation.status == "open"
        bad_mail = await run_tool(session, scope, "request_callback", {"email": "not-an-email"})
        assert bad_mail["status"] == "invalid_email" and scope.conversation.status == "open"
        # Nothing else is required: account name/email are used and the reason has a default.
        ok = await run_tool(session, scope, "request_callback", {"name": "Sam", "email": "sam@example.com"})
        assert ok["status"] == "requested" and scope.conversation.status == "escalated"
        assert scope.conversation.contact_email == "sam@example.com" and scope.conversation.contact_name == "Sam"
        assert (await run_tool(session, scope, "request_callback", {"reason": "again"}))["status"] == "already_requested"
        assert "request_callback" in {s["function"]["name"] for s in tool_specs(scope)}
    finally:
        await session.rollback()
        await session.close()



# =========================================================================== #
# Staff agent: everything the user can do, through the app's own API
# =========================================================================== #
from app.models import AuditLog  # noqa: E402
from app.services.chatbot import api_tools  # noqa: E402


async def _rival_campaign_id(rival_name: str) -> str:
    async with AsyncSessionLocal() as s:
        return str((await s.execute(select(Campaign.id).where(Campaign.name == rival_name))).scalar_one())


async def _staff_scope(email: str):
    return await _scope_for("staff", user_email=email)


def test_api_catalog_hides_sensitive_operations_and_scopes_by_role():
    from app.models import User as _U

    conv = ChatConversation(audience="staff", session_key="k")
    admin = ChatScope(audience="staff", conversation=conv, user=_U(name="a", email="a@x", role="admin"))
    client = ChatScope(audience="staff", conversation=conv, user=_U(name="c", email="c@x", role="client"))
    every = api_tools._catalog()
    paths = {p for _, p in every}
    for banned in ("/api/auth", "/api/admin", "/api/chatbot", "/api/webhooks", "/api/public", "/api/voice/"):
        assert not any(p.startswith(banned) for p in paths), banned
    assert ("POST", "/api/client/account/delete") not in every and ("POST", "/api/client/account/deactivate") not in every
    assert ("POST", "/api/invitations/{tracking_token}/respond") not in every
    assert all(m == "GET" for m, p in every if p.startswith(("/api/integrations", "/api/settings")))
    # Core portal areas are there, and a client doesn't get admin-only areas.
    assert ("GET", "/api/campaigns") in api_tools.catalog_for(client) and ("POST", "/api/automations") in api_tools.catalog_for(client)
    assert not any(p.startswith(("/api/integrations", "/api/audit-logs")) for _, p in api_tools.catalog_for(client))
    # Visibility follows who the SERVER lets call each route: an admin-only route is hidden from clients,
    # client-only routes from admins, and public (unauthenticated) routes from everyone.
    assert ("GET", "/api/reports/campaigns/{campaign_id}") in api_tools.catalog_for(admin)
    assert ("GET", "/api/reports/campaigns/{campaign_id}") not in api_tools.catalog_for(client)
    assert ("GET", "/api/client/dashboard") in api_tools.catalog_for(client)
    assert ("GET", "/api/client/dashboard") not in api_tools.catalog_for(admin)
    assert not any(v["access"] == "admin" for v in api_tools.catalog_for(client).values())
    assert not any(v["access"] == "client" for v in api_tools.catalog_for(admin).values())
    assert all((m, p) in api_tools._access_map() for m, p in every)  # nothing unauthenticated is offered
    text = api_tools.catalog_text(client)
    assert "GET /api/campaigns" in text and "/api/auth" not in text


def test_the_assistant_can_operate_ai_autopilot_and_real_sends_need_a_clear_yes():
    from app.models import User as _U

    conv = ChatConversation(audience="staff", session_key="k")
    admin = ChatScope(audience="staff", conversation=conv, user=_U(name="a", email="a@x", role="admin"))
    client = ChatScope(audience="staff", conversation=conv, user=_U(name="c", email="c@x", role="client"))
    for scope in (admin, client):
        cat = api_tools.catalog_for(scope)
        for op in (
            ("GET", "/api/autopilot/campaigns/{campaign_id}"),
            ("PUT", "/api/autopilot/campaigns/{campaign_id}"),
            ("POST", "/api/autopilot/campaigns/{campaign_id}/run"),
            ("PUT", "/api/autopilot/defaults"),
        ):
            assert op in cat, op
    assert "AI Autopilot" in api_tools.catalog_text(client)
    # Running it, or switching it on, can email real shoppers: both are flagged as high impact for the confirmation.
    assert api_tools._impact("POST", "/api/autopilot/campaigns/{campaign_id}/run")[0] == "high"
    assert api_tools._impact("PUT", "/api/autopilot/campaigns/{campaign_id}")[0] == "high"
    assert api_tools._impact("PUT", "/api/autopilot/defaults")[0] == "high"


@pytest.mark.asyncio
async def test_api_reads_keep_tenant_isolation():
    await _fresh_db()
    rival_name = await _make_rival_tenant()
    rival_id = await _rival_campaign_id(rival_name)
    session, scope = await _staff_scope("client@ms-demo.example")
    try:
        res = await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/campaigns"})
        assert res["status_code"] == 200
        assert rival_name not in json.dumps(res["data"])
        # The rival's campaign is a 404 from the real endpoint, exactly as in the UI.
        other = await run_tool(session, scope, "call_api", {"method": "GET", "path": f"/api/campaigns/{rival_id}"})
        assert other["status_code"] == 404
        assert rival_name not in json.dumps(other)
    finally:
        await session.rollback()
        await session.close()
    admin_session, admin_scope = await _staff_scope("admin@isn.com")
    try:
        res = await run_tool(admin_session, admin_scope, "call_api", {"method": "GET", "path": f"/api/campaigns/{rival_id}"})
        assert res["status_code"] == 200
    finally:
        await admin_session.rollback()
        await admin_session.close()


@pytest.mark.asyncio
async def test_api_rejects_paths_outside_the_catalog():
    await _fresh_db()
    session, scope = await _staff_scope("client@ms-demo.example")
    try:
        for path in (
            "/api/auth/login",
            "/api/admin/users",
            "/api/chatbot/staff/message",
            "http://evil.example/api/campaigns",
            "/api/campaigns/../admin/users",
            "/api/campaigns?status=active",
            "//api/campaigns",
            "/api/client/account/delete",
            "/openapi.json",
        ):
            res = await run_tool(session, scope, "call_api", {"method": "GET" if "delete" not in path else "POST", "path": path})
            assert "error" in res and "status_code" not in res, (path, res)
        assert "error" in await run_tool(session, scope, "call_api", {"method": "TRACE", "path": "/api/campaigns"})
        # Admin-only areas aren't offered to a client user at all.
        assert "error" in await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/audit-logs"})
        assert "error" in await run_tool(session, scope, "describe_api_operation", {"method": "GET", "path": "/api/audit-logs"})
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_api_write_is_proposed_then_runs_the_stored_proposal_after_a_yes():
    await _fresh_db()
    session, scope = await _staff_scope("client@ms-demo.example")
    body = {"name": "Reminder (approved)", "subject": "Your visit", "html_body": "<p>Hi</p>"}
    try:
        async def template_names():
            r = await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/email-templates"})
            return {t["name"] for t in r["data"]["items"]}

        before = await template_names()
        prop = await run_tool(session, scope, "call_api", {"method": "POST", "path": "/api/email-templates", "body": body})
        assert prop["status"] == "needs_confirmation" and prop["risk"] == "normal" and prop["request_body"] == body
        token = prop["confirmation_token"]
        assert await template_names() == before  # nothing happened

        # Same message: the user hasn't answered, so the token is refused.
        early = await run_tool(session, scope, "call_api", {"confirm_token": token})
        assert early["status"] == "needs_user_confirmation" and await template_names() == before

        scope.conversation.turn_count += 1  # the user said yes
        # The model tries to sneak in a different body: it is ignored, the stored proposal runs.
        done = await run_tool(
            session, scope, "call_api",
            {"confirm_token": token, "method": "POST", "path": "/api/email-templates", "body": {**body, "name": "SWAPPED"}},
        )
        assert done["status_code"] == 200 and done["executed"] == "POST /api/email-templates", done
        names = await template_names()
        assert "Reminder (approved)" in names and "SWAPPED" not in names
        assert scope.ui_actions == [{"type": "refresh", "label": "Refresh page"}]
        # Single use.
        assert "error" in await run_tool(session, scope, "call_api", {"confirm_token": token})
        # Audited.
        async with AsyncSessionLocal() as check:
            audit = (await check.execute(select(AuditLog).where(AuditLog.action == "chatbot.api_call"))).scalars().all()
            assert any("POST /api/email-templates" in (a.summary or "") for a in audit)
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_real_world_effects_are_called_out_before_confirmation():
    await _fresh_db()
    _, inv_id = await _make_invitation()
    session, scope = await _staff_scope("client@ms-demo.example")
    try:
        send = await run_tool(session, scope, "call_api", {"method": "POST", "path": f"/api/invitations/{inv_id}/send"})
        assert send["status"] == "needs_confirmation" and send["risk"] == "high" and "real emails" in send["effect"]
        calls = await run_tool(session, scope, "call_api", {"method": "POST", "path": "/api/voice-calls/bulk", "body": {"numbers": ["+15550001111"]}})
        assert calls["risk"] == "high" and "REAL phone calls" in calls["effect"]
        auto = await run_tool(session, scope, "call_api", {"method": "POST", "path": f"/api/automations/{uuid.uuid4()}/start"})
        assert auto["risk"] == "high" and "email sequence" in auto["effect"]
        post = await run_tool(session, scope, "call_api", {"method": "POST", "path": f"/api/social/posts/{uuid.uuid4()}/publish"})
        assert post["risk"] == "high" and "publishes" in post["effect"]
        delete = await run_tool(session, scope, "call_api", {"method": "DELETE", "path": f"/api/email-templates/{uuid.uuid4()}"})
        assert delete["risk"] == "high" and "permanently deletes" in delete["effect"]
        # None of those ran: no confirmation was ever given.
        async with AsyncSessionLocal() as check:
            assert (await check.execute(select(AuditLog).where(AuditLog.action == "chatbot.api_call"))).scalars().first() is None
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_api_per_turn_caps_and_large_responses():
    await _fresh_db()
    session, scope = await _staff_scope("admin@isn.com")
    try:
        big = await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/shoppers"})
        assert len(json.dumps(big["data"])) <= api_tools.MAX_RESPONSE_CHARS + 1000
        scope.api_writes = api_tools.MAX_WRITES_PER_TURN
        prop = await run_tool(session, scope, "call_api", {"method": "POST", "path": "/api/email-templates", "body": {"name": "n", "subject": "s", "html_body": "b"}})
        scope.conversation.turn_count += 1
        capped = await run_tool(session, scope, "call_api", {"confirm_token": prop["confirmation_token"]})
        assert "Too many changes" in capped["error"]
        scope.api_calls = api_tools.MAX_CALLS_PER_TURN
        assert "Too many API calls" in (await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/campaigns"}))["error"]
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_describe_operation_returns_fields():
    await _fresh_db()
    session, scope = await _staff_scope("client@ms-demo.example")
    try:
        d = await run_tool(session, scope, "describe_api_operation", {"method": "POST", "path": "/api/email-templates"})
        assert d["writes"] is True and d["body_fields"]["name"]["required"] is True and "subject" in d["body_fields"]
        by_concrete = await run_tool(session, scope, "describe_api_operation", {"method": "GET", "path": f"/api/campaigns/{uuid.uuid4()}"})
        assert by_concrete["operation"] == "GET /api/campaigns/{campaign_id}" and by_concrete["writes"] is False
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_staff_chat_confirms_across_turns_end_to_end(fake_llm):
    """Turn 1 proposes (nothing happens); turn 2 the user says yes and the model confirms with the token
    it is shown in its instructions."""
    await _fresh_db()
    import re as _re

    body = {"name": "Chat-made template", "subject": "Hello", "html_body": "<p>Hello</p>"}
    ms = await _ms_client()

    def confirm(messages):
        token = _re.search(r"confirmation_token ([0-9a-f]{6})", messages[0]["content"]).group(1)
        return _call("call_api", {"confirm_token": token})

    fake_llm([
        _call("call_api", {"method": "POST", "path": "/api/email-templates", "body": body}),
        _say("I'll create the template 'Chat-made template'. Shall I go ahead?"),
        confirm,
        _say("Done — the template is created."),
    ])
    async with _client() as c:
        r1 = (await c.post("/api/chatbot/staff/message", json={"message": "create a template called Chat-made template"}, headers=ms)).json()
        assert r1["actions"] == []  # nothing changed yet, so no refresh button
        listing = (await c.get("/api/email-templates", headers=ms)).json()["items"]
        assert all(t["name"] != "Chat-made template" for t in listing)
        r2 = (await c.post("/api/chatbot/staff/message", json={"message": "yes, go ahead", "conversation_id": r1["conversation_id"]}, headers=ms)).json()
        assert r2["actions"] == [{"type": "refresh", "label": "Refresh page"}]
        listing = (await c.get("/api/email-templates", headers=ms)).json()["items"]
        assert any(t["name"] == "Chat-made template" for t in listing)


@pytest.mark.asyncio
async def test_staff_prompt_lists_operations_and_pending_actions(fake_llm):
    await _fresh_db()
    fake = fake_llm([_say("hi")])
    ms = await _ms_client()
    async with _client() as c:
        await c.post("/api/chatbot/staff/message", json={"message": "hello"}, headers=ms)
    system = fake.seen[0][0]["content"]
    assert "OPERATIONS YOU CAN CALL" in system and "GET /api/campaigns" in system and "POST /api/automations" in system
    assert "/api/auth" not in system and "/api/admin" not in system
    assert "never ask for details you already have" in system



@pytest.mark.asyncio
async def test_repeating_the_identical_write_on_a_later_turn_confirms_it_once():
    await _fresh_db()
    session, scope = await _staff_scope("client@ms-demo.example")
    body = {"name": "Repeat-confirmed", "subject": "S", "html_body": "<p>b</p>"}
    call = {"method": "POST", "path": "/api/email-templates", "body": body}
    try:
        async def names():
            r = await run_tool(session, scope, "call_api", {"method": "GET", "path": "/api/email-templates"})
            return [t["name"] for t in r["data"]["items"]]

        assert (await run_tool(session, scope, "call_api", call))["status"] == "needs_confirmation"
        # Same turn: repeating is NOT a confirmation (the user hasn't spoken yet).
        again = await run_tool(session, scope, "call_api", call)
        assert again["status"] == "needs_confirmation" and "Repeat-confirmed" not in await names()
        scope.conversation.turn_count += 1  # the user said yes
        # A DIFFERENT body is a new proposal, not a confirmation.
        changed = await run_tool(session, scope, "call_api", {**call, "body": {**body, "name": "Other"}})
        assert changed["status"] == "needs_confirmation" and "Other" not in await names()
        # The identical call now runs the original proposal, exactly once.
        done = await run_tool(session, scope, "call_api", call)
        assert done["status_code"] == 200 and (await names()).count("Repeat-confirmed") == 1
        scope.conversation.turn_count += 1
        assert (await run_tool(session, scope, "call_api", call))["status"] == "needs_confirmation"  # needs a fresh yes
    finally:
        await session.rollback()
        await session.close()



@pytest.mark.asyncio
async def test_repeated_identical_tool_calls_are_stopped_and_rounds_end_with_a_summary(fake_llm):
    await _fresh_db()
    same = _call("list_campaigns", {"status": "active"})
    # The model loops on one call until the rounds run out, then must wrap up without tools.
    script = [same] * (settings.chatbot_staff_max_tool_rounds + 1) + [_say("I looked up your campaigns but couldn't finish; how should we continue?")]
    fake = fake_llm(script)
    ms = await _ms_client()
    async with _client() as c:
        r = (await c.post("/api/chatbot/staff/message", json={"message": "start an automation"}, headers=ms)).json()
        admin = await _admin()
        detail = (await c.get(f"/api/chatbot/admin/conversations/{r['conversation_id']}", headers=admin)).json()
    assert "couldn't finish" in r["reply"]
    tool_msgs = [m for m in detail["messages"] if m["role"] == "tool"]
    assert "campaigns" in tool_msgs[0]["content"]  # the first call really ran
    assert all("already made this exact call" in m["content"] for m in tool_msgs[1:])


@pytest.mark.asyncio
async def test_staff_model_setting_is_used(fake_llm, monkeypatch):
    await _fresh_db()
    monkeypatch.setattr(settings, "chatbot_staff_model", "gpt-staff")
    seen: list = []

    class Rec(FakeLLM):
        async def __call__(self, messages, tools, model=None):
            seen.append(model)
            return await super().__call__(messages, tools, model)

    monkeypatch.setattr(chatbot_agent, "_chat_completion", Rec([_say("a"), _say("b")]))
    ms = await _ms_client()
    async with _client() as c:
        await c.post("/api/chatbot/staff/message", json={"message": "hi"}, headers=ms)
        await c.post("/api/chatbot/visitor/message", json={"message": "hi"})
    assert seen == ["gpt-staff", None]  # only the staff agent uses it



@pytest.mark.asyncio
async def test_staff_agent_knows_which_page_the_user_is_on(fake_llm):
    await _fresh_db()
    fake = fake_llm([_say("ok"), _say("ok"), _say("ok")])
    ms = await _ms_client()
    async with _client() as c:
        await c.post("/api/chatbot/staff/message", headers=ms,
                     json={"message": "what can I do here?", "page": "/client/email-automation?tab=bulk-call"})
        await c.post("/api/chatbot/staff/message", headers=ms, json={"message": "hi", "page": "javascript:alert(1)"})
        await c.post("/api/chatbot/staff/message", headers=ms, json={"message": "hi"})
    with_page, hostile, none = (f[0]["content"] for f in fake.seen)
    assert "currently on the page /client/email-automation" in with_page and "Bulk Voice Call tab" in with_page
    assert "currently on the page" not in hostile and "currently on the page" not in none  # only plain in-app paths are used
    # Shoppers/visitors never receive a page (nothing to leak into their prompt).
    fake2 = fake_llm([_say("ok")])
    async with _client() as c:
        await c.post("/api/chatbot/visitor/message", json={"message": "hi", "page": "/client/dashboard"})
    assert "currently on the page" not in fake2.seen[0][0]["content"]



@pytest.mark.asyncio
async def test_client_can_fetch_its_own_dashboard_and_profile_and_navigate_names_are_forgiving():
    await _fresh_db()
    session, scope = await _staff_scope("client@ms-demo.example")
    try:
        for path in ("/api/client/dashboard", "/api/client/profile", "/api/client/reports"):
            res = await run_tool(session, scope, "call_api", {"method": "GET", "path": path})
            assert res["status_code"] == 200, (path, res)
        # An admin-only route is simply not available to a client (no wasted 403 round trip).
        assert "error" in await run_tool(session, scope, "call_api", {"method": "GET", "path": f"/api/reports/campaigns/{uuid.uuid4()}"})
        assert "error" not in await run_tool(session, scope, "navigate", {"page": "Profile"})
        assert "error" not in await run_tool(session, scope, "navigate", {"page": "bulk voice call"})
        assert scope.ui_actions[0]["path"] == "/client/profile" and scope.ui_actions[1]["path"] == "/client/email-automation?tab=bulk-call"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_the_agent_is_handed_the_relevant_knowledge_before_it_answers(fake_llm):
    """Grounding must not depend on the model remembering to call the search tool."""
    await _fresh_db()
    fake = fake_llm([_say("ok"), _say("ok"), _say("ok")])
    async with _client() as c:
        a = (await c.post("/api/chatbot/visitor/message", json={"message": "How do I create an account for my company?"})).json()
        keys = {"conversation_id": a["conversation_id"], "session_key": a["session_key"]}
        # A short follow-up is searched together with the previous question.
        await c.post("/api/chatbot/visitor/message", json={"message": "and the password?", **keys})
        await c.post("/api/chatbot/visitor/message", json={"message": "qwerty zxcvb"})
    first, follow_up, nonsense = (fake.seen[i][0]["content"] for i in range(3))
    assert "KNOWLEDGE BASE EXCERPTS" in first and "Create a client account" in first
    assert "KNOWLEDGE BASE EXCERPTS" in follow_up and "Forgot or reset my password" in follow_up
    assert "KNOWLEDGE BASE EXCERPTS" not in nonsense  # nothing relevant: no noise is injected


@pytest.mark.asyncio
async def test_the_assistant_never_pushes_a_human_for_a_product_question(fake_llm):
    await _fresh_db()
    fake = fake_llm([_say("ok")])
    async with _client() as c:
        await c.post("/api/chatbot/visitor/message", json={"message": "what is shoppermatch"})
    system = fake.seen[0][0]["content"]
    assert "do NOT push the user to a human" in system and "without any human support" in system
