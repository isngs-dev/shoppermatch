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
