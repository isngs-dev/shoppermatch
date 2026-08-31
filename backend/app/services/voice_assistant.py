"""Voice Assistant — the client portal's "Hey" wake-word assistant.

Three real OpenAI calls, each a thin httpx wrapper (same lazy-import-httpx
pattern as services/email.py's SendGrid path — no vendor SDK dependency):

  * transcribe_audio  — Whisper turns the recorded command clip into text.
  * run_agent         — Chat Completions decides what the client meant:
                         either a plain spoken answer, or one structured
                         tool call the frontend carries out itself (this
                         service never touches the database — every real
                         action still goes through the exact same
                         `api.*` calls a click would have used, so it
                         can't bypass tenant scoping, over-selection
                         guards, or audit logging).
  * synthesize_speech — TTS turns the reply back into audio to play.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from ..config import settings

# The only actions the assistant is allowed to ask the frontend to take.
# Kept deliberately small: reads/navigation are unrestricted, but the one
# real write action (send_campaign_invitations) always gets a spoken
# confirmation round-trip in the frontend before it actually calls the API.
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Go to a different page in the client portal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "string",
                        "enum": [
                            "dashboard",
                            "campaigns",
                            "email-automation",
                            "insights",
                            "reports",
                            "profile",
                        ],
                    }
                },
                "required": ["page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_campaign_invitations",
            "description": (
                "Auto-assign and email AI-recommended shoppers across every shop in a named "
                "active campaign — the voice equivalent of the Auto Assign Shoppers button. "
                "Only call this once the client has clearly confirmed (e.g. said 'yes' or "
                "'confirm' or 'send it') after being asked; otherwise call propose_send_invitations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string", "description": "Name (or close match) of the campaign, from the provided context."},
                },
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_send_invitations",
            "description": (
                "First step of a send request — identifies the campaign and asks the client "
                "to confirm out loud before anything is actually sent. Always call this before "
                "send_campaign_invitations, never send_campaign_invitations directly on the first ask."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                },
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_theme",
            "description": "Switch the UI between light and dark mode.",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["light", "dark"]}},
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disable_assistant",
            "description": "Stop listening / turn the voice assistant off, per the client's request.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_out",
            "description": "Sign the client out of their account.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SYSTEM_PROMPT = """You are the voice assistant embedded in ShopperMatch.AI's \
client portal — a mystery-shopping campaign dashboard. The client just spoke \
a command after saying "Hey". You are given the current page and live \
dashboard/campaign data as JSON context.

Rules:
- If the client is asking a question answerable from the provided context \
  (a stat, a count, campaign status, etc.), just answer in one or two short \
  spoken sentences — no tool call needed.
- If they want to go somewhere, call `navigate`.
- If they want invitations/emails sent for a campaign, call \
  `propose_send_invitations` first and ask them to confirm out loud — only \
  call `send_campaign_invitations` on a clear follow-up confirmation.
- If they want to stop the assistant, call `disable_assistant`.
- Keep every spoken reply short — one or two sentences, like a voice \
  assistant, never a long paragraph.
- If the command is unclear or unrelated to this app, say so briefly and \
  ask them to rephrase — never invent data that isn't in the context."""


async def transcribe_audio(audio_bytes: bytes, filename: str, content_type: str) -> str:
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice assistant is not configured (missing OPENAI_API_KEY).")
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data={"model": settings.openai_whisper_model},
            files={"file": (filename, audio_bytes, content_type or "audio/webm")},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {res.text[:300]}")
    return res.json().get("text", "").strip()


async def run_agent(transcript: str, context: dict[str, Any]) -> dict[str, Any]:
    """Returns {"reply_text": str, "action": {"name": str, "arguments": dict} | None}."""
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice assistant is not configured (missing OPENAI_API_KEY).")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Context (JSON): {json.dumps(context, default=str)}\n\nClient said: \"{transcript}\""},
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_chat_model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.3,
            },
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Assistant reasoning failed: {res.text[:300]}")

    choice = res.json()["choices"][0]["message"]
    tool_calls = choice.get("tool_calls") or []
    if tool_calls:
        call = tool_calls[0]["function"]
        try:
            arguments = json.loads(call.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        reply_text = _default_reply_for(call["name"], arguments)
        return {"reply_text": reply_text, "action": {"name": call["name"], "arguments": arguments}}

    return {"reply_text": (choice.get("content") or "Sorry, I didn't catch that.").strip(), "action": None}


def _default_reply_for(name: str, arguments: dict[str, Any]) -> str:
    if name == "navigate":
        return f"Opening {arguments.get('page', 'that page')}."
    if name == "propose_send_invitations":
        campaign = arguments.get("campaign_name", "this campaign")
        return f"I'll auto-assign and email AI-recommended shoppers across {campaign}. Say confirm to go ahead."
    if name == "send_campaign_invitations":
        return f"Sending invitations for {arguments.get('campaign_name', 'the campaign')} now."
    if name == "toggle_theme":
        return f"Switching to {arguments.get('mode', 'the other')} mode."
    if name == "disable_assistant":
        return "Okay, I'll stop listening. Say Hey to wake me up again anytime."
    if name == "log_out":
        return "Signing you out."
    return "Done."


async def synthesize_speech(text: str) -> bytes:
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice assistant is not configured (missing OPENAI_API_KEY).")
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={"model": settings.openai_tts_model, "voice": settings.openai_tts_voice, "input": text},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {res.text[:300]}")
    return res.content
