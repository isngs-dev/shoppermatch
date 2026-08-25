"""Phase 11 — AI Outreach Prioritization.

Ranks already-scored candidates (the output of services/semantic_matching's
run_matching) by *who should be contacted first*, not just who scores
highest. Combines three real signals:

  * match_score        — from semantic_matching.score_shopper (0-100)
  * acceptance_probability — from acceptance_predictor.predict_acceptance,
    when the shopper has enough history; otherwise treated as unknown and
    the weight is redistributed onto match_score rather than guessed.
  * urgency             — how close the campaign deadline is (0..1), so a
    campaign closing in two days pulls high-fit-but-not-certain candidates
    up the queue over waiting for a "sure thing" that may respond slowly.

Never invents an acceptance number — mirrors acceptance_predictor's own
"Insufficient historical data" honesty.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Campaign, Shopper
from .acceptance_predictor import predict_acceptance

HIGH_THRESHOLD = 75
MEDIUM_THRESHOLD = 55


def _urgency(deadline: datetime | None) -> float:
    if deadline is None:
        return 0.3  # unknown deadline — mild, neutral urgency
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
    now = datetime.now(timezone.utc)
    days_left = (deadline - now).total_seconds() / 86400
    if days_left <= 0:
        return 1.0
    if days_left >= 30:
        return 0.1
    return max(0.1, min(1.0, 1.0 - (days_left / 30)))


async def prioritize_outreach(
    session: AsyncSession, campaign: Campaign, recommendations: list[dict]
) -> list[dict]:
    urgency = _urgency(campaign.deadline)
    ranked: list[dict] = []

    for r in recommendations:
        shopper = await session.get(Shopper, uuid.UUID(r["shopper_id"]))
        if shopper is None:
            continue
        pred = await predict_acceptance(session, shopper, r.get("distance_km"))
        prob = pred["probability"]

        if prob is not None:
            priority_score = round(0.5 * r["match_score"] + 0.35 * prob + 0.15 * urgency * 100)
        else:
            priority_score = round(0.7 * r["match_score"] + 0.3 * urgency * 100)
        priority_score = max(0, min(100, priority_score))

        if priority_score >= HIGH_THRESHOLD:
            tier = "HIGH"
        elif priority_score >= MEDIUM_THRESHOLD:
            tier = "MEDIUM"
        else:
            tier = "LOW"

        ranked.append(
            {
                "shopper_id": r["shopper_id"],
                "name": r["name"],
                "match_score": r["match_score"],
                "acceptance_probability": prob,
                "acceptance_label": pred["label"],
                "priority_score": priority_score,
                "priority_tier": tier,
                "distance_km": r.get("distance_km"),
                "availability": r.get("availability"),
            }
        )

    ranked.sort(key=lambda x: x["priority_score"], reverse=True)
    return ranked
