"""Tools for the shopper-facing campaign assistant (spec: "ShopperMatch —
Agentic Campaign Assistant").

Identity and scope come ONLY from the secure invitation link the chat was
opened with (`scope.invitation`): the model never supplies a shopper id, and
every shop id it passes is re-validated against the campaigns this shopper may
discuss. Write tools that change something for the shopper are gated in code —
the first call only records a pending action and asks the model to get an
explicit "yes"; it is honoured only when the identical call repeats on a
LATER user turn.

Nothing here books a shop on the source MS platform (SASSIE / ShopMetrics):
interest and reschedule/cancel requests are recorded for a coordinator, and a
shop only reads "Scheduled" when its status really says so.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import settings
from ...models import (
    INTEREST_PENDING,
    Campaign,
    ChatEscalation,
    Invitation,
    Shop,
    Shopper,
    ShopperFollowup,
    ShopperInterest,
)
from ...serializers import iso
from ..audit import record_audit
from ..recommendation import haversine_km
from ..tracking import add_event, mark_response
from . import knowledge
from .base import ChatScope, ToolHandler, spec

IST = timezone(timedelta(hours=5, minutes=30))
MAX_SHOPS = 5

ESCALATION_REASONS = [
    "payment_issue",
    "assignment_conflict",
    "technical_issue",
    "complaint",
    "data_deletion",
    "low_confidence",
    "policy_question",
]
ACTIVITY_TYPES = ["chatbot_interaction", "eligibility_checked", "interest_recorded", "escalated", "other"]


# --------------------------------------------------------------------------- #
# Scope helpers
# --------------------------------------------------------------------------- #
def _inv(scope: ChatScope) -> Invitation:
    assert scope.invitation is not None
    return scope.invitation


def _shopper(scope: ChatScope) -> Shopper:
    return _inv(scope).shopper


async def _allowed_campaigns(session: AsyncSession, scope: ChatScope) -> list[Campaign]:
    """single_campaign: just the invitation's campaign. multi_campaign: every
    campaign THIS shopper was invited to — never any other."""
    inv = _inv(scope)
    if settings.chatbot_mode != "multi_campaign":
        return [inv.campaign]
    ids = (
        await session.execute(select(Invitation.campaign_id).where(Invitation.shopper_id == inv.shopper_id).distinct())
    ).scalars().all()
    rows = (await session.execute(select(Campaign).where(Campaign.id.in_(ids)))).scalars().all()
    return list(rows) or [inv.campaign]


async def _pick_campaign(session: AsyncSession, scope: ChatScope, name: str | None) -> tuple[Campaign | None, dict | None]:
    allowed = await _allowed_campaigns(session, scope)
    if not name or not name.strip() or settings.chatbot_mode != "multi_campaign":
        # Single-campaign mode (or no name given): the invitation's own campaign.
        return (_inv(scope).campaign if len(allowed) > 1 or not allowed else allowed[0]), None
    matches = [c for c in allowed if name.strip().lower() in c.name.lower()]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, {"error": "That campaign isn't one this shopper was invited to.", "campaigns": [c.name for c in allowed]}
    return None, {"error": "More than one campaign matches — ask which.", "campaigns": [c.name for c in matches]}


async def _shop_in_scope(session: AsyncSession, scope: ChatScope, shop_id: str | None) -> tuple[Shop | None, dict | None]:
    if not shop_id:
        return None, {"error": "shop_id is required (use an id returned by list_available_shops)."}
    allowed = {c.id for c in await _allowed_campaigns(session, scope)}
    try:
        sid = uuid.UUID(str(shop_id))
    except ValueError:
        # The model sometimes passes the shop's name instead of its id: accept it
        # only when it identifies exactly ONE shop in the campaigns allowed here.
        wanted = re.sub(r"[^a-z0-9]", "", str(shop_id).lower())
        shops = (await session.execute(select(Shop).where(Shop.campaign_id.in_(allowed)).limit(400))).scalars().all()
        hits = [x for x in shops if wanted and re.sub(r"[^a-z0-9]", "", x.shop_name.lower()) == wanted]
        if len(hits) == 1:
            return hits[0], None
        return None, {"error": "That shop_id is not valid — use one from list_available_shops."}
    shop = (await session.execute(select(Shop).where(Shop.id == sid))).scalar_one_or_none()
    if shop is None or shop.campaign_id not in allowed:
        # Same answer for "doesn't exist" and "not yours" — never confirm other campaigns' shops.
        return None, {"error": "No such shop in this campaign."}
    return shop, None


def _display_client(campaign: Campaign) -> str | None:
    return None if campaign.client_confidential else campaign.client_name


def _c(campaign: Campaign | None, text: str | None) -> str | None:
    """Redact the client/brand name from `text` when the campaign is confidential
    (campaign, shop and description text often contain it)."""
    if text is None or campaign is None or not campaign.client_confidential or not campaign.client_name:
        return text
    return re.sub(re.escape(campaign.client_name), "the client", text, flags=re.IGNORECASE)


def _window(shop: Shop) -> str | None:
    if shop.visit_start and shop.visit_end:
        return f"{shop.visit_start.date().isoformat()} to {shop.visit_end.date().isoformat()}"
    return None


def _bookable_window(shop: Shop) -> str | None:
    """Visit window clipped to today (IST) — the only dates worth proposing."""
    if not (shop.visit_start and shop.visit_end):
        return None
    start = max(_today_ist(), shop.visit_start.date())
    end = shop.visit_end.date()
    return f"{start.isoformat()} to {end.isoformat()}" if start <= end else None


def _fee(shop: Shop) -> str | None:
    return f"{shop.compensation} {shop.currency}" if shop.compensation else None


def _gate(scope: ChatScope, tool: str, args: dict) -> dict | None:
    """Two-step write guard enforced in code. `args` holds only the fields that
    define WHAT is being confirmed (shop, date, action ...); free-text extras such
    as notes or a reason are deliberately left out, because a model rarely
    repeats those word for word. Returns needs_confirmation on the first call, None
    (proceed) when a call with the same key fields repeats on a LATER user turn."""
    conv = scope.conversation
    key = tool + ":" + json.dumps(args, sort_keys=True, default=str)
    # Several different writes can be waiting for one "yes" (e.g. record interest AND set a
    # reminder), so keep a small map of key -> the turn it was proposed on.
    pending: dict[str, int] = dict((conv.pending_action or {}).get("keys") or {})
    if key in pending and int(pending[key]) < conv.turn_count:
        pending.pop(key)
        conv.pending_action = {"keys": pending}
        return None
    pending[key] = conv.turn_count
    while len(pending) > 6:  # bounded: drop the oldest proposal
        pending.pop(next(iter(pending)))
    conv.pending_action = {"keys": pending}
    return {
        "status": "needs_confirmation",
        "instruction": (
            "NOTHING has been done yet. Restate the key details to the shopper in your own words (what, which "
            "shop/date, etc.) and ask for an explicit yes. Only after they clearly say yes in their NEXT message, "
            f"call {tool} again with the same {', '.join(args)} ({json.dumps(args, sort_keys=True, default=str)}); "
            "you may repeat any optional details too."
        ),
    }


def _parse_date(value: Any) -> tuple[date | None, dict | None]:
    try:
        return date.fromisoformat(str(value)), None
    except ValueError:
        return None, {"error": "Dates must be in YYYY-MM-DD format."}


def _today_ist() -> date:
    return datetime.now(IST).date()


# --------------------------------------------------------------------------- #
# Read tools
# --------------------------------------------------------------------------- #
async def _get_campaign_details(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _pick_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    fees = [s.compensation for s in shops if s.compensation]
    currency = next((s.currency for s in shops if s.compensation), None)
    return {
        "name": _c(campaign, campaign.name),
        "client": _display_client(campaign),
        "client_name_hidden": bool(campaign.client_confidential),
        "status": campaign.status,
        "description": _c(campaign, campaign.description),
        "deadline": iso(campaign.deadline),
        "total_shops": len(shops),
        "open_shops": sum(1 for s in shops if s.status == "open"),
        "compensation_per_shop": (
            {"min": min(fees), "max": max(fees), "currency": currency} if fees else "not specified in campaign data"
        ),
        "requirements_text": _c(campaign, campaign.requirements_text),
        "parsed_requirements": campaign.parsed_requirements,
    }


def _chunks_for_campaign(campaign: Campaign, shops: list[Shop]) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    if campaign.description:
        chunks.append(("campaign_description", campaign.description))
    if campaign.requirements_text:
        chunks.append(("campaign_requirements", campaign.requirements_text))
    parsed = (campaign.parsed_requirements or {}).get("parsed_fields") if isinstance(campaign.parsed_requirements, dict) else None
    for k, v in (parsed or {}).items():
        chunks.append(("campaign_requirements", f"{k.replace('_', ' ')}: {v}"))
    if campaign.deadline:
        chunks.append(("campaign_deadline", f"Campaign deadline: {iso(campaign.deadline)}"))
    for s in shops[:200]:
        bits = [s.shop_name, s.address or "", s.city or "", s.state or "", s.category or ""]
        w = _window(s)
        if w:
            bits.append(f"visit window {w}")
        if _fee(s):
            bits.append(f"fee {_fee(s)}")
        chunks.append(("shop_info", " | ".join(b for b in bits if b)))
    return chunks


async def _search_campaign_knowledge(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _pick_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    query = str(args.get("query") or "")
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    q = knowledge._tokens(query)
    scored: list[tuple[int, str, str]] = []
    for source, text in _chunks_for_campaign(campaign, list(shops)):
        overlap = len(q & knowledge._tokens(text))
        if overlap:
            scored.append((overlap, source, text))
    scored.sort(key=lambda s: s[0], reverse=True)
    threshold = 1 if len(q) <= 2 else 2
    facts = [{"source": s[1], "text": _c(campaign, s[2])[:600]} for s in scored if s[0] >= threshold][:4]
    general = knowledge.search(query, "shopper")
    if general["status"] == "ok":
        facts += [{"source": "general_faq", "text": f["text"]} for f in general["facts"]][: max(0, 5 - len(facts))]
    conv = scope.conversation
    if not facts:
        conv.unanswered_count = (conv.unanswered_count or 0) + 1
        return {
            "status": "no_match",
            "instruction": "Nothing grounded was found. Do not guess: ask ONE clarifying question, and if still unsure "
            "escalate with reason low_confidence.",
        }
    conv.unanswered_count = 0
    return {"status": "ok", "facts": facts}


async def _filled_shop_ids(session: AsyncSession, shop_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not shop_ids:
        return {}
    rows = (
        await session.execute(
            select(Invitation.shop_id, func.sum(case((Invitation.response == "accepted", 1), else_=0)))
            .where(Invitation.shop_id.in_(shop_ids))
            .group_by(Invitation.shop_id)
        )
    ).all()
    return {sid: int(n or 0) for sid, n in rows}


async def _list_available_shops(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _pick_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    stmt = select(Shop).where(Shop.campaign_id == campaign.id, Shop.status == "open")
    if args.get("city"):
        c = f"%{str(args['city']).strip()}%"
        stmt = stmt.where(Shop.city.ilike(c) | Shop.state.ilike(c))
    if args.get("area"):
        a = f"%{str(args['area']).strip()}%"
        stmt = stmt.where(Shop.address.ilike(a) | Shop.city.ilike(a) | Shop.shop_name.ilike(a))
    if args.get("pincode"):
        stmt = stmt.where(Shop.address.ilike(f"%{str(args['pincode']).strip()}%"))
    wanted: date | None = None
    if args.get("date"):
        wanted, derr = _parse_date(args["date"])
        if derr:
            return derr
    shops = (await session.execute(stmt.order_by(Shop.shop_name).limit(300))).scalars().all()
    filled = await _filled_shop_ids(session, [s.id for s in shops])
    now = datetime.now(timezone.utc)
    out: list[Shop] = []
    for s in shops:
        if filled.get(s.id, 0) >= s.required_shoppers:
            continue  # already covered
        if s.visit_end and s.visit_end.replace(tzinfo=s.visit_end.tzinfo or timezone.utc) < now:
            continue  # window already over
        if wanted and s.visit_start and s.visit_end and not (s.visit_start.date() <= wanted <= s.visit_end.date()):
            continue
        out.append(s)
    shown = out[:MAX_SHOPS]
    hint: dict = {}
    filtered = any(args.get(k) for k in ("city", "area", "pincode", "date"))
    if not out and filtered:
        # Don't let an over-narrow filter read as "no shops exist": say where there ARE open shops.
        every = (
            await session.execute(select(Shop).where(Shop.campaign_id == campaign.id, Shop.status == "open").limit(300))
        ).scalars().all()
        covered = await _filled_shop_ids(session, [x.id for x in every])
        counts: dict[str, int] = {}
        for x in every:
            ends = x.visit_end.replace(tzinfo=x.visit_end.tzinfo or timezone.utc) if x.visit_end else None
            if covered.get(x.id, 0) >= x.required_shoppers or (ends and ends < now):
                continue
            label = ", ".join(b for b in (x.city, x.state) if b) or "other"
            counts[label] = counts.get(label, 0) + 1
        hint = {
            "instruction": (
                "No shop matched those filters. This does NOT mean there are none: retry with fewer filters (use only "
                "what the shopper actually said) or offer the areas below."
            ),
            "areas_with_open_shops": dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]),
        }
    return {
        **hint,
        "campaign": _c(campaign, campaign.name),
        "shops": [
            {
                "shop_id": str(s.id),
                "name": _c(campaign, s.shop_name),
                "address": _c(campaign, s.address),
                "city": s.city,
                "state": s.state,
                "visit_window": _window(s),
                "bookable_dates": _bookable_window(s),
                "fee": _fee(s),
                "category": s.category,
            }
            for s in shown
        ],
        "total_matching": len(out),
        "more_available": max(0, len(out) - len(shown)),
        "today_ist": _today_ist().isoformat(),
        "note": "Show the shopper at most 5; offer 'more options?' if more_available > 0. Only propose dates inside bookable_dates.",
    }


async def _shop_status_for(session: AsyncSession, shopper_id: uuid.UUID, shop: Shop) -> str:
    """Available / Contacted / Responded / Scheduled / Completed. 'Scheduled'
    only when the shop or a coordinator-confirmed interest says so."""
    if shop.status == "completed":
        return "Completed"
    interest = (
        await session.execute(
            select(ShopperInterest).where(ShopperInterest.shopper_id == shopper_id, ShopperInterest.shop_id == shop.id)
        )
    ).scalars().all()
    if shop.status == "scheduled" or any(i.status == "Scheduled" for i in interest):
        return "Scheduled"
    invs = (
        await session.execute(select(Invitation).where(Invitation.shopper_id == shopper_id, Invitation.shop_id == shop.id))
    ).scalars().all()
    if any(i.status == "completed" for i in invs):
        return "Completed"
    if interest or any(i.response for i in invs):
        return "Responded"
    if invs:
        return "Contacted"
    return "Available"


async def _allowed_campaigns_by_id(session: AsyncSession, scope: ChatScope) -> dict[uuid.UUID, Campaign]:
    return {c.id: c for c in await _allowed_campaigns(session, scope)}


async def _get_shop_status(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    shop, err = await _shop_in_scope(session, scope, args.get("shop_id"))
    if err:
        return err
    status = await _shop_status_for(session, _inv(scope).shopper_id, shop)
    camp = (await _allowed_campaigns_by_id(session, scope)).get(shop.campaign_id)
    return {
        "shop": _c(camp, shop.shop_name),
        "status": status,
        "can_say_assigned": status == "Scheduled",
        "note": "Only tell the shopper they are assigned/booked when can_say_assigned is true.",
    }


async def _get_shopper_context(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    inv = _inv(scope)
    shopper = inv.shopper
    allowed = await _allowed_campaigns(session, scope)
    allowed_ids = [c.id for c in allowed]
    allowed_by_id = {c.id: c for c in allowed}
    invs = (
        await session.execute(
            select(Invitation)
            .where(Invitation.shopper_id == shopper.id, Invitation.campaign_id.in_(allowed_ids))
            .options(selectinload(Invitation.shop), selectinload(Invitation.campaign))
            .order_by(Invitation.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    interests = (
        await session.execute(
            select(ShopperInterest)
            .where(ShopperInterest.shopper_id == shopper.id, ShopperInterest.campaign_id.in_(allowed_ids))
            .options(selectinload(ShopperInterest.shop))
            .order_by(ShopperInterest.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    open_esc = (
        await session.execute(
            select(func.count()).select_from(ChatEscalation).where(
                ChatEscalation.shopper_id == shopper.id, ChatEscalation.status == "open"
            )
        )
    ).scalar_one()
    return {
        "first_name": shopper.name.split(" ")[0],
        "city": shopper.city,
        "state": shopper.state,
        "preferred_language": (shopper.languages or ["auto"])[0] if shopper.languages else "auto",
        "email_opted_out": shopper.opted_out_email,
        "phone_opted_out": shopper.opted_out_phone,
        "campaigns_invited_to": [_c(c, c.name) for c in allowed],
        "invitations": [
            {
                "campaign": _c(i.campaign, i.campaign.name) if i.campaign else None,
                "shop": _c(i.campaign, i.shop.shop_name) if i.shop else None,
                "status": i.status,
                "response": i.response,
            }
            for i in invs
        ],
        "recorded_interests": [
            {"shop": _c(allowed_by_id.get(i.campaign_id), i.shop.shop_name) if i.shop else None, "preferred_date": i.preferred_date.isoformat(), "status": i.status}
            for i in interests
        ],
        "open_coordinator_requests": int(open_esc),
    }


async def _check_eligibility(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _pick_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    shopper = _shopper(scope)
    shops = (
        await session.execute(select(Shop).where(Shop.campaign_id == campaign.id, Shop.status == "open"))
    ).scalars().all()
    parsed = {}
    if isinstance(campaign.parsed_requirements, dict):
        parsed = campaign.parsed_requirements.get("parsed_fields") or {}
    criteria: list[dict] = []

    def add(name: str, met: bool | None, detail: str) -> None:
        criteria.append({"criterion": name, "met": met, "detail": detail})

    add(
        "Account active and available",
        bool(shopper.active) and shopper.availability_status == "available",
        f"availability: {shopper.availability_status}",
    )

    wanted_cats = {c.lower() for c in (parsed.get("categories") or [])} or {(s.category or "").lower() for s in shops if s.category}
    mine = {c.lower() for c in (shopper.categories or []) + (shopper.preferred_categories or [])}
    if wanted_cats:
        overlap = wanted_cats & mine
        add("Category match", bool(overlap), f"campaign categories: {', '.join(sorted(wanted_cats))}; "
            + (f"you match: {', '.join(sorted(overlap))}" if overlap else "none of your listed categories match"))

    limit_km = parsed.get("maximum_distance_km") or shopper.preferred_distance_km or 50
    if shopper.latitude is not None and shopper.longitude is not None:
        dists = [
            haversine_km(shopper.latitude, shopper.longitude, s.latitude, s.longitude)
            for s in shops
            if s.latitude is not None and s.longitude is not None
        ]
        if dists:
            nearest = min(dists)
            add("Within travel distance", nearest <= limit_km, f"nearest open shop is about {nearest:.0f} km away (limit {limit_km} km)")
        else:
            add("Within travel distance", None, "open shops have no coordinates on file")
    else:
        add("Within travel distance", None, "your location isn't on file")

    if parsed.get("minimum_rating"):
        add("Minimum rating", shopper.rating >= parsed["minimum_rating"], f"required {parsed['minimum_rating']}, yours {shopper.rating}")
    if parsed.get("minimum_completion_rate"):
        add(
            "Minimum completion rate",
            (shopper.completion_rate or 0) >= parsed["minimum_completion_rate"],
            f"required {round(parsed['minimum_completion_rate'] * 100)}%, yours {round((shopper.completion_rate or 0) * 100)}%",
        )
    if parsed.get("experience_required"):
        add("Experience", (shopper.years_experience or 0) > 0 or shopper.previous_assignments > 0, f"{shopper.previous_assignments} previous assignments")

    known = [c["met"] for c in criteria if c["met"] is not None]
    return {
        "campaign": _c(campaign, campaign.name),
        "eligible": (all(known) if known else None),
        "criteria": criteria,
        "note": "Explain matched and unmatched criteria simply. 'met: null' means unknown, not failed.",
    }


async def _get_form_guide(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _pick_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    reminders = (
        "Explain what each question asks and what to observe. NEVER suggest answers or help fill in a form for a "
        "visit that hasn't happened. Remind the shopper to stay discreet and not reveal they are a mystery shopper."
    )
    text = campaign.requirements_text or ""
    if not text.strip():
        return {
            "status": "no_data",
            "reminders": reminders,
            "instruction": "No form guide is on file for this campaign. Say you'll check and escalate with reason "
            "low_confidence if the shopper needs it.",
        }
    qid = str(args.get("question_id") or "").strip().lower()
    if qid:
        lines = [ln for ln in text.splitlines() if qid in ln.lower()]
        if lines:
            return {"status": "ok", "guide": "\n".join(lines)[:1500], "reminders": reminders}
    return {"status": "ok", "guide": text[:1500], "reminders": reminders}


# --------------------------------------------------------------------------- #
# Write tools
# --------------------------------------------------------------------------- #
async def _record_shopper_interest(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    shop, err = await _shop_in_scope(session, scope, args.get("shop_id"))
    if err:
        return err
    pref, derr = _parse_date(args.get("preferred_date"))
    if derr:
        return derr
    if pref < _today_ist():
        return {"error": f"That date is in the past (today is {_today_ist().isoformat()} IST). "
                f"Ask the shopper for a date in {_bookable_window(shop) or 'the visit window'}."}
    if shop.visit_start and shop.visit_end and not (shop.visit_start.date() <= pref <= shop.visit_end.date()):
        return {"error": f"That date is outside this shop's visit window ({_window(shop)}). "
                f"Bookable dates: {_bookable_window(shop)}."}
    gated = _gate(scope, "record_shopper_interest", {"shop_id": str(shop.id), "preferred_date": pref.isoformat()})
    if gated:
        return gated

    inv = _inv(scope)
    existing = (
        await session.execute(
            select(ShopperInterest).where(
                ShopperInterest.shopper_id == inv.shopper_id,
                ShopperInterest.shop_id == shop.id,
                ShopperInterest.status == INTEREST_PENDING,
            )
        )
    ).scalar_one_or_none()
    notes = (str(args.get("notes") or "")[:500]) or None
    if existing:
        existing.preferred_date, existing.preferred_time, existing.notes = pref, args.get("preferred_time"), notes
    else:
        session.add(
            ShopperInterest(
                shopper_id=inv.shopper_id,
                campaign_id=shop.campaign_id,
                shop_id=shop.id,
                conversation_id=scope.conversation.id,
                preferred_date=pref,
                preferred_time=(str(args.get("preferred_time") or "")[:40]) or None,
                notes=notes,
            )
        )
    await add_event(
        session, inv, "shopper_interest_recorded",
        {"shop": shop.shop_name, "preferred_date": pref.isoformat(), "channel": "chatbot"},
    )
    await record_audit(
        session, actor="shopper", action="chatbot.interest_recorded", entity_type="shop", entity_id=str(shop.id),
        summary=f"{inv.shopper.name} showed interest in {shop.shop_name} for {pref.isoformat()} via chatbot",
        meta={"campaign_id": str(shop.campaign_id), "conversation_id": str(scope.conversation.id)},
    )
    return {
        "status": "recorded",
        "shopper_status": INTEREST_PENDING,
        "shop": _c(inv.campaign, shop.shop_name),
        "preferred_date": pref.isoformat(),
        "note": "This is NOT a booking. A coordinator or the MS platform confirms the final assignment. Offer "
        "schedule_followup for a visit reminder.",
    }


async def _update_shopper_response(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    response = args.get("response")
    if response not in ("accepted", "declined", "maybe"):
        return {"error": "response must be accepted, declined or maybe"}
    inv = _inv(scope)
    if args.get("shop_id"):
        shop, err = await _shop_in_scope(session, scope, args["shop_id"])
        if err:
            return err
        target = (
            await session.execute(
                select(Invitation).where(Invitation.shopper_id == inv.shopper_id, Invitation.shop_id == shop.id)
                .options(selectinload(Invitation.shopper), selectinload(Invitation.campaign))
            )
        ).scalars().first()
        if target is None:
            return {"error": "This shopper has no invitation for that shop."}
    else:
        target = inv
    if response != "maybe" and target.responded_at is not None:
        return {"status": "already_responded", "response": target.response}
    reason = (str(args.get("reason") or "")[:300]) or None
    gated = _gate(scope, "update_shopper_response", {"response": response, "invitation": str(target.id)})
    if gated:
        return gated
    if response == "maybe":
        await add_event(session, target, "shopper_response_maybe", {"reason": reason, "channel": "chatbot"})
        return {"status": "noted", "response": "maybe", "note": "Not final — the invitation stays open for them."}
    recorded = await mark_response(session, target, response, {"source": target.source, "page": "chatbot", **({"note": reason} if reason else {})})
    if recorded:
        await record_audit(
            session, actor="shopper", action=f"assignment.{response}", entity_type="invitation", entity_id=str(target.id),
            summary=f"{target.shopper.name if target.shopper else 'Shopper'} {response} {target.reference} via chatbot",
            meta={"campaign_id": str(target.campaign_id), "shop_id": str(target.shop_id), "channel": "chatbot", "reason": reason},
        )
    return {"status": "recorded" if recorded else "already_responded", "response": target.response}


async def _request_reschedule_or_cancel(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    action = args.get("action")
    if action not in ("reschedule", "cancel"):
        return {"error": "action must be reschedule or cancel"}
    reason = str(args.get("reason") or "").strip()
    if not reason:
        return {"error": "A short reason is required — ask the shopper why."}
    inv = _inv(scope)
    shop = inv.shop
    if args.get("shop_id"):
        shop, err = await _shop_in_scope(session, scope, args["shop_id"])
        if err:
            return err
    new_date = None
    if action == "reschedule":
        d, derr = _parse_date(args.get("new_date"))
        if derr:
            return {"error": "A new date (YYYY-MM-DD) is required for a reschedule."}
        if d < _today_ist():
            return {"error": "That new date is in the past."}
        new_date = d.isoformat()
    gated = _gate(scope, "request_reschedule_or_cancel", {"action": action, "shop_id": str(shop.id) if shop else None, "new_date": new_date})
    if gated:
        return gated
    esc = ChatEscalation(
        conversation_id=scope.conversation.id, shopper_id=inv.shopper_id, campaign_id=shop.campaign_id if shop else inv.campaign_id,
        shop_id=shop.id if shop else None, kind=action, reason="assignment_conflict", priority="medium",
        summary=f"{inv.shopper.name} asked to {action} their visit to {shop.shop_name if shop else 'a shop'}"
        + (f" — new date {new_date}" if new_date else "") + f". Reason: {reason[:300]}",
        new_date=new_date,
    )
    session.add(esc)
    await add_event(session, inv, f"shopper_{action}_requested", {"shop": shop.shop_name if shop else None, "new_date": new_date, "channel": "chatbot"})
    await record_audit(
        session, actor="shopper", action=f"chatbot.{action}_requested", entity_type="invitation", entity_id=str(inv.id),
        summary=esc.summary, meta={"conversation_id": str(scope.conversation.id)},
    )
    return {
        "status": "requested",
        "next_step": f"A coordinator will review and confirm. Expect a reply within {settings.chatbot_coordinator_sla}.",
    }


def _local_to_utc(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)  # shoppers speak IST
    return dt.astimezone(timezone.utc)


async def _schedule_followup(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    channel, purpose = args.get("channel"), args.get("purpose")
    if channel not in ("email", "phone"):
        return {"error": "channel must be email or phone"}
    if purpose not in ("visit_reminder", "form_deadline", "incomplete_response"):
        return {"error": "purpose must be visit_reminder, form_deadline or incomplete_response"}
    send_at = _local_to_utc(str(args.get("send_at") or ""))
    if send_at is None:
        return {"error": "send_at must be an ISO date-time such as 2026-10-20T09:00 (IST)."}
    now = datetime.now(timezone.utc)
    if send_at < now + timedelta(minutes=1) or send_at > now + timedelta(days=90):
        return {"error": f"send_at must be in the future and within 90 days (now is "
                f"{now.astimezone(IST).strftime('%Y-%m-%d %H:%M')} IST). If the reminder date would already be past, "
                "tell the shopper and offer a time that is still ahead."}
    inv = _inv(scope)
    shopper = inv.shopper
    if channel == "email" and (shopper.opted_out_email or not (inv.email or shopper.email)):
        return {"error": "This shopper has opted out of email or has no email on file."}
    if channel == "phone" and (shopper.opted_out_phone or not shopper.phone):
        return {"error": "This shopper has opted out of calls or has no phone number on file."}
    gated = _gate(scope, "schedule_followup", {"channel": channel, "purpose": purpose, "send_at": send_at.isoformat()})
    if gated:
        return gated
    session.add(ShopperFollowup(shopper_id=shopper.id, campaign_id=inv.campaign_id, invitation_id=inv.id, channel=channel, purpose=purpose, send_at=send_at))
    await add_event(session, inv, "followup_scheduled", {"channel": channel, "purpose": purpose, "send_at": iso(send_at), "channel_source": "chatbot"})
    return {
        "status": "scheduled",
        "channel": channel,
        "send_at_ist": send_at.astimezone(IST).strftime("%Y-%m-%d %H:%M IST"),
        "note": "Email reminders are sent automatically. Phone follow-ups are passed to a coordinator to call — "
        "say that, don't promise an automatic call.",
    }


async def _record_opt_out(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    """Applied immediately (no confirmation round) — the shopper asked."""
    channel = args.get("channel") or "all"
    if channel not in ("email", "phone", "all"):
        return {"error": "channel must be email, phone or all"}
    inv = _inv(scope)
    shopper = inv.shopper
    if channel in ("email", "all"):
        shopper.opted_out_email = True
    if channel in ("phone", "all"):
        shopper.opted_out_phone = True
    shopper.opted_out_at = datetime.now(timezone.utc)
    pending = (
        await session.execute(
            select(ShopperFollowup).where(ShopperFollowup.shopper_id == shopper.id, ShopperFollowup.status == "pending")
        )
    ).scalars().all()
    for f in pending:
        if channel == "all" or f.channel == channel:
            f.status = "skipped_opt_out"
    await add_event(session, inv, "shopper_opted_out", {"channel": channel, "source": "chatbot"})
    await record_audit(
        session, actor="shopper", action="chatbot.opt_out", entity_type="shopper", entity_id=str(shopper.id),
        summary=f"{shopper.name} opted out of {channel} contact via chatbot", meta={"channel": channel},
    )
    return {"status": "opted_out", "channel": channel}


async def _escalate_to_coordinator(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    reason = args.get("reason")
    if reason not in ESCALATION_REASONS:
        return {"error": f"reason must be one of: {', '.join(ESCALATION_REASONS)}"}
    priority = args.get("priority") if args.get("priority") in ("low", "medium", "high") else "medium"
    summary = str(args.get("summary") or "").strip()
    if not summary:
        return {"error": "summary is required (use the escalation summary format)."}
    inv = _inv(scope)
    conv = scope.conversation
    session.add(
        ChatEscalation(
            conversation_id=conv.id, shopper_id=inv.shopper_id, campaign_id=inv.campaign_id, kind="escalation",
            reason=reason, priority=priority, summary=summary[:3000],
        )
    )
    conv.status = "escalated"
    conv.escalation_reason = f"{reason}: {summary[:300]}"
    conv.contact_name, conv.contact_email, conv.contact_phone = inv.shopper.name, inv.email, inv.shopper.phone
    conv.contact_consent = True  # the shopper's own request; uses contact already on file
    await add_event(session, inv, "chatbot_escalated", {"reason": reason, "priority": priority, "channel": "chatbot"})
    await record_audit(
        session, actor="shopper", action="chatbot.escalated", entity_type="invitation", entity_id=str(inv.id),
        summary=f"Chatbot escalated ({reason}, {priority}) for {inv.shopper.name}", meta={"conversation_id": str(conv.id)},
    )
    return {"status": "escalated", "coordinator_sla": settings.chatbot_coordinator_sla}


async def _log_activity(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    event_type = args.get("event_type") if args.get("event_type") in ACTIVITY_TYPES else "other"
    await add_event(
        session, _inv(scope), "chatbot_activity",
        {"activity": event_type, "details": str(args.get("details") or "")[:500], "channel": "chatbot"},
    )
    return {"status": "logged"}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_CAMPAIGN = {"campaign_name": {"type": "string", "description": "Only needed in multi-campaign mode."}}

SHOPPER_TOOLS: dict[str, tuple[dict, ToolHandler]] = {
    "get_campaign_details": (
        spec("get_campaign_details", "Campaign name, description, dates, compensation range, requirements and deadlines.", _CAMPAIGN),
        _get_campaign_details,
    ),
    "search_campaign_knowledge": (
        spec(
            "search_campaign_knowledge",
            "Search this campaign's instructions, requirements, shop info and the general FAQ. ALWAYS use before "
            "answering any campaign fact.",
            {"query": {"type": "string"}, **_CAMPAIGN},
            ["query"],
        ),
        _search_campaign_knowledge,
    ),
    "list_available_shops": (
        spec(
            "list_available_shops",
            "Open shops with free slots; the result is already capped at 5 (see more_available). Use ONLY filters the "
            "shopper explicitly gave (city names in the data are like 'Brooklyn' or 'Newark'); when unsure, call with no filters.",
            {"city": {"type": "string"}, "area": {"type": "string"}, "pincode": {"type": "string"},
             "date": {"type": "string", "description": "YYYY-MM-DD"}, **_CAMPAIGN},
        ),
        _list_available_shops,
    ),
    "get_shop_status": (
        spec("get_shop_status", "Status of one shop for this shopper: Available/Contacted/Responded/Scheduled/Completed.",
             {"shop_id": {"type": "string"}}, ["shop_id"]),
        _get_shop_status,
    ),
    "get_shopper_context": (
        spec("get_shopper_context", "This shopper's profile basics, invitations, status per shop, recorded interests."),
        _get_shopper_context,
    ),
    "check_eligibility": (
        spec("check_eligibility", "Matched / unmatched eligibility criteria for this shopper and campaign.", _CAMPAIGN),
        _check_eligibility,
    ),
    "get_form_guide": (
        spec("get_form_guide", "What the MS form sections/questions mean and what to observe (never answers).",
             {"question_id": {"type": "string"}, **_CAMPAIGN}),
        _get_form_guide,
    ),
    "record_shopper_interest": (
        spec(
            "record_shopper_interest",
            "WRITE (needs the shopper's explicit yes first). Record interest in a shop on a preferred date. This is "
            "not a booking; status becomes 'Shopper Responded / Pending Confirmation'.",
            {"shop_id": {"type": "string"}, "preferred_date": {"type": "string", "description": "YYYY-MM-DD"},
             "preferred_time": {"type": "string"}, "notes": {"type": "string"}},
            ["shop_id", "preferred_date"],
        ),
        _record_shopper_interest,
    ),
    "update_shopper_response": (
        spec(
            "update_shopper_response",
            "WRITE (needs the shopper's explicit yes first). Record accepted / declined / maybe for their invitation.",
            {"response": {"type": "string", "enum": ["accepted", "declined", "maybe"]}, "reason": {"type": "string"},
             "shop_id": {"type": "string", "description": "Only for multi-campaign mode / a different shop."}},
            ["response"],
        ),
        _update_shopper_response,
    ),
    "request_reschedule_or_cancel": (
        spec(
            "request_reschedule_or_cancel",
            "WRITE (needs the shopper's explicit yes first). Ask a coordinator to reschedule or cancel their visit.",
            {"action": {"type": "string", "enum": ["reschedule", "cancel"]}, "reason": {"type": "string"},
             "shop_id": {"type": "string"}, "new_date": {"type": "string", "description": "YYYY-MM-DD, for reschedule"}},
            ["action", "reason"],
        ),
        _request_reschedule_or_cancel,
    ),
    "schedule_followup": (
        spec(
            "schedule_followup",
            "WRITE (needs the shopper's explicit yes first). Schedule a reminder. Email is automatic; phone is passed to a coordinator.",
            {"channel": {"type": "string", "enum": ["email", "phone"]},
             "send_at": {"type": "string", "description": "ISO date-time in IST, e.g. 2026-10-20T09:00"},
             "purpose": {"type": "string", "enum": ["visit_reminder", "form_deadline", "incomplete_response"]}},
            ["channel", "send_at", "purpose"],
        ),
        _schedule_followup,
    ),
    "record_opt_out": (
        spec("record_opt_out", "Stop contacting the shopper on a channel. Apply IMMEDIATELY when they ask to stop messages.",
             {"channel": {"type": "string", "enum": ["email", "phone", "all"]}}),
        _record_opt_out,
    ),
    "escalate_to_coordinator": (
        spec(
            "escalate_to_coordinator",
            "Hand the case to a human coordinator with the full escalation summary.",
            {"summary": {"type": "string"}, "reason": {"type": "string", "enum": ESCALATION_REASONS},
             "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
            ["summary", "reason", "priority"],
        ),
        _escalate_to_coordinator,
    ),
    "log_activity": (
        spec("log_activity", "Record a meaningful chatbot event for the activity trail.",
             {"event_type": {"type": "string", "enum": ACTIVITY_TYPES}, "details": {"type": "string"}}, ["event_type"]),
        _log_activity,
    ),
}
