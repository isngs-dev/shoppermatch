"""Real outbound phone calls via Twilio Programmable Voice — the one
telephony integration in this app. Uses Twilio's plain REST API directly
over httpx (same "lazy-import httpx, no vendor SDK" pattern as
services/email.py's SendGrid path and services/facebook_oauth.py) rather
than adding the `twilio` Python package as a dependency.

Compliance note (mirrors services/facebook_graph.py's posture): this only
ever dials a shopper's own phone number already on file, using Twilio's
officially documented Voice API and TwiML — no dialer automation, no
spoofing, no scraping. Inert (raise if not configured) until
TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER are set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from ..config import settings


def is_configured() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_phone_number)


def _require_configured() -> None:
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice Call Follow-Up is not configured — set TWILIO_ACCOUNT_SID, "
                "TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER (see .env.example)."
            ),
        )


def _api_base() -> str:
    return f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}"


async def create_call(to_number: str, twiml_url: str, status_callback_url: str) -> str:
    """Places a real outbound call. Returns Twilio's Call SID. `twiml_url` is
    fetched by Twilio once the call connects (routers/voice_calls.py) to get
    the actual conversation TwiML — never generated client-side."""
    import httpx

    _require_configured()
    payload = {
        "To": to_number,
        "From": settings.twilio_phone_number,
        "Url": twiml_url,
        "StatusCallback": status_callback_url,
        "StatusCallbackEvent": "completed",
        # Caps a single call at 5 minutes — a "human to human" conversation
        # that goes on forever is a cost/abuse risk, not a feature.
        "TimeLimit": "300",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{_api_base()}/Calls.json",
            data=payload,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Twilio call failed to start: {res.text[:300]}")
    return res.json()["sid"]


def verify_twilio_signature(url: str, params: dict[str, Any], signature: str | None) -> bool:
    """Twilio's documented webhook signature algorithm: HMAC-SHA1 over the
    full request URL followed by each POST param's key+value (sorted by
    key, no delimiter), keyed by the Auth Token, base64-encoded.
    https://www.twilio.com/docs/usage/webhooks/webhook-security

    Returns True if no auth token is configured at all (demo-friendly
    default, same posture as services/webhooks.py's SendGrid verifier) —
    False only when a token IS configured and verification actually fails."""
    if not settings.twilio_auth_token:
        return True
    if not signature:
        return False
    data = url
    for key in sorted(params.keys()):
        data += key + str(params[key])
    computed = base64.b64encode(
        hmac.new(settings.twilio_auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature)


def twiml_say_gather(message: str, gather_action_url: str, *, hang_up_after: bool = False) -> str:
    """Builds the TwiML for one conversation turn: speak `message`, then
    listen for the shopper's spoken reply (Twilio's own speech-to-text —
    no separate ASR integration needed) and POST it to `gather_action_url`.
    `hang_up_after=True` skips the Gather and ends the call politely."""
    voice = settings.twilio_voice
    say = f'<Say voice="{voice}">{_escape(message)}</Say>'
    if hang_up_after:
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{say}<Hangup/></Response>'
    gather = (
        f'<Gather input="speech" language="en-US" speechTimeout="auto" '
        f'action="{quote(gather_action_url, safe="/:?=&")}" method="POST">{say}</Gather>'
    )
    # If the shopper says nothing at all, Gather times out and Twilio moves
    # past it — fall through to a polite goodbye rather than a dead silence.
    fallback = f'<Say voice="{voice}">We didn\'t catch a response — thanks for your time, goodbye.</Say><Hangup/>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{gather}{fallback}</Response>'


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
