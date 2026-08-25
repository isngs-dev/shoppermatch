"""Tenant-isolation helper for the operational modules shared by both
portals (Campaigns/Shops/Shoppers/Recommendations/Outreach/AI).

An admin passes through unconditionally. A client-role user is only ever
allowed to touch a campaign that belongs to their own `client_id` — every
other campaign 404s (never 403, so a client can't even confirm another
tenant's campaign exists).
"""
from __future__ import annotations

from fastapi import HTTPException

from ..models import Campaign, User


def enforce_campaign_access(campaign: Campaign | None, user: User) -> Campaign:
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == "client" and campaign.client_id != user.client_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign
