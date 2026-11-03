"""Agentic chatbot endpoints — /api/chatbot/*. The agent itself lives in
services/chatbot/; this router authenticates each audience, resolves (or
starts) the conversation, rate limits, and shapes the response.

  * POST /api/chatbot/staff/message                 — ISN admin / client user (bearer token)
  * POST /api/chatbot/shopper/{tracking_token}/message — shopper holding an invitation link
  * POST /api/chatbot/visitor/message               — anonymous website visitor
  * GET  /api/chatbot/status                        — is the assistant usable at all
  * GET  /api/chatbot/admin/conversations[/{id}]    — admin review of transcripts

Public conversations are only resumable with the `session_key` returned when
they were created, so one visitor can never read or continue another's chat.
"""
from __future__ import annotations

import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_session
from ..deps import require_admin, require_operator
from ..models import ChatConversation, ChatEscalation, Invitation, Shopper, User
from ..rate_limit import SlidingWindowRateLimiter
from ..serializers import iso
from ..services.chatbot.agent import greeting_for, run_turn
from ..services.chatbot.tools import ChatScope
from ..services.tracking import add_event
from .tracking import _get_by_token, _parse_token

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot"])

_limiter = SlidingWindowRateLimiter(settings.chatbot_rate_limit_per_minute)


class ChatMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    # Required to resume a shopper/visitor conversation (returned on creation).
    session_key: str | None = Field(default=None, max_length=64)
    # Staff chat only: the page the user is on (e.g. /client/email-automation?tab=bulk-call).
    page: str | None = Field(default=None, max_length=200)


_PAGE_RE = re.compile(r"^/[A-Za-z0-9/_\-?=&.%]*$")


def _clean_page(value: str | None) -> str | None:
    """The page path is only context for the model; accept a plain in-app path and nothing else."""
    return value if value and _PAGE_RE.match(value) else None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request, bucket: str) -> None:
    if not _limiter.allow(f"{bucket}:{_client_ip(request)}"):
        raise HTTPException(status_code=429, detail="You're sending messages too fast — please wait a moment.")


async def _load_or_create(
    session: AsyncSession,
    body: ChatMessageIn,
    *,
    audience: str,
    user: User | None = None,
    invitation: Invitation | None = None,
) -> ChatConversation:
    """Resume the caller's own conversation, or start a fresh one. A
    conversation that doesn't belong to this caller (wrong audience, user,
    invitation or session key) is silently replaced, never exposed."""
    if body.conversation_id is not None:
        conv = await session.get(ChatConversation, body.conversation_id)
        if conv is not None and conv.audience == audience:
            if audience == "staff":
                ok = user is not None and conv.user_id == user.id
            else:
                ok = (
                    bool(body.session_key)
                    and secrets.compare_digest(conv.session_key, body.session_key)
                    and conv.invitation_id == (invitation.id if invitation else None)
                )
            if ok:
                return conv
    conv = ChatConversation(
        audience=audience,
        session_key=secrets.token_urlsafe(24),
        user_id=user.id if user else None,
        client_id=user.client_id if user and user.role == "client" else None,
        invitation_id=invitation.id if invitation else None,
    )
    session.add(conv)
    await session.flush()
    if invitation is not None:
        # Activity trail: "Chatbot accessed" shows on the invitation's timeline.
        await add_event(session, invitation, "chatbot_accessed", {"channel": "chatbot", "conversation_id": str(conv.id)})
    return conv


async def _respond(session: AsyncSession, scope: ChatScope, body: ChatMessageIn) -> dict:
    result = await run_turn(session, scope, body.message)
    conv = scope.conversation
    return {
        "conversation_id": str(conv.id),
        "session_key": conv.session_key if scope.audience != "staff" else None,
        **result,
    }


@router.get("/status")
async def chatbot_status():
    """The UI hides the chat launcher when this is false rather than showing a
    chat that can only error."""
    return {"available": bool(settings.openai_api_key)}


