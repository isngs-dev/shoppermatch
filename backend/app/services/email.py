"""Email rendering + delivery.

Providers are selected via the ``EMAIL_PROVIDER`` env var:

* ``mock``     – the default. Nothing is actually sent; the rendered message is
                 returned so the UI can preview it. Perfect for the demo.
* ``sendgrid`` – real delivery via SendGrid's HTTP API, used only when
                 ``SENDGRID_API_KEY`` is configured.
* ``smtp``     – direct SMTP AUTH login (e.g. Gmail app password).
* ``direct``   – self-hosted delivery straight to the recipient's MX server.
* ``emailjs``  – real delivery via EmailJS's REST API (emailjs.com). EmailJS's
                 Gmail service authenticates over OAuth rather than SMTP AUTH,
                 so it isn't subject to the "app password rejected" blocks.

The rendered HTML contains the two things that make attribution work:
  1. A ``View Assignment`` button that points at the click-tracking URL
     (``/r/{token}`` with UTM params), and
  2. A 1x1 transparent tracking pixel at the bottom (``/track/open/{token}.gif``).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import EmailComposition, Invitation
from ..serializers import pixel_url, tracking_url


def _fmt_money(amount: int | None, currency: str) -> str:
    if amount is None:
        return ""
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "")
    return f"{symbol}{amount:,}"


def _fmt_window(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "See assignment details"
    if start.year == end.year:
        return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def build_click_url(inv: Invitation) -> str:
    """Click-tracking URL embedded in the CTA, carrying UTM parameters."""
    base = tracking_url(inv.tracking_token)
    params = []
    for key, val in (
        ("utm_source", inv.utm_source),
        ("utm_medium", inv.utm_medium),
        ("utm_campaign", inv.utm_campaign),
        ("utm_content", inv.utm_content),
    ):
        if val:
            params.append(f"{key}={val}")
    return f"{base}?{'&'.join(params)}" if params else base


# --------------------------- Composer: template variables --------------------------- #
# Tokens the email composer's "Insert Variable" dropdown offers. Every value
# is derived straight from the campaign/shop/shopper rows already loaded on
# the invitation — nothing here is invented.
VARIABLE_TOKENS = [
    "shopper_name",
    "campaign_name",
    "client_name",
    "shop_name",
    "location",
    "compensation",
    "deadline",
    "assignment_link",
    "invitation_id",
]

_MINIMAL_HTML_TAG_STRIP = re.compile(r"<\s*(script|iframe|object|embed)\b.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_ON_ATTR_STRIP = re.compile(r'\son\w+\s*=\s*(".*?"|\'.*?\'|[^\s>]+)', re.IGNORECASE)
_JS_HREF_STRIP = re.compile(r'(href\s*=\s*["\'])\s*javascript:[^"\']*(["\'])', re.IGNORECASE)


def sanitize_html(html: str) -> str:
    """Best-effort defensive stripping of script-executing constructs from
    admin-authored HTML. Email clients don't run JavaScript anyway, but this
    also protects the in-app preview iframe. Not a substitute for a real
    sanitizer library (none is installed in this project) — a full HTML
    parser (e.g. bleach) would be more robust for untrusted multi-tenant
    input."""
    html = _MINIMAL_HTML_TAG_STRIP.sub("", html or "")
    html = _ON_ATTR_STRIP.sub("", html)
    html = _JS_HREF_STRIP.sub(r"\1#\2", html)
    return html


def build_variable_context(inv: Invitation, preview: bool = False) -> dict[str, str]:
    shopper = inv.shopper
    shop = inv.shop
    campaign = inv.campaign
    first_name = shopper.name.split(" ")[0] if shopper else "there"
    comp = _fmt_money(shop.compensation if shop else None, shop.currency if shop else "INR")
    location = ", ".join([p for p in [shop.city if shop else None, shop.state if shop else None] if p])
    return {
        "shopper_name": first_name,
        "campaign_name": campaign.name if campaign else "",
        "client_name": campaign.client_name if campaign else "",
        "shop_name": shop.shop_name if shop else "",
        "location": location or "—",
        "compensation": comp or "—",
        "deadline": _fmt_window(shop.visit_start if shop else None, shop.visit_end if shop else None),
        "assignment_link": build_click_url(inv),
        "invitation_id": inv.reference,
    }


def render_variables(template: str, context: dict[str, str]) -> str:
    """Replace every ``{{token}}`` in `template` with its context value.
    Unknown tokens are left as-is rather than silently dropped, so a typo is
    visible in the preview instead of producing blank text."""
    def repl(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        return context.get(key, match.group(0))

    return re.sub(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", repl, template or "")


def render_composed_email(inv: Invitation, subject_template: str, html_template: str, preview: bool = False) -> dict[str, Any]:
    """Render an admin-composed subject/body: variable substitution, then
    auto-append the tracking pixel if the admin's HTML doesn't already
    contain one (spec: pixel insertion must not be a manual step)."""
    context = build_variable_context(inv, preview=preview)
    subject = render_variables(subject_template, context) or inv.subject
    html = render_variables(html_template, context)
    html = sanitize_html(html)

    pixel = pixel_url(inv.tracking_token) + ("?preview=1" if preview else "")
    if "track/open/" not in html:
        html = f'{html}\n<img src="{pixel}" width="1" height="1" style="display:block;border:0;" alt="" />'

    # Plain-text fallback: strip tags crudely — good enough for the text/plain part.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    return {
        "from": f"{settings.email_from_name} <{settings.email_from_address}>",
        "to": inv.email,
        "subject": subject,
        "html": html,
        "text": text,
        "click_url": context["assignment_link"],
        "pixel_url": pixel,
        "invitation_id": str(inv.id),
    }


def assignment_button_html() -> str:
    """Email-safe HTML snippet the composer's "Insert Assignment Button"
    action inserts. The href is a template token so it survives editing;
    it's substituted for the real tracking URL at render time."""
    return (
        '<a href="{{assignment_link}}" '
        'style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;'
        'font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
        "VIEW ASSIGNMENT</a>"
    )


