"""K/L/M. Response Feedback Analysis (Summarization, Sentiment, Quality Control).

Scope note: this project has no separate "store visit report" model/UI —
shoppers only leave an optional free-text `note` when accepting/declining an
invitation (RespondRequest.note -> InvitationEvent.event_metadata). These
three AI features operate on that real, existing field rather than a
fabricated reports subsystem. A lexicon-based sentiment classifier is used
(no LLM configured in this project) — every output traces back to specific
words actually present in the note.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import EventType, Invitation, InvitationEvent

POSITIVE_WORDS = {
    "friendly", "helpful", "great", "good", "excellent", "clean", "fast",
    "quick", "polite", "professional", "welcoming", "smooth", "easy", "nice",
}
NEGATIVE_WORDS = {
    "slow", "rude", "dirty", "unhelpful", "delay", "delayed", "ignored",
    "wait", "waited", "poor", "bad", "unavailable", "far", "difficult",
    "confusing", "unclear", "problem", "issue",
}


def analyze_sentiment(text: str) -> dict:
    if not text or not text.strip():
        return {"sentiment": "neutral", "positive_points": [], "negative_points": [], "severity": "none"}

    words = {w.strip(".,!?").lower() for w in text.split()}
    positive_hits = sorted(words & POSITIVE_WORDS)
    negative_hits = sorted(words & NEGATIVE_WORDS)

    if positive_hits and negative_hits:
        sentiment = "mixed"
    elif positive_hits:
        sentiment = "positive"
    elif negative_hits:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    severity = "high" if len(negative_hits) >= 3 else "medium" if negative_hits else "low"
    return {
        "sentiment": sentiment,
        "positive_points": positive_hits,
        "negative_points": negative_hits,
        "severity": severity if negative_hits else "none",
    }


async def collect_campaign_notes(session: AsyncSession, campaign_id) -> list[dict]:
    stmt = (
        select(InvitationEvent)
        .join(Invitation, InvitationEvent.invitation_id == Invitation.id)
        .where(
            Invitation.campaign_id == campaign_id,
            InvitationEvent.event_type.in_([EventType.ASSIGNMENT_ACCEPTED, EventType.ASSIGNMENT_DECLINED]),
        )
        .options(selectinload(InvitationEvent.invitation).selectinload(Invitation.shopper))
    )
    events = (await session.execute(stmt)).scalars().all()

    notes = []
    for e in events:
        note = (e.event_metadata or {}).get("note")
        if not note:
            continue
        inv = e.invitation
        notes.append(
            {
                "shopper_name": inv.shopper.name if inv.shopper else inv.email,
                "response": inv.response,
                "note": note,
                "responded_at": e.event_timestamp,
                "sentiment": analyze_sentiment(note),
            }
        )
    return notes


def summarize_notes(notes: list[dict]) -> dict:
    if not notes:
        return {
            "executive_summary": "No shopper feedback notes have been submitted for this campaign yet.",
            "key_issues": [],
            "counts": {"positive": 0, "negative": 0, "mixed": 0, "neutral": 0},
        }

    counts = {"positive": 0, "negative": 0, "mixed": 0, "neutral": 0}
    all_negative: dict[str, int] = {}
    all_positive: dict[str, int] = {}
    for n in notes:
        counts[n["sentiment"]["sentiment"]] += 1
        for w in n["sentiment"]["negative_points"]:
            all_negative[w] = all_negative.get(w, 0) + 1
        for w in n["sentiment"]["positive_points"]:
            all_positive[w] = all_positive.get(w, 0) + 1

    total = len(notes)
    summary = (
        f"Of {total} response(s) with feedback, {counts['positive']} were positive, "
        f"{counts['negative']} negative, and {counts['mixed']} mixed."
    )
    key_issues = []
    for word, count in sorted(all_negative.items(), key=lambda x: -x[1])[:3]:
        key_issues.append({"severity": "red" if count >= 3 else "yellow", "issue": word, "mentions": count})
    for word, count in sorted(all_positive.items(), key=lambda x: -x[1])[:2]:
        key_issues.append({"severity": "green", "issue": word, "mentions": count})

    return {"executive_summary": summary, "key_issues": key_issues, "counts": counts}


def qa_flag_notes(notes: list[dict]) -> list[dict]:
    """Report Quality Control: flag suspiciously generic or duplicated notes."""
    flags = []
    seen: dict[str, list[str]] = {}
    for n in notes:
        text = n["note"].strip().lower()
        seen.setdefault(text, []).append(n["shopper_name"])
        word_count = len(n["note"].split())
        if word_count <= 2:
            flags.append(
                {
                    "shopper_name": n["shopper_name"],
                    "note": n["note"],
                    "reason": "Note is very short/generic — may not contain enough detail for review.",
                }
            )
    for text, names in seen.items():
        if len(names) > 1 and len(text.split()) > 2:
            flags.append(
                {
                    "shopper_name": ", ".join(names),
                    "note": text,
                    "reason": "Identical note text submitted by multiple shoppers — potential copy/paste.",
                }
            )
    return flags
