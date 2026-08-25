"""G. AI Campaign Success Prediction (also powers sections 12/27/28 —
active-campaign health, completed-campaign performance, upcoming-campaign
readiness). One function, three presentations of the same real data."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Campaign, Invitation, Shop, Shopper
from ..semantic_matching import run_matching


async def campaign_health(session: AsyncSession, campaign: Campaign) -> dict:
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    shoppers = (await session.execute(select(Shopper))).scalars().all()

    # Shop coverage: how many required shopper slots are filled.
    total_required = sum(s.required_shoppers for s in shops) or 1
    total_completed = campaign.completed_shops or 0
    shop_coverage = min(100, round((total_completed / (campaign.total_shops or 1)) * 100))

    # Eligible shoppers + candidate quality: run the real matching engine
    # against every shop, exactly as the AI Recommendations tab does.
    eligible_fractions = []
    quality_scores = []
    risks: list[str] = []
    low_coverage_shops = []
    for shop in shops:
        result = run_matching(list(shoppers), shop, campaign)
        eligible_fractions.append(result["eligible_count"] / max(1, len(shoppers)))
        top3 = result["recommendations"][:3]
        if top3:
            quality_scores.append(sum(r["match_score"] for r in top3) / len(top3))
        strong_or_top = result["classification_counts"]["top_match"] + result["classification_counts"]["strong_match"]
        if strong_or_top < shop.required_shoppers:
            low_coverage_shops.append(shop)

    eligible_pct = round((sum(eligible_fractions) / len(eligible_fractions)) * 100) if eligible_fractions else 0
    candidate_quality = round(sum(quality_scores) / len(quality_scores)) if quality_scores else 0

    # Expected completion: blend historical acceptance rate for this
    # campaign's invitations with shop coverage already achieved.
    row = (
        await session.execute(
            select(Invitation.response, Invitation.sent_at).where(Invitation.campaign_id == campaign.id)
        )
    ).all()
    sent = sum(1 for _, sent_at in row if sent_at is not None)
    accepted = sum(1 for resp, _ in row if resp == "accepted")
    acceptance_rate = (accepted / sent * 100) if sent else None
    expected_completion = round((shop_coverage + (acceptance_rate if acceptance_rate is not None else eligible_pct)) / 2)

    readiness = round(shop_coverage * 0.30 + eligible_pct * 0.25 + candidate_quality * 0.25 + expected_completion * 0.20)

    if low_coverage_shops:
        names = ", ".join(s.shop_name for s in low_coverage_shops[:3])
        city_counts: dict[str, int] = {}
        for s in low_coverage_shops:
            if s.city:
                city_counts[s.city] = city_counts.get(s.city, 0) + 1
        worst_city = max(city_counts, key=city_counts.get) if city_counts else None
        if worst_city:
            risks.append(
                f"{worst_city} currently has insufficient eligible shoppers for {city_counts[worst_city]} shop(s) "
                f"and may delay campaign completion."
            )
        else:
            risks.append(f"{names} currently have insufficient top/strong-match candidates.")

    return {
        "campaign_id": str(campaign.id),
        "readiness": max(0, min(100, readiness)),
        "breakdown": {
            "shop_coverage": shop_coverage,
            "eligible_shoppers": eligible_pct,
            "candidate_quality": candidate_quality,
            "expected_completion": expected_completion,
        },
        "acceptance_rate": round(acceptance_rate) if acceptance_rate is not None else None,
        "risks": risks,
        "low_coverage_shops": [s.shop_name for s in low_coverage_shops],
    }


async def performance_summary(session: AsyncSession, campaign: Campaign) -> dict:
    """For completed campaigns: real completion/response/rating stats +
    a templated (not invented) natural-language summary."""
    invs = (
        await session.execute(select(Invitation).where(Invitation.campaign_id == campaign.id))
    ).scalars().all()
    sent = sum(1 for i in invs if i.sent_at)
    accepted = sum(1 for i in invs if i.response == "accepted")
    declined = sum(1 for i in invs if i.response == "declined")
    responded = accepted + declined
    response_rate = round((responded / sent) * 100) if sent else 0
    completion_rate = round(((campaign.completed_shops or 0) / (campaign.total_shops or 1)) * 100)

    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    by_city: dict[str, list[int]] = {}
    for inv in invs:
        shop = next((s for s in shops if s.id == inv.shop_id), None)
        if shop and shop.city and inv.response:
            by_city.setdefault(shop.city, []).append(1 if inv.response == "accepted" else 0)
    city_rates = {c: round(sum(v) / len(v) * 100) for c, v in by_city.items() if v}

    sentence = f"Campaign completion was {completion_rate}%."
    if len(city_rates) >= 2:
        best = max(city_rates, key=city_rates.get)
        worst = min(city_rates, key=city_rates.get)
        if best != worst and city_rates[best] != city_rates[worst]:
            sentence += f" Acceptance was strongest in {best} ({city_rates[best]}%) and lower in {worst} ({city_rates[worst]}%)."

    return {
        "completion_rate": completion_rate,
        "response_rate": response_rate,
        "accepted": accepted,
        "declined": declined,
        "city_acceptance_rates": city_rates,
        "summary": sentence,
    }
