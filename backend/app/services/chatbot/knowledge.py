"""The chatbot's grounded knowledge base — the ONLY non-database facts the
bot may state. Each entry lists the audiences it is relevant to. Retrieval is
plain keyword overlap (this app runs on SQLite — no pgvector); a lookup that
finds nothing returns an explicit "no_match" so the agent says it doesn't know
and offers a human callback instead of improvising.

Keep every entry true to what the product really does. Anything about pay
amounts or dates is deliberately NOT here — those live per assignment in the
database and are read through tools.
"""
from __future__ import annotations

import re

# (id, audiences, keywords-rich text)
_ENTRIES: list[tuple[str, set[str], str]] = [
    (
        "what_is_shoppermatch",
        {"visitor", "shopper", "staff"},
        "ShopperMatch.AI is ISN's shopper recruitment, outreach and attribution platform for mystery "
        "shopping. ISN matches mystery shoppers to shops that need to be visited, emails them an "
        "invitation, and tracks who opened it, clicked it and accepted or declined.",
    ),
    (
        "what_is_mystery_shopping",
        {"visitor", "shopper"},
        "Mystery shopping means visiting a store, restaurant or other business as an ordinary customer, "
        "noting what you experience (service, cleanliness, product availability and so on) and submitting "
        "an honest report afterwards. No special experience is required.",
    ),
    (
        "how_invitations_work",
        {"visitor", "shopper"},
        "A shopper receives an email invitation from ISN with a personal link. The link opens a page "
        "showing the shop, location, visit window, category and compensation. The shopper can accept or "
        "decline there (or by telling this chat assistant). Accepting or declining can only be recorded once "
        "per invitation.",
    ),
    (
        "compensation",
        {"visitor", "shopper"},
        "Shoppers are paid per completed assignment. The exact compensation for an assignment is shown on "
        "its invitation page. General pay figures, payment dates and payout timing are not set by this chat "
        "assistant, so for payout timing questions a human follow-up is needed.",
    ),
    (
        "flexible_optional",
        {"visitor", "shopper"},
        "Assignments are optional: a shopper chooses whether to accept each invitation. Each assignment has "
        "a visit window (start and end date) during which the visit must be done.",
    ),
    (
        "tracking_privacy",
        {"visitor", "shopper"},
        "ISN tracks invitation engagement so it knows which invited shopper responded: the email carries a "
        "tiny tracking image (to see if it was opened), the link is tracked when clicked, and the page visit "
        "and accept or decline response are recorded against that invitation. Invitation links are unique "
        "to one shopper.",
    ),
    (
        "followup_calls",
        {"visitor", "shopper"},
        "If an invited shopper does not reply to the emails, ISN may follow up with an automated AI voice "
        "call that asks whether they are still interested. Calls may be recorded, and the call says so at "
        "the start.",
    ),
    (
        "stop_contact",
        {"shopper", "visitor"},
        "A person who wants to stop being contacted, or has a privacy or data question, should be handed to a "
        "human via a callback request. This assistant cannot delete data or change contact preferences itself.",
    ),
    (
        "staff_outreach",
        {"staff"},
        "Outreach: pick a campaign, choose AI-recommended shoppers per shop, compose or generate the invitation "
        "email and send it. Each invitation gets a unique tracking token.",
    ),
    (
        "staff_email_automation",
        {"staff"},
        "Email Automation sends a multi-step email sequence to every recommended shopper in a campaign. An "
        "optional AI Voice Call Follow-Up calls shoppers who did not respond. Bulk Voice Call calls a pasted "
        "list of numbers one at a time with an AI conversation; transcripts appear under Call Tracking.",
    ),
    (
        "staff_tracking",
        {"staff"},
        "Email Tracking and the dashboard show the funnel Sent, Delivered, Opened, Clicked, Accepted per "
        "campaign, with per-shopper timelines. Opened means the tracking pixel loaded, Clicked means the link "
        "redirect was followed, Visited means the assignment page loaded.",
    ),
    (
        "staff_privacy_clients",
        {"staff"},
        "Client portal users see only their own campaigns and only aggregate shopper counts, never shopper "
        "names or contact details. ISN admins can see shopper profiles.",
    ),
    (
        "staff_other_areas",
        {"staff"},
        "Other areas: Recommendations (AI shopper matching per shop), Insights and Reports (campaign "
        "analytics), Social Media (region-targeted posts), and the Integrations page for SASSIE, email and "
        "other connections.",
    ),
]

_STOP = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "in", "on", "for", "do", "does", "i", "you",
    "me", "my", "it", "this", "that", "can", "how", "what", "when", "will", "be", "with", "about", "get",
    "have", "there", "if", "so", "at", "as", "by", "from", "am", "we", "your",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and len(t) > 2}


def search(query: str, audience: str, limit: int = 3) -> dict:
    """Keyword-overlap lookup restricted to entries relevant to `audience`."""
    q = _tokens(query)
    scored: list[tuple[int, str, str]] = []
    for entry_id, audiences, text in _ENTRIES:
        if audience not in audiences:
            continue
        overlap = len(q & _tokens(text))
        if overlap:
            scored.append((overlap, entry_id, text))
    scored.sort(key=lambda s: s[0], reverse=True)
    # One shared word is noise; require two (or a short query matching once).
    threshold = 1 if len(q) <= 2 else 2
    hits = [s for s in scored if s[0] >= threshold][:limit]
    if not hits:
        return {"status": "no_match", "note": "Nothing in the knowledge base answers this. Do not guess."}
    return {"status": "ok", "facts": [{"id": h[1], "text": h[2]} for h in hits]}
