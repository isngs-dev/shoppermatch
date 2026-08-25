"""AI-assisted email template drafting for the Email Templates page.

Same approach as the rest of this project's "AI" features (see
email_personalizer.py, requirement_parser.py): local, deterministic,
rule/template-based composition — never a call to an external LLM provider
(none is configured; see config.py's AI_* settings). Given a short free-text
goal and a tone, assembles a subject + HTML body using the same
`{{variable}}` tokens the rest of the app already renders
(services/email.py::render_variables), so the draft is immediately usable
and editable — never sent on its own.
"""
from __future__ import annotations

import re

_OPENERS = {
    "professional": "We have a mystery shopping opportunity that matches your profile.",
    "friendly": "Hope you're doing well! We've got a great mystery shopping opportunity for you.",
    "urgent": "Spots are filling up fast — we need a shopper for this opportunity soon.",
}

_SIGNOFFS = {
    "professional": "Thank you,<br/>ShopperMatch.AI Team",
    "friendly": "Thanks so much,<br/>ShopperMatch.AI Team",
    "urgent": "Please respond promptly,<br/>ShopperMatch.AI Team",
}

_SUBJECT_PREFIX = {
    "professional": "Mystery Shopping Opportunity",
    "friendly": "A New Opportunity For You",
    "urgent": "Urgent: Mystery Shopper Needed",
}


def _clean_goal(goal: str) -> str:
    goal = re.sub(r"\s+", " ", (goal or "")).strip()
    return goal


def generate_template_draft(goal: str, tone: str = "professional") -> dict:
    """Returns {name, subject, html_body} — never invents data about a real
    campaign/shop/shopper; only the standard {{tokens}} are used so it's
    correct regardless of who it's eventually sent to."""
    tone = tone if tone in _OPENERS else "professional"
    goal_clean = _clean_goal(goal)

    intro = _OPENERS[tone]
    if goal_clean:
        intro = f"{intro[:-1]} — {goal_clean[0].lower()}{goal_clean[1:]}" if goal_clean[0].isupper() else f"{intro[:-1]} — {goal_clean}"

    name = (goal_clean[:60].strip() or "AI Generated Template").rstrip(".")
    name = name[0].upper() + name[1:] if name else "AI Generated Template"

    subject = f"{_SUBJECT_PREFIX[tone]} — {{{{shop_name}}}}"

    html_body = (
        f"<p>Hi {{{{shopper_name}}}},</p>\n"
        f"<p>{intro}</p>\n"
        "<p><strong>Campaign:</strong><br/>{{campaign_name}}</p>\n"
        "<p><strong>Shop:</strong><br/>{{shop_name}}</p>\n"
        "<p><strong>Location:</strong><br/>{{location}}</p>\n"
        "<p><strong>Compensation:</strong><br/>{{compensation}}</p>\n"
        "<p><strong>Deadline:</strong><br/>{{deadline}}</p>\n"
        '<p><a href="{{assignment_link}}" style="display:inline-block;background:#4f46e5;color:#ffffff;'
        'text-decoration:none;font-size:15px;font-weight:600;padding:14px 30px;border-radius:10px;">'
        "VIEW ASSIGNMENT</a></p>\n"
        f"<p>{_SIGNOFFS[tone]}</p>"
    )

    return {"name": name, "subject": subject, "html_body": html_body, "tone": tone}
