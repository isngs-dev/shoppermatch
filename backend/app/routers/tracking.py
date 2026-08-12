"""Public tracking endpoints + tracking analytics.

Public (no auth):
  * GET  /r/{tracking_token}                       -> record click, 302 -> /shop
  * GET  /track/open/{tracking_token}.gif          -> record open, return 1x1 GIF
  * GET  /api/public/invitations/{tracking_token}  -> landing-page data
  * POST /api/invitations/{tracking_token}/respond -> record accept/decline

Admin (auth):
  * GET  /api/tracking/summary                     -> KPI + funnel aggregates
  * GET  /api/tracking/events                      -> event feed (filterable)
"""
from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_session
from ..deps import get_current_user
from ..models import Invitation, InvitationEvent, User
from ..rate_limit import tracking_limiter
from ..schemas import RespondRequest
from ..serializers import iso, invitation_row, public_invitation
from ..services.analytics import compute_summary
from ..services.tracking import mark_clicked, mark_opened, mark_response

router = APIRouter(tags=["Tracking"])

# A real 1x1 transparent GIF (43 bytes).
_TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)
_PIXEL_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Content-Type": "image/gif",
}


def _summarize_user_agent(ua: str | None) -> str:
    """Coarse, non-identifying summary (never store the raw UA/IP)."""
    if not ua:
        return "unknown"
    ua_l = ua.lower()
    browser = next(
        (b for b in ("edg", "chrome", "firefox", "safari") if b in ua_l), "browser"
    )
    browser = {"edg": "Edge", "chrome": "Chrome", "firefox": "Firefox", "safari": "Safari"}.get(
        browser, "Browser"
    )
    if "windows" in ua_l:
        os_name = "Windows"
    elif "android" in ua_l:
        os_name = "Android"
    elif "iphone" in ua_l or "ipad" in ua_l or "ios" in ua_l:
        os_name = "iOS"
    elif "mac os" in ua_l or "macintosh" in ua_l:
        os_name = "macOS"
    elif "linux" in ua_l:
        os_name = "Linux"
    else:
        os_name = "device"
    mobile = "Mobile " if "mobile" in ua_l else ""
    return f"{browser} on {mobile}{os_name}".strip()


def _collect_utm(request: Request) -> dict:
    return {
        k: request.query_params[k]
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content")
        if k in request.query_params
    }


