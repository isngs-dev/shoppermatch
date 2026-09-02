"""AI post generation — reuses this project's existing OpenAI integration
(same OPENAI_API_KEY / openai_chat_model already configured for the voice
assistant and Distribution's image generation; see services/voice_assistant.py,
services/distribution.py) rather than introducing a second AI provider.

The model is given ONLY the selected CRM record's own data (via
services/social_templates.py's variables_from_*) plus the client's own
tone/platform/language/instructions — never invented facts. Output is always
returned to the client for review; nothing here ever calls a publish
endpoint itself (see routers/social.py).
"""
from __future__ import annotations

from fastapi import HTTPException

from ..config import settings

TONE_GUIDANCE = {
    "professional": "a professional, polished tone",
    "friendly": "a warm, friendly, conversational tone",
    "promotional": "an energetic, promotional, sales-forward tone with urgency",
    "short": "a very short, punchy tone — one or two sentences maximum",
}


async def generate_post_text(
    *,
    platform: str,
    tone: str,
    language: str,
    variables: dict[str, str],
    instructions: str | None,
) -> str:
    import httpx

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="AI post generation is not configured (missing OPENAI_API_KEY).")

    tone_desc = TONE_GUIDANCE.get(tone, tone)
    facts = "\n".join(f"- {k}: {v}" for k, v in variables.items() if v)
    prompt = (
        f"Write a {platform} post in {tone_desc}, in {language}. "
        "Use ONLY the facts listed below — never invent details, prices, dates, or claims not given here. "
        "Plain text only, no markdown, no HTML. Keep it appropriate for the platform's typical length.\n\n"
        f"Facts:\n{facts}\n"
    )
    if instructions:
        prompt += f"\nAdditional instructions from the user: {instructions}\n"

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"AI post generation failed: {res.text[:300]}")
    return res.json()["choices"][0]["message"]["content"].strip()
