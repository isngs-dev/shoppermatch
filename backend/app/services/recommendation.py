"""Rule-based, explainable shopper→shop matching (MVP scope).

This is intentionally transparent scoring — *not* a trained ML model — matching
the MVP requirement to be technically honest. Each factor contributes a bounded
number of points and the breakdown is returned so the UI can explain the score.
"""
from __future__ import annotations

import math

from ..models import Shop, Shopper

# Max points per factor (sum = 96, mirroring the scope's worked example).
WEIGHTS = {
    "distance": 25,
    "category": 20,
    "availability": 20,
    "completion": 18,
    "rating": 13,
}

MAX_DISTANCE_KM = 60.0  # beyond this, the distance factor contributes 0


def haversine_km(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _availability_fraction(status: str) -> float:
    return {
        "available": 1.0,
        "limited": 0.55,
        "busy": 0.3,
        "unavailable": 0.0,
    }.get((status or "").lower(), 0.5)


def score_shopper(shopper: Shopper, shop: Shop) -> dict:
    distance_km = haversine_km(
        shopper.latitude, shopper.longitude, shop.latitude, shop.longitude
    )

    # --- distance factor ---
    if distance_km is None:
        distance_fraction = 0.6  # unknown → neutral-ish
    else:
        distance_fraction = max(0.0, 1.0 - distance_km / MAX_DISTANCE_KM)

    # --- category experience factor ---
    cats = [c.lower() for c in (shopper.categories or [])]
    shop_cat = (shop.category or "").lower()
    if shop_cat and shop_cat in cats:
        category_fraction = 1.0
    elif cats:
        category_fraction = 0.35  # some experience, different category
    else:
        category_fraction = 0.1

    availability_fraction = _availability_fraction(shopper.availability_status)
    completion_fraction = max(0.0, min(1.0, shopper.completion_rate or 0.0))
    rating_fraction = max(0.0, min(1.0, (shopper.rating or 0.0) / 5.0))

    factors = [
        ("Distance", "distance", distance_fraction),
        ("Category Experience", "category", category_fraction),
        ("Availability", "availability", availability_fraction),
        ("Completion Rate", "completion", completion_fraction),
        ("Rating", "rating", rating_fraction),
    ]

    breakdown = []
    total = 0.0
    for label, key, fraction in factors:
        points = round(WEIGHTS[key] * fraction)
        total += points
        breakdown.append(
            {"label": label, "points": points, "max": WEIGHTS[key], "fraction": round(fraction, 3)}
        )

    score = int(round(total))
    confidence = "High" if score >= 80 else "Medium" if score >= 60 else "Low"

    return {
        "shopper_id": str(shopper.id),
        "shopper_name": shopper.name,
        "shopper_code": shopper.shopper_code,
        "match_score": score,
        "confidence": confidence,
        "distance_km": round(distance_km, 1) if distance_km is not None else None,
        "breakdown": breakdown,
        "availability_status": shopper.availability_status,
        "previous_assignments": shopper.previous_assignments,
        "rating": round(shopper.rating, 2),
        "completion_rate": round(shopper.completion_rate, 3),
        "city": shopper.city,
    }


def recommend_for_shop(shoppers: list[Shopper], shop: Shop, limit: int = 10) -> list[dict]:
    scored = [score_shopper(s, shop) for s in shoppers if s.active]
    scored.sort(key=lambda r: r["match_score"], reverse=True)
    return scored[:limit]
