"""I. AI Fraud / Anomaly Detection.

Rule-based signals computed from real Invitation/InvitationEvent timing and
Shopper location data — never a blanket accusation. Every flagged shopper
gets "Potential Anomaly — Requires Human Review", exactly per spec section 13.
"""
from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Invitation, Shopper

# Roughly the geographic centroid of each city we seed shoppers in — used
# only to flag a shopper whose stored coordinates are wildly inconsistent
# with their stated city (a real data-integrity signal), never to "prove"
# anything about a person.
CITY_CENTROIDS = {
    "Mumbai": (19.0760, 72.8777), "Pune": (18.5204, 73.8567), "Nashik": (19.9975, 73.7898),
    "Thane": (19.2183, 72.9781), "Navi Mumbai": (19.0330, 73.0297), "Bangalore": (12.9716, 77.5946),
    "Delhi": (28.7041, 77.1025), "Gurgaon": (28.4595, 77.0266), "Hyderabad": (17.3850, 78.4867),
    "Chennai": (13.0827, 80.2707), "Ahmedabad": (23.0225, 72.5714), "Kolkata": (22.5726, 88.3639),
    "Jaipur": (26.9124, 75.7873), "Indore": (22.7196, 75.8577), "Nagpur": (21.1458, 79.0882),
}


def _km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def detect_anomalies(session: AsyncSession) -> list[dict]:
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    invs = (
        await session.execute(select(Invitation).where(Invitation.shopper_id.isnot(None)))
    ).scalars().all()
    by_shopper: dict = {}
    for inv in invs:
        by_shopper.setdefault(inv.shopper_id, []).append(inv)

    flags: list[dict] = []
    for s in shoppers:
        signals: list[str] = []
        score = 0

        # Location inconsistency: stored coordinates far from the stated city.
        if s.city in CITY_CENTROIDS and s.latitude is not None and s.longitude is not None:
            clat, clon = CITY_CENTROIDS[s.city]
            dist = _km(s.latitude, s.longitude, clat, clon)
            if dist > 60:
                signals.append(f"Location inconsistency — coordinates are {round(dist)} km from {s.city}'s city center")
                score += 30

        shopper_invs = by_shopper.get(s.id, [])
        responded = [i for i in shopper_invs if i.responded_at and i.clicked_at]

        # Unusually fast completion: accept/decline within seconds of the click.
        fast = [i for i in responded if (i.responded_at - i.clicked_at).total_seconds() < 5]
        if len(fast) >= 2:
            signals.append(f"Unusually fast response on {len(fast)} invitation(s) (<5s after clicking)")
            score += 25

        # Repeated response-timing pattern (proxy for "identical response
        # behaviour" without an extra per-invitation event-metadata query —
        # keeps this whole scan at a fixed, small number of queries).
        if len(responded) >= 5:
            timestamps = sorted(i.responded_at for i in responded)
            gaps = [(timestamps[i + 1] - timestamps[i]).total_seconds() for i in range(len(timestamps) - 1)]
            identical_gaps = Counter(round(g) for g in gaps if g > 0)
            if identical_gaps and max(identical_gaps.values()) >= 3:
                signals.append("Similar response-timing pattern detected across multiple invitations")
                score += 20

        # Abnormally perfect accept rate at high volume — bot-like behaviour.
        total_responded = sum(1 for i in shopper_invs if i.response)
        accepted = sum(1 for i in shopper_invs if i.response == "accepted")
        if total_responded >= 10 and accepted == total_responded:
            signals.append(f"100% acceptance across {total_responded} invitations — unusually consistent")
            score += 15

        if signals and score >= 25:
            flags.append(
                {
                    "shopper_id": str(s.id),
                    "shopper_name": s.name,
                    "risk_score": min(100, score),
                    "signals": signals,
                    "status": "Potential Anomaly — Requires Human Review",
                }
            )

    flags.sort(key=lambda f: f["risk_score"], reverse=True)
    return flags
