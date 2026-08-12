"""Pure functions that convert ORM objects into JSON-safe dictionaries.

Centralising serialization keeps public payloads free of raw DB ids, guarantees
UUID/datetime formatting is consistent, and masks the tracking token in admin
views so the full unguessable value is never leaked to the UI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .config import settings
from .models import (
    AuditLog,
    Campaign,
    Invitation,
    InvitationEvent,
    EmailJob,
    Shop,
    Shopper,
    User,
)


def iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to UTC ISO-8601 with a trailing 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def mask_token(token: Any) -> str:
    """Show only the last 4 characters of the tracking token, e.g. ``••••9abc``."""
    s = str(token)
    tail = s.replace("-", "")[-4:]
    return f"••••{tail}"


# ---- URL builders (public, unguessable, token-based) ---- #
def tracking_url(token: Any) -> str:
    return f"{settings.public_base_url}/r/{token}"


def pixel_url(token: Any) -> str:
    return f"{settings.public_base_url}/track/open/{token}.gif"


def shopper_url(token: Any) -> str:
    return f"{settings.public_base_url}/shop/{token}"


def utm_query(inv: Invitation) -> str:
    parts = []
    for key, val in (
        ("utm_source", inv.utm_source),
        ("utm_medium", inv.utm_medium),
        ("utm_campaign", inv.utm_campaign),
        ("utm_content", inv.utm_content),
    ):
        if val:
            parts.append(f"{key}={val}")
    return "&".join(parts)


# --------------------------------------------------------------------------- #
def user_out(user: User) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
    }


def shopper_out(s: Shopper) -> dict:
    return {
        "id": str(s.id),
        "shopper_code": s.shopper_code,
        "name": s.name,
        "email": s.email,
        "phone": s.phone,
        "city": s.city,
        "state": s.state,
        "zip_code": s.zip_code,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "categories": s.categories or [],
        "availability_status": s.availability_status,
        "source": s.source,
        "rating": round(s.rating, 2),
        "completion_rate": round(s.completion_rate, 3),
        "previous_assignments": s.previous_assignments,
        "active": s.active,
        "created_at": iso(s.created_at),
    }


def shop_out(shop: Shop) -> dict:
    return {
        "id": str(shop.id),
        "campaign_id": str(shop.campaign_id),
        "shop_name": shop.shop_name,
        "address": shop.address,
        "city": shop.city,
        "state": shop.state,
        "latitude": shop.latitude,
        "longitude": shop.longitude,
        "required_shoppers": shop.required_shoppers,
        "compensation": shop.compensation,
        "currency": shop.currency,
        "category": shop.category,
        "visit_start": iso(shop.visit_start),
        "visit_end": iso(shop.visit_end),
        "status": shop.status,
    }


def campaign_out(c: Campaign, shops: Optional[list[Shop]] = None) -> dict:
    data = {
        "id": str(c.id),
        "name": c.name,
        "client_name": c.client_name,
        "description": c.description,
        "status": c.status,
        "total_shops": c.total_shops,
        "completed_shops": c.completed_shops,
        "remaining_shops": c.remaining_shops,
        "created_at": iso(c.created_at),
        "deadline": iso(c.deadline),
    }
    if shops is not None:
        data["shops"] = [shop_out(s) for s in shops]
    return data


def event_out(e: InvitationEvent) -> dict:
    return {
        "id": str(e.id),
        "invitation_id": str(e.invitation_id),
        "event_type": e.event_type,
        "event_timestamp": iso(e.event_timestamp),
        "metadata": e.event_metadata or {},
    }


def invitation_row(inv: Invitation) -> dict:
    """Compact row used by the tracking table (relations must be eager-loaded)."""
    return {
        "id": str(inv.id),
        "reference": inv.reference,
        "tracking_token_masked": mask_token(inv.tracking_token),
        "shopper_name": inv.shopper.name if inv.shopper else None,
        "shopper_email": inv.email,
        "campaign_name": inv.campaign.name if inv.campaign else None,
        "shop_name": inv.shop.shop_name if inv.shop else None,
        "status": inv.status,
        "source": inv.source,
        "sent_at": iso(inv.sent_at),
        "delivered_at": iso(inv.delivered_at),
        "opened_at": iso(inv.opened_at),
        "clicked_at": iso(inv.clicked_at),
        "responded_at": iso(inv.responded_at),
        "response": inv.response,
        "created_at": iso(inv.created_at),
        "email_delivery": email_job_out(inv.email_job) if inv.email_job else None,
    }


def invitation_detail(inv: Invitation) -> dict:
    """Full invitation payload including generated URLs, attribution + events."""
    row = invitation_row(inv)
    row.update(
        {
            "campaign_id": str(inv.campaign_id),
            "shop_id": str(inv.shop_id),
            "shopper_id": str(inv.shopper_id),
            "subject": inv.subject,
            "utm": {
                "utm_source": inv.utm_source,
                "utm_medium": inv.utm_medium,
                "utm_campaign": inv.utm_campaign,
                "utm_content": inv.utm_content,
            },
            "urls": {
                "tracking_url": tracking_url(inv.tracking_token),
                "pixel_url": pixel_url(inv.tracking_token),
                "shopper_url": shopper_url(inv.tracking_token),
            },
            "attribution": {
                "attributed": True,
                "source": inv.source,
                "campaign": inv.campaign.name if inv.campaign else None,
                "invitation_id": inv.reference,
                "tracking_token_masked": mask_token(inv.tracking_token),
                "landing_page": "ShopperMatch.AI",
                "first_click": iso(inv.clicked_at),
                "response": inv.response,
            },
            "events": [event_out(e) for e in inv.events],
        }
    )
    return row


def email_job_out(job: EmailJob) -> dict:
    """Safe operator-facing status of an internal outbox job."""
    return {
        "id": str(job.id),
        "provider": job.provider,
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error,
        "queued_at": iso(job.queued_at),
        "attempted_at": iso(job.attempted_at),
        "completed_at": iso(job.completed_at),
        "next_attempt_at": iso(job.next_attempt_at),
    }


def public_invitation(inv: Invitation) -> dict:
    """Payload for the public shopper landing page — no internal ids, no full token."""
    shop = inv.shop
    campaign = inv.campaign
    return {
        "reference": inv.reference,
        "tracking_token_masked": mask_token(inv.tracking_token),
        "status": inv.status,
        "response": inv.response,
        "responded_at": iso(inv.responded_at),
        "source": inv.source,
        "delivered_through": "ISN",
        "shopper_first_name": (inv.shopper.name.split(" ")[0] if inv.shopper else "there"),
        "campaign": {
            "name": campaign.name if campaign else None,
            "client_name": campaign.client_name if campaign else None,
            "deadline": iso(campaign.deadline) if campaign else None,
        },
        "shop": {
            "shop_name": shop.shop_name if shop else None,
            "city": shop.city if shop else None,
            "state": shop.state if shop else None,
            "address": shop.address if shop else None,
            "compensation": shop.compensation if shop else None,
            "currency": shop.currency if shop else "INR",
            "visit_start": iso(shop.visit_start) if shop else None,
            "visit_end": iso(shop.visit_end) if shop else None,
            "category": shop.category if shop else None,
        },
    }


def audit_out(a: AuditLog) -> dict:
    return {
        "id": str(a.id),
        "actor": a.actor,
        "action": a.action,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "summary": a.summary,
        "created_at": iso(a.created_at),
        "meta": a.meta or {},
    }
