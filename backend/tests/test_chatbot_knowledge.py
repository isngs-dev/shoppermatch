"""The knowledge base answers real questions about the product and the website — for every audience, in English and
Hinglish — instead of falling back to "ask a human"."""
from __future__ import annotations

import pytest

from app.services.chatbot import knowledge

# (audience, admin, question, text that must come back among the top results)
QUESTIONS = [
    # ---- anonymous website visitors ----
    ("visitor", False, "what is shoppermatch", "ShopperMatch.AI is ISN"),
    ("visitor", False, "how can I sign in", "How to sign in"),
    ("visitor", False, "I want to create an account for my company", "Create a client account"),
    ("visitor", False, "I forgot my password", "Forgot or reset my password"),
    ("visitor", False, "password bhool gaya kaise reset karu", "Forgot or reset my password"),
    ("visitor", False, "do you have pricing plans", "What does it cost"),
    ("visitor", False, "which languages does the assistant speak", "Languages supported"),
    ("visitor", False, "is my data private and safe", "Where does my data go"),
    ("visitor", False, "what is mystery shopping", "Mystery shopping means visiting"),
    ("visitor", False, "how do I become a mystery shopper", "How do I become a mystery shopper"),
    ("visitor", False, "does it work on my phone", "phones"),
    ("visitor", False, "what technology is the website built with", "What technology is it built with"),
    ("visitor", False, "how does tracking work", "How does tracking an invitation work"),
    ("visitor", False, "what does the home page show", "What the home page contains"),
    ("visitor", False, "mujhe shopper kaise banna hai", "How do I become a mystery shopper"),
    # ---- shoppers ----
    ("shopper", False, "how much will I be paid", "How much will I be paid and when"),
    ("shopper", False, "paisa kab milega", "How much will I be paid and when"),
    ("shopper", False, "what is a bonus on a shop", "What is a shop bonus"),
    ("shopper", False, "how do I stop getting messages", "How do I stop getting messages"),
    ("shopper", False, "will I get phone calls from you", "Will I get phone calls"),
    ("shopper", False, "how are shoppers matched to shops", "How are shoppers matched to shops"),
    ("shopper", False, "how do I decline an invitation", "How do I accept or decline an invitation"),
    ("shopper", False, "what do I do during the visit", "What do I do on a mystery shopping visit"),
    ("shopper", False, "why did I get several invitations", "Why did I get several invitations"),
    # ---- signed-in client users ----
    ("staff", False, "what does autopilot do", "AI Autopilot: what it is"),
    ("staff", False, "what are the autopilot modes review and automatic", "AI Autopilot modes"),
    ("staff", False, "what does fill every shop mean", "Fill every shop"),
    ("staff", False, "how do I add a bonus to a shop", "Add or edit a shop bonus"),
    ("staff", False, "how do I send bulk emails to shoppers", "How do I send emails to many shoppers at once"),
    ("staff", False, "why is my shop not filled", "find out why a shop is not filled"),
    ("staff", False, "how do I export a report", "How do I export data"),
    ("staff", False, "my emails are not being delivered", "My emails are not being delivered"),
    ("staff", False, "what is over-selection", "Over-selection"),
    ("staff", False, "how is the match score calculated", "match score"),
    ("staff", False, "the tracking links open localhost", "tracking links point to localhost"),
    ("staff", False, "how does the ai voice call follow up work", "AI voice call follow-up"),
    ("staff", False, "how do campaigns get added to the platform", "how they get into the platform"),
    ("staff", False, "what do the colours on the map mean", "Campaign Map tab"),
    ("staff", False, "how do I create an email automation", "Create and run an email automation"),
    ("staff", False, "what is the difference between auto assign and autopilot", "Auto Assign"),
    ("staff", False, "how do I post on social media to recruit shoppers", "Social Media posts"),
    ("staff", False, "what can the assistant not do", "What the assistant cannot do"),
    ("staff", False, "autopilot kya karta hai", "AI Autopilot: what it is"),
    ("staff", False, "bonus kaise add karte hain", "Add or edit a shop bonus"),
    ("staff", False, "what is the coverage of a shop", "Coverage"),
    ("staff", False, "how many emails can be sent per day", "Outbox and throttling"),
    # ---- administrators ----
    ("staff", True, "which environment variables matter", "Environment variables that matter most"),
    ("staff", True, "how do I switch on real email", "Switching on real email"),
    ("staff", True, "how do I deploy this", "Deployment"),
    ("staff", True, "describe the system architecture", "Architecture"),
    ("staff", True, "what are the autopilot environment settings", "AI Autopilot configuration"),
]


@pytest.mark.parametrize("audience,admin,question,expected", QUESTIONS, ids=[q[2][:50] for q in QUESTIONS])
def test_every_real_question_gets_an_answer_from_the_knowledge_base(audience, admin, question, expected):
    result = knowledge.search(question, audience, admin=admin)
    assert result["status"] == "ok", f"no answer for {question!r}: {result.get('topics', [])[:5]}"
    haystack = " ".join(f["title"] + " " + f["text"] for f in result["facts"]).lower()
    assert expected.lower() in haystack, f"{question!r} returned {[f['title'] for f in result['facts']]}"


def test_audiences_never_see_content_meant_for_others():
    # Anonymous visitors and shoppers get nothing from the staff or admin guides.
    for audience in ("visitor", "shopper"):
        for q in ("autopilot modes", "environment variables deployment", "audit logs integrations", "bulk voice call"):
            for f in knowledge.search(q, audience).get("facts", []):
                assert not f["id"].startswith(("client_portal", "ai_features", "admin", "howto", "troubleshooting", "SHOPPERMATCH")), f["id"]
    # Client users never get the administrator-only reference documents or admin guide…
    for f in knowledge.search("environment variables deployment architecture", "staff", admin=False).get("facts", []):
        assert not f["id"].startswith(("admin:", "SHOPPERMATCH")), f["id"]
    # …while administrators do.
    ids = {f["id"] for f in knowledge.search("environment variables", "staff", admin=True)["facts"]}
    assert any(i.startswith("admin:") for i in ids)


def test_nonsense_is_no_match_but_still_offers_topics_to_browse():
    miss = knowledge.search("qwerty zxcvb", "staff")
    assert miss["status"] == "no_match" and miss["topics"], "a miss must list topics so the agent can retry"


def test_no_secret_or_credential_is_ever_in_the_guides():
    import re

    secret = re.compile(r"sk-[A-Za-z0-9]{10,}|SG\.[A-Za-z0-9_-]{10,}|isn-demo-2026|client-demo-2026|ms-demo-2026|AC[a-f0-9]{30}")
    for chunk in knowledge._load():
        assert not secret.search(chunk.text), chunk.id
