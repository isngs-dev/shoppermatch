"""Reusable {{variable}} post-copy templates rendered from an existing CRM
record — Campaign or Shop, the two entities this app actually has (there is
no generic "product/lead/listing" model here; see models.py). Deliberately a
tiny, dependency-free substitution (str.replace in a loop), not a templating
engine — the variable set is small and fixed per source type.
"""
from __future__ import annotations

from ..models import Campaign, Shop

# What {{variable}} names are available depends on the source record type —
# surfaced to the frontend (GET /api/social/templates/variables) so the
# composer's "insert variable" picker never offers one that won't resolve.
CAMPAIGN_VARIABLES: list[tuple[str, str]] = [
    ("title", "Campaign name"),
    ("description", "Campaign description"),
    ("price", "Compensation (per shop)"),
    ("location", "Client name"),
    ("deadline", "Deadline"),
    ("url", "ShopperMatch campaign link"),
]
SHOP_VARIABLES: list[tuple[str, str]] = [
    ("title", "Shop name"),
    ("description", "Category"),
    ("price", "Compensation"),
    ("location", "City, state"),
    ("deadline", "Visit window"),
    ("url", "ShopperMatch campaign link"),
]

DEFAULT_TEMPLATE = (
    "New opportunity available! 🎯\n"
    "{{title}}\n"
    "{{description}}\n"
    "Compensation: {{price}}\n"
    "Location: {{location}}\n"
    "Learn more: {{url}}\n"
    "#ShopperMatch"
)


def variables_for(source_type: str) -> list[tuple[str, str]]:
    return CAMPAIGN_VARIABLES if source_type == "campaign" else SHOP_VARIABLES


def _fmt_money(amount: int | None, currency: str = "INR") -> str:
    if amount is None:
        return "—"
    return f"{currency} {amount}"


def variables_from_campaign(campaign: Campaign, base_url: str | None = None) -> dict[str, str]:
    return {
        "title": campaign.name,
        "description": campaign.description or "",
        "price": "",  # a campaign spans many shops at different rates — see variables_from_shop for a real figure
        "location": campaign.client_name or "",
        "deadline": campaign.deadline.strftime("%b %d, %Y") if campaign.deadline else "",
        "url": f"{base_url}/client/campaigns/{campaign.id}" if base_url else "",
    }


def variables_from_shop(shop: Shop, campaign: Campaign, base_url: str | None = None) -> dict[str, str]:
    location = ", ".join(p for p in (shop.city, shop.state) if p) or "—"
    visit_window = ""
    if shop.visit_start and shop.visit_end:
        visit_window = f"{shop.visit_start.strftime('%b %d')} – {shop.visit_end.strftime('%b %d, %Y')}"
    return {
        "title": shop.shop_name,
        "description": shop.category or "",
        "price": _fmt_money(shop.compensation, shop.currency),
        "location": location,
        "deadline": visit_window,
        "url": f"{base_url}/client/campaigns/{campaign.id}?tab=shops" if base_url else "",
    }


def render_template(body_template: str, variables: dict[str, str]) -> str:
    rendered = body_template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered
