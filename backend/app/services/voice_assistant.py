"""Voice Assistant — the client portal's "Hey" wake-word assistant, now a
chatbot+voice hybrid: it keeps conversation memory across turns (so "make it
shorter" after "draft me an email" refers back to that draft), can draft/
revise email copy directly, and can trigger a real campaign-wide Email
Automation send.

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
# Kept deliberately small: reads/navigation/drafting are unrestricted, but
# every real write action (send_campaign_invitations,
# start_campaign_automation) always gets a spoken confirmation round-trip in
# the frontend before it actually calls the API.
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": (
                "Go to a different page in the client portal. Use page='campaign_detail' to open ONE "
                "specific campaign's page directly (e.g. 'open the outreach tab for Nike Mumbai Store "
                "Audit') — set campaign_name and detail_tab. Use page='social-media' for the client's "
                "Social Media Automation hub (posts/templates/connected accounts across ALL campaigns) — "
                "not a per-campaign tab."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "string",
                        "enum": [
                            "dashboard",
                            "campaigns",
                            "email-automation",
                            "outreach",
                            "social-media",
                            "insights",
                            "reports",
                            "profile",
                            "campaign_detail",
                        ],
                    },
                    "campaign_filter": {
                        "type": "string",
                        "enum": ["active", "upcoming", "completed"],
                        "description": (
                            "Only meaningful when page is 'campaigns' — which tab to open. "
                            "Omit for the default (active)."
                        ),
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": "Only meaningful when page is 'campaign_detail' — which campaign to open.",
                    },
                    "detail_tab": {
                        "type": "string",
                        "enum": [
                            "overview",
                            "map",
                            "shops",
                            "shoppers",
                            "recommendations",
                            "outreach",
                            "tracking",
                            "insights",
                        ],
                        "description": "Only meaningful when page is 'campaign_detail'. Omit for the overview tab.",
                    },
                },
                "required": ["page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reload_page",
            "description": "Reload the current page, per the client's request.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_email",
            "description": (
                "Write or revise an email subject + body for the client to review — a mystery-"
                "shopping invitation, reminder, or similar. If the client is asking to change a "
                "draft you already wrote earlier in this conversation (e.g. 'make it shorter', "
                "'more casual', 'add the deadline'), revise THAT draft and return the full updated "
                "text, not just the changed part. Plain text only — no markdown, no HTML."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_draft_to_outreach",
            "description": (
                "Put the most recently drafted email into the Outreach compose box, per the "
                "client's request (e.g. 'use this', 'put it in outreach', 'edit this email in "
                "outreach'). Only call this after draft_email has produced something in this "
                "conversation."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_distribution_post",
            "description": (
                "Write or revise the social/portal post creative (caption text) for a named "
                "campaign's Region-Targeted Social Media Posting (viewable on the Social Media page) — "
                "e.g. 'write a post for Nike Mumbai Store Audit', 'make that post punchier'. If revising "
                "a draft from earlier in this conversation, return the full updated text. This is "
                "text only — no image is generated at this step (that happens right before "
                "posting, via post_distribution, so nothing is generated for a draft that gets "
                "discarded)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["campaign_name", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_post_distribution",
            "description": (
                "First step of actually publishing a distribution post — asks the client to "
                "confirm out loud before anything is generated/posted. Always call this before "
                "post_distribution. Requires a draft_distribution_post to already exist in this "
                "conversation for the same campaign."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string"}},
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_distribution",
            "description": (
                "Generates the post graphic and publishes the most recently drafted distribution "
                "post to every one of the client's connected accounts region-matched to this "
                "campaign's shops. Only call this once the client has clearly confirmed after "
                "propose_post_distribution."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string"}},
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_send_invitations",
            "description": (
                "First step of an Outreach send request — identifies the campaign and asks the "
                "client to confirm out loud before anything is actually sent. Always call this "
                "before send_campaign_invitations, never send_campaign_invitations directly on "
                "the first ask. Use this (not the Email Automation tools) when the client just "
                "says 'send invitations' / 'email the shoppers' without mentioning automation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string", "description": "Name (or close match) of the campaign, from the provided context."}},
                "required": ["campaign_name"],
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
                "'confirm' or 'send it') after propose_send_invitations."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string"}},
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_start_automation",
            "description": (
                "First step of an Email Automation request — the client wants a multi-step email "
                "sequence sent to every shopper across a named campaign (e.g. 'in email automation, "
                "send mail to active campaign's shoppers'). Identifies the campaign and asks the "
                "client to confirm out loud. Always call this before start_campaign_automation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string"}},
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_campaign_automation",
            "description": (
                "Creates and immediately starts a campaign-wide Email Automation covering every "
                "AI-recommended shopper across every shop in the named campaign. Only call this "
                "once the client has clearly confirmed after propose_start_automation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"campaign_name": {"type": "string"}},
                "required": ["campaign_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_edit_email_template",
            "description": (
                "First step of editing one of the client's SAVED, reusable email templates (the "
                "Templates list under Email Automation/Outreach — distinct from a one-off "
                "draft_email draft). Use when the client names an existing template, e.g. 'edit the "
                "Standard Invitation template's subject to ...', 'update the Reminder template body'. "
                "Include the full new subject and/or body text you intend to save, and ask the client "
                "to confirm out loud before edit_email_template actually saves it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_name": {"type": "string", "description": "Name (or close match) of the template, from the provided context."},
                    "subject": {"type": "string", "description": "New subject line, if changing it."},
                    "body": {"type": "string", "description": "New body text (plain text — no HTML), if changing it."},
                },
                "required": ["template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_email_template",
            "description": (
                "Saves the edit to an existing email template. Only call this once the client has "
                "clearly confirmed after propose_edit_email_template — repeat the same template_name/"
                "subject/body arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_name": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["template_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_campaign_report",
            "description": (
                "Downloads a campaign report for the client — e.g. 'export the Nike Mumbai report as "
                "PDF', 'download a CSV of that campaign's report'. Non-destructive read-only download, "
                "so call it directly without confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "format": {"type": "string", "enum": ["pdf", "csv", "xlsx"], "description": "Defaults to pdf if not specified."},
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

SYSTEM_PROMPT = """You are the voice + chat assistant embedded in \
ShopperMatch.AI's client portal — a mystery-shopping campaign dashboard. \
You're given the current page and live dashboard/campaign data as JSON \
context, plus the recent conversation history. Use that history: if the \
client refers back to something they or you said earlier ("edit it", "make \
it shorter", "that campaign"), resolve it from history rather than asking \
them to repeat themselves.

Rules:
- If the client is asking a question answerable from the provided context \
  (a stat, a count, campaign status, etc.), just answer in one or two short \
  sentences — no tool call needed.
- If they want to go somewhere, call `navigate`. If they mention active, \
  upcoming, or completed campaigns specifically, set `campaign_filter` \
  accordingly on the campaigns page.
- If they want to reload the page, call `reload_page`.
- If they want an email written, drafted, or an existing draft changed \
  (any request to compose/write/edit email copy), you MUST call the \
  `draft_email` tool with the FULL subject + body (not a diff) — never write \
  the subject/body directly in your own reply text, even formatted with \
  markdown. The tool call is the ONLY way that draft becomes usable later. \
  If they then say something like "use this" / "put it in outreach", call \
  `apply_draft_to_outreach`.
- Outreach sends (one-off invitations, "send invitations", "email the \
  shoppers") go through propose_send_invitations -> send_campaign_invitations. \
  Email Automation sends (an ongoing multi-step sequence, "in email \
  automation...", "send an automation to...") go through \
  propose_start_automation -> start_campaign_automation. Always propose \
  first and require a clear spoken/typed confirmation before the actual \
  send tool.
- Region-Targeted Social Media Posting (viewable on the Social Media page — \
  posting a campaign's creative to region-matched Facebook/Instagram/ \
  LinkedIn/Twitter/JobSlinger/TrustedHerd accounts): writing/revising the \
  post's caption text \
  goes through `draft_distribution_post` (MUST call this tool, never write \
  the caption directly in your reply). Actually publishing it goes through \
  propose_post_distribution -> post_distribution, same propose-then-confirm \
  pattern as every other send in this app.
- Editing a SAVED, reusable email template (not a one-off draft — the client \
  will name it, e.g. "edit the Standard Invitation template") goes through \
  propose_edit_email_template -> edit_email_template, same propose-then-\
  confirm pattern, carrying the full new subject/body in both calls. Template \
  names available are listed in the context.
- Exporting/downloading a campaign report (`export_campaign_report`) is \
  read-only and non-destructive — call it directly, no confirmation needed.
- If they want to stop the assistant, call `disable_assistant`.
- Keep replies short — one or two sentences — EXCEPT when returning an email \
  draft, where the full subject/body belongs in the tool arguments.
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


async def run_agent(transcript: str, context: dict[str, Any], history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Returns {"reply_text": str, "history_text": str, "action": {...} | None}.

    `reply_text` is what gets spoken/shown as the assistant's short turn;
    `history_text` is what gets stored in the conversation log the client
    resends next turn — usually the same, but for draft_email it's the full
    subject/body so a later "make it shorter" can actually see what to
    shorten."""
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Voice assistant is not configured (missing OPENAI_API_KEY).")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append(
        {"role": "user", "content": f"Context (JSON): {json.dumps(context, default=str)}\n\nClient said: \"{transcript}\""}
    )

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_chat_model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.4,
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
        name = call["name"]
        reply_text = _default_reply_for(name, arguments)
        history_text = _history_text_for(name, arguments, reply_text)
        return {"reply_text": reply_text, "history_text": history_text, "action": {"name": name, "arguments": arguments}}

    text = (choice.get("content") or "Sorry, I didn't catch that.").strip()
    return {"reply_text": text, "history_text": text, "action": None}


def _default_reply_for(name: str, arguments: dict[str, Any]) -> str:
    if name == "navigate":
        page = arguments.get("page", "that page")
        campaign_filter = arguments.get("campaign_filter")
        if page == "campaigns" and campaign_filter:
            return f"Opening your {campaign_filter} campaigns."
        if page == "campaign_detail":
            campaign = arguments.get("campaign_name", "that campaign")
            tab = arguments.get("detail_tab")
            return f"Opening the {tab} tab for {campaign}." if tab else f"Opening {campaign}."
        return f"Opening {page}."
    if name == "reload_page":
        return "Reloading the page."
    if name == "draft_email":
        return "Here's a draft — check the chat. Say \"edit it\" with changes, or \"use this in outreach\" to apply it."
    if name == "apply_draft_to_outreach":
        return "Applied to the Outreach compose box."
    if name == "draft_distribution_post":
        return "Here's a draft post — check the chat. Say \"post it\" when you're ready, or ask me to revise it."
    if name == "propose_post_distribution":
        campaign = arguments.get("campaign_name", "this campaign")
        return f"I'll generate a graphic and post that to your connected accounts for {campaign}. Say confirm to go ahead."
    if name == "post_distribution":
        return f"Posting for {arguments.get('campaign_name', 'the campaign')} now."
    if name == "propose_send_invitations":
        campaign = arguments.get("campaign_name", "this campaign")
        return f"I'll auto-assign and email AI-recommended shoppers across {campaign}. Say confirm to go ahead."
    if name == "send_campaign_invitations":
        return f"Sending invitations for {arguments.get('campaign_name', 'the campaign')} now."
    if name == "propose_start_automation":
        campaign = arguments.get("campaign_name", "this campaign")
        return f"I'll start an email automation sequence to every shopper across {campaign}. Say confirm to go ahead."
    if name == "start_campaign_automation":
        return f"Starting the email automation for {arguments.get('campaign_name', 'the campaign')} now."
    if name == "propose_edit_email_template":
        template = arguments.get("template_name", "that template")
        return f"I'll update the {template} template. Say confirm to save it."
    if name == "edit_email_template":
        return f"Saving changes to the {arguments.get('template_name', 'template')} now."
    if name == "export_campaign_report":
        fmt = (arguments.get("format") or "pdf").upper()
        return f"Downloading the {fmt} report for {arguments.get('campaign_name', 'that campaign')}."
    if name == "toggle_theme":
        return f"Switching to {arguments.get('mode', 'the other')} mode."
    if name == "disable_assistant":
        return "Okay, I'll stop listening. Say Hey to wake me up again anytime."
    if name == "log_out":
        return "Signing you out."
    return "Done."


def _history_text_for(name: str, arguments: dict[str, Any], reply_text: str) -> str:
    if name == "draft_email":
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        return f"Drafted email:\nSubject: {subject}\n\n{body}"
    if name == "draft_distribution_post":
        campaign = arguments.get("campaign_name", "")
        message = arguments.get("message", "")
        return f"Drafted distribution post for {campaign}:\n{message}"
    if name == "propose_edit_email_template":
        template = arguments.get("template_name", "")
        subject = arguments.get("subject")
        body = arguments.get("body")
        parts = [f"Proposed template edit for {template}:"]
        if subject:
            parts.append(f"Subject: {subject}")
        if body:
            parts.append(body)
        return "\n".join(parts)
    return reply_text


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
