"""F. AI Acceptance Probability.

A statistical estimate — not a trained model — built from the shopper's own
real invitation history (Invitation.response), lightly smoothed against the
platform-wide base rate so a single early response doesn't swing to 0%/100%.
Explicitly refuses to guess when there isn't enough history, per spec:
"If there is insufficient historical data, show 'Insufficient historical
data' rather than inventing a probability."
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Invitation, Shopper

MIN_HISTORY_FOR_INDIVIDUAL = 3


async def _platform_base_rate(session: AsyncSession) -> float:
    row = (
        await session.execute(
            select(
                func.count(Invitation.id).filter(Invitation.response.isnot(None)),
                func.count(Invitation.id).filter(Invitation.response == "accepted"),
            )
        )
    ).one()
    total, accepted = row
    return (accepted / total) if total else 0.5


async def predict_acceptance(session: AsyncSession, shopper: Shopper, distance_km: float | None) -> dict:
    row = (
        await session.execute(
            select(
                func.count(Invitation.id).filter(Invitation.response.isnot(None)),
                func.count(Invitation.id).filter(Invitation.response == "accepted"),
            ).where(Invitation.shopper_id == shopper.id)
        )
    ).one()
    total, accepted = row
    total = total or 0
    accepted = accepted or 0

    if total < MIN_HISTORY_FOR_INDIVIDUAL:
        return {
            "shopper_id": str(shopper.id),
            "probability": None,
            "label": "Insufficient historical data",
            "responses_on_record": total,
            "factors": [],
        }

    base_rate = await _platform_base_rate(session)
    # Bayesian smoothing toward the platform base rate — 2 "virtual" prior
    # responses at the base rate, so a shopper with exactly 3 responses
    # isn't reported as a hard 100%/0%.
    probability = (accepted + 2 * base_rate) / (total + 2)

    factors: list[str] = []
    if shopper.rating and shopper.rating >= 4.5:
        factors.append(f"High rating ({shopper.rating:.1f})")
    if shopper.completion_rate and shopper.completion_rate >= 0.9:
        factors.append(f"Strong completion history ({round(shopper.completion_rate * 100)}%)")
    if distance_km is not None and distance_km <= 10:
        factors.append(f"Nearby location ({distance_km:.1f} km)")
    if shopper.availability_status == "available":
        factors.append("High availability")
    if accepted:
        factors.append(f"Accepted {accepted} of {total} previous invitations")
    if shopper.previous_assignments and shopper.previous_assignments >= 10:
        factors.append(f"{shopper.previous_assignments} previous assignments")

    return {
        "shopper_id": str(shopper.id),
        "probability": round(probability * 100),
        "label": "AI Estimate",
        "responses_on_record": total,
        "factors": factors,
    }