@router.post("/staff/message")
async def staff_message(
    body: ChatMessageIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    _rate_limit(request, "staff")
    conv = await _load_or_create(session, body, audience="staff", user=user)
    return await _respond(session, ChatScope(audience="staff", conversation=conv, user=user, page=_clean_page(body.page)), body)


@router.post("/shopper/{tracking_token}/message")
async def shopper_message(
    tracking_token: str,
    body: ChatMessageIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    token = _parse_token(tracking_token)
    inv = await _get_by_token(session, token) if token else None
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    _rate_limit(request, f"shopper:{inv.id}")
    conv = await _load_or_create(session, body, audience="shopper", invitation=inv)
    return await _respond(session, ChatScope(audience="shopper", conversation=conv, invitation=inv), body)


@router.get("/shopper/{tracking_token}/greeting")
async def shopper_greeting(tracking_token: str, session: AsyncSession = Depends(get_session)):
    """First message for a freshly opened shopper chat (spec section 10)."""
    token = _parse_token(tracking_token)
    inv = await _get_by_token(session, token) if token else None
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    conv = ChatConversation(audience="shopper", session_key="", invitation_id=inv.id)  # transient, never saved
    return {"greeting": greeting_for(ChatScope(audience="shopper", conversation=conv, invitation=inv))}


@router.post("/visitor/message")
async def visitor_message(
    body: ChatMessageIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    _rate_limit(request, "visitor")
    conv = await _load_or_create(session, body, audience="visitor")
    return await _respond(session, ChatScope(audience="visitor", conversation=conv), body)


# --------------------------------------------------------------------------- #
# Admin review — what the bot said and did, and who asked for a human.
# --------------------------------------------------------------------------- #
def _conv_row(c: ChatConversation) -> dict:
    return {
        "id": str(c.id),
        "audience": c.audience,
        "status": c.status,
        "turn_count": c.turn_count,
        "escalation_reason": c.escalation_reason,
        "preferred_time": c.preferred_time,
        "contact_name": c.contact_name,
        "contact_email": c.contact_email,
        "contact_phone": c.contact_phone,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
    }


@router.get("/admin/escalations")
async def admin_escalations(
    status: str = Query(default="open", pattern="^(open|resolved)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    """Escalations, reschedule/cancel requests raised by the shopper chatbot."""
    rows = (
        await session.execute(
            select(ChatEscalation, Shopper)
            .join(Shopper, Shopper.id == ChatEscalation.shopper_id, isouter=True)
            .where(ChatEscalation.status == status)
            .order_by(ChatEscalation.created_at.desc())
            .limit(limit)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(e.id),
                "kind": e.kind,
                "reason": e.reason,
                "priority": e.priority,
                "shopper": sh.name if sh else None,
                "summary": e.summary,
                "new_date": e.new_date,
                "conversation_id": str(e.conversation_id) if e.conversation_id else None,
                "created_at": iso(e.created_at),
            }
            for e, sh in rows
        ]
    }


@router.get("/admin/conversations")
async def admin_conversations(
    audience: str | None = Query(default=None, pattern="^(staff|shopper|visitor)$"),
    status: str | None = Query(default=None, pattern="^(open|escalated)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    stmt = select(ChatConversation).order_by(ChatConversation.updated_at.desc()).limit(limit)
    if audience:
        stmt = stmt.where(ChatConversation.audience == audience)
    if status:
        stmt = stmt.where(ChatConversation.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_conv_row(c) for c in rows], "total": len(rows)}


@router.get("/admin/conversations/{conversation_id}")
async def admin_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    conv = (
        await session.execute(
            select(ChatConversation)
            .where(ChatConversation.id == conversation_id)
            .options(selectinload(ChatConversation.messages))
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        **_conv_row(conv),
        "messages": [
            {"role": m.role, "content": m.content, "meta": m.meta, "at": iso(m.created_at)} for m in conv.messages
        ],
    }
