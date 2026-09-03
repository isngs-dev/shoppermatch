"""Social Media Automation — /api/social/*.

Extends the existing Region-Targeted Social Media Posting feature
(DistributionPost / ClientSocialAccount, services/distribution.py) with: real
Facebook OAuth, a generalized post composer/scheduler, AI generation, a
reusable template system, and the manual/approval workflow for Facebook
Groups (Meta does not support automated Group posting — see
services/facebook_graph.py's module docstring).

Every endpoint here is client-scoped via `require_client` and additionally
filters through `Campaign.client_id == user.client_id` (never trusts a
campaign_id/post_id from the request alone) — same tenant-isolation
discipline as routers/client_portal.py and routers/campaigns.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_session
from ..deps import require_client
from ..models import (
    Campaign,
    ClientSocialAccount,
    DistributionPost,
    Shop,
    SocialPostTemplate,
    User,
)
from ..serializers import iso
from ..services import facebook_oauth
from ..services.audit import record_audit
from ..services.crypto import encrypt_token
from ..services.distribution import DESTINATION_TYPES, generate_post_image, generate_post_image_from_photo
from ..services.social_ai import extract_document_text, generate_post_text
from ..services.social_publisher import _claim_for_publishing, attempt_publish
from ..services.tracking import now

# A generated/uploaded post graphic can be a sizeable base64 data: URI —
# cap the source photo upload itself well below that so one request can't
# tie up the OpenAI call with an oversized file.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(prefix="/api/social", tags=["Social Media Automation"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _require_campaign(session: AsyncSession, campaign_id: uuid.UUID, user: User) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None or campaign.client_id != user.client_id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _require_post(session: AsyncSession, post_id: uuid.UUID, user: User) -> DistributionPost:
    stmt = (
        select(DistributionPost)
        .where(DistributionPost.id == post_id)
        .options(selectinload(DistributionPost.campaign), selectinload(DistributionPost.source_shop))
    )
    post = (await session.execute(stmt)).scalar_one_or_none()
    if post is None or post.campaign.client_id != user.client_id:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


def _post_out(post: DistributionPost) -> dict:
    return {
        "id": str(post.id),
        "campaign_id": str(post.campaign_id),
        "campaign_name": post.campaign.name if post.campaign else None,
        "source_type": post.source_type,
        "source_shop_id": str(post.source_shop_id) if post.source_shop_id else None,
        "source_shop_name": post.source_shop.shop_name if post.source_shop else None,
        "region": post.region,
        "destination_type": post.destination_type,
        "destination_name": post.destination_name,
        "target_kind": post.target_kind,
        "target_ref": post.target_ref,
        "message": post.message,
        "image_url": post.image_url,
        "status": post.status,
        "scheduled_at": iso(post.scheduled_at),
        "timezone": post.timezone,
        "posted_at": iso(post.posted_at),
        "posted_by": post.posted_by,
        "external_post_id": post.external_post_id,
        "error_message": post.error_message,
        "retry_count": post.retry_count,
        "requires_manual_posting": post.requires_manual_posting,
    }


async def _account_for(session: AsyncSession, client_id: uuid.UUID, platform: str) -> ClientSocialAccount | None:
    stmt = select(ClientSocialAccount).where(
        ClientSocialAccount.client_id == client_id, ClientSocialAccount.platform == platform
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Facebook OAuth (real Meta Graph API — see services/facebook_oauth.py)
# --------------------------------------------------------------------------- #
@router.get("/facebook/status")
async def facebook_status(user: User = Depends(require_client)):
    return {"configured": facebook_oauth.is_configured()}


@router.get("/facebook/connect")
async def facebook_connect(user: User = Depends(require_client)):
    url = facebook_oauth.build_authorize_url(str(user.client_id))
    return {"authorize_url": url}


@router.get("/facebook/callback", include_in_schema=False)
async def facebook_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """Public — Meta redirects the user's browser here directly, so this
    request never carries our Authorization bearer header. `state` (signed
    at /facebook/connect time) is what proves which client this belongs to."""
    settings_page = f"{settings.public_base_url.rstrip('/')}/client/settings/social"
    if error or not code or not state:
        msg = error_description or error or "Facebook did not return an authorization code."
        return RedirectResponse(url=f"{settings_page}?fb_error={msg}")
    try:
        client_id = facebook_oauth.verify_state(state)
        pages = await facebook_oauth.exchange_code_for_pages(code)
    except HTTPException as exc:
        return RedirectResponse(url=f"{settings_page}?fb_error={exc.detail}")
    if not pages:
        return RedirectResponse(
            url=f"{settings_page}?fb_error=No Facebook Pages found for this account — you must be an admin of at least one Page."
        )
    pending_id = facebook_oauth.stash_pending_pages(client_id, pages)
    return RedirectResponse(url=f"{settings_page}?fb_pending={pending_id}")


@router.get("/facebook/pending/{pending_id}")
async def facebook_pending_pages(pending_id: str, user: User = Depends(require_client)):
    pages = facebook_oauth.get_pending_pages(pending_id, str(user.client_id))
    return {"pages": [{"id": p.get("id"), "name": p.get("name"), "category": p.get("category")} for p in pages]}


class SelectPageRequest(BaseModel):
    pending_id: str
    page_id: str


@router.post("/facebook/select-page")
async def facebook_select_page(
    body: SelectPageRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    page = facebook_oauth.pop_pending_page(body.pending_id, str(user.client_id), body.page_id)
    account = await _account_for(session, user.client_id, "facebook")
    if account is None:
        account = ClientSocialAccount(client_id=user.client_id, platform="facebook", connected_by=user.email)
        session.add(account)
    account.account_name = page.get("name") or "Facebook Page"
    account.external_account_id = page.get("id")
    account.access_token_encrypted = encrypt_token(page["access_token"])
    account.status = "connected"
    account.connected_by = user.email
    account.token_expires_at = None  # Page tokens derived from a long-lived user token don't carry a fixed expiry
    await record_audit(
        session,
        action="social_account.facebook_connected",
        actor=user.email,
        entity_type="client",
        entity_id=str(user.client_id),
        summary=f"Connected Facebook Page: {account.account_name}",
        meta={"page_id": account.external_account_id},
    )
    await session.commit()
    return {"platform": "facebook", "account_name": account.account_name, "connected": True}


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #
@router.get("/posts")
async def list_posts(
    campaign_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    stmt = (
        select(DistributionPost)
        .join(Campaign, DistributionPost.campaign_id == Campaign.id)
        .where(Campaign.client_id == user.client_id)
        .order_by(DistributionPost.posted_at.desc())
        .options(selectinload(DistributionPost.campaign), selectinload(DistributionPost.source_shop))
    )
    if campaign_id is not None:
        stmt = stmt.where(DistributionPost.campaign_id == campaign_id)
    if status_filter:
        stmt = stmt.where(DistributionPost.status == status_filter)
    posts = (await session.execute(stmt)).scalars().all()
    return {"items": [_post_out(p) for p in posts], "total": len(posts)}


@router.get("/posts/{post_id}")
async def get_post(post_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_client)):
    post = await _require_post(session, post_id, user)
    return _post_out(post)


class CreatePostRequest(BaseModel):
    campaign_id: uuid.UUID
    source_type: str = Field(pattern="^(campaign|shop)$")
    source_shop_id: uuid.UUID | None = None
    destination_type: str
    target_kind: str = Field(default="page", pattern="^(page|group)$")
    target_ref: str | None = None
    message: str = Field(min_length=1, max_length=5000)
    image_url: str | None = None


@router.post("/posts")
async def create_post(
    body: CreatePostRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    campaign = await _require_campaign(session, body.campaign_id, user)
    valid_platforms = {p for p, _ in DESTINATION_TYPES}
    if body.destination_type not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {body.destination_type}")

    shop = None
    if body.source_type == "shop":
        if body.source_shop_id is None:
            raise HTTPException(status_code=400, detail="source_shop_id is required when source_type='shop'")
        shop = await session.get(Shop, body.source_shop_id)
        if shop is None or shop.campaign_id != campaign.id:
            raise HTTPException(status_code=404, detail="Shop not found in this campaign")

    from ..services.distribution import region_for_shop, regions_for_shops

    region = region_for_shop(shop) if shop else (next(iter(regions_for_shops(await campaign.awaitable_attrs.shops)), "Unspecified Region"))
    is_group = body.target_kind == "group"

    post = DistributionPost(
        campaign_id=campaign.id,
        region=region,
        destination_type=body.destination_type,
        destination_name=body.target_ref or f"{body.destination_type} {body.target_kind}",
        message=body.message,
        image_url=body.image_url,
        status="manual_required" if is_group else "draft",
        posted_by=user.email,
        posted_at=now(),
        source_type=body.source_type,
        source_shop_id=shop.id if shop else None,
        target_kind=body.target_kind,
        target_ref=body.target_ref,
        requires_manual_posting=is_group,
    )
    session.add(post)
    await record_audit(
        session,
        action="social_post.created",
        actor=user.email,
        entity_type="distribution_post",
        entity_id=str(post.id),
        summary=f"Created {body.destination_type} post draft for {campaign.name}",
        meta={"platform": body.destination_type, "target_kind": body.target_kind},
    )
    await session.commit()
    return _post_out(post)


class UpdatePostRequest(BaseModel):
    message: str | None = Field(default=None, max_length=5000)
    image_url: str | None = None
    target_ref: str | None = None


_TERMINAL_STATUSES = {"posted", "posted_manual", "publishing"}


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: uuid.UUID,
    body: UpdatePostRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    post = await _require_post(session, post_id, user)
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot edit a post that is already {post.status}")
    if body.message is not None:
        post.message = body.message
    if body.image_url is not None:
        post.image_url = body.image_url
    if body.target_ref is not None:
        post.target_ref = body.target_ref
        post.destination_name = body.target_ref
    await session.commit()
    return _post_out(post)


@router.delete("/posts/{post_id}")
async def delete_post(post_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_client)):
    post = await _require_post(session, post_id, user)
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="Cannot delete a post that has already been published")
    await session.delete(post)
    await session.commit()
    return {"deleted": True}


@router.post("/posts/{post_id}/duplicate")
async def duplicate_post(post_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_client)):
    post = await _require_post(session, post_id, user)
    copy = DistributionPost(
        campaign_id=post.campaign_id,
        region=post.region,
        destination_type=post.destination_type,
        destination_name=post.destination_name,
        message=post.message,
        image_url=post.image_url,
        status="manual_required" if post.target_kind == "group" else "draft",
        posted_by=user.email,
        posted_at=now(),
        source_type=post.source_type,
        source_shop_id=post.source_shop_id,
        target_kind=post.target_kind,
        target_ref=post.target_ref,
        requires_manual_posting=post.target_kind == "group",
    )
    session.add(copy)
    await session.commit()
    return _post_out(copy)


class ScheduleRequest(BaseModel):
    scheduled_at: datetime
    timezone: str = "UTC"


@router.post("/posts/{post_id}/schedule")
async def schedule_post(
    post_id: uuid.UUID,
    body: ScheduleRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    post = await _require_post(session, post_id, user)
    if post.target_kind == "group":
        raise HTTPException(
            status_code=400,
            detail="Facebook Groups cannot be scheduled for automatic publishing — use Mark as Posted after posting manually.",
        )
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot schedule a post that is already {post.status}")
    account = await _account_for(session, user.client_id, post.destination_type)
    if account is None or account.status != "connected" or not account.access_token_encrypted:
        raise HTTPException(
            status_code=400,
            detail=f"Connect a {post.destination_type} account with a valid token before scheduling.",
        )
    post.scheduled_at = body.scheduled_at
    post.timezone = body.timezone
    post.status = "scheduled"
    post.error_message = None
    await record_audit(
        session,
        action="social_post.scheduled",
        actor=user.email,
        entity_type="distribution_post",
        entity_id=str(post.id),
        summary=f"Scheduled {post.destination_type} post for {iso(body.scheduled_at)}",
        meta={"scheduled_at": iso(body.scheduled_at), "timezone": body.timezone},
    )
    await session.commit()
    return _post_out(post)


@router.post("/posts/{post_id}/publish")
async def publish_post_now(
    post_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Immediate publish — a real, synchronous Graph API call (same
    single-POST latency the pre-existing simulated Distribution "Post Now"
    already accepted blocking the request for), not the scheduled/background
    path. Group targets are rejected outright — see the class docstring."""
    post = await _require_post(session, post_id, user)
    if post.target_kind == "group":
        raise HTTPException(status_code=400, detail="Facebook Groups require manual posting — see Mark as Posted.")
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"This post is already {post.status}")
    account = await _account_for(session, user.client_id, post.destination_type)
    if account is None or account.status != "connected" or not account.access_token_encrypted:
        raise HTTPException(
            status_code=400,
            detail=f"Connect a {post.destination_type} account with a valid token before publishing.",
        )
    # Route through the same idempotent claim the scheduler uses: flip to
    # 'scheduled' first so status='scheduled' -> 'publishing' applies
    # uniformly whether a post got here via a click or a scheduled tick —
    # see services/social_publisher.py::attempt_publish, shared by both.
    post.status = "scheduled"
    post.scheduled_at = now()
    await session.commit()

    if not await _claim_for_publishing(session, post.id):
        raise HTTPException(status_code=409, detail="This post is already being published.")

    post = await _require_post(session, post_id, user)
    await attempt_publish(session, post, account)
    await session.commit()
    if post.status == "failed":
        raise HTTPException(status_code=502, detail=post.error_message)
    return _post_out(post)


