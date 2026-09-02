"""Real Facebook Page publishing via the Graph API — the one genuinely-live
external call in Social Media Automation. Only ever called for
target_kind="page" with a connected, real (OAuth) ClientSocialAccount;
target_kind="group" NEVER reaches this module (see models.py::DistributionPost
and the module docstring below on why).

Facebook Groups: Meta deprecated general-purpose Group posting via the API
years ago (the old `publish_to_groups` permission is no longer grantable to
new apps in essentially any case). There is currently no supported Graph API
call this app — or any third-party app — can make to post into a Facebook
Group on a user's behalf. That is why every group-targeted post in this
feature is routed to the manual/approval workflow (see routers/social.py)
instead of this module, unconditionally.
"""
from __future__ import annotations

from typing import Any

from ..config import settings


class FacebookPublishError(Exception):
    """Raised on any Graph API failure — caller (services/social_publisher.py)
    catches this to record a PublishingLog row and decide whether to retry."""

    def __init__(self, message: str, *, is_auth_error: bool = False):
        super().__init__(message)
        self.is_auth_error = is_auth_error


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_api_version}"


async def publish_to_page(page_id: str, page_access_token: str, message: str, image_url: str | None) -> str:
    """Publishes to a Facebook Page's feed. Returns the external post id.

    Uses /{page-id}/photos (caption becomes the post message) when an image
    is attached, otherwise /{page-id}/feed — the two documented Graph API
    endpoints for a Page's own feed content."""
    import httpx

    endpoint = "photos" if image_url else "feed"
    payload: dict[str, Any] = {"access_token": page_access_token}
    if image_url:
        payload["url"] = image_url
        payload["caption"] = message
    else:
        payload["message"] = message

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{_graph_base()}/{page_id}/{endpoint}", data=payload)
    except httpx.TimeoutException as exc:
        raise FacebookPublishError(f"Facebook API timed out: {exc}") from exc
    except httpx.HTTPError as exc:
        raise FacebookPublishError(f"Network error calling Facebook API: {exc}") from exc

    if res.status_code >= 400:
        body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        error = body.get("error", {})
        code = error.get("code")
        # 190 = OAuthException (expired/invalid token), 200-series = missing
        # permission — both mean "reconnect required", not "retry later".
        is_auth_error = code in (190, 200, 10) or error.get("type") == "OAuthException"
        raise FacebookPublishError(
            error.get("message") or res.text[:300] or f"Facebook API error (HTTP {res.status_code})",
            is_auth_error=is_auth_error,
        )

    data = res.json()
    # /photos returns {"id": "<photo_id>", "post_id": "<page_id>_<post_id>"};
    # /feed returns {"id": "<page_id>_<post_id>"} directly.
    return data.get("post_id") or data.get("id") or ""
