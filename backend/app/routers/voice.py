"""Voice Assistant endpoints — client-portal only. See
services/voice_assistant.py for the actual OpenAI calls; this router just
validates the request, enforces auth, and shapes the response."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import settings
from ..deps import require_client
from ..models import User
from ..services.voice_assistant import run_agent, synthesize_speech, transcribe_audio

router = APIRouter(prefix="/api/voice", tags=["Voice Assistant"])


@router.get("/status")
async def voice_status(user: User = Depends(require_client)):
    """Whether the assistant is usable at all — the frontend hides every
    voice UI element when this is false rather than showing a broken mic."""
    return {"available": bool(settings.openai_api_key)}


class SpeakRequest(BaseModel):
    text: str


@router.post("/command")
async def voice_command(
    audio: UploadFile | None = File(default=None),
    transcript: str | None = Form(default=None),
    context: str = Form(default="{}"),
    history: str = Form(default="[]"),
    user: User = Depends(require_client),
):
    """Accepts either a recorded audio clip (transcribed via Whisper) or an
    already-known transcript (typed chat messages, and tests) — either way,
    runs the same reasoning step. `history` is the client-held conversation
    log (a plain list of {role, content}) — this endpoint is otherwise
    stateless, so multi-turn memory ("edit it", "that campaign") only works
    because the frontend resends it every call."""
    try:
        parsed_context = json.loads(context) if context else {}
    except json.JSONDecodeError:
        parsed_context = {}
    try:
        parsed_history = json.loads(history) if history else []
        if not isinstance(parsed_history, list):
            parsed_history = []
    except json.JSONDecodeError:
        parsed_history = []

    final_transcript = transcript
    if audio is not None:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio clip")
        final_transcript = await transcribe_audio(audio_bytes, audio.filename or "clip.webm", audio.content_type or "audio/webm")

    if not final_transcript or not final_transcript.strip():
        return {"transcript": "", "reply_text": "I didn't hear anything — try again.", "history_text": "", "action": None}

    result = await run_agent(final_transcript, parsed_context, parsed_history)
    return {"transcript": final_transcript, **result}


@router.post("/speak")
async def voice_speak(body: SpeakRequest, user: User = Depends(require_client)):
    audio_bytes = await synthesize_speech(body.text)
    return Response(content=audio_bytes, media_type="audio/mpeg")
