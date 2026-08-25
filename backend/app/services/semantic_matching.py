"""AI-assisted semantic + structured shopper matching, scoped to one shop
within one campaign.

Two layers combine into a single explainable score:

1. Semantic similarity — a lightweight, dependency-free term-frequency
   cosine-similarity between a normalized campaign/shop requirement text and
   each shopper's normalized profile text. The demo environment has no
   sentence-transformers / pgvector installed, so this keyword-vector
   fallback stands in for a real embedding model (see ``embed`` below) — the
   function boundary is deliberate so a real embedding service can replace
   it later without touching callers.
2. Structured business rules — distance (haversine), category overlap,
   availability, completion history, rating, and (where the schema actually
   has it) client history.

Weights are configurable in ``MATCHING_WEIGHTS`` and the full breakdown is
always returned — nothing about the scoring is hidden from the API response.

Only fields that exist on the Shopper/Shop/Campaign models are used. Fields
the product brief mentions but the schema doesn't have (certifications,
named previous clients, languages) are never fabricated: they contribute a
neutral score and are called out as unavailable in the UI, they are not
invented as false positive/negative signal.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from ..models import Campaign, Shop, Shopper
from .recommendation import haversine_km

# Configurable weights (spec section 9). Sum to 1.0 == 100 points.
MATCHING_WEIGHTS: dict[str, float] = {
    "semantic_similarity": 0.30,
    "distance": 0.20,
    "category_experience": 0.15,
    "availability": 0.15,
    "completion_history": 0.10,
    "rating": 0.05,
    "client_experience": 0.05,
}

MAX_DISTANCE_KM = 60.0  # beyond this, the distance factor contributes 0

STOPWORDS = {
    "the", "a", "an", "and", "or", "in", "of", "for", "to", "with", "on", "is", "are",
    "preferred", "within", "near", "strong", "good", "high", "shoppers", "shopper",
    "mystery", "shopping", "audit", "store",
}


# ------------------------------ text vectors ------------------------------ #
def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def embed(text: str) -> Counter:
    """Term-frequency vector standing in for a real embedding. Swap this
    function out for a sentence-transformers call to upgrade to true
    semantic embeddings without changing any caller."""
    return Counter(_tokenize(text))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ------------------------------ requirement / profile text ------------------------------ #
def build_requirement_text(campaign: Campaign, shop: Shop) -> str:
    parts = [
        campaign.name or "",
        campaign.client_name or "",
        campaign.description or "",
        shop.shop_name or "",
        shop.category or "",
        shop.city or "",
        shop.state or "",
    ]
    return " ".join(p for p in parts if p)


def build_requirement_summary(campaign: Campaign, shop: Shop) -> str:
    category_bit = (
        f"strong {shop.category.lower()} mystery shopping experience"
        if shop.category
        else "relevant category experience"
    )
    loc = ", ".join(p for p in [shop.city, shop.state] if p)
    location_bit = f"in {loc}" if loc else "near the shop location"
    return (
        f"Available shoppers {location_bit} with {category_bit}, strong completion "
        f"history and good ratings, ranked by overall fit for "
        f"{shop.shop_name or 'this shop'}."
    )


def build_shopper_profile_text(shopper: Shopper) -> str:
    parts = [
        shopper.city or "",
        shopper.state or "",
        " ".join(shopper.categories or []),
        shopper.availability_status or "",
        shopper.source or "",
        " ".join(shopper.skills or []),
        shopper.experience_description or "",
        " ".join(shopper.certifications or []),
        " ".join(shopper.previous_clients or []),
        " ".join(shopper.languages or []),
    ]
    return " ".join(p for p in parts if p)


# ------------------------------ factor scoring ------------------------------ #
def _availability_fraction(status: str | None) -> float:
    return {
        "available": 1.0,
        "limited": 0.55,
        "busy": 0.3,
        "unavailable": 0.0,
    }.get((status or "").lower(), 0.5)


def _category_overlap_fraction(shopper: Shopper, shop: Shop) -> float:
    cats = [c.lower() for c in (shopper.categories or [])]
    shop_cat = (shop.category or "").lower()
    if not cats:
        return 0.1
    if shop_cat and shop_cat in cats:
        return 1.0
    shop_tokens = set(_tokenize(shop_cat))
    cat_tokens: set[str] = set()
    for c in cats:
        cat_tokens |= set(_tokenize(c))
    if shop_tokens and cat_tokens and (shop_tokens & cat_tokens):
        return 0.65
    return 0.25


def _client_experience_fraction(shopper: Shopper, campaign: Campaign) -> tuple[float, str | None]:
    """Real previous-client matching (Shopper.previous_clients vs
    Campaign.client_name) — no longer a flat neutral placeholder now that
    the field actually exists. Returns (fraction, matched_client_name)."""
    clients = [c for c in (shopper.previous_clients or []) if c]
    if not clients:
        return 0.3, None  # no history recorded — mild, honest penalty
    campaign_client = (campaign.client_name or "").lower()
    for c in clients:
        cl = c.lower()
        if campaign_client and (campaign_client in cl or cl in campaign_client):
            return 1.0, c
    return 0.5, None  # has prior-client experience, just not with this client


def score_shopper(
    shopper: Shopper, shop: Shop, campaign: Campaign, requirement_vec: Counter
) -> dict:
    # Semantic similarity
    profile_vec = embed(build_shopper_profile_text(shopper))
    sim = _cosine(requirement_vec, profile_vec)

    # Distance
    distance_km = haversine_km(shopper.latitude, shopper.longitude, shop.latitude, shop.longitude)
    distance_known = distance_km is not None
    distance_fraction = max(0.0, 1.0 - distance_km / MAX_DISTANCE_KM) if distance_known else 0.5

    category_fraction = _category_overlap_fraction(shopper, shop)
    availability_fraction = _availability_fraction(shopper.availability_status)
    completion_fraction = max(0.0, min(1.0, shopper.completion_rate or 0.0))
    rating_fraction = max(0.0, min(1.0, (shopper.rating or 0.0) / 5.0))
    client_fraction, matched_client = _client_experience_fraction(shopper, campaign)

    factors = [
        ("semantic_similarity", "Semantic Requirement Match", sim),
        ("distance", "Distance", distance_fraction),
        ("category_experience", "Category Experience", category_fraction),
        ("availability", "Availability", availability_fraction),
        ("completion_history", "Completion History", completion_fraction),
        ("rating", "Rating", rating_fraction),
        ("client_experience", "Previous Client Experience", client_fraction),
    ]

    breakdown: dict[str, dict] = {}
    total = 0.0
    for key, label, fraction in factors:
        max_points = round(MATCHING_WEIGHTS[key] * 100)
        points = round(MATCHING_WEIGHTS[key] * 100 * fraction)
        total += points
        breakdown[key] = {"label": label, "points": points, "max": max_points}

    score = int(round(min(100, total)))
    if score >= 90:
        classification = "TOP_MATCH"
    elif score >= 80:
        classification = "STRONG_MATCH"
    elif score >= 70:
        classification = "POTENTIAL_MATCH"
    else:
        classification = "LOW_MATCH"

    # Reasons — only real, derived facts, never invented specifics.
    reasons: list[str] = []
    if distance_known:
        reasons.append(f"{round(distance_km, 1)} km from {shop.shop_name}")
    else:
        reasons.append("Distance unknown — shopper or shop is missing coordinates")
    if category_fraction >= 0.65 and shopper.categories:
        reasons.append(f"Relevant category experience ({', '.join(shopper.categories)})")
    if shopper.completion_rate:
        reasons.append(f"{round(shopper.completion_rate * 100)}% completion rate")
    if shopper.rating:
        reasons.append(f"{shopper.rating:.1f} rating")
    if shopper.previous_assignments:
        reasons.append(f"{shopper.previous_assignments} previous assignments")
    if matched_client:
        reasons.append(f"Previous {matched_client} experience")
    status = (shopper.availability_status or "").lower()
    reasons.append("Available now" if status == "available" else f"Availability: {shopper.availability_status}")

    # Confidence: how much real signal backs this score, separate from the
    # score itself — a high match_score built on missing distance and zero
    # assignment history is not the same as one built on complete data
    # (spec section 25: "never pretend the AI is certain when the
    # underlying data is weak").
    data_points = sum([
        distance_known,
        shopper.previous_assignments >= 3,
        bool(shopper.rating),
        bool(shopper.completion_rate),
        bool(shopper.previous_clients),
    ])
    if data_points >= 4:
        confidence = "High"
    elif data_points >= 2:
        confidence = "Medium"
    else:
        confidence = "Low"

    return {
        "shopper_id": str(shopper.id),
        "name": shopper.name,
        "match_score": score,
        "classification": classification,
        "confidence": confidence,
        "distance_km": round(distance_km, 1) if distance_known else None,
        "latitude": shopper.latitude,
        "longitude": shopper.longitude,
        "availability": shopper.availability_status,
        "rating": round(shopper.rating, 2) if shopper.rating else None,
        "completion_rate": round(shopper.completion_rate, 3) if shopper.completion_rate is not None else None,
        "previous_assignments": shopper.previous_assignments,
        "previous_client_match": matched_client,
        "categories": shopper.categories or [],
        "city": shopper.city,
        "state": shopper.state,
        "breakdown": breakdown,
        "reasons": reasons,
    }


def run_matching(
    shoppers: list[Shopper],
    shop: Shop,
    campaign: Campaign,
    radius_km: float | None = None,
    requirements: dict | None = None,
) -> dict:
    """Full pipeline: normalize requirement → embed → score every active,
    available candidate → rank. Nothing here is randomly generated — every
    candidate comes from the existing shopper table.

    `requirements` (optional) is the structured output of
    services/ai/requirement_parser.py — when present, its fields become
    additional Stage 1 hard filters (min rating, min completion, required
    categories) applied *before* scoring, on top of the always-on
    active/available/radius filters. This is the "hard filter then
    semantic rank" two-stage pipeline the AI spec calls for."""
    requirement_text = build_requirement_text(campaign, shop)
    requirement_vec = embed(requirement_text)
    requirements = requirements or {}

    min_rating = requirements.get("minimum_rating")
    min_completion = requirements.get("minimum_completion_rate")
    required_categories = [c.lower() for c in requirements.get("categories", [])]

    total_candidates = len(shoppers)
    scored: list[dict] = []
    excluded_inactive = 0
    excluded_unavailable = 0
    excluded_radius = 0
    excluded_requirements = 0

    for s in shoppers:
        if not s.active:
            excluded_inactive += 1
            continue
        if (s.availability_status or "").lower() == "unavailable":
            excluded_unavailable += 1
            continue
        if min_rating is not None and (s.rating or 0) < min_rating:
            excluded_requirements += 1
            continue
        if min_completion is not None and (s.completion_rate or 0) < min_completion:
            excluded_requirements += 1
            continue
        if required_categories:
            shopper_cats = [c.lower() for c in (s.categories or [])]
            if not any(rc in shopper_cats for rc in required_categories):
                excluded_requirements += 1
                continue

        row = score_shopper(s, shop, campaign, requirement_vec)
        if radius_km is not None and row["distance_km"] is not None and row["distance_km"] > radius_km:
            excluded_radius += 1
            continue
        scored.append(row)

    scored.sort(key=lambda r: r["match_score"], reverse=True)
    counts = Counter(r["classification"] for r in scored)

    return {
        "requirement_summary": build_requirement_summary(campaign, shop),
        "total_candidates": total_candidates,
        "eligible_count": len(scored),
        "excluded": {
            "inactive": excluded_inactive,
            "unavailable": excluded_unavailable,
            "outside_radius": excluded_radius,
            "requirements_not_met": excluded_requirements,
        },
        "classification_counts": {
            "top_match": counts.get("TOP_MATCH", 0),
            "strong_match": counts.get("STRONG_MATCH", 0),
            "potential_match": counts.get("POTENTIAL_MATCH", 0),
            "low_match": counts.get("LOW_MATCH", 0),
        },
        "recommendations": scored,
    }