def _parse_token(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _get_by_token(session: AsyncSession, token: uuid.UUID) -> Invitation | None:
    stmt = (
        select(Invitation)
        .where(Invitation.tracking_token == token)
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# --------------------------- Click tracking --------------------------- #
@router.get("/r/{tracking_token}", include_in_schema=True)
async def click_redirect(
    tracking_token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    ip = request.client.host if request.client else "anon"
    if not tracking_limiter.allow(f"click:{ip}"):
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

    token = _parse_token(tracking_token)
    if token is None:
        raise HTTPException(status_code=404, detail="Invalid tracking token")

    inv = await _get_by_token(session, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    metadata = {
        "source": inv.source,
        "campaign": inv.campaign.name if inv.campaign else None,
        "page": "email_cta",
        "referrer": request.headers.get("referer"),
        "user_agent_summary": _summarize_user_agent(request.headers.get("user-agent")),
        "utm": _collect_utm(request),
    }
    await mark_clicked(session, inv, metadata)
    await session.commit()

    # The destination is deployment configuration, never a request parameter,
    # so the tracking endpoint cannot be used as an open redirect. When no
    # approved destination is configured, retain the built-in shopper page.
    destination = settings.invitation_destination_url or f"/shop/{tracking_token}"
    response = RedirectResponse(url=destination, status_code=302)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    return response


# --------------------------- Open tracking pixel --------------------------- #
@router.get("/track/open/{tracking_token}.gif", include_in_schema=True)
async def open_pixel(
    tracking_token: str,
    request: Request,
    preview: int = Query(default=0),
    session: AsyncSession = Depends(get_session),
):
    # Always return a valid GIF (never reveal token validity via the image),
    # and never record when rendered in the admin preview (?preview=1).
    ip = request.client.host if request.client else "anon"
    if preview != 1 and tracking_limiter.allow(f"open:{ip}"):
        token = _parse_token(tracking_token)
        if token is not None:
            inv = await _get_by_token(session, token)
            if inv is not None:
                await mark_opened(
                    session,
                    inv,
                    {
                        "source": inv.source,
                        "campaign": inv.campaign.name if inv.campaign else None,
                        "page": "email_open_pixel",
                        "user_agent_summary": _summarize_user_agent(
                            request.headers.get("user-agent")
                        ),
                        "note": "approximate signal — clients may proxy/prefetch images",
                    },
                )
                await session.commit()

    return Response(content=_TRANSPARENT_GIF, media_type="image/gif", headers=_PIXEL_HEADERS)


# --------------------------- Public landing data --------------------------- #
@router.get("/api/public/sample-invitation")
async def sample_invitation(session: AsyncSession = Depends(get_session)):
    """Surface one invitation token so the public home page can link to a live
    shopper landing page. Prefers an invitation that has not yet responded."""
    stmt = (
        select(Invitation)
        .order_by(Invitation.responded_at.is_(None).desc(), Invitation.created_at.desc())
        .limit(1)
        .options(
            selectinload(Invitation.campaign),
            selectinload(Invitation.shop),
            selectinload(Invitation.shopper),
        )
    )
    inv = (await session.execute(stmt)).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="No invitations available")
    payload = public_invitation(inv)
    payload["tracking_token"] = str(inv.tracking_token)
    return payload


@router.get("/api/public/invitations/{tracking_token}")
async def public_landing(
    tracking_token: str,
    session: AsyncSession = Depends(get_session),
):
    token = _parse_token(tracking_token)
    if token is None:
        raise HTTPException(status_code=404, detail="Invalid tracking token")
    inv = await _get_by_token(session, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return public_invitation(inv)


# --------------------------- Respond (accept/decline) --------------------------- #
@router.post("/api/invitations/{tracking_token}/respond")
async def respond(
    tracking_token: str,
    body: RespondRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    token = _parse_token(tracking_token)
    if token is None:
        raise HTTPException(status_code=404, detail="Invalid tracking token")
    inv = await _get_by_token(session, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    metadata = {
        "source": inv.source,
        "page": "shopper_landing",
        "user_agent_summary": _summarize_user_agent(request.headers.get("user-agent")),
    }
    if body.note:
        metadata["note"] = body.note

    recorded = await mark_response(session, inv, body.response, metadata)
    await session.commit()

    payload = public_invitation(inv)
    payload["recorded"] = recorded
    payload["already_responded"] = not recorded
    return payload


# --------------------------- Analytics (admin) --------------------------- #
@router.get("/api/tracking/summary", tags=["Analytics"])
async def tracking_summary(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    return await compute_summary(session)


@router.get("/api/tracking/events", tags=["Analytics"])
async def tracking_events(
    invitation_id: uuid.UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    stmt = (
        select(InvitationEvent)
        .order_by(InvitationEvent.event_timestamp.desc())
        .limit(limit)
        .options(
            selectinload(InvitationEvent.invitation).selectinload(Invitation.shopper),
            selectinload(InvitationEvent.invitation).selectinload(Invitation.campaign),
        )
    )
    if invitation_id is not None:
        stmt = stmt.where(InvitationEvent.invitation_id == invitation_id)
    if event_type:
        stmt = stmt.where(InvitationEvent.event_type == event_type)

    events = (await session.execute(stmt)).scalars().all()
    items = []
    for e in events:
        inv = e.invitation
        items.append(
            {
                "id": str(e.id),
                "invitation_id": str(e.invitation_id),
                "reference": inv.reference if inv else None,
                "event_type": e.event_type,
                "event_timestamp": iso(e.event_timestamp),
                "shopper_name": inv.shopper.name if inv and inv.shopper else None,
                "campaign_name": inv.campaign.name if inv and inv.campaign else None,
                "metadata": e.event_metadata or {},
            }
        )
    return {"items": items, "total": len(items)}
