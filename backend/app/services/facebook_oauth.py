"""Real Meta OAuth for Facebook Pages — the only platform with a genuine
API integration in this feature (see models.py::ClientSocialAccount and
the module docstring on services/distribution.py for why every other
platform stays simulated).

Flow (standard OAuth "authorization code" grant, Meta's currently documented
version — see https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow):

  1. GET /api/social/facebook/connect (authenticated) builds the Meta
     authorize URL and returns it — the frontend does a full-page redirect
     there, never an embedded iframe/webview (Meta blocks Login in webviews).
  2. Meta redirects the user's browser back to
     GET /api/social/facebook/callback?code=...&state=... — a PUBLIC endpoint,
     since this is Meta's own redirect, not an API call this app controls
     headers for. This app's auth is Bearer-token only (no cookies), so the
     callback can't carry an Authorization header; instead `state` is a
     signed, expiring token (sign_state/verify_state below) that identifies
     which client initiated the connection, using the same `secret_key`
     every session/reset token in this app is already signed with.
  3. The callback exchanges `code` for a short-lived user token, upgrades it
     to a long-lived one, and lists the user's Facebook Pages
     (GET /me/accounts) — Meta returns a page-scoped access token per page
     directly in that response (already effectively long-lived once the
     parent user token is), so no separate page-token exchange is needed.
  4. The pages list is held in a short-lived server-side cache (in-process,
     TTL — see _PENDING below) and the browser is redirected to the
     frontend's page-picker; POST /api/social/facebook/select-page finalizes
     the one the client picked into a real ClientSocialAccount row.

Required permissions (Meta App Review must approve these before this works
in production — see the class-level docstring on why "inert until
configured" is this app's standard posture for any unconfigured integration):
  pages_show_list, pages_read_engagement, pages_manage_posts

NOTE on scale: `_PENDING` is an in-process dict, fine for this single-process
deployment. A multi-instance production deployment would need a shared store
(Redis, or a DB table) instead — the pending-connection step is the only
piece of this flow that assumes a single process.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from ..config import settings

FACEBOOK_OAUTH_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts"
_STATE_TTL_SECONDS = 600  # 10 minutes to complete the Meta redirect round-trip
_PENDING_TTL_SECONDS = 600
_PENDING: dict[str, dict[str, Any]] = {}


def is_configured() -> bool:
    return bool(settings.facebook_app_id and settings.facebook_app_secret and settings.facebook_redirect_uri)


def _require_configured() -> None:
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Facebook integration is not configured — set FACEBOOK_APP_ID, "
                "FACEBOOK_APP_SECRET and FACEBOOK_REDIRECT_URI (see .env.example)."
            ),
        )


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_api_version}"


# --------------------------------------------------------------------------- #
# Signed `state` — same HMAC-over-payload pattern as this app already trusts
# for its own auth (see security.py), reused here rather than adding a new
# dependency (e.g. itsdangerous) for one call site.
# --------------------------------------------------------------------------- #
def sign_state(client_id: str) -> str:
    nonce = secrets.token_urlsafe(12)
    expires_at = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"{client_id}:{nonce}:{expires_at}"
    sig = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode("utf-8")).decode("utf-8")


def verify_state(state: str) -> str:
    """Returns the client_id encoded in `state`, or raises HTTPException."""
    try:
        decoded = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        client_id, nonce, expires_at, sig = decoded.split(":")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Facebook OAuth state")
    payload = f"{client_id}:{nonce}:{expires_at}"
    expected = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=400, detail="Invalid Facebook OAuth state")
    if int(expires_at) < time.time():
        raise HTTPException(status_code=400, detail="Facebook OAuth state expired — please try connecting again")
    return client_id


def build_authorize_url(client_id: str) -> str:
    _require_configured()
    params = {
        "client_id": settings.facebook_app_id,
        "redirect_uri": settings.facebook_redirect_uri,
        "state": sign_state(client_id),
        "scope": FACEBOOK_OAUTH_SCOPES,
        "response_type": "code",
    }
    return f"https://www.facebook.com/{settings.facebook_graph_api_version}/dialog/oauth?{urlencode(params)}"


async def exchange_code_for_pages(code: str) -> list[dict[str, Any]]:
    """Exchanges the authorization code for a long-lived user token, then
    lists the user's Facebook Pages with their page-scoped access tokens.
    Returns [{"id", "name", "access_token"}, ...] — never persisted here,
    only handed to the short-lived pending cache by the caller."""
    import httpx

    _require_configured()
    async with httpx.AsyncClient(timeout=30) as client:
        token_res = await client.get(
            f"{_graph_base()}/oauth/access_token",
            params={
                "client_id": settings.facebook_app_id,
                "client_secret": settings.facebook_app_secret,
                "redirect_uri": settings.facebook_redirect_uri,
                "code": code,
            },
        )
        if token_res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Facebook token exchange failed: {token_res.text[:300]}")
        short_lived_token = token_res.json().get("access_token")
        if not short_lived_token:
            raise HTTPException(status_code=502, detail="Facebook did not return an access token")

        # Exchange for a long-lived user token (~60 days) before deriving
        # page tokens, so the resulting page tokens outlive a short session.
        long_res = await client.get(
            f"{_graph_base()}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.facebook_app_id,
                "client_secret": settings.facebook_app_secret,
                "fb_exchange_token": short_lived_token,
            },
        )
        if long_res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Facebook long-lived token exchange failed: {long_res.text[:300]}")
        long_lived_token = long_res.json().get("access_token", short_lived_token)

        pages_res = await client.get(
            f"{_graph_base()}/me/accounts",
            params={"access_token": long_lived_token, "fields": "id,name,access_token,category"},
        )
        if pages_res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Failed to list Facebook Pages: {pages_res.text[:300]}")
        return pages_res.json().get("data", [])


def stash_pending_pages(client_id: str, pages: list[dict[str, Any]]) -> str:
    pending_id = secrets.token_urlsafe(24)
    _PENDING[pending_id] = {"client_id": client_id, "pages": pages, "expires_at": time.time() + _PENDING_TTL_SECONDS}
    _prune_pending()
    return pending_id


def get_pending_pages(pending_id: str, client_id: str) -> list[dict[str, Any]]:
    entry = _PENDING.get(pending_id)
    if entry is None or entry["expires_at"] < time.time():
        _PENDING.pop(pending_id, None)
        raise HTTPException(status_code=404, detail="This connection attempt has expired — try connecting again.")
    if entry["client_id"] != client_id:
        raise HTTPException(status_code=403, detail="This connection attempt belongs to a different account.")
    return entry["pages"]


def pop_pending_page(pending_id: str, client_id: str, page_id: str) -> dict[str, Any]:
    pages = get_pending_pages(pending_id, client_id)
    page = next((p for p in pages if p.get("id") == page_id), None)
    if page is None:
        raise HTTPException(status_code=404, detail="That Page wasn't in the list from your Facebook account.")
    _PENDING.pop(pending_id, None)
    return page


def _prune_pending() -> None:
    now = time.time()
    expired = [k for k, v in _PENDING.items() if v["expires_at"] < now]
    for k in expired:
        _PENDING.pop(k, None)


async def validate_page_token(page_access_token: str) -> bool:
    """Lightweight liveness check used by the background validator
    (services/social_publisher.py) — a revoked/expired token fails this
    with a 190 OAuthException from Meta."""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{_graph_base()}/me", params={"access_token": page_access_token})
    return res.status_code < 400
