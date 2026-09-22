"""Real outbound phone calls via Plivo Voice — the one telephony integration
in this app. Uses the official `plivo` SDK (unlike this app's other
integrations, e.g. services/email.py's SendGrid path, which use plain httpx
directly) specifically because Plivo's V3 webhook signature scheme (HMAC-
SHA256 over a nonce + sorted params) is intricate enough that hand-rolling it
from documentation alone is a real correctness risk — the SDK's
validate_v3_signature() is the one part of this file worth a vendor
dependency for.

Compliance note (mirrors services/facebook_graph.py's posture): this only
ever dials a shopper's own phone number already on file, using Plivo's
officially documented Voice API and Plivo XML (PLXML) — no dialer
automation, no spoofing, no scraping. Inert (raise if not configured) until
PLIVO_AUTH_ID/AUTH_TOKEN/PHONE_NUMBER are set.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import HTTPException

from ..config import settings


def is_configured() -> bool:
    return bool(settings.plivo_auth_id and settings.plivo_auth_token and settings.plivo_phone_number)


def _require_configured() -> None:
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice Call Follow-Up is not configured — set PLIVO_AUTH_ID, "
                "PLIVO_AUTH_TOKEN and PLIVO_PHONE_NUMBER (see .env.example)."
            ),
        )


async def create_call(to_number: str, answer_url: str, hangup_url: str) -> str:
    """Places a real outbound call. Returns Plivo's call request UUID.
    `answer_url` is fetched by Plivo once the call connects
    (routers/voice_calls.py) to get the actual conversation PLXML — never
    generated client-side."""
    import plivo

    _require_configured()
    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)
    try:
        result = client.calls.create(
            from_=settings.plivo_phone_number,
            to_=to_number,
            answer_url=answer_url,
            answer_method="POST",
            hangup_url=hangup_url,
            hangup_method="POST",
            # Caps a single call at 5 minutes — a "human to human" conversation
            # that goes on forever is a cost/abuse risk, not a feature.
            time_limit=300,
        )
    except Exception as exc:  # noqa: BLE001 — the SDK raises its own exception types
        raise HTTPException(status_code=502, detail=f"Plivo call failed to start: {exc}") from None
    return result.request_uuid


def verify_plivo_signature(method: str, url: str, nonce: str | None, signature: str | None, params: dict[str, Any]) -> bool:
    """Plivo's documented V3 webhook signature: HMAC-SHA256 over the request
    URL + sorted POST params + the nonce, keyed by the Auth Token,
    base64-encoded. https://www.plivo.com/docs/voice/concepts/signature-validation

    Returns True if no auth token is configured at all (demo-friendly
    default, same posture as services/webhooks.py's SendGrid verifier) —
    False only when a token IS configured and verification actually fails,
    or the request is missing the signature/nonce headers Plivo always sends
    once V3 signing is active."""
    if not settings.plivo_auth_token:
        return True
    if not signature or not nonce:
        return False
    import plivo

    try:
        return bool(
            plivo.utils.validate_v3_signature(method, url, nonce, settings.plivo_auth_token, signature, params)
        )
    except Exception:  # noqa: BLE001 — malformed signature/params must fail closed, not 500
        return False


def plxml_say_gather(message: str, gather_action_url: str, *, hang_up_after: bool = False) -> str:
    """Builds the PLXML for one conversation turn: speak `message`, then
    listen for the shopper's spoken reply (Plivo's own speech-to-text, via
    <GetInput inputType="speech"> — no separate ASR integration needed) and
    POST it to `gather_action_url`. `hang_up_after=True` skips GetInput and
    ends the call politely."""
    voice = settings.plivo_voice
    say = f'<Speak voice="{voice}">{escape(message)}</Speak>'
    if hang_up_after:
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{say}<Hangup/></Response>'
    # url-quote first (preserving the URL's own structural characters), then
    # XML-attribute-escape the result — a `&` surviving url-quoting still
    # needs to become `&amp;` to be valid inside a double-quoted attribute.
    action_url = escape(quote(gather_action_url, safe="/:?=&"), {'"': "&quot;"})
    get_input = (
        f'<GetInput action="{action_url}" method="POST" '
        f'inputType="speech" language="en-US" speechEndTimeout="auto">{say}</GetInput>'
    )
    # If the shopper says nothing at all, GetInput's action URL is never hit
    # and Plivo falls through to whatever follows it in the Response — a
    # polite goodbye rather than dead silence.
    fallback = f'<Speak voice="{voice}">We didn\'t catch a response — thanks for your time, goodbye.</Speak><Hangup/>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{get_input}{fallback}</Response>'
