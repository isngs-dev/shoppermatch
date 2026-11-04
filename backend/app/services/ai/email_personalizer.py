"""E. AI Email Personalization.

Builds a subject/body pre-filled with a personalization sentence drawn
directly from the selected shopper's own real profile fields
(experience_description, previous_clients, city) plus real campaign/shop
data — reusing the exact same {{variable}} substitution the Outreach
composer already renders with (services/email.py), so "Generate with AI"
produces something the admin can review/edit in the same box before
sending, never sends on its own (spec section 10/31).
"""
from __future__ import annotations

from ...models import Campaign, Shop, Shopper


def _personalization_sentence(shopper: Shopper, campaign: Campaign, shop: Shop) -> str:
    bits: list[str] = []
    if shopper.experience_description:
        # Use the shopper's own recorded experience verbatim — never invent one.
        bits.append(shopper.experience_description)
    else:
        cats = ", ".join(shopper.categories or []) or "your profile"
        bits.append(f"Based on your experience in {cats}, this assignment could be a strong fit.")

    if shopper.previous_clients and campaign.client_name in shopper.previous_clients:
        bits.append(f"You've worked with {campaign.client_name} before, which is a great match for this campaign.")

    return " ".join(bits)


def generate_personalized_email(shopper: Shopper, campaign: Campaign, shop: Shop) -> dict:
    first_name = shopper.name.split(" ")[0] if shopper.name else "there"
    subject = f"New Mystery Shopping Opportunity — {campaign.client_name} {shop.city or ''}".strip()
    personalization = _personalization_sentence(shopper, campaign, shop)

    body = (
        f"<p>Hi {first_name},</p>\n"
        f"<p>{personalization}</p>\n"
        "<p>Campaign: {{campaign_name}}<br/>Shop: {{shop_name}}<br/>Location: {{location}}<br/>"
        "Compensation: {{compensation}}<br/>Deadline: {{deadline}}</p>\n"
        '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
        'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
        "VIEW ASSIGNMENT</a></p>\n"
        "<p>Thank you,<br/>ISN Shopper Recruitment Team</p>"
    )
    return {"subject": subject, "body": body, "personalization_used": personalization}


# --------------------------------------------------------------------------- #
# Autopilot: a real model writes each shopper's opening paragraph.
# --------------------------------------------------------------------------- #
async def ai_intro(shopper: Shopper, campaign: Campaign, shop: Shop, bonus_amount: int | None = None) -> str | None:
    """A short, personal opening for one shopper, written by the configured OpenAI chat model from that
    shopper's own recorded profile and the real campaign/shop facts (never invented ones). Returns None when no
    key is configured or the call fails, so the caller falls back to the rule-based sentence above."""
    import httpx

    from ...config import settings

    if not settings.openai_api_key:
        return None
    facts = {
        "shopper_first_name": (shopper.name or "").split(" ")[0] or "there",
        "shopper_city": shopper.city,
        "shopper_experience": shopper.experience_description,
        "shopper_categories": ", ".join(shopper.categories or []) or None,
        "shopper_previous_clients": ", ".join(shopper.previous_clients or []) or None,
        "shopper_previous_assignments": shopper.previous_assignments,
        "campaign": campaign.name,
        "client": campaign.client_name,
        "shop": shop.shop_name,
        "shop_city": shop.city,
        "category": shop.category,
        "pay": f"{shop.currency} {shop.compensation}" if shop.compensation else None,
        "extra_bonus": f"{shop.currency} {bonus_amount}" if bonus_amount else None,
    }
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v)
    prompt = (
        "Write the opening paragraph (2 sentences, max 55 words) of an email inviting a mystery shopper to a "
        "specific assignment. Be warm and specific to this person: reference something from their own profile "
        "that genuinely fits this assignment. Use ONLY the facts below — never invent experience, numbers, "
        "dates or promises. If an extra bonus is listed, mention it once. No greeting, no sign-off, no markdown, "
        "no HTML. Plain text only.\n\nFacts:\n" + lines
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_chat_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.6,
                    "max_tokens": 140,
                },
            )
        if res.status_code >= 400:
            return None
        text = (res.json()["choices"][0]["message"]["content"] or "").strip().strip('"')
        return text or None
    except Exception:  # noqa: BLE001 - personalization is optional; never block a send on it
        return None


def build_autopilot_email(shopper: Shopper, campaign: Campaign, shop: Shop, intro: str, bonus_amount: int | None) -> dict:
    """Subject + HTML for an autopilot send. Uses the same {{variables}} the composer renders (campaign, shop,
    deadline, tracked assignment link), plus the bonus line when the shop has one."""
    from html import escape

    first_name = escape((shopper.name or "").split(" ")[0] or "there")
    subject = f"New Mystery Shopping Opportunity — {campaign.client_name} {shop.city or ''}".strip()
    bonus_line = (
        f"<p><strong>Bonus:</strong> {escape(shop.currency or 'USD')} {bonus_amount} on top of the standard pay.</p>\n"
        if bonus_amount
        else ""
    )
    body = (
        f"<p>Hi {first_name},</p>\n"
        f"<p>{escape(intro)}</p>\n"
        "<p>Campaign: {{campaign_name}}<br/>Shop: {{shop_name}}<br/>Location: {{location}}<br/>"
        "Compensation: {{compensation}}<br/>Deadline: {{deadline}}</p>\n"
        f"{bonus_line}"
        '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
        'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
        "VIEW ASSIGNMENT</a></p>\n"
        "<p>Thank you,<br/>ISN Shopper Recruitment Team</p>"
    )
    return {"subject": subject, "html": body}
