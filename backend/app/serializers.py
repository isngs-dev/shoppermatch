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
    IntegrationConfig,
    Shop,
    Shopper,
    SyncLog,
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
        "client_id": str(user.client_id) if user.client_id else None,
        "client_name": user.client.company_name if user.client_id and user.client else None,
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
        "gender": s.gender,
        "age": s.age,
        "pincode": s.pincode,
        "skills": s.skills or [],
        "experience_description": s.experience_description,
        "years_experience": s.years_experience,
        "preferred_distance_km": s.preferred_distance_km,
        "preferred_locations": s.preferred_locations or [],
        "preferred_categories": s.preferred_categories or [],
        "languages": s.languages or [],
        "certifications": s.certifications or [],
        "previous_clients": s.previous_clients or [],
    }


def shop_bonus_out(bonus) -> Optional[dict]:
    if bonus is None:
        return None
    return {
        "id": str(bonus.id),
        "amount": bonus.amount,
        "currency": bonus.currency,
        "note": bonus.note,
        "created_by": bonus.created_by,
        "created_at": iso(bonus.created_at),
        "awarded_shopper_name": bonus.awarded_shopper_name,
        "completed_at": iso(bonus.completed_at),
        "reminder_sent_at": iso(bonus.reminder_sent_at),
    }


def shop_out(shop: Shop, bonus=None) -> dict:
    """`bonus` is an optional pre-fetched ShopBonus (or None) — never lazy-
    loaded here since this runs outside an async context; pass it in from
    callers that already queried it (see routers/campaigns.py, shops.py)."""
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
        "allow_over_selection": shop.allow_over_selection,
        "bonus": shop_bonus_out(bonus),
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


def invitation_row(inv: Invitation, shop_bonus=None) -> dict:
    """Compact row used by the tracking table (relations must be eager-loaded).

    `shop_bonus` is an optional pre-fetched ShopBonus for `inv.shop_id` —
    passed in by callers that separately queried it (see routers/invitations.py,
    campaigns.py), never lazy-loaded here."""
    return {
        "id": str(inv.id),
        "reference": inv.reference,
        "tracking_token_masked": mask_token(inv.tracking_token),
        "shopper_id": str(inv.shopper_id),
        "shopper_name": inv.shopper.name if inv.shopper else None,
        "shopper_email": inv.email,
        "campaign_name": inv.campaign.name if inv.campaign else None,
        "client_name": inv.campaign.client_name if inv.campaign else None,
        "shop_id": str(inv.shop_id),
        "shop_name": inv.shop.shop_name if inv.shop else None,
        "shop_city": inv.shop.city if inv.shop else None,
        "shop_status": inv.shop.status if inv.shop else None,
        "status": inv.status,
        "source": inv.source,
        "sent_at": iso(inv.sent_at),
        "delivered_at": iso(inv.delivered_at),
        "opened_at": iso(inv.opened_at),
        "clicked_at": iso(inv.clicked_at),
        "visited_at": iso(inv.visited_at),
        "responded_at": iso(inv.responded_at),
        "response": inv.response,
        "created_at": iso(inv.created_at),
        "email_delivery": email_job_out(inv.email_job) if inv.email_job else None,
        "automation_id": str(inv.automation_id) if inv.automation_id else None,
        "automation_name": inv.automation.name if inv.automation_id and inv.automation else None,
        "automation_step": inv.automation_step,
        "shop_bonus": shop_bonus_out(shop_bonus),
    }


def invitation_detail(inv: Invitation, shop_bonus=None) -> dict:
    """Full invitation payload including generated URLs, attribution + events."""
    row = invitation_row(inv, shop_bonus=shop_bonus)
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
                # Only claim attribution when the unique tracking link was
                # actually used — never assumed from an email being merely
                # sent or opened (open tracking is a weak, provider-side
                # signal; a real click is the proof).
                "attributed": inv.clicked_at is not None,
                "channel": "ISN_EMAIL",
                "source": inv.source,
                "campaign": inv.campaign.name if inv.campaign else None,
                "invitation_id": inv.reference,
                "tracking_token_masked": mask_token(inv.tracking_token),
                "landing_page": "ShopperMatch.AI",
                "first_click": iso(inv.clicked_at),
                "visited": iso(inv.visited_at),
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


def integration_out(cfg: IntegrationConfig) -> dict:
    """`secret_config` is deliberately never included here — this is the
    only place integration data is turned into an API response."""
    return {
        "id": str(cfg.id),
        "provider": cfg.provider,
        "display_name": cfg.display_name,
        "status": cfg.status,
        "enabled": cfg.enabled,
        "configuration": cfg.configuration or {},
        "has_secrets": bool(cfg.secret_config),
        "last_tested_at": iso(cfg.last_tested_at),
        "last_sync_at": iso(cfg.last_sync_at),
        "last_error": cfg.last_error,
        "created_at": iso(cfg.created_at),
        "updated_at": iso(cfg.updated_at),
    }


def sync_log_out(log: SyncLog) -> dict:
    return {
        "id": str(log.id),
        "provider": log.provider,
        "status": log.status,
        "started_at": iso(log.started_at),
        "completed_at": iso(log.completed_at),
        "campaigns": {"fetched": log.campaigns_fetched, "created": log.campaigns_created, "updated": log.campaigns_updated},
        "shops": {"fetched": log.shops_fetched, "created": log.shops_created, "updated": log.shops_updated},
        "shoppers": {"fetched": log.shoppers_fetched, "created": log.shoppers_created, "updated": log.shoppers_updated},
        "errors": log.errors or [],
        "error_message": log.error_message,
        "created_at": iso(log.created_at),
    }
