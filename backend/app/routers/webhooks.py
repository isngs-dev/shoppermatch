"""SendGrid Event Webhook receiver.

Handles provider-side delivery lifecycle events (delivered, bounce, dropped,
deferred, processed, spam report, unsubscribe). Deliberately does NOT handle
"open"/"click" event types from SendGrid: those are disabled at send time
(see services/email.py `_send_via_sendgrid`'s `tracking_settings`) because
ShopperMatch already owns first-party open/click tracking via its own pixel
and `/r/{token}` redirect — accepting both would double-count the same
interaction and (worse) SendGrid's link-rewriting would break the tracked
UUID redirect entirely if ever turned on.

No bearer-token auth here — SendGrid can't send one. Authenticity instead
comes from the payload's `custom_args.invitation_id` matching a real
invitation, plus optional ECDSA signature verification when
SENDGRID_WEBHOOK_VERIFICATION_KEY is configured.
"""
from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import EventType, Invitation
from ..services.tracking import add_event, mark_delivered, now

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

# SendGrid event types we act on. "open"/"click" are intentionally absent —
# see module docstring.
_HANDLED = {"delivered", "bounce", "dropped", "deferred", "processed", "spamreport", "unsubscribe"}


def _verify_signature(payload: bytes, signature: str | None, timestamp: str | None) -> bool:
    """Returns True if verification passes OR is not configured (demo
    default). Returns False only when a key IS configured and verification
    actually fails — that's the only case the caller should reject on."""
    key = settings.sendgrid_webhook_verification_key
    if not key:
        return True
    if not signature or not timestamp:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        public_key = serialization.load_der_public_key(base64.b64decode(key))
        signed_payload = timestamp.encode() + payload
        public_key.verify(
            base64.b64decode(signature),
            signed_payload,
            ec.ECDSA(hashes.SHA256()),
        )
        return True
    except InvalidSignature:
        return False
    except Exception:  # noqa: BLE001 — misconfigured key shouldn't 500 the webhook
        return False


@router.post("/sendgrid")
async def sendgrid_event_webhook(
    request: Request,
    x_twilio_email_event_webhook_signature: str | None = Header(default=None),
    x_twilio_email_event_webhook_timestamp: str | None = Header(default=None),
):
    raw = await request.body()
    if not _verify_signature(raw, x_twilio_email_event_webhook_signature, x_twilio_email_event_webhook_timestamp):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        events = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(events, list):
        events = [events]

    processed = 0
    async with AsyncSessionLocal() as session:
        for evt in events:
            event_type = evt.get("event")
            if event_type not in _HANDLED:
                continue
            invitation_id = evt.get("invitation_id")
            if not invitation_id:
                continue
            try:
                inv_uuid = uuid.UUID(invitation_id)
            except ValueError:
                continue

            stmt = select(Invitation).where(Invitation.id == inv_uuid).options(
                selectinload(Invitation.campaign), selectinload(Invitation.email_job)
            )
            inv = (await session.execute(stmt)).scalar_one_or_none()
            if inv is None:
                continue

            metadata = {"provider": "sendgrid", "sg_event_id": evt.get("sg_event_id"), "raw_event": event_type}

            if event_type == "delivered":
                await mark_delivered(session, inv, metadata)
            elif event_type in ("bounce", "dropped"):
                await add_event(session, inv, EventType.EMAIL_BOUNCED, metadata)
                if inv.email_job is not None:
                    inv.email_job.status = "failed"
                    inv.email_job.last_error = evt.get("reason") or f"SendGrid reported '{event_type}'"
                    inv.email_job.completed_at = now()
            elif event_type == "deferred":
                await add_event(session, inv, EventType.EMAIL_DEFERRED, metadata)
            elif event_type in ("processed", "spamreport", "unsubscribe"):
                await add_event(session, inv, event_type, metadata)

            processed += 1

        await session.commit()

    return {"received": len(events), "processed": processed}
