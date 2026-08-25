"""N. AI Natural Language Insights + P. AI Operations Assistant.

Pipeline: Natural Language -> Intent Detection (keyword matching against a
FIXED set of supported question patterns) -> Safe Database Query (read-only
SQLAlchemy `select`, no free-text SQL is ever executed) -> AI Explanation.

If a question doesn't match a known, safe intent, the answer is exactly
"I don't have enough data to answer that." — this function never falls back
to executing arbitrary SQL from user text, and never invents a number.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AuditLog,
    BatchAutomation,
    Campaign,
    Client,
    EmailAutomation,
    EmailTemplate,
    IntegrationConfig,
    Invitation,
    Shop,
    Shopper,
    User,
)
from ...routers.campaigns import status_bucket
from ..analytics import compute_summary
from ..semantic_matching import run_matching
from .campaign_predictor import campaign_health
from .next_best_action import get_next_best_actions

FALLBACK = "I don't have enough data to answer that."

# "Hey Assistant" / wake-word style greetings — answered directly, without
# ever reaching the FALLBACK path, so the assistant always sounds alive even
# when a message isn't really a question yet.
_GREETING_PHRASES = {
    "hey assistant", "hi assistant", "hello assistant", "ok assistant",
    "hey operations assistant", "hi operations assistant",
    "hey", "hi", "hello", "yo", "sup",
}


async def _match_campaign(session: AsyncSession, q: str) -> Campaign | None:
    """Finds the campaign the question names, by substring match against
    the campaign name or client name — never a fuzzy guess beyond that."""
    campaigns = (await session.execute(select(Campaign))).scalars().all()
    for c in campaigns:
        if c.name and c.name.lower() in q:
            return c
    for c in campaigns:
        if c.client_name and c.client_name.lower() in q:
            return c
    return None


async def _campaign_acceptance_rates(session: AsyncSession) -> list[tuple[str, float, int]]:
    campaigns = (await session.execute(select(Campaign))).scalars().all()
    out = []
    for c in campaigns:
        row = (
            await session.execute(
                select(
                    func.count(Invitation.id).filter(Invitation.sent_at.isnot(None)),
                    func.count(Invitation.id).filter(Invitation.response == "accepted"),
                ).where(Invitation.campaign_id == c.id)
            )
        ).one()
        sent, accepted = row
        if sent:
            out.append((c.name, accepted / sent * 100, sent))
    return out


async def _city_completion_rates(session: AsyncSession) -> list[tuple[str, float]]:
    shops = (await session.execute(select(Shop))).scalars().all()
    by_city: dict[str, list[str]] = {}
    for s in shops:
        if s.city:
            by_city.setdefault(s.city, []).append(s.status)
    out = []
    for city, statuses in by_city.items():
        done = sum(1 for st in statuses if st == "completed")
        out.append((city, done / len(statuses) * 100))
    return out


async def _top_completion_shoppers(session: AsyncSession, limit: int = 5) -> list[tuple[str, float]]:
    rows = (
        await session.execute(
            select(Shopper.name, Shopper.completion_rate)
            .where(Shopper.active.is_(True), Shopper.completion_rate > 0)
            .order_by(Shopper.completion_rate.desc())
            .limit(limit)
        )
    ).all()
    return [(name, round(rate * 100)) for name, rate in rows]


async def _campaigns_with_low_coverage(session: AsyncSession) -> list[str]:
    campaigns = (await session.execute(select(Campaign))).scalars().all()
    flagged = []
    for c in campaigns:
        if status_bucket(c.status) != "active":
            continue
        health = await campaign_health(session, c)
        if health["breakdown"]["eligible_shoppers"] < 50 or health["risks"]:
            flagged.append(c.name)
    return flagged


# Known ISN Admin routes the assistant can send someone to. Ordered so a
# more specific phrase (e.g. "client activity") is checked before a shorter
# one that could accidentally be a substring of it were the order reversed.
_NAV_TARGETS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Client Activity", "/admin/client-activity", ("client activity", "clients activity", "client's activity")),
    ("Audit Logs", "/admin/audit-logs", ("audit log", "audit trail")),
    ("Users", "/admin/users", ("user management", "client users", "shopper director", "users page", "uses page", "user page")),
    ("Tracking", "/admin/tracking", ("tracking",)),
    ("Insights", "/admin/insights", ("insight",)),
    ("Integrations", "/admin/integrations", ("integration",)),
    ("Settings", "/admin/settings", ("setting",)),
    ("Dashboard", "/admin/dashboard", ("dashboard", "home page", "main page")),
]

_NAV_TRIGGERS = (
    "take me to", "go to", "open the", "open ", "show me the", "show me",
    "where can i see", "where can i find", "which page", "what page",
    "navigate to", "give me the page", "page where",
)


def _match_nav_target(q: str) -> tuple[str, str] | None:
    if not any(t in q for t in _NAV_TRIGGERS) and "page" not in q:
        return None
    for label, path, keywords in _NAV_TARGETS:
        if any(k in q for k in keywords):
            return label, path
    return None


async def _match_client(session: AsyncSession, q: str) -> Client | None:
    """Finds the client the question names, by substring match against the
    company name — same convention as `_match_campaign`."""
    clients = (await session.execute(select(Client))).scalars().all()
    for c in clients:
        if c.company_name and c.company_name.lower() in q:
            return c
    return None


async def _match_shopper(session: AsyncSession, q: str) -> Shopper | None:
    """Finds the shopper the question names, by substring match against their
    name — never a fuzzy/phonetic guess, same convention as the other
    `_match_*` helpers."""
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    for s in shoppers:
        if s.name and s.name.lower() in q:
            return s
    return None


async def _match_shop(session: AsyncSession, q: str) -> Shop | None:
    """Finds the shop the question names, by substring match against its
    name."""
    shops = (await session.execute(select(Shop))).scalars().all()
    for s in shops:
        if s.shop_name and s.shop_name.lower() in q:
            return s
    return None


async def _client_counts(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(Client.status, func.count(Client.id)).group_by(Client.status))).all()
    counts = {status: int(n) for status, n in rows}
    counts["total"] = sum(counts.values())
    return counts


async def _shop_counts(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(Shop.status, func.count(Shop.id)).group_by(Shop.status))).all()
    counts = {status: int(n) for status, n in rows}
    counts["total"] = sum(counts.values())
    return counts


async def _campaign_bucket_counts(session: AsyncSession) -> dict[str, int]:
    campaigns = (await session.execute(select(Campaign))).scalars().all()
    counts: dict[str, int] = {"active": 0, "upcoming": 0, "completed": 0, "cancelled": 0}
    for c in campaigns:
        bucket = status_bucket(c.status)
        counts[bucket] = counts.get(bucket, 0) + 1
    counts["total"] = len(campaigns)
    return counts


async def _client_recent_activity(session: AsyncSession, client: Client, limit: int = 5) -> list[AuditLog]:
    users = (
        await session.execute(select(User).where(User.client_id == client.id, User.role == "client"))
    ).scalars().all()
    emails = [u.email for u in users]
    if not emails:
        return []
    return list(
        (
            await session.execute(
                select(AuditLog).where(AuditLog.actor.in_(emails)).order_by(AuditLog.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    )


async def _most_recent_client_login(session: AsyncSession) -> User | None:
    return (
        await session.execute(
            select(User)
            .where(User.role == "client", User.last_login_at.isnot(None))
            .options(selectinload(User.client))
            .order_by(User.last_login_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def answer_question(session: AsyncSession, question: str) -> dict:
    q = question.lower().strip().strip("!?.")

    if q in _GREETING_PHRASES:
        return {"answer": "How can I help you?", "intent": "greeting", "data": None}

    # ------------------------- Navigation ------------------------- #
    # "Take me to X" / "open the X page" / "where can I see X" — resolved
    # against a fixed map of known ISN Admin routes (never a free-text URL),
    # so the frontend can render/follow a real in-app link.
    nav_hit = _match_nav_target(q)
    if nav_hit is not None:
        label, path = nav_hit
        return {
            "answer": f"Here's the {label} page.",
            "intent": "navigate",
            "data": {"path": path, "label": label},
        }

    # ------------------------- Exports ------------------------- #
    if "client activity" in q and any(
        kw in q for kw in ("pdf", "export", "download", "excel", "xlsx", "csv", "spreadsheet", "report")
    ):
        fmt = "xlsx" if any(k in q for k in ("excel", "xlsx", "spreadsheet")) else "csv" if "csv" in q else "pdf"
        return {
            "answer": f"Here's the Client Activity report as a {fmt.upper()} — downloading now.",
            "intent": "export_client_activity",
            "data": {
                "action": "download",
                "format": fmt,
                "endpoint": "/api/admin/users/clients/activity-summary/export",
                "filename": f"client_activity.{fmt}",
            },
        }

    # ------------------------- Named shopper / shop lookup ------------------------- #
    if any(kw in q for kw in ("tell me about", "who is", "details on", "details for", "profile of", "info on", "information on")):
        shopper = await _match_shopper(session, q)
        if shopper is not None:
            loc = ", ".join(filter(None, [shopper.city, shopper.state])) or "unknown location"
            return {
                "answer": (
                    f"{shopper.name} — {loc}, {shopper.availability_status}, "
                    f"{round(shopper.completion_rate * 100)}% completion rate, {shopper.previous_assignments} prior assignment(s), "
                    f"rating {shopper.rating}/5. Categories: {', '.join(shopper.categories) or 'none listed'}."
                ),
                "intent": "shopper_profile",
                "data": {
                    "name": shopper.name, "city": shopper.city, "status": shopper.availability_status,
                    "completion_rate": shopper.completion_rate, "rating": shopper.rating,
                },
            }
        shop = await _match_shop(session, q)
        if shop is not None:
            return {
                "answer": (
                    f"{shop.shop_name} — {shop.city or 'unknown city'}, status {shop.status}, "
                    f"requires {shop.required_shoppers} shopper(s), compensation {shop.currency} {shop.compensation}, "
                    f"category {shop.category or 'unspecified'}."
                ),
                "intent": "shop_profile",
                "data": {
                    "name": shop.shop_name, "city": shop.city, "status": shop.status,
                    "required_shoppers": shop.required_shoppers, "compensation": shop.compensation,
                },
            }
        client = await _match_client(session, q)
        if client is not None:
            return {
                "answer": f"{client.company_name} — status {client.status}, contact {client.contact_name or 'unlisted'} ({client.contact_email or 'no email on file'}).",
                "intent": "client_profile",
                "data": {"company_name": client.company_name, "status": client.status},
            }
        campaign = await _match_campaign(session, q)
        if campaign is not None:
            health = await campaign_health(session, campaign)
            return {
                "answer": (
                    f"{campaign.name} ({campaign.client_name}) — {status_bucket(campaign.status)}, "
                    f"{campaign.completed_shops}/{campaign.total_shops} shops complete, readiness {health['readiness']}%."
                ),
                "intent": "campaign_profile",
                "data": {"name": campaign.name, "status": campaign.status, "readiness": health["readiness"]},
            }

    # ------------------------- Templates ------------------------- #
    if "template" in q:
        templates = (await session.execute(select(EmailTemplate))).scalars().all()
        active = sum(1 for t in templates if t.active)
        names = ", ".join(t.name for t in templates[:12])
        return {
            "answer": f"{len(templates)} email template(s), {active} active: {names}.",
            "intent": "template_overview",
            "data": {"total": len(templates), "active": active},
        }

    # ------------------------- Automations / sequences ------------------------- #
    if "automation" in q or "sequence" in q:
        seq_rows = (await session.execute(select(EmailAutomation.status, func.count(EmailAutomation.id)).group_by(EmailAutomation.status))).all()
        batch_rows = (await session.execute(select(BatchAutomation.status, func.count(BatchAutomation.id)).group_by(BatchAutomation.status))).all()
        seq_counts = {s: int(n) for s, n in seq_rows}
        batch_counts = {s: int(n) for s, n in batch_rows}
        seq_total = sum(seq_counts.values())
        batch_total = sum(batch_counts.values())
        return {
            "answer": (
                f"{seq_total} outreach sequence(s) ({seq_counts.get('active', 0)} active, {seq_counts.get('draft', 0)} draft) "
                f"and {batch_total} batch automation(s) ({batch_counts.get('active', 0)} active, {batch_counts.get('draft', 0)} draft)."
            ),
            "intent": "automation_overview",
            "data": {"sequences": seq_counts, "batch": batch_counts},
        }

    # ------------------------- Integrations ------------------------- #
    if "integration" in q:
        integrations = (await session.execute(select(IntegrationConfig))).scalars().all()
        if not integrations:
            return {"answer": "No integrations configured yet.", "intent": "integration_overview", "data": {"items": []}}
        listing = ", ".join(f"{i.display_name} ({i.status})" for i in integrations)
        return {
            "answer": f"Integrations: {listing}.",
            "intent": "integration_overview",
            "data": {"items": [{"name": i.display_name, "status": i.status} for i in integrations]},
        }

    # ------------------------- Clients ------------------------- #
    if "how many client" in q or ("clients" in q and ("count" in q or "total" in q)):
        counts = await _client_counts(session)
        return {
            "answer": f"There are {counts['total']} client account(s) — {counts.get('active', 0)} active"
            + (f", {counts.get('deactivated', 0)} deactivated" if counts.get("deactivated") else "")
            + ".",
            "intent": "client_counts",
            "data": counts,
        }

    if "list" in q and "client" in q:
        clients = (await session.execute(select(Client).order_by(Client.company_name))).scalars().all()
        if not clients:
            return {"answer": "There are no client accounts yet.", "intent": "list_clients", "data": {"clients": []}}
        names = ", ".join(f"{c.company_name} ({c.status})" for c in clients)
        return {"answer": f"Clients: {names}.", "intent": "list_clients", "data": {"clients": [c.company_name for c in clients]}}

    if "who logged in" in q or "last login" in q or "most recent login" in q:
        user = await _most_recent_client_login(session)
        if user is None:
            return {"answer": "No client has logged in yet.", "intent": "last_client_login", "data": None}
        company = user.client.company_name if user.client else user.email
        return {
            "answer": f"{company} ({user.email}) logged in most recently.",
            "intent": "last_client_login",
            "data": {"company": company, "email": user.email, "last_login_at": str(user.last_login_at)},
        }

    if ("what did" in q or "activity" in q or "actions" in q or "recent" in q) and (
        client := await _match_client(session, q)
    ) is not None:
        logs = await _client_recent_activity(session, client)
        if not logs:
            return {
                "answer": f"No recorded activity for {client.company_name} yet.",
                "intent": "client_activity",
                "data": {"client": client.company_name, "actions": []},
            }
        listing = "; ".join(a.summary or a.action for a in logs)
        return {
            "answer": f"Recent activity for {client.company_name}: {listing}.",
            "intent": "client_activity",
            "data": {"client": client.company_name, "actions": [a.action for a in logs]},
        }

    # ------------------------- Shoppers (totals) ------------------------- #
    if "how many shopper" in q and "eligible" not in q and "available" not in q and not any(
        city in q for city in ("mumbai", "pune", "nashik", "thane", "bangalore", "delhi", "hyderabad", "chennai")
    ):
        total = await session.scalar(select(func.count(Shopper.id)))
        active = await session.scalar(select(func.count(Shopper.id)).where(Shopper.active.is_(True)))
        return {
            "answer": f"There are {total or 0} shopper(s) in the network, {active or 0} active.",
            "intent": "shopper_counts",
            "data": {"total": total or 0, "active": active or 0},
        }

    # ------------------------- Shops ------------------------- #
    if "how many shop" in q and "shopper" not in q:
        counts = await _shop_counts(session)
        parts = ", ".join(f"{v} {k}" for k, v in counts.items() if k != "total")
        return {
            "answer": f"There are {counts['total']} shop(s) total ({parts}).",
            "intent": "shop_counts",
            "data": counts,
        }

    # ------------------------- Email / tracking activity ------------------------- #
    if any(kw in q for kw in ("email tracking", "tracking activity", "email activity")) or (
        "email" in q and any(w in q for w in ("sent", "delivered", "opened", "clicked", "stats", "summary"))
    ):
        s = await compute_summary(session)
        return {
            "answer": (
                f"Email tracking overall: {s['sent']} sent, {s['delivered']} delivered "
                f"({s['delivery_rate']}%), {s['opened']} opened ({s['open_rate']}%), "
                f"{s['clicked']} clicked ({s['click_rate']}%), {s['accepted']} accepted, {s['declined']} declined."
            ),
            "intent": "email_tracking_summary",
            "data": s,
        }

    # ------------------------- Campaigns (totals) ------------------------- #
    if "how many campaign" in q:
        counts = await _campaign_bucket_counts(session)
        return {
            "answer": (
                f"There are {counts['total']} campaign(s) total — {counts['active']} active, "
                f"{counts['upcoming']} upcoming, {counts['completed']} completed."
            ),
            "intent": "campaign_counts",
            "data": counts,
        }

    if "lowest acceptance" in q or ("acceptance" in q and "lowest" in q):
        rates = await _campaign_acceptance_rates(session)
        if not rates:
            return {"answer": FALLBACK, "intent": "lowest_acceptance_campaign", "data": None}
        name, rate, sent = min(rates, key=lambda r: r[1])
        return {
            "answer": f"{name} has the lowest acceptance rate at {round(rate)}% ({sent} invitations sent).",
            "intent": "lowest_acceptance_campaign",
            "data": {"campaign": name, "acceptance_rate": round(rate)},
        }

    if "highest" in q and "completion" in q and "city" in q:
        rates = await _city_completion_rates(session)
        if not rates:
            return {"answer": FALLBACK, "intent": "highest_completion_city", "data": None}
        city, rate = max(rates, key=lambda r: r[1])
        return {
            "answer": f"{city} has the highest campaign completion rate at {round(rate)}%.",
            "intent": "highest_completion_city",
            "data": {"city": city, "completion_rate": round(rate)},
        }

    if "completion rate" in q and "shopper" in q:
        top = await _top_completion_shoppers(session)
        if not top:
            return {"answer": FALLBACK, "intent": "top_completion_shoppers", "data": None}
        listing = ", ".join(f"{n} ({r}%)" for n, r in top)
        return {
            "answer": f"Shoppers with the highest completion rates: {listing}.",
            "intent": "top_completion_shoppers",
            "data": {"shoppers": top},
        }

    if "insufficient" in q and "eligible" in q:
        flagged = await _campaigns_with_low_coverage(session)
        if not flagged:
            return {"answer": "No active campaigns currently show insufficient eligible shoppers.", "intent": "low_coverage_campaigns", "data": {"campaigns": []}}
        return {
            "answer": f"These campaigns currently have insufficient eligible shoppers: {', '.join(flagged)}.",
            "intent": "low_coverage_campaigns",
            "data": {"campaigns": flagged},
        }

    if "highest response rate" in q or ("response rate" in q and "highest" in q):
        rates = await _campaign_acceptance_rates(session)
        if not rates:
            return {"answer": FALLBACK, "intent": "highest_response_campaign", "data": None}
        name, rate, sent = max(rates, key=lambda r: r[1])
        return {
            "answer": f"{name} has the highest response rate at {round(rate)}% ({sent} invitations sent).",
            "intent": "highest_response_campaign",
            "data": {"campaign": name, "response_rate": round(rate)},
        }

    if "needs attention" in q or "which campaign needs" in q:
        actions = await get_next_best_actions(session, limit=3)
        if not actions:
            return {"answer": "No campaigns currently need attention.", "intent": "campaign_needs_attention", "data": {"actions": []}}
        top = actions[0]
        return {
            "answer": f"{top['campaign_name']} needs attention: {top['message']} Recommended: {top['recommended_action']}",
            "intent": "campaign_needs_attention",
            "data": {"actions": actions},
        }

    if "how many eligible" in q or ("eligible shoppers" in q and "how many" in q):
        for city in ("mumbai", "pune", "nashik", "thane", "bangalore", "delhi", "hyderabad", "chennai"):
            if city in q:
                count = await session.scalar(
                    select(func.count(Shopper.id)).where(
                        func.lower(Shopper.city) == city, Shopper.active.is_(True), Shopper.availability_status != "unavailable"
                    )
                )
                return {
                    "answer": f"There are {count or 0} available, active shoppers in {city.title()}.",
                    "intent": "eligible_shoppers_in_city",
                    "data": {"city": city.title(), "count": count or 0},
                }
        return {"answer": FALLBACK, "intent": "eligible_shoppers_in_city", "data": None}

    if ("why" in q and ("behind" in q or "at risk" in q or "delayed" in q)) or (
        "what caused" in q and ("low coverage" in q or "coverage" in q)
    ):
        campaign = await _match_campaign(session, q)
        if campaign is None:
            actions = await get_next_best_actions(session, limit=1)
            if not actions:
                return {"answer": "No campaigns currently show signs of being behind.", "intent": "campaign_risk_reason", "data": None}
            campaign = await session.get(Campaign, uuid.UUID(actions[0]["campaign_id"]))
        health = await campaign_health(session, campaign)
        if not health["risks"]:
            return {
                "answer": f"{campaign.name} shows no specific risk factors right now — readiness is {health['readiness']}%.",
                "intent": "campaign_risk_reason",
                "data": {"campaign": campaign.name, "readiness": health["readiness"]},
            }
        return {
            "answer": f"{campaign.name}: {' '.join(health['risks'])}",
            "intent": "campaign_risk_reason",
            "data": {"campaign": campaign.name, "risks": health["risks"], "readiness": health["readiness"]},
        }

    if "best shopper" in q and ("for" in q or "find" in q):
        campaign = await _match_campaign(session, q)
        if campaign is None:
            return {"answer": FALLBACK, "intent": "best_shoppers_for_campaign", "data": None}
        shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
        if not shops:
            return {"answer": f"{campaign.name} has no shops to match against yet.", "intent": "best_shoppers_for_campaign", "data": None}
        shoppers = (await session.execute(select(Shopper))).scalars().all()
        result = run_matching(list(shoppers), shops[0], campaign)
        top = result["recommendations"][:3]
        if not top:
            return {"answer": f"No eligible shoppers found for {campaign.name} right now.", "intent": "best_shoppers_for_campaign", "data": {"campaign": campaign.name, "shoppers": []}}
        listing = ", ".join(f"{r['name']} ({r['match_score']}%)" for r in top)
        return {
            "answer": f"Top matches for {campaign.name} ({shops[0].shop_name}): {listing}.",
            "intent": "best_shoppers_for_campaign",
            "data": {"campaign": campaign.name, "shop": shops[0].shop_name, "shoppers": [{"name": r["name"], "match_score": r["match_score"]} for r in top]},
        }

    if "who should i contact" in q or ("contact first" in q):
        actions = await get_next_best_actions(session, limit=1)
        if not actions:
            return {"answer": "No campaigns currently need outreach prioritization.", "intent": "who_to_contact_first", "data": None}
        return {
            "answer": f"Start with {actions[0]['campaign_name']}: {actions[0]['message']} Use AI Outreach Prioritization on that campaign for the ranked shopper list.",
            "intent": "who_to_contact_first",
            "data": {"campaign": actions[0]["campaign_name"]},
        }

    # ------------------------- Category fallback ------------------------- #
    # Nothing above matched exactly, but the question is clearly ABOUT one of
    # these entities — rather than a flat "I don't have enough data", give a
    # real, data-backed overview for that entity. This is what makes loosely
    # phrased questions ("give me clients data", "what about shoppers")
    # answerable without hand-enumerating every possible wording as its own
    # intent above — the specific intents still win when they match, since
    # they're all checked earlier in this function.
    if "client" in q:
        counts = await _client_counts(session)
        clients = (await session.execute(select(Client).order_by(Client.company_name))).scalars().all()
        names = ", ".join(f"{c.company_name} ({c.status})" for c in clients[:10])
        more = f" and {len(clients) - 10} more" if len(clients) > 10 else ""
        return {
            "answer": (
                f"{counts['total']} client account(s), {counts.get('active', 0)} active: {names}{more}. "
                "Ask me to open the Client Activity page for full detail, or export it as a PDF."
            ),
            "intent": "client_overview",
            "data": counts,
        }

    if "shopper" in q:
        total = await session.scalar(select(func.count(Shopper.id)))
        active = await session.scalar(select(func.count(Shopper.id)).where(Shopper.active.is_(True)))
        available = await session.scalar(
            select(func.count(Shopper.id)).where(Shopper.availability_status == "available")
        )
        return {
            "answer": f"{total or 0} shopper(s) in the network — {active or 0} active, {available or 0} currently available.",
            "intent": "shopper_overview",
            "data": {"total": total or 0, "active": active or 0, "available": available or 0},
        }

    if "shop" in q:
        counts = await _shop_counts(session)
        parts = ", ".join(f"{v} {k}" for k, v in counts.items() if k != "total")
        return {
            "answer": f"{counts['total']} shop(s) total ({parts}).",
            "intent": "shop_overview",
            "data": counts,
        }

    if "campaign" in q:
        counts = await _campaign_bucket_counts(session)
        return {
            "answer": (
                f"{counts['total']} campaign(s) — {counts['active']} active, {counts['upcoming']} upcoming, "
                f"{counts['completed']} completed."
            ),
            "intent": "campaign_overview",
            "data": counts,
        }

    if "track" in q or "email" in q:
        s = await compute_summary(session)
        return {
            "answer": (
                f"Overall outreach: {s['sent']} sent, {s['delivered']} delivered, {s['opened']} opened, "
                f"{s['clicked']} clicked, {s['accepted']} accepted."
            ),
            "intent": "email_tracking_overview",
            "data": s,
        }

    return {"answer": FALLBACK, "intent": None, "data": None}
