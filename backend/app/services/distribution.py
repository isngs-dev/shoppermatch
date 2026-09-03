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

from fastapi import HTTPException

from ..config import settings
from ..models import Shop

# Whether JobSlinger and TrustedHerd actually support posting scoped to a
# region is an open question in the source spec ("TO BE DEFINED") — assumed
# yes here (uniformly, alongside every platform) so the feature is
# demonstrable end-to-end; flip this if that assumption turns out to be
# wrong for either platform. A destination only ever actually appears for
# a client if they've "connected" that platform (ClientSocialAccount) —
# this is just the full menu of what CAN be connected.
DESTINATION_TYPES: list[tuple[str, str]] = [
    ("facebook", "Facebook Group"),
    ("instagram", "Instagram"),
    ("linkedin", "LinkedIn"),
    ("twitter", "Twitter / X"),
    ("jobslinger", "JobSlinger"),
    ("trustedherd", "TrustedHerd"),
]
DESTINATION_LABELS: dict[str, str] = dict(DESTINATION_TYPES)


def region_for_shop(shop: Shop) -> str:
    """State first (broadest reasonable "region" granularity with zero new
    data entry), falling back to city, then a catch-all bucket for shops
    missing both — never silently dropped from the matching."""
    return shop.state or shop.city or "Unspecified Region"


def destination_name(destination_type: str, region: str) -> str:
    if destination_type == "facebook":
        return f"{region} Mystery Shoppers — Facebook Group"
    if destination_type == "instagram":
        return f"@{region.lower().replace(' ', '')}mysteryshoppers"
    if destination_type == "linkedin":
        return f"{region} Mystery Shopper Network — LinkedIn Page"
    if destination_type == "twitter":
        return f"@{region.replace(' ', '')}Shoppers"
    if destination_type == "jobslinger":
        return f"JobSlinger — {region}"
    if destination_type == "trustedherd":
        return f"TrustedHerd — {region}"
    return f"{destination_type} — {region}"


def default_account_name(platform: str, client_name: str) -> str:
    label = DESTINATION_LABELS.get(platform, platform)
    return f"{client_name} — {label}"


def regions_for_shops(shops: list[Shop]) -> dict[str, list[Shop]]:
    """Groups a campaign's shops by region — this is the "Determine Shop
    Region" + implicit grouping step from the flow diagram."""
    grouped: dict[str, list[Shop]] = {}
    for shop in shops:
        region = region_for_shop(shop)
        grouped.setdefault(region, []).append(shop)
    return grouped


async def generate_post_image(campaign_name: str, message: str) -> str:
    """The one genuinely-real AI call in this feature: DALL-E generates an
    actual promotional graphic for the post (the "same one-click posting
    automation" from the source doc still applies to the *posting* step —
    this just gives it real creative to post instead of text-only). Returns
    a temporary OpenAI-hosted image URL — the same kind Outreach/Email
    Automation already link out to for assignment/tracking, nothing new
    architecturally.

    Deliberately does NOT ask the model to render the campaign's own body
    copy as in-image text — image models are unreliable at legible text
    rendering, so the caption stays a separate, always-legible layer the
    frontend overlays underneath the image, the way a real social post
    (image + separate caption) actually works."""
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Image generation is not configured (missing OPENAI_API_KEY).")

    prompt = (
        f"A vibrant, professional social media promotional graphic recruiting mystery shoppers for the "
        f'"{campaign_name}" campaign. Theme/mood drawn from: "{message}". Bright, eye-catching, modern retail '
        f"marketing style, no readable text or letters in the image, wide banner composition."
    )
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": settings.openai_image_model, "prompt": prompt, "size": "1024x1024", "n": 1},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Image generation failed: {res.text[:300]}")
    data = res.json()["data"][0]
    url = data.get("url")
    if not url:
        b64 = data.get("b64_json")
        if not b64:
            raise HTTPException(status_code=502, detail="Image generation returned no image")
        url = f"data:image/png;base64,{b64}"
    return url


async def generate_post_image_from_photo(
    campaign_name: str, message: str, photo_bytes: bytes, photo_filename: str, content_type: str | None
) -> str:
    """Same promotional-graphic generation as generate_post_image, but
    starting from a client-supplied photo (OpenAI's image *edit* endpoint,
    not text-to-image) — the client uploads a real shop/product/shopper
    photo and gets back a on-brand graphic built from it, rather than a
    generic AI illustration. gpt-image-1 (this app's configured image
    model) only ever returns b64_json for edits, never a hosted url."""
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Image generation is not configured (missing OPENAI_API_KEY).")

    prompt = (
        f"Turn this photo into a vibrant, professional social media promotional graphic recruiting mystery "
        f'shoppers for the "{campaign_name}" campaign. Theme/mood drawn from: "{message}". Keep the subject of '
        "the original photo recognizable, but make it bright, eye-catching, modern retail marketing style. "
        "No readable text or letters in the image."
    )
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data={"model": settings.openai_image_model, "prompt": prompt, "size": "1024x1024", "n": "1"},
            files={"image": (photo_filename, photo_bytes, content_type or "image/png")},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Image generation failed: {res.text[:300]}")
    data = res.json()["data"][0]
    url = data.get("url")
    if not url:
        b64 = data.get("b64_json")
        if not b64:
            raise HTTPException(status_code=502, detail="Image generation returned no image")
        url = f"data:image/png;base64,{b64}"
    return url
