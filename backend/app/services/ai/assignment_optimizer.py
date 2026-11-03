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

from ...models import Campaign, Shop, ShopBonus, Shopper
from ..selection import active_invitation_count, active_shopper_ids
from ..semantic_matching import run_matching
from ..staffing import effective_radius, gap_options


async def optimize_assignments(
    session: AsyncSession,
    campaign: Campaign,
    radius_km: float | None = None,
    shop_radii: dict[str, float] | None = None,
) -> dict:
    """`shop_radii` overrides the campaign-wide radius for individual shops (widening one shop that came up
    short shouldn't also widen every other). A shop's bonus extends how far its candidates may live."""
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    shoppers = (await session.execute(select(Shopper))).scalars().all()
    bonus_by_shop = {
        b.shop_id: b
        for b in (await session.execute(select(ShopBonus).where(ShopBonus.campaign_id == campaign.id))).scalars().all()
    }
    shop_radii = shop_radii or {}

    per_shop_results = []
    eligible_counts: dict[str, int] = {}
    outside_by_shop: dict[str, list[float]] = {}
    base_radius: dict[str, float | None] = {}
    for shop in shops:
        base = shop_radii.get(str(shop.id), radius_km)
        base_radius[str(shop.id)] = base
        bonus = bonus_by_shop.get(shop.id)
        result = run_matching(
            list(shoppers), shop, campaign, radius_km=effective_radius(base, bonus.amount if bonus else None)
        )
        per_shop_results.append((shop, result["recommendations"]))
        eligible_counts[str(shop.id)] = result["eligible_count"]
        outside_by_shop[str(shop.id)] = result["outside_distances"]

    # Hardest-first: fewer eligible candidates means less flexibility later.
    per_shop_results.sort(key=lambda pair: len(pair[1]))

    used_shopper_ids: set[str] = set()
    proposals = []
    unfilled = []
    distances = []

    # A shop that already has people selected only needs the remainder — proposing the full
    # required count would be rejected by the over-selection guard (409) at approval time.
    already_invited = {str(shop.id): {str(i) for i in await active_shopper_ids(session, shop.id)} for shop in shops}
    total_slots = 0

    for shop, candidates in per_shop_results:
        invited_here = already_invited[str(shop.id)]
        slots_needed = max(0, shop.required_shoppers - await active_invitation_count(session, shop.id))
        total_slots += slots_needed
        chosen = []
        for cand in candidates:
            if len(chosen) >= slots_needed:
                break
            if cand["shopper_id"] in used_shopper_ids or cand["shopper_id"] in invited_here:
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
                    "reasons": (cand.get("reasons") or [])[:3],
                }
            )
            if cand["distance_km"] is not None:
                distances.append(cand["distance_km"])

        if len(chosen) < slots_needed:
            missing = slots_needed - len(chosen)
            existing = bonus_by_shop.get(shop.id)
            # Same rule as the AI Recommendations page: widen the radius or add/raise a bonus (each really
            # changes who's eligible), or recruit locally when the nearest shopper is far.
            gap = gap_options(
                shop,
                base_radius=base_radius[str(shop.id)],
                bonus=existing,
                distances=outside_by_shop[str(shop.id)],
                eligible=eligible_counts.get(str(shop.id), 0),
                slots_open=slots_needed,
                shortfall=missing,
            )
            unfilled.append({
                "shop_id": str(shop.id),
                "shop_name": shop.shop_name,
                "unfilled_slots": missing,
                "radius_km": base_radius[str(shop.id)],
                "has_bonus": existing is not None,
                **gap,
                # Why: either the candidate pool ran dry (few/no eligible
                # people for this shop at all) or it was contested (enough
                # eligible people existed, but this campaign's other shops
                # claimed them first in the hardest-first pass).
                "reason": "no eligible candidates" if eligible_counts.get(str(shop.id), 0) <= len(chosen) else "candidates claimed by other shops",
            })

    # Nothing left to fill anywhere means the campaign is fully covered, not 0% covered.
    coverage = round((len(proposals) / total_slots) * 100) if total_slots else 100
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