@router.post("/posts/{post_id}/cancel")
async def cancel_post(post_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_client)):
    post = await _require_post(session, post_id, user)
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a post that is already {post.status}")
    post.status = "cancelled"
    await session.commit()
    return _post_out(post)


@router.post("/posts/{post_id}/mark-posted")
async def mark_posted_manually(
    post_id: uuid.UUID, session: AsyncSession = Depends(get_session), user: User = Depends(require_client)
):
    """The Facebook Groups manual/approval workflow's final step — the
    client posted it themselves in the Facebook app/site, and confirms that
    here. This app never claims to have posted it automatically."""
    post = await _require_post(session, post_id, user)
    if post.target_kind != "group":
        raise HTTPException(status_code=400, detail="Only group posts use the manual-posting workflow")
    post.status = "posted_manual"
    post.posted_at = now()
    post.posted_by = user.email
    await record_audit(
        session,
        action="social_post.marked_posted_manually",
        actor=user.email,
        entity_type="distribution_post",
        entity_id=str(post.id),
        summary=f"Marked group post as manually posted for {post.campaign.name}",
        meta={"target_ref": post.target_ref},
    )
    await session.commit()
    return _post_out(post)


class GeneratePostRequest(BaseModel):
    tone: str = Field(default="professional", pattern="^(professional|friendly|promotional|short)$")
    language: str = Field(default="English")
    instructions: str | None = Field(default=None, max_length=1000)
    document_text: str | None = Field(default=None, max_length=8000)


