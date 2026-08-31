"""Region-Targeted Social Media Posting — conceptual/demo feature.

Existing behavior (per the product doc this implements): the same campaign
creative gets posted to every owned social page/portal equally, with no
targeting. This adds a region-matching step in front of that: each shop's
region (derived from its existing city/state — no new field needed) is
matched to a small set of regional destinations, and posting only reaches
the destinations that actually cover a shop in this campaign.

There is no real Meta Graph API / JobSlinger / TrustedHerd integration here
— those would each need their own OAuth app + credentials this project
doesn't have. Matches this app's existing demo-mode pattern (see
services/integrations/sassie.py): the matching logic is real and runs
against real shop data, but the final "post" is simulated and durably
recorded (DistributionPost), never silently claimed as a live connection.
"""
from __future__ import annotations

from ..models import Shop

# Whether JobSlinger and TrustedHerd actually support posting scoped to a
# region is an open question in the source spec ("TO BE DEFINED") — assumed
# yes here (uniformly, alongside Facebook) so the feature is demonstrable
# end-to-end; flip this if that assumption turns out to be wrong for either
# platform.
DESTINATION_TYPES: list[tuple[str, str]] = [
    ("facebook", "Facebook Group"),
    ("jobslinger", "JobSlinger"),
    ("trustedherd", "TrustedHerd"),
]


def region_for_shop(shop: Shop) -> str:
    """State first (broadest reasonable "region" granularity with zero new
    data entry), falling back to city, then a catch-all bucket for shops
    missing both — never silently dropped from the matching."""
    return shop.state or shop.city or "Unspecified Region"


def destination_name(destination_type: str, region: str) -> str:
    if destination_type == "facebook":
        return f"{region} Mystery Shoppers — Facebook Group"
    if destination_type == "jobslinger":
        return f"JobSlinger — {region}"
    if destination_type == "trustedherd":
        return f"TrustedHerd — {region}"
    return f"{destination_type} — {region}"


def regions_for_shops(shops: list[Shop]) -> dict[str, list[Shop]]:
    """Groups a campaign's shops by region — this is the "Determine Shop
    Region" + implicit grouping step from the flow diagram."""
    grouped: dict[str, list[Shop]] = {}
    for shop in shops:
        region = region_for_shop(shop)
        grouped.setdefault(region, []).append(shop)
    return grouped
