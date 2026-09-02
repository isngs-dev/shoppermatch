"""The conversational side of AI Voice Call Follow-Up — GPT decides what to
say on each turn of a real phone call, using the exact same OpenAI
tool-calling architecture as services/voice_assistant.py's browser voice
assistant (one small structured "conclude" tool the model calls once it has
a real answer, otherwise it just replies with the next thing to say).

Turn-based, not full-duplex: Twilio's <Gather input="speech"> transcribes
each shopper utterance and POSTs it to us (routers/voice_calls.py), we ask
GPT for the next line + optionally an outcome, and respond with new TwiML.
This reads as a natural back-and-forth conversation to the shopper even
though there's no persistent audio stream — the same request/response shape
Twilio's own docs use for building voice IVRs.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from ..config import settings

_CONCLUDE_TOOL = {
    "type": "function",
    "function": {
        "name": "conclude_call",
        "description": (
            "Call this ONLY once you have a clear enough answer to end the call politely, or the "
            "shopper wants to stop talking / asks not to be called again. Never call it just because "
            "the conversation is going well — keep talking naturally until the shopper's intent is "
            "actually clear, but don't drag it out past 2-3 exchanges."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["interested", "not_interested", "undecided", "voicemail"],
                    "description": (
                        "interested = wants the assignment; not_interested = declines, or asks not to be "
                        "called again; undecided = wants time to think / will check the email; voicemail = "
                        "this was an answering machine, not the actual shopper."
                    ),
                },
                "closing_line": {"type": "string", "description": "The final short, polite line to say before hanging up."},
            },
            "required": ["outcome", "closing_line"],
        },
    },
}


def _system_prompt(shopper_name: str, shop_name: str, campaign_name: str, compensation: str) -> str:
    return (
        f"You are a friendly ISN recruiting coordinator making a brief, natural phone call to a mystery "
        f"shopper named {shopper_name}. They were already emailed about a mystery shopping opportunity "
        f'("{shop_name}", part of the "{campaign_name}" campaign, compensation: {compensation}) but never '
        "replied. This call is a polite follow-up — NOT a cold sales pitch. Sound like a real person: "
        "brief, warm, casual, a couple of sentences per turn, never a monologue. "
        "Confirm you're speaking with the right person, briefly remind them what the opportunity is, "
        "and ask if they're interested. Answer any quick question they have using ONLY the facts given "
        "above — never invent pay, dates, or details not provided. If they sound like voicemail/an "
        "answering machine, treat it as such. Once their intent is clear (or they ask to stop being "
        "called, or you've had a couple of exchanges without clarity), call conclude_call. Keep every "
        "reply under 2 sentences — this is a phone call, not an email."
    )


async def next_turn(
    *,
    history: list[dict[str, str]],
    shopper_name: str,
    shop_name: str,
    campaign_name: str,
    compensation: str,
) -> dict[str, Any]:
    """Returns {"say": str, "outcome": str | None} — outcome is set only
    once the model calls conclude_call, at which point `say` is its closing
    line and the caller should hang up rather than Gather again."""
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice Call Follow-Up needs OPENAI_API_KEY configured.")

    messages = [{"role": "system", "content": _system_prompt(shopper_name, shop_name, campaign_name, compensation)}]
    messages.extend(history)

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_chat_model,
                "messages": messages,
                "tools": [_CONCLUDE_TOOL],
                "tool_choice": "auto",
                "temperature": 0.6,
                "max_tokens": 150,
            },
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Voice call AI turn failed: {res.text[:300]}")

    choice = res.json()["choices"][0]["message"]
    tool_calls = choice.get("tool_calls") or []
    if tool_calls:
        try:
            args = json.loads(tool_calls[0]["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        return {"say": args.get("closing_line", "Thanks for your time — goodbye."), "outcome": args.get("outcome", "undecided")}

    text = (choice.get("content") or "Sorry, could you say that again?").strip()
    return {"say": text, "outcome": None}


def opening_line(shopper_name: str, shop_name: str, campaign_name: str) -> str:
    """The very first thing said when the call connects — no GPT round-trip
    needed for a fixed, predictable greeting."""
    first_name = (shopper_name or "there").split(" ")[0]
    return (
        f"Hi {first_name}, this is an automated call from ISN Shopper Recruitment about the "
        f"{shop_name} mystery shopping opportunity you were emailed about. Are you still interested?"
    )
