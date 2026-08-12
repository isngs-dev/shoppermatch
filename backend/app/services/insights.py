"""Lightweight, rule-based operational insights (informational only).

Deliberately NOT a trained ML model — these are threshold/heuristic notes derived
from live aggregates so the demo stays technically honest.
"""
from __future__ import annotations


def generate_insights(summary: dict, city_coverage: dict[str, int]) -> list[dict]:
    insights: list[dict] = []

    sent = summary.get("sent", 0)
    opened = summary.get("opened", 0)
    clicked = summary.get("clicked", 0)
    accepted = summary.get("accepted", 0)
    open_rate = summary.get("open_rate", 0.0)
    click_rate = summary.get("click_rate", 0.0)

    if sent and open_rate < 70:
        insights.append(
            {
                "type": "engagement",
                "severity": "warning",
                "title": "Open rate below target",
                "message": f"Email open rate is {open_rate}%, below the 70% target. "
                "Consider adjusting subject lines or send times.",
            }
        )

    if opened and click_rate < 50:
        insights.append(
            {
                "type": "engagement",
                "severity": "warning",
                "title": "Click-through below threshold",
                "message": f"Click-through rate is {click_rate}% of opened invitations, "
                "below the configured 50% threshold.",
            }
        )

    # Coverage gaps: any city with fewer than 2 active shoppers.
    low_cities = sorted([c for c, n in city_coverage.items() if n < 2])
    for city in low_cities[:3]:
        insights.append(
            {
                "type": "coverage",
                "severity": "info",
                "title": f"Low shopper coverage in {city}",
                "message": f"Shopper coverage is low for {city}. "
                "Consider expanding the recruitment radius or recruiting locally.",
            }
        )

    if accepted:
        insights.append(
            {
                "type": "progress",
                "severity": "success",
                "title": "Acceptances recorded",
                "message": f"{accepted} shopper(s) have accepted assignments across active campaigns.",
            }
        )

    if not insights:
        insights.append(
            {
                "type": "progress",
                "severity": "info",
                "title": "All metrics within range",
                "message": "Outreach metrics are within configured thresholds. No action needed.",
            }
        )

    return insights
