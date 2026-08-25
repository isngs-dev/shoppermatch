"""O. AI Next-Best-Action.

Derived from the same real signals notifications.py already surfaces
(coverage, opened-not-accepted invitations, completion) but framed as
actionable recommendations rather than a raw event feed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import Campaign, Invitation, Shop
from ...routers.campaigns import status_bucket


async def get_next_best_actions(session: AsyncSession, limit: int = 10) -> list[dict]:
    campaigns = (
        await session.execute(select(Campaign).options(selectinload(Campaign.shops)))
    ).scalars().all()

    actions: list[dict] = []
    for c in campaigns:
        bucket = status_bucket(c.status)
        if bucket not in ("active", "upcoming"):
            continue

        invs = (
            await session.execute(select(Invitation).where(Invitation.campaign_id == c.id))
        ).scalars().all()

        shops_needing = c.total_shops - (c.completed_shops or 0)
        opened_not_accepted = sum(1 for i in invs if i.opened_at and not i.response)

        if bucket == "active" and shops_needing > 0 and shops_needing >= max(1, round((c.total_shops or 1) * 0.4)):
            actions.append(
                {
                    "campaign_id": str(c.id),
                    "campaign_name": c.name,
                    "severity": "high",
                    "message": f"{shops_needing} shops still require shoppers.",
                    "recommended_action": "Find additional eligible shoppers.",
                    "action_type": "find_shoppers",
                }
            )
        elif opened_not_accepted >= 2:
            actions.append(
                {
                    "campaign_id": str(c.id),
                    "campaign_name": c.name,
                    "severity": "medium",
                    "message": f"{opened_not_accepted} invitations were opened but not accepted.",
                    "recommended_action": "Send a personalized follow-up.",
                    "action_type": "follow_up",
                }
            )
        elif c.total_shops and (c.completed_shops or 0) / c.total_shops >= 0.9:
            actions.append(
                {
                    "campaign_id": str(c.id),
                    "campaign_name": c.name,
                    "severity": "low",
                    "message": f"Campaign is {round((c.completed_shops or 0) / c.total_shops * 100)}% complete.",
                    "recommended_action": "No action required.",
                    "action_type": "none",
                }
            )

    order = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda a: order.get(a["severity"], 3))
    return actions[:limit]
