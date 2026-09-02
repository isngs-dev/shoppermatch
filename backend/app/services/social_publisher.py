"""Background worker for Social Media Automation — same in-process asyncio
poller pattern as services/automation.py::run_automation_scheduler and
services/outbox.py::run_outbox_worker (see main.py's lifespan), not a
separate queue system, since this project doesn't have one.

Handles:
  * Publishing posts whose scheduled_at has arrived (Page targets only —
    Group targets are never auto-published, see facebook_graph.py).
  * Retrying failed attempts up to social_publisher_max_attempts, with a
    small exponential backoff between attempts.
  * Periodically validating connected Facebook accounts' tokens, flipping
    status to "expired" so the client sees "Reconnect" instead of silently
    failing posts later.

Idempotency: a post is only ever claimed for publishing via a conditional
UPDATE ... WHERE status='scheduled' — if that update affects zero rows
(another tick already claimed it, or a client cancelled it in the meantime),
this tick skips it. Once external_post_id is set the post is "posted" and
is never re-selected by the due-posts query again (status != 'scheduled').
This is what actually prevents a retry or duplicate tick from publishing the
same post twice — see PR discussion / spec requirement on idempotency.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import ClientSocialAccount, DistributionPost
from .crypto import decrypt_token
from .facebook_graph import FacebookPublishError, publish_to_page
from .facebook_oauth import validate_page_token
from .tracking import now


async def _claim_for_publishing(session, post_id) -> bool:
    """Atomically flips one post from 'scheduled' to 'publishing'. Returns
    True only if THIS call made that transition — the idempotency guard."""
    result = await session.execute(
        update(DistributionPost)
        .where(DistributionPost.id == post_id, DistributionPost.status == "scheduled")
        .values(status="publishing")
    )
    await session.commit()
    return result.rowcount == 1


async def attempt_publish(session, post: DistributionPost, account: ClientSocialAccount | None) -> None:
    """The actual "call Meta, record the outcome" step — shared by the
    background scheduler (_publish_one below) and the router's immediate
    "Publish Now" action (routers/social.py::publish_post_now), so the two
    call sites can never silently drift apart on retry/error/logging
    behavior. Caller is responsible for the idempotent claim beforehand
    (_claim_for_publishing) and for `session.commit()`-ing afterward."""
    from .audit import record_audit
    from ..models import SocialPublishingLog

    log = SocialPublishingLog(
        post_id=post.id,
        platform=post.destination_type,
        target_ref=post.target_ref,
        attempted_at=now(),
        status="failed",
        retry_count=post.retry_count,
    )

    if account is None or not account.access_token_encrypted:
        post.status = "failed"
        post.error_message = f"No connected {post.destination_type} account with a valid token."
        log.error_message = post.error_message
        session.add(log)
        return

    try:
        page_token = decrypt_token(account.access_token_encrypted)
        external_id = await publish_to_page(account.external_account_id, page_token, post.message, post.image_url)
        post.status = "posted"
        post.external_post_id = external_id
        post.posted_at = now()
        post.error_message = None
        log.status = "success"
        log.published_at = post.posted_at
        log.external_post_id = external_id
        session.add(log)
        await record_audit(
            session,
            action="social_post.published",
            actor="system",
            entity_type="distribution_post",
            entity_id=str(post.id),
            summary=f"Published {post.destination_type} post for {post.campaign.name} ({external_id})",
            meta={"platform": post.destination_type, "external_post_id": external_id},
        )
    except FacebookPublishError as exc:
        post.retry_count += 1
        post.error_message = str(exc)[:500]
        log.error_message = post.error_message
        log.retry_count = post.retry_count
        session.add(log)
        if exc.is_auth_error:
            account.status = "expired"
            post.status = "failed"
            post.error_message = f"{post.error_message} — reconnect the {post.destination_type} account."
        elif post.retry_count >= settings.social_publisher_max_attempts:
            post.status = "failed"
        else:
            # Small exponential backoff before the next attempt, capped at 1
            # hour, so a transient outage doesn't hammer Meta's API.
            post.status = "scheduled"
            post.scheduled_at = now() + timedelta(minutes=min(60, 2 ** post.retry_count))


async def _publish_one(post_id) -> None:
    async with AsyncSessionLocal() as session:
        if not await _claim_for_publishing(session, post_id):
            return  # already claimed/handled by another tick, or cancelled

        post = await session.get(DistributionPost, post_id, options=[selectinload(DistributionPost.campaign)])
        if post is None:
            return

        account_stmt = select(ClientSocialAccount).where(
            ClientSocialAccount.client_id == post.campaign.client_id,
            ClientSocialAccount.platform == post.destination_type,
        )
        account = (await session.execute(account_stmt)).scalar_one_or_none()

        await attempt_publish(session, post, account)
        await session.commit()


async def process_due_social_posts() -> int:
    """One scheduler tick. Returns the number of posts attempted."""
    due = now()
    async with AsyncSessionLocal() as session:
        stmt = select(DistributionPost.id).where(
            DistributionPost.status == "scheduled",
            DistributionPost.target_kind == "page",
            DistributionPost.scheduled_at.is_not(None),
            DistributionPost.scheduled_at <= due,
        )
        due_ids = (await session.execute(stmt)).scalars().all()

    for post_id in due_ids:
        try:
            await _publish_one(post_id)
        except Exception as exc:  # noqa: BLE001 — one post's failure must never break the others
            print(f"WARNING: ShopperMatch social publisher error for post {post_id}: {exc}")

    return len(due_ids)


async def refresh_connected_accounts() -> int:
    """Validates every connected Facebook account's token, flipping expired/
    revoked ones to status='expired' so the client sees "Reconnect" instead
    of every subsequent post silently failing one at a time."""
    checked = 0
    async with AsyncSessionLocal() as session:
        stmt = select(ClientSocialAccount).where(
            ClientSocialAccount.platform == "facebook",
            ClientSocialAccount.status == "connected",
            ClientSocialAccount.access_token_encrypted.is_not(None),
        )
        accounts = (await session.execute(stmt)).scalars().all()
        for account in accounts:
            try:
                token = decrypt_token(account.access_token_encrypted)
                if not await validate_page_token(token):
                    account.status = "expired"
            except Exception:  # noqa: BLE001 — a corrupt/undecryptable token is also "expired"
                account.status = "expired"
            checked += 1
        await session.commit()
    return checked


async def run_social_publisher() -> None:
    """Runs for the FastAPI process lifetime — background, browser-independent.
    Token validation runs far less often than the publish check (it's an
    external API call per connected account, not a cheap DB query)."""
    tick = 0
    validate_every_n_ticks = max(1, int(600 / max(settings.social_publisher_poll_seconds, 1)))
    while True:
        try:
            await process_due_social_posts()
            tick += 1
            if tick % validate_every_n_ticks == 0:
                await refresh_connected_accounts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            print(f"WARNING: ShopperMatch social publisher error: {exc}")
        await asyncio.sleep(settings.social_publisher_poll_seconds)
