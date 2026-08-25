"""D. AI Assignment Optimization.

Greedy best-fit: for each shop (best-covered-first, i.e. hardest slot first
by lowest eligible-candidate count), assign its top-scoring eligible
shopper who hasn't already been proposed for another shop in this same
optimization pass. Never persists anything — returns a proposal the admin
must explicitly approve (spec section 8: "Never silently assign shoppers").
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Campaign, Shop, Shopper
from ..semantic_matching import run_matching


async def optimize_assignments(session: AsyncSession, campaign: Campaign) -> dict:
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    shoppers = (await session.execute(select(Shopper))).scalars().all()

    per_shop_results = []
    for shop in shops:
        result = run_matching(list(shoppers), shop, campaign)
        per_shop_results.append((shop, result["recommendations"]))

    # Hardest-first: fewer eligible candidates means less flexibility later.
    per_shop_results.sort(key=lambda pair: len(pair[1]))

    used_shopper_ids: set[str] = set()
    proposals = []
    unfilled = []
    distances = []

    for shop, candidates in per_shop_results:
        slots_needed = shop.required_shoppers
        chosen = []
        for cand in candidates:
            if len(chosen) >= slots_needed:
                break
            if cand["shopper_id"] in used_shopper_ids:
                continue
            chosen.append(cand)
            used_shopper_ids.add(cand["shopper_id"])

        for cand in chosen:
            proposals.append(
                {
                    "shop_id": str(shop.id),
                    "shop_name": shop.shop_name,
                    "shopper_id": cand["shopper_id"],
                    "shopper_name": cand["name"],
                    "match_score": cand["match_score"],
                    "distance_km": cand["distance_km"],
                }
            )
            if cand["distance_km"] is not None:
                distances.append(cand["distance_km"])

        if len(chosen) < slots_needed:
            unfilled.append({"shop_id": str(shop.id), "shop_name": shop.shop_name, "unfilled_slots": slots_needed - len(chosen)})

    total_slots = sum(s.required_shoppers for s in shops) or 1
    filled_slots = len(proposals)
    coverage = round((filled_slots / total_slots) * 100)
    requirement_satisfaction = round(((len(shops) - len(unfilled)) / len(shops)) * 100) if shops else 100
    avg_distance = round(sum(distances) / len(distances), 1) if distances else None

    return {
        "campaign_id": str(campaign.id),
        "proposals": proposals,
        "unfilled": unfilled,
        "summary": {
            "coverage": coverage,
            "requirement_satisfaction": requirement_satisfaction,
            "average_distance_km": avg_distance,
        },
    }
