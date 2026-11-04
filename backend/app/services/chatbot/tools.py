"""Tools the chatbot agent can call, one registry per audience.

Scope is enforced HERE, in code, from the authenticated `ChatScope` — the
model never supplies a tenant, user or invitation id, and tool output is
treated as data by the prompt. A client-role staff scope can only ever read
its own campaigns and never sees shopper identities (same rule as
routers/client_portal.py); the shopper scope is bound to exactly one
invitation.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    BulkCallBatch,
    BulkCallTarget,
    Campaign,
    ChatConversation,
    ChatEscalation,
    Invitation,
    InvitationEvent,
    Shop,
    Shopper,
    User,
)
from ...serializers import iso
from ..audit import record_audit
from . import knowledge
from .base import MAX_ROWS, ChatScope, ToolHandler
from .base import spec as _spec
from .api_tools import API_TOOLS
from .shopper_tools import SHOPPER_TOOLS



# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _campaign_filter(scope: ChatScope):
    """SQLAlchemy criterion limiting campaigns to what this scope may see."""
    if scope.is_admin:
        return None
    # A client user is always tenant-bound; any other staff shape sees nothing.
    return Campaign.client_id == (scope.client_id or uuid.UUID(int=0))


async def _accessible_campaigns(session: AsyncSession, scope: ChatScope, name: str | None = None) -> list[Campaign]:
    stmt = select(Campaign)
    crit = _campaign_filter(scope)
    if crit is not None:
        stmt = stmt.where(crit)
    if name:
        stmt = stmt.where(Campaign.name.ilike(f"%{name.strip()}%"))
    stmt = stmt.order_by(Campaign.created_at.desc()).limit(50)
    return list((await session.execute(stmt)).scalars().all())


async def _resolve_campaign(session: AsyncSession, scope: ChatScope, name: str | None) -> tuple[Campaign | None, dict | None]:
    """(campaign, None) on a unique match; (None, error-dict) otherwise."""
    if not name or not name.strip():
        return None, {"error": "campaign_name is required"}
    matches = await _accessible_campaigns(session, scope, name)
    if not matches:
        return None, {"error": f"No campaign matching '{name}' that you can access."}
    exact = [c for c in matches if c.name.lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0], None
    if len(matches) == 1:
        return matches[0], None
    return None, {
        "error": "More than one campaign matches — ask which one.",
        "candidates": [{"name": c.name, "status": c.status} for c in matches[:8]],
    }


def _funnel_columns():
    return (
        func.count(Invitation.id).label("total"),
        func.sum(case((Invitation.sent_at.isnot(None), 1), else_=0)).label("sent"),
        func.sum(case((Invitation.delivered_at.isnot(None), 1), else_=0)).label("delivered"),
        func.sum(case((Invitation.opened_at.isnot(None), 1), else_=0)).label("opened"),
        func.sum(case((Invitation.clicked_at.isnot(None), 1), else_=0)).label("clicked"),
        func.sum(case((Invitation.visited_at.isnot(None), 1), else_=0)).label("visited"),
        func.sum(case((Invitation.response == "accepted", 1), else_=0)).label("accepted"),
        func.sum(case((Invitation.response == "declined", 1), else_=0)).label("declined"),
    )


def _funnel_dict(row) -> dict:
    return {k: int(getattr(row, k) or 0) for k in ("total", "sent", "delivered", "opened", "clicked", "visited", "accepted", "declined")}


# --------------------------------------------------------------------------- #
# Staff tools (read-only)
# --------------------------------------------------------------------------- #
# The app files a campaign under active / upcoming / completed by its free-text status (routers/campaigns.py::
# status_bucket): "draft" and "scheduled" are upcoming, "in_progress" / "filled" are active, and so on. The assistant
# filters the same way, so "active" really means every live campaign, not just the ones literally named "active".
_UPCOMING_STATUSES = ("draft", "upcoming", "scheduled")
_COMPLETED_STATUSES = ("completed",)
_CANCELLED_STATUSES = ("cancelled",)


def _campaign_query(scope: ChatScope, status: str | None, name: str | None):
    stmt = select(Campaign)
    crit = _campaign_filter(scope)
    if crit is not None:
        stmt = stmt.where(crit)
    lowered = func.lower(Campaign.status)
    if status == "upcoming":
        stmt = stmt.where(lowered.in_(_UPCOMING_STATUSES))
    elif status == "completed":
        stmt = stmt.where(lowered.in_(_COMPLETED_STATUSES))
    elif status == "active":
        stmt = stmt.where(lowered.notin_(_UPCOMING_STATUSES + _COMPLETED_STATUSES + _CANCELLED_STATUSES))
    if name:
        stmt = stmt.where(Campaign.name.ilike(f"%{name}%"))
    return stmt


async def _list_campaigns(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    status = (args.get("status") or "").strip().lower() or None
    name = (args.get("name") or "").strip() or None
    note = None
    stmt = _campaign_query(scope, status, name)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if not total and status and name:
        # Asked for one campaign by name under the wrong status (the status is easy to guess wrong): look again
        # without it rather than let the assistant conclude the campaign doesn't exist.
        stmt = _campaign_query(scope, None, name)
        total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        if total:
            note = f"Nothing matched status '{status}'; these matches are in other statuses (see each one's status)."
    rows = (await session.execute(stmt.order_by(Campaign.created_at.desc()).limit(MAX_ROWS))).scalars().all()
    out = {
        "campaigns": [
            {
                "id": str(c.id),
                "name": c.name,
                "client": c.client_name,
                "status": c.status,
                "total_shops": c.total_shops,
                "completed_shops": c.completed_shops,
                "remaining_shops": c.remaining_shops,
                "deadline": iso(c.deadline),
            }
            for c in rows
        ],
        "shown": len(rows),
        # More may match than are shown: narrow with `name` (part of the campaign name) rather than assume it is missing.
        "total_matching": total,
    }
    if note:
        out["note"] = note
    return out


async def _campaign_overview(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    campaign, err = await _resolve_campaign(session, scope, args.get("campaign_name"))
    if err:
        return err
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    funnel = _funnel_dict(
        (await session.execute(select(*_funnel_columns()).where(Invitation.campaign_id == campaign.id))).one()
    )
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "client": campaign.client_name,
        "status": campaign.status,
        "description": campaign.description,
        "deadline": iso(campaign.deadline),
        "shops": {
            "count": len(shops),
            "required_shoppers_total": sum(s.required_shoppers for s in shops),
            "open": sum(1 for s in shops if s.status == "open"),
            "completed": sum(1 for s in shops if s.status == "completed"),
        },
        "outreach_funnel": funnel,
    }


async def _outreach_funnel(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    stmt = select(*_funnel_columns())
    label = "all accessible campaigns"
    if args.get("campaign_name"):
        campaign, err = await _resolve_campaign(session, scope, args["campaign_name"])
        if err:
            return err
        stmt = stmt.where(Invitation.campaign_id == campaign.id)
        label = campaign.name
    else:
        crit = _campaign_filter(scope)
        if crit is not None:
            stmt = stmt.join(Campaign, Campaign.id == Invitation.campaign_id).where(crit)
    f = _funnel_dict((await session.execute(stmt)).one())

    def rate(n: int, d: int) -> float:
        return round(n / d * 100, 1) if d else 0.0

    return {
        "scope": label,
        **f,
        "open_rate_pct": rate(f["opened"], f["delivered"]),
        "click_rate_pct": rate(f["clicked"], f["opened"]),
        "acceptance_rate_pct": rate(f["accepted"], f["clicked"]),
    }


async def _shops_needing_shoppers(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    stmt = select(Shop, Campaign).join(Campaign, Campaign.id == Shop.campaign_id).where(Shop.status == "open")
    crit = _campaign_filter(scope)
    if crit is not None:
        stmt = stmt.where(crit)
    if args.get("campaign_name"):
        campaign, err = await _resolve_campaign(session, scope, args["campaign_name"])
        if err:
            return err
        stmt = stmt.where(Shop.campaign_id == campaign.id)
    pairs = (await session.execute(stmt.limit(300))).all()
    if not pairs:
        return {"shops": [], "note": "No open shops."}
    shop_ids = [s.id for s, _ in pairs]
    counts = {
        sid: (invited, accepted)
        for sid, invited, accepted in (
            await session.execute(
                select(
                    Invitation.shop_id,
                    func.sum(case((Invitation.response != "declined", 1), (Invitation.response.is_(None), 1), else_=0)),
                    func.sum(case((Invitation.response == "accepted", 1), else_=0)),
                )
                .where(Invitation.shop_id.in_(shop_ids))
                .group_by(Invitation.shop_id)
            )
        ).all()
    }
    out = []
    for shop, campaign in pairs:
        invited, accepted = counts.get(shop.id, (0, 0))
        invited, accepted = int(invited or 0), int(accepted or 0)
        if invited < shop.required_shoppers:
            out.append(
                {
                    "campaign": campaign.name,
                    "shop": shop.shop_name,
                    "city": shop.city,
                    "state": shop.state,
                    "required": shop.required_shoppers,
                    "invited_or_pending": invited,
                    "accepted": accepted,
                    "gap": shop.required_shoppers - invited,
                }
            )
    out.sort(key=lambda r: r["gap"], reverse=True)
    return {"shops": out[:MAX_ROWS], "total_with_gap": len(out)}


async def _recent_activity(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    limit = max(1, min(int(args.get("limit") or 10), MAX_ROWS))
    stmt = (
        select(InvitationEvent)
        .join(Invitation, Invitation.id == InvitationEvent.invitation_id)
        .join(Campaign, Campaign.id == Invitation.campaign_id)
        .order_by(InvitationEvent.event_timestamp.desc())
        .limit(limit)
        .options(
            selectinload(InvitationEvent.invitation).selectinload(Invitation.shopper),
            selectinload(InvitationEvent.invitation).selectinload(Invitation.campaign),
        )
    )
    crit = _campaign_filter(scope)
    if crit is not None:
        stmt = stmt.where(crit)
    if args.get("event_type"):
        stmt = stmt.where(InvitationEvent.event_type == args["event_type"])
    events = (await session.execute(stmt)).scalars().all()
    items = []
    for e in events:
        inv = e.invitation
        item = {
            "event": e.event_type,
            "at": iso(e.event_timestamp),
            "campaign": inv.campaign.name if inv and inv.campaign else None,
            "reference": inv.reference if inv else None,
        }
        # Shopper identity is admin-only (client portal shows counts only).
        if scope.is_admin and inv and inv.shopper:
            item["shopper"] = inv.shopper.name
        items.append(item)
    return {"events": items}


async def _shopper_search(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if not scope.is_admin:
        return {"error": "Shopper details are only available to ISN admins."}
    stmt = select(Shopper).where(Shopper.active.is_(True))
    if args.get("query"):
        q = f"%{args['query'].strip()}%"
        stmt = stmt.where((Shopper.name.ilike(q)) | (Shopper.shopper_code.ilike(q)))
    if args.get("city"):
        stmt = stmt.where(Shopper.city.ilike(f"%{args['city'].strip()}%"))
    if args.get("state"):
        stmt = stmt.where(Shopper.state.ilike(f"%{args['state'].strip()}%"))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await session.execute(stmt.order_by(Shopper.rating.desc()).limit(MAX_ROWS))).scalars().all()
    return {
        "total_matching": int(total),
        "shoppers": [
            {
                "code": s.shopper_code,
                "name": s.name,
                "city": s.city,
                "state": s.state,
                "rating": s.rating,
                "completion_rate_pct": round((s.completion_rate or 0) * 100),
                "previous_assignments": s.previous_assignments,
                "availability": s.availability_status,
                "categories": (s.categories or [])[:5],
            }
            for s in rows
        ],
    }


async def _shopper_history(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if not scope.is_admin:
        return {"error": "Shopper details are only available to ISN admins."}
    ident = (args.get("shopper") or "").strip()
    if not ident:
        return {"error": "shopper (name or code) is required"}
    stmt = select(Shopper).where((Shopper.shopper_code.ilike(ident)) | (Shopper.name.ilike(f"%{ident}%"))).limit(5)
    found = (await session.execute(stmt)).scalars().all()
    if not found:
        return {"error": f"No shopper matching '{ident}'."}
    if len(found) > 1:
        return {"error": "More than one shopper matches — ask which.", "candidates": [{"code": s.shopper_code, "name": s.name, "city": s.city} for s in found]}
    shopper = found[0]
    invs = (
        await session.execute(
            select(Invitation)
            .where(Invitation.shopper_id == shopper.id)
            .order_by(Invitation.created_at.desc())
            .limit(MAX_ROWS)
            .options(selectinload(Invitation.campaign), selectinload(Invitation.shop))
        )
    ).scalars().all()
    return {
        "shopper": {"code": shopper.shopper_code, "name": shopper.name, "city": shopper.city, "state": shopper.state, "rating": shopper.rating},
        "invitations": [
            {
                "reference": i.reference,
                "campaign": i.campaign.name if i.campaign else None,
                "shop": i.shop.shop_name if i.shop else None,
                "status": i.status,
                "response": i.response,
                "sent_at": iso(i.sent_at),
                "opened_at": iso(i.opened_at),
                "responded_at": iso(i.responded_at),
            }
            for i in invs
        ],
    }


async def _voice_call_summary(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if not scope.is_admin:
        return {"error": "Voice call results are only available to ISN admins."}
    rows = (
        await session.execute(
            select(BulkCallTarget.outcome, func.count()).group_by(BulkCallTarget.outcome)
        )
    ).all()
    by_outcome = {(o or "none"): int(n) for o, n in rows}
    recent = (
        await session.execute(select(BulkCallBatch).order_by(BulkCallBatch.created_at.desc()).limit(5))
    ).scalars().all()
    return {
        "bulk_call_targets_by_outcome": by_outcome,
        "recent_batches": [
            {"created_at": iso(b.created_at), "status": b.status, "total": b.total_count} for b in recent
        ],
    }


async def _chat_escalations(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if not scope.is_admin:
        return {"error": "Chat escalations are only available to ISN admins."}
    rows = (
        await session.execute(
            select(ChatEscalation, Shopper)
            .join(Shopper, Shopper.id == ChatEscalation.shopper_id, isouter=True)
            .where(ChatEscalation.status == "open")
            .order_by(ChatEscalation.created_at.desc())
            .limit(MAX_ROWS)
        )
    ).all()
    visitors = (
        await session.execute(
            select(ChatConversation)
            .where(ChatConversation.status == "escalated", ChatConversation.audience == "visitor")
            .order_by(ChatConversation.updated_at.desc())
            .limit(MAX_ROWS)
        )
    ).scalars().all()
    return {
        "shopper_requests": [
            {
                "kind": e.kind,
                "reason": e.reason,
                "priority": e.priority,
                "shopper": sh.name if sh else None,
                "summary": e.summary[:400],
                "new_date": e.new_date,
                "at": iso(e.created_at),
            }
            for e, sh in rows
        ],
        "visitor_callbacks": [
            {
                "reason": c.escalation_reason,
                "preferred_time": c.preferred_time,
                "contact_name": c.contact_name,
                "contact_email": c.contact_email,
                "contact_phone": c.contact_phone,
                "at": iso(c.updated_at),
                "conversation_id": str(c.id),
            }
            for c in visitors
        ],
    }


async def _staff_request_callback(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    """A logged-in admin/client user asks for a human at ISN to get back to them. Their account
    name + email are already on file, so nothing else is required: reason, phone, preferred time and
    a different name/email are optional extras."""
    user = scope.user
    conv = scope.conversation
    if user is None:
        return {"error": "Not signed in."}
    if conv.status == "escalated":
        return {"status": "already_requested", "note": "A callback is already requested for this chat."}
    reason = str(args.get("reason") or "").strip() or "Callback requested via the assistant"
    name = str(args.get("name") or "").strip()[:255] or user.name
    email = str(args.get("email") or "").strip()[:255] or user.email
    if not _EMAIL_RE.match(email):
        return {"status": "invalid_email", "instruction": "That email address looks invalid — ask them to re-check it."}
    phone = str(args.get("phone") or "").strip()[:50]
    if phone and not _PHONE_RE.match(phone):
        return {"status": "invalid_phone", "instruction": "That phone number looks invalid — ask them to re-check it."}
    when = str(args.get("preferred_time") or "").strip()[:120] or None
    company = user.client.company_name if user.client is not None else "ISN"
    summary = (
        f"Callback requested by {name} ({email}, account {user.email}, {company}). "
        f"Reason: {reason[:500]}. Phone: {phone or 'not given (use the email)'}. "
        f"Preferred time: {when or 'not given'}."
    )
    session.add(
        ChatEscalation(
            conversation_id=conv.id, campaign_id=None, kind="callback", reason="other", priority="medium", summary=summary
        )
    )
    conv.contact_name, conv.contact_email, conv.contact_phone = name, email, phone or None
    conv.contact_consent = True  # they asked to be contacted
    _mark_escalated(conv, reason, when)
    await record_audit(
        session,
        actor=user.email,
        action="chatbot.callback_requested",
        entity_type="chat_conversation",
        entity_id=str(conv.id),
        summary=f"{name} ({company}) requested a callback via the assistant",
        meta={"conversation_id": str(conv.id)},
    )
    return {"status": "requested", "note": f"An ISN team member will contact them at {email}" + (f" / {phone}" if phone else "") + "."}


_STAFF_PAGES_ADMIN = {
    "dashboard": "/admin/dashboard",
    "tracking": "/admin/tracking",
    "insights": "/admin/insights",
    "users": "/admin/users",
    "client_activity": "/admin/client-activity",
    "audit_logs": "/admin/audit-logs",
    "integrations": "/admin/integrations",
    "settings": "/admin/settings",
}
_STAFF_PAGES_CLIENT = {
    "dashboard": "/client/dashboard",
    "campaigns": "/client/campaigns/active",
    "profile": "/client/profile",
    "outreach": "/client/outreach",
    "email_automation": "/client/email-automation",
    "bulk_voice_call": "/client/email-automation?tab=bulk-call",
    "call_tracking": "/client/email-automation?tab=call-tracking",
    "email_tracking": "/client/email-automation?tab=tracking",
    "insights": "/client/insights",
    "reports": "/client/reports",
    "social_media": "/client/social-media",
}


async def _navigate(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    pages = _STAFF_PAGES_ADMIN if scope.is_admin else _STAFF_PAGES_CLIENT
    page = re.sub(r"[\s\-]+", "_", (args.get("page") or "").strip().lower())
    path = pages.get(page)
    if not path:
        return {"error": f"Unknown page. Available: {', '.join(sorted(pages))}"}
    scope.ui_actions.append({"type": "navigate", "path": path, "label": page.replace("_", " ").title()})
    return {"status": "ok", "note": "A button to open this page is shown to the user."}


# --------------------------------------------------------------------------- #
# Shared + shopper + visitor tools
# --------------------------------------------------------------------------- #
async def _search_knowledge(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    result = knowledge.search(str(args.get("query") or ""), scope.audience, admin=scope.is_admin)
    conv = scope.conversation
    if result["status"] == "no_match":
        conv.unanswered_count = (conv.unanswered_count or 0) + 1
    else:
        conv.unanswered_count = 0
    return result


def _mark_escalated(conv: ChatConversation, reason: str, preferred_time: str | None) -> None:
    conv.status = "escalated"
    conv.escalation_reason = (reason or "Callback requested")[:1000]
    if preferred_time:
        conv.preferred_time = preferred_time[:120]


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{6,19}$")


async def _visitor_request_callback(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if args.get("consent_given") is not True:
        return {
            "status": "consent_required",
            "instruction": (
                "Ask the visitor, in plain words, whether ISN may store their name and contact details so a team "
                "member can contact them, and only retry with consent_given=true after they clearly agree."
            ),
        }
    name = str(args.get("name") or "").strip()[:255]
    email = str(args.get("email") or "").strip()[:255]
    phone = str(args.get("phone") or "").strip()[:50]
    if not name or not (email or phone):
        return {"status": "missing_details", "instruction": "Ask for their name and an email address or phone number."}
    if email and not _EMAIL_RE.match(email):
        return {"status": "invalid_email", "instruction": "That email address looks invalid — ask them to re-check it."}
    if phone and not _PHONE_RE.match(phone):
        return {"status": "invalid_phone", "instruction": "That phone number looks invalid — ask them to re-check it."}
    conv = scope.conversation
    conv.contact_name, conv.contact_email, conv.contact_phone = name, email or None, phone or None
    conv.contact_consent = True
    _mark_escalated(conv, str(args.get("reason") or "Visitor requested a callback"), args.get("preferred_time"))
    await record_audit(
        session,
        actor="visitor",
        action="chatbot.callback_requested",
        entity_type="chat_conversation",
        entity_id=str(conv.id),
        summary="Website visitor requested a callback via chatbot (consent given)",
        meta={"conversation_id": str(conv.id)},
    )
    return {"status": "requested", "note": "A team member will get back to them."}


async def _open_opportunities(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    """Anonymous aggregate only — never client/brand names or addresses."""
    stmt = select(Shop.state, Shop.category, func.count()).where(Shop.status == "open").group_by(Shop.state, Shop.category)
    if args.get("state"):
        stmt = stmt.where(Shop.state.ilike(f"%{args['state'].strip()}%"))
    rows = (await session.execute(stmt.limit(200))).all()
    by_state: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for state, category, n in rows:
        by_state[state or "Other"] = by_state.get(state or "Other", 0) + int(n)
        by_category[category or "General"] = by_category.get(category or "General", 0) + int(n)
    top_states = sorted(by_state.items(), key=lambda kv: kv[1], reverse=True)[:8]
    top_cats = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "open_shops_total": sum(by_state.values()),
        "by_state": dict(top_states),
        "by_category": dict(top_cats),
        "note": "Counts only. No brand names or pay figures are shared with anonymous visitors.",
    }


# --------------------------------------------------------------------------- #
# Registries
# --------------------------------------------------------------------------- #
_KNOWLEDGE_SPEC = _spec(
    "search_knowledge",
    "Search the product and website knowledge base: what ShopperMatch is, every page and feature, how to do things step "
    "by step, the AI features (matching, recommendations, bonus, Autopilot, voice, emails), tracking, settings, "
    "troubleshooting, and for shoppers how invitations, pay and privacy work. Call it for ANY question about the product "
    "or website before answering. Query in short ENGLISH keywords (translate Hindi/Hinglish). If the result is weak or "
    "no_match, search again with different keywords or use the topics/related titles it returns, up to three tries, "
    "before saying you don't know. Quote only what it returns.",
    {"query": {"type": "string", "description": "A few English keywords, e.g. 'autopilot modes' or 'reset password'"}},
    ["query"],
)
_CAMPAIGN_NAME = {"campaign_name": {"type": "string", "description": "Campaign name or part of it."}}

_STAFF_TOOLS: dict[str, tuple[dict, ToolHandler]] = {
    "list_campaigns": (
        _spec(
            "list_campaigns",
            "List campaigns you can access, with progress. Filter by status (active = every live campaign, incl. in progress; "
            "upcoming = draft/scheduled) and/or `name` (part of the campaign name). To find one campaign by its name, pass "
            "name — don't conclude it doesn't exist from a status-filtered list.",
            {
                "status": {"type": "string", "enum": ["active", "upcoming", "completed"]},
                "name": {"type": "string", "description": "Part of the campaign name"},
            },
        ),
        _list_campaigns,
    ),
    "campaign_overview": (
        _spec("campaign_overview", "Details for one campaign: shops, required shoppers and outreach funnel counts.", _CAMPAIGN_NAME, ["campaign_name"]),
        _campaign_overview,
    ),
    "outreach_funnel": (
        _spec("outreach_funnel", "Invitation funnel (sent, delivered, opened, clicked, visited, accepted, declined) with rates; for one campaign or all.", _CAMPAIGN_NAME),
        _outreach_funnel,
    ),
    "shops_needing_shoppers": (
        _spec("shops_needing_shoppers", "Open shops that have fewer invited shoppers than required.", _CAMPAIGN_NAME),
        _shops_needing_shoppers,
    ),
    "recent_activity": (
        _spec(
            "recent_activity",
            "Most recent invitation events (opens, clicks, accepts...).",
            {"limit": {"type": "integer"}, "event_type": {"type": "string", "description": "e.g. email_opened, assignment_accepted"}},
        ),
        _recent_activity,
    ),
    "shopper_search": (
        _spec(
            "shopper_search",
            "ADMIN ONLY. Search the shopper pool by name/code, city or state.",
            {"query": {"type": "string"}, "city": {"type": "string"}, "state": {"type": "string"}},
        ),
        _shopper_search,
    ),
    "shopper_history": (
        _spec("shopper_history", "ADMIN ONLY. One shopper's profile and recent invitations (name or code).", {"shopper": {"type": "string"}}, ["shopper"]),
        _shopper_history,
    ),
    "voice_call_summary": (_spec("voice_call_summary", "ADMIN ONLY. AI voice call outcome counts and recent batches."), _voice_call_summary),
    "chat_escalations": (_spec("chat_escalations", "ADMIN ONLY. Chatbot conversations awaiting human follow-up."), _chat_escalations),
    "navigate": (
        _spec("navigate", "Offer the user a button that opens a page of the app.", {"page": {"type": "string"}}, ["page"]),
        _navigate,
    ),
    "request_callback": (
        _spec(
            "request_callback",
            "Ask a human at ISN to call or contact this user back (they said 'call me back', 'can someone contact me', "
            "'talk to a person', or you can't answer something). Their account name and email are used; a phone "
            "number and preferred time are optional.",
            {
                "reason": {"type": "string", "description": "What it is about, if they said."},
                "name": {"type": "string", "description": "Only if they gave a different name."},
                "email": {"type": "string", "description": "Only if they gave a different email."},
                "phone": {"type": "string", "description": "Optional phone number they gave."},
                "preferred_time": {"type": "string", "description": "Optional, e.g. 'tomorrow 3pm IST'."},
            },
        ),
        _staff_request_callback,
    ),
    "search_knowledge": (_KNOWLEDGE_SPEC, _search_knowledge),
}

_VISITOR_TOOLS: dict[str, tuple[dict, ToolHandler]] = {
    "open_opportunities": (
        _spec("open_opportunities", "Anonymous counts of currently open shops by state and category.", {"state": {"type": "string"}}),
        _open_opportunities,
    ),
    "request_callback": (
        _spec(
            "request_callback",
            "Have a human contact the visitor. consent_given must be true ONLY if the visitor explicitly agreed to ISN storing their contact details.",
            {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "reason": {"type": "string"},
                "preferred_time": {"type": "string"},
                "consent_given": {"type": "boolean"},
            },
            ["name", "consent_given"],
        ),
        _visitor_request_callback,
    ),
    "search_knowledge": (_KNOWLEDGE_SPEC, _search_knowledge),
}

_STAFF_TOOLS.update(API_TOOLS)

_REGISTRIES = {"staff": _STAFF_TOOLS, "shopper": SHOPPER_TOOLS, "visitor": _VISITOR_TOOLS}


def tool_specs(scope: ChatScope) -> list[dict]:
    registry = _REGISTRIES[scope.audience]
    return [
        spec
        for name, (spec, _) in registry.items()
        # Hide admin-only tools from client-role users entirely.
        if scope.is_admin or scope.audience != "staff" or not spec["function"]["description"].startswith("ADMIN ONLY")
    ]


async def run_tool(session: AsyncSession, scope: ChatScope, name: str, args: dict[str, Any]) -> dict:
    """Execute one tool call; never raises into the agent loop."""
    entry = _REGISTRIES[scope.audience].get(name)
    if entry is None:
        return {"error": f"Unknown tool '{name}'."}
    if not isinstance(args, dict):
        args = {}
    try:
        return await entry[1](session, scope, args)
    except Exception as exc:  # noqa: BLE001 — surfaced to the model as data, logged server-side
        import logging

        logging.getLogger(__name__).exception("chatbot tool %s failed", name)
        return {"error": f"Tool failed: {type(exc).__name__}"}
