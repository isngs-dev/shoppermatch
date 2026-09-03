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
    document_text: str | None = None,
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
    if document_text:
        prompt += (
            f"\nThe client also attached a document — pull any relevant recruiting details from it "
            f"(without inventing anything beyond what it says):\n{document_text}\n"
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


# Cap how much of an uploaded document actually reaches the prompt — this is
# recruiting-post copy, not document summarization, so a few thousand
# characters of context is plenty and keeps the prompt cheap.
_DOCUMENT_TEXT_LIMIT = 8000


def extract_document_text(filename: str, content: bytes, content_type: str | None) -> str:
    """Best-effort text extraction for a client-uploaded reference document
    (.txt/.pdf/.docx) so "Generate with AI" can pull real details from it
    instead of the client having to retype them into the instructions box."""
    name = (filename or "").lower()
    try:
        if name.endswith(".txt") or (content_type or "").startswith("text/"):
            text = content.decode("utf-8", errors="ignore")
        elif name.endswith(".pdf") or content_type == "application/pdf":
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif name.endswith(".docx") or content_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            import io

            from docx import Document

            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            raise HTTPException(status_code=400, detail="Unsupported document type — upload a .txt, .pdf, or .docx file.")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surfaced to the client as a plain 400, not a 500
        raise HTTPException(status_code=400, detail=f"Could not read that document: {exc}") from exc

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in that document.")
    return text[:_DOCUMENT_TEXT_LIMIT]