@router.post("/posts/{post_id}/generate")
async def generate_post(
    post_id: uuid.UUID,
    body: GeneratePostRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    post = await _require_post(session, post_id, user)
    if post.status in _TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Cannot regenerate a post that is already {post.status}")

    from ..services.social_templates import variables_from_campaign, variables_from_shop

    if post.source_shop:
        variables = variables_from_shop(post.source_shop, post.campaign, settings.public_base_url)
    else:
        variables = variables_from_campaign(post.campaign, settings.public_base_url)

    text = await generate_post_text(
        platform=post.destination_type,
        tone=body.tone,
        language=body.language,
        variables=variables,
        instructions=body.instructions,
        document_text=body.document_text,
    )
    post.message = text
    await session.commit()
    return _post_out(post)


@router.post("/posts/{post_id}/analyze-document")
async def analyze_document_endpoint(
    post_id: uuid.UUID,
    document: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    """Extracts text from a client-uploaded reference document (.txt/.pdf/
    .docx) so the frontend can feed it into /generate's document_text field
    — kept as a separate step (rather than one multipart /generate call) so
    the existing JSON-body /generate endpoint doesn't need to change shape."""
    await _require_post(session, post_id, user)
    content = await document.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Document must be smaller than 10 MB.")
    text = extract_document_text(document.filename or "document", content, document.content_type)
    return {"text": text}


class GenerateImageRequest(BaseModel):
    # A free-text prompt the client typed themselves — when set, this fully
    # replaces the auto-built campaign/message prompt rather than merging
    # with it (see services/distribution.py::generate_post_image).
    prompt: str | None = Field(default=None, max_length=1000)


@router.post("/posts/{post_id}/generate-image")
async def generate_post_image_endpoint(
    post_id: uuid.UUID,
    body: GenerateImageRequest = GenerateImageRequest(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    post = await _require_post(session, post_id, user)
    image_url = await generate_post_image(post.campaign.name, post.message, custom_prompt=body.prompt or None)
    post.image_url = image_url
    await session.commit()
    return _post_out(post)


@router.post("/posts/{post_id}/generate-image-from-photo")
async def generate_post_image_from_photo_endpoint(
    post_id: uuid.UUID,
    photo: UploadFile = File(...),
    prompt: str | None = Form(default=None, max_length=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_client),
):
    post = await _require_post(session, post_id, user)
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")
    content = await photo.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Photo must be smaller than 10 MB.")
    image_url = await generate_post_image_from_photo(
        post.campaign.name, post.message, content, photo.filename or "photo.png", photo.content_type,
        custom_prompt=prompt or None,
    )
    post.image_url = image_url
    await session.commit()
    return _post_out(post)


