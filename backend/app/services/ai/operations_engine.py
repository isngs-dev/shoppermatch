"""Phase 23/24 — AI Operations Engine.

A small set of purpose-built "agents" that each evaluate one operational
dimension of every active/upcoming campaign, over the existing Campaign /
Shop / Invitation tables — nothing here maintains its own state or a second
dataset. Each agent yields zero or more issues in one shared shape:

    condition            short machine-ish label, e.g. "low_shopper_coverage"
    severity              "HIGH" | "MEDIUM" | "LOW"
    reason                 human-readable explanation, built only from real numbers
    recommended_action     what a human operator should consider doing
    action_type             machine key the frontend maps to a button/route
    required_approval       True if executing the action changes campaign
                             state (assign, send, bonus, parameter change) —
                             False if it's just preparing something for review
                             (viewing candidates, drafting an email/reminder)

This mirrors the "detect -> analyze -> recommend -> risk -> approval" agentic
flow from the spec without pulling in an orchestration framework: five plain
async functions with single responsibilities cover it, and the aggregator
(`run_operations_engine`) is the "Operations Decision Agent" that merges
their output. Nothing here executes an action — every recommendation still
requires an explicit human step through the existing approve-gated endpoints
(recommendations/approve, optimize-assignments, outreach send).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import Campaign, Invitation
from ...routers.campaigns import status_bucket
from .campaign_predictor import campaign_health

# Action types that only prepare something for human review — never mutate
# campaign/shopper/invitation state on their own.
LOW_RISK_ACTIONS = {
    "view_candidates",
    "suggest_candidates",
    "prepare_reminder",
    "prepare_email",
    "no_action",
}


def _required_approval(action_type: str) -> bool:
    return action_type not in LOW_RISK_ACTIONS


async def _campaign_invitation_stats(session: AsyncSession, campaign_id) -> dict:
    invs = (
        await session.execute(select(Invitation).where(Invitation.campaign_id == campaign_id))
    ).scalars().all()
    sent = sum(1 for i in invs if i.sent_at)
    opened = sum(1 for i in invs if i.opened_at)
    responded = sum(1 for i in invs if i.response is not None)
    accepted = sum(1 for i in invs if i.response == "accepted")
    opened_not_accepted = sum(1 for i in invs if i.opened_at and not i.response)
    return {
        "sent": sent,
        "opened": opened,
        "responded": responded,
        "accepted": accepted,
        "opened_not_accepted": opened_not_accepted,
        "response_rate": (responded / sent * 100) if sent else None,
    }


# --------------------------------------------------------------------------- #
# Coverage Agent — are there enough eligible shoppers for what's required?
# --------------------------------------------------------------------------- #
async def coverage_agent(session: AsyncSession, campaign: Campaign, health: dict) -> list[dict]:
    issues = []
    breakdown = health["breakdown"]
    if breakdown["shop_coverage"] < 100:
        severity = "HIGH" if breakdown["shop_coverage"] < 60 else "MEDIUM"
        issues.append(
            {
                "agent": "coverage",
                "condition": "low_shop_coverage",
                "severity": severity,
                "reason": f"Shop coverage is {round(breakdown['shop_coverage'])}% — some shops still need eligible shopper candidates.",
                "recommended_action": "Review AI recommendations and find additional eligible shoppers.",
                "action_type": "view_candidates",
            }
        )
    if breakdown["eligible_shoppers"] < 50:
        issues.append(
            {
                "agent": "coverage",
                "condition": "low_shopper_coverage",
                "severity": "HIGH" if breakdown["eligible_shoppers"] < 30 else "MEDIUM",
                "reason": f"Only {round(breakdown['eligible_shoppers'])}% of shops have strong eligible-shopper coverage.",
                "recommended_action": "Expand search radius or recruit additional shoppers in the affected cities.",
                "action_type": "suggest_candidates",
            }
        )
    return issues


# --------------------------------------------------------------------------- #
# Outreach Agent — is the outreach funnel converting?
# --------------------------------------------------------------------------- #
async def outreach_agent(session: AsyncSession, campaign: Campaign, stats: dict) -> list[dict]:
    issues = []
    if stats["sent"] == 0:
        return issues
    if stats["opened_not_accepted"] >= 2:
        issues.append(
            {
                "agent": "outreach",
                "condition": "opened_not_accepted",
                "severity": "MEDIUM",
                "reason": f"{stats['opened_not_accepted']} invitation(s) were opened but never responded to.",
                "recommended_action": "Send a personalized follow-up to shoppers who opened but didn't respond.",
                "action_type": "prepare_reminder",
            }
        )
    if stats["response_rate"] is not None and stats["response_rate"] < 30 and stats["sent"] >= 3:
        issues.append(
            {
                "agent": "outreach",
                "condition": "low_response_rate",
                "severity": "HIGH" if stats["response_rate"] < 15 else "MEDIUM",
                "reason": f"Outreach response rate is {round(stats['response_rate'])}% across {stats['sent']} invitations sent.",
                "recommended_action": "Launch a new outreach round with AI-personalized emails.",
                "action_type": "prepare_email",
            }
        )
    return issues


# --------------------------------------------------------------------------- #
# Deadline Agent — is the campaign on pace to finish in time?
# --------------------------------------------------------------------------- #
async def deadline_agent(session: AsyncSession, campaign: Campaign) -> list[dict]:
    from datetime import datetime, timezone

    issues = []
    if campaign.deadline is None or not campaign.total_shops:
        return issues
    deadline = campaign.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    days_left = (deadline - datetime.now(timezone.utc)).total_seconds() / 86400
    completion = (campaign.completed_shops or 0) / campaign.total_shops

    if days_left <= 7 and completion < 0.8:
        issues.append(
            {
                "agent": "deadline",
                "condition": "deadline_at_risk",
                "severity": "HIGH" if days_left <= 3 else "MEDIUM",
                "reason": f"Deadline is in {max(0, round(days_left))} day(s) and only {round(completion * 100)}% of shops are complete.",
                "recommended_action": "Prioritize outreach to remaining shops and consider expanding the shopper search.",
                "action_type": "prepare_email",
            }
        )
    return issues


# --------------------------------------------------------------------------- #
# Shopper (recruitment gap) Agent — required vs. remaining open slots
# --------------------------------------------------------------------------- #
async def shopper_agent(session: AsyncSession, campaign: Campaign) -> list[dict]:
    issues = []
    shops_needing = campaign.total_shops - (campaign.completed_shops or 0)
    if campaign.total_shops and shops_needing >= max(1, round(campaign.total_shops * 0.4)):
        issues.append(
            {
                "agent": "shopper",
                "condition": "recruitment_gap",
                "severity": "HIGH",
                "reason": f"{shops_needing} of {campaign.total_shops} shops still require shoppers.",
                "recommended_action": f"Recruit additional shoppers to close the {shops_needing}-shop gap.",
                "action_type": "suggest_candidates",
            }
        )
    return issues


# --------------------------------------------------------------------------- #
# Campaign Agent — overall readiness sanity check
# --------------------------------------------------------------------------- #
async def campaign_agent(session: AsyncSession, campaign: Campaign, health: dict) -> list[dict]:
    issues = []
    if health["readiness"] < 60:
        issues.append(
            {
                "agent": "campaign",
                "condition": "low_overall_readiness",
                "severity": "HIGH",
                "reason": f"Overall AI readiness score is {health['readiness']}%.",
                "recommended_action": "Review shop coverage, candidate quality and outreach response together — multiple factors are weak.",
                "action_type": "view_candidates",
            }
        )
    return issues


SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


async def run_operations_engine(session: AsyncSession, campaign_ids: list | None = None) -> list[dict]:
    """Runs all five agents across every active/upcoming campaign (or a
    given subset) and returns the raw, per-agent issue list — one row per
    (campaign, agent, condition). Callers that want one summary per campaign
    should use `campaign_action_items` instead."""
    q = select(Campaign).options(selectinload(Campaign.shops))
    campaigns = (await session.execute(q)).scalars().all()

    all_issues: list[dict] = []
    for c in campaigns:
        if campaign_ids is not None and str(c.id) not in campaign_ids:
            continue
        bucket = status_bucket(c.status)
        if bucket not in ("active", "upcoming"):
            continue

        health = await campaign_health(session, c)
        stats = await _campaign_invitation_stats(session, c.id)

        agent_issues: list[dict] = []
        agent_issues += await coverage_agent(session, c, health)
        agent_issues += await outreach_agent(session, c, stats)
        agent_issues += await deadline_agent(session, c)
        agent_issues += await shopper_agent(session, c)
        agent_issues += await campaign_agent(session, c, health)

        for issue in agent_issues:
            issue["campaign_id"] = str(c.id)
            issue["campaign_name"] = c.name
            issue["required_approval"] = _required_approval(issue["action_type"])
            all_issues.append(issue)

    all_issues.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 3))
    return all_issues


async def campaign_action_items(session: AsyncSession) -> list[dict]:
    """One row per active/upcoming campaign — the single most severe issue
    found by any agent, or an 'on track' status if none. This is what the
    AI Action Center (Phase 26) renders."""
    issues = await run_operations_engine(session)
    by_campaign: dict[str, dict] = {}
    for issue in issues:
        cid = issue["campaign_id"]
        if cid not in by_campaign or SEVERITY_ORDER[issue["severity"]] < SEVERITY_ORDER[by_campaign[cid]["severity"]]:
            by_campaign[cid] = issue

    q = select(Campaign)
    campaigns = (await session.execute(q)).scalars().all()
    items = []
    for c in campaigns:
        bucket = status_bucket(c.status)
        if bucket not in ("active", "upcoming"):
            continue
        cid = str(c.id)
        if cid in by_campaign:
            issue = by_campaign[cid]
            items.append(
                {
                    "campaign_id": cid,
                    "campaign_name": c.name,
                    "status": "attention",
                    "severity": issue["severity"],
                    "condition": issue["condition"],
                    "reason": issue["reason"],
                    "recommended_action": issue["recommended_action"],
                    "action_type": issue["action_type"],
                    "required_approval": issue["required_approval"],
                    "agent": issue["agent"],
                }
            )
        else:
            items.append(
                {
                    "campaign_id": cid,
                    "campaign_name": c.name,
                    "status": "on_track",
                    "severity": "LOW",
                    "condition": "on_track",
                    "reason": "No issues detected across coverage, outreach, deadline or recruitment checks.",
                    "recommended_action": "No action required.",
                    "action_type": "no_action",
                    "required_approval": False,
                    "agent": None,
                }
            )
    items.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 3))
    return items