def render_email(inv: Invitation, preview: bool = False) -> dict[str, Any]:
    """Render subject + HTML + text for an invitation. Relations must be loaded.

    When ``preview=True`` the tracking pixel points at ``?preview=1`` so that
    viewing the email inside the admin UI does NOT record a real email-open
    (that stays reserved for the explicit 'Simulate Email Open' action / a real
    recipient opening the message).
    """
    shopper = inv.shopper
    shop = inv.shop
    campaign = inv.campaign

    first_name = shopper.name.split(" ")[0] if shopper else "there"
    comp = _fmt_money(shop.compensation if shop else None, shop.currency if shop else "INR")
    window = _fmt_window(shop.visit_start if shop else None, shop.visit_end if shop else None)
    location = ", ".join([p for p in [shop.city if shop else None, shop.state if shop else None] if p])
    click = build_click_url(inv)
    pixel = pixel_url(inv.tracking_token) + ("?preview=1" if preview else "")
    from_display = f"{settings.email_from_name} <{settings.email_from_address}>"

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{inv.subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
        <tr>
          <td style="background:#0f172a;padding:22px 32px;">
            <div style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:-0.2px;">ShopperMatch<span style="color:#6366f1;">.AI</span></div>
            <div style="color:#94a3b8;font-size:12px;margin-top:2px;">Delivered through ISN Shopper Recruitment</div>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 32px 8px 32px;">
            <div style="display:inline-block;background:#eef2ff;color:#4f46e5;font-size:12px;font-weight:600;padding:5px 10px;border-radius:999px;">Mystery Shopping Invitation</div>
            <h1 style="font-size:22px;color:#0f172a;margin:16px 0 4px 0;">Hi {first_name}, you've been selected 🎯</h1>
            <p style="color:#475569;font-size:15px;line-height:1.6;margin:8px 0 0 0;">
              Based on your profile and location, our matching engine selected you for a mystery shopping opportunity. Review the details below and let us know if you can take it.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;">
              <tr>
                <td style="padding:18px 20px;">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="padding:6px 0;color:#64748b;font-size:13px;width:40%;">Campaign</td>
                      <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{campaign.name if campaign else ''}</td>
                    </tr>
                    <tr>
                      <td style="padding:6px 0;color:#64748b;font-size:13px;">Shop</td>
                      <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{shop.shop_name if shop else ''}</td>
                    </tr>
                    <tr>
                      <td style="padding:6px 0;color:#64748b;font-size:13px;">Location</td>
                      <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{location}</td>
                    </tr>
                    <tr>
                      <td style="padding:6px 0;color:#64748b;font-size:13px;">Compensation</td>
                      <td style="padding:6px 0;color:#16a34a;font-size:14px;font-weight:700;">{comp}</td>
                    </tr>
                    <tr>
                      <td style="padding:6px 0;color:#64748b;font-size:13px;">Visit Window</td>
                      <td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{window}</td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:8px 32px 28px 32px;">
            <a href="{click}" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">View Assignment →</a>
            <p style="color:#94a3b8;font-size:12px;margin:16px 0 0 0;">Invitation reference: {inv.reference}</p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:18px 32px;">
            <p style="color:#94a3b8;font-size:12px;line-height:1.6;margin:0;">
              You received this because you are an active shopper in the ShopperMatch.AI / ISN network. This is a synthetic demo message.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
  <!-- Email-open tracking pixel (no JavaScript required) -->
  <img src="{pixel}" width="1" height="1" style="display:block;border:0;" alt="" />
</body>
</html>"""

    text = (
        f"Hi {first_name},\n\n"
        f"You've been selected for a mystery shopping opportunity via ISN.\n\n"
        f"Campaign: {campaign.name if campaign else ''}\n"
        f"Shop: {shop.shop_name if shop else ''}\n"
        f"Location: {location}\n"
        f"Compensation: {comp}\n"
        f"Visit Window: {window}\n\n"
        f"View & respond to your assignment:\n{click}\n\n"
        f"Invitation reference: {inv.reference}\n"
    )

    return {
        "from": from_display,
        "to": inv.email,
        "subject": inv.subject,
        "html": html,
        "text": text,
        "click_url": click,
        "pixel_url": pixel,
        "invitation_id": str(inv.id),
    }


async def load_composition(session: AsyncSession, invitation_id) -> EmailComposition | None:
    return (
        await session.execute(
            select(EmailComposition).where(EmailComposition.invitation_id == invitation_id)
        )
    ).scalar_one_or_none()


async def render_invitation_email(session: AsyncSession, inv: Invitation, preview: bool = False) -> dict[str, Any]:
    """Single entry point used by preview, send, and the outbox worker: uses
    the admin's composed subject/body when one was saved for this invitation,
    otherwise falls back to the default generated template."""
    composition = await load_composition(session, inv.id)
    if composition is not None:
        return render_composed_email(inv, composition.subject_template, composition.html_template, preview=preview)
    return render_email(inv, preview=preview)


# --------------------------- Providers --------------------------- #
async def send_email(message: dict[str, Any]) -> dict[str, Any]:
    """Deliver (or mock) an email. Returns a provider result dict."""
    provider = settings.email_provider.lower()

    if provider == "sendgrid" and settings.sendgrid_api_key:
        return await _send_via_sendgrid(message)
    if provider == "smtp":
        return await _send_via_smtp(message)
    if provider == "direct":
        return await _send_via_direct_mta(message)
    if provider == "emailjs" and settings.emailjs_service_id:
        return await _send_via_emailjs(message)

    # Default: mock provider — do not actually send.
    return {
        "provider": "mock",
        "delivered": True,
        "detail": "Rendered by mock provider (no external email sent).",
    }


async def _send_via_smtp(message: dict[str, Any]) -> dict[str, Any]:
    """Send an HTML + plain-text message through STARTTLS SMTP off the event loop."""
    if not settings.smtp_username or not settings.smtp_password:
        return {"provider": "smtp", "delivered": False, "detail": "SMTP_USERNAME and SMTP_PASSWORD must be configured for the smtp provider."}
    if settings.email_from_address != settings.smtp_username:
        return {"provider": "smtp", "delivered": False, "detail": "For Gmail SMTP, EMAIL_FROM_ADDRESS must exactly match SMTP_USERNAME."}

    import asyncio
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr

    def deliver() -> None:
        email = EmailMessage()
        email["From"] = formataddr((settings.email_from_name, settings.email_from_address))
        email["To"] = message["to"]
        email["Subject"] = message["subject"]
        email.set_content(message["text"])
        email.add_alternative(message["html"], subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            client.ehlo()
            client.starttls()
            client.ehlo()
            client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(email, from_addr=settings.email_from_address, to_addrs=[message["to"]])

    try:
        await asyncio.to_thread(deliver)
        return {"provider": "smtp", "delivered": True, "detail": "Sent via SMTP."}
    except Exception as exc:  # noqa: BLE001
        return {"provider": "smtp", "delivered": False, "detail": f"SMTP error: {exc}"}


async def _send_via_direct_mta(message: dict[str, Any]) -> dict[str, Any]:
    """Self-hosted delivery: resolve the recipient's MX records and hand the
    message directly to their mail server — the same mechanism SendGrid (or
    any mail provider) uses on the final hop, without going through one.

    No third-party API and no login required, but also none of the sending
    reputation (SPF/DKIM/rDNS, warmed-up IP) that real providers maintain —
    acceptance at the SMTP level does not guarantee inbox placement.
    """
    import asyncio
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr, make_msgid

    import dns.resolver

    to_addr = message["to"]
    domain = to_addr.rsplit("@", 1)[-1]

    def resolve_mx() -> list[str]:
        answers = dns.resolver.resolve(domain, "MX")
        ranked = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in ranked]

    def deliver() -> str:
        hosts = resolve_mx()
        if not hosts:
            raise RuntimeError(f"No MX records found for {domain}")

        email = EmailMessage()
        email["From"] = formataddr((settings.email_from_name, settings.email_from_address))
        email["To"] = to_addr
        email["Subject"] = message["subject"]
        email["Message-ID"] = make_msgid(domain=domain.split(".")[-2] + "." + domain.split(".")[-1] if "." in domain else domain)
        email.set_content(message["text"])
        email.add_alternative(message["html"], subtype="html")

        last_error: Exception | None = None
        for host in hosts:
            try:
                with smtplib.SMTP(host, 25, timeout=15) as client:
                    client.ehlo()
                    if client.has_extn("starttls"):
                        client.starttls()
                        client.ehlo()
                    client.send_message(
                        email,
                        from_addr=settings.email_from_address,
                        to_addrs=[to_addr],
                    )
                return host
            except Exception as exc:  # noqa: BLE001 — try the next MX host
                last_error = exc
                continue
        raise last_error or RuntimeError("All MX hosts failed")

    try:
        host = await asyncio.to_thread(deliver)
        return {
            "provider": "direct",
            "delivered": True,
            "detail": f"Delivered directly to {host} (MX for {domain}). Acceptance at SMTP level does not guarantee inbox placement.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"provider": "direct", "delivered": False, "detail": f"Direct MTA error: {exc}"}


async def _send_via_emailjs(message: dict[str, Any]) -> dict[str, Any]:
    """Deliver via EmailJS's REST API. EmailJS's Gmail service authenticates
    with Google over OAuth (not raw SMTP AUTH), so it isn't subject to the
    "app password rejected" / IP-authorization blocks SMTP hits.

    The EmailJS template must define fields matching the keys sent below
    (to_email, subject, message_html, message_text) — map them to the
    template's "To email"/body fields in the EmailJS dashboard.
    """
    import httpx  # imported lazily so the demo never needs it

    payload = {
        "service_id": settings.emailjs_service_id,
        "template_id": settings.emailjs_template_id,
        "user_id": settings.emailjs_public_key,
        "template_params": {
            "to_email": message["to"],
            "from_name": settings.email_from_name,
            "subject": message["subject"],
            "message_html": message["html"],
            "message_text": message["text"],
        },
    }
    if settings.emailjs_private_key:
        payload["accessToken"] = settings.emailjs_private_key

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.emailjs.com/api/v1.0/email/send",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        return {
            "provider": "emailjs",
            "delivered": resp.status_code == 200,
            "status_code": resp.status_code,
            "detail": "Sent via EmailJS" if resp.status_code == 200 else resp.text[:300],
        }
    except Exception as exc:  # noqa: BLE001 — demo resilience
        return {"provider": "emailjs", "delivered": False, "detail": f"EmailJS error: {exc}"}


async def _send_via_sendgrid(message: dict[str, Any]) -> dict[str, Any]:
    import httpx  # imported lazily so the demo never needs it

    payload = {
        "personalizations": [{"to": [{"email": message["to"]}]}],
        "from": {
            "email": settings.email_from_address,
            "name": settings.email_from_name,
        },
        "subject": message["subject"],
        "content": [
            {"type": "text/plain", "value": message["text"]},
            {"type": "text/html", "value": message["html"]},
        ],
        # Disable SendGrid's own click/open tracking: it would rewrite our
        # /r/{token} link and pixel URL through its own redirector, breaking
        # first-party attribution and double-counting opens/clicks against
        # the SendGrid Event Webhook handler below.
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }
    if message.get("invitation_id"):
        # Echoed back verbatim on every Event Webhook callback so
        # /api/webhooks/sendgrid can correlate a delivery/bounce event to the
        # right invitation without exposing the tracking token to SendGrid.
        payload["custom_args"] = {"invitation_id": message["invitation_id"]}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
            )
        return {
            "provider": "sendgrid",
            "delivered": resp.status_code in (200, 202),
            "status_code": resp.status_code,
            "detail": "Sent via SendGrid" if resp.status_code in (200, 202) else resp.text[:300],
        }
    except Exception as exc:  # noqa: BLE001 — demo resilience
        return {"provider": "sendgrid", "delivered": False, "detail": f"SendGrid error: {exc}"}
