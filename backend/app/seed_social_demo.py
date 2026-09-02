"""Idempotent seed extension: populates the Social Media page (Posts,
Calendar, Templates, Automation, Connected Accounts) for the Nike demo
client so it can be shown as a working example instead of an empty state.

Does NOT touch or delete any existing row — every record here is looked up
by a stable identifying field first (platform for connected accounts, name
for templates/rules, a fixed marker for posts) and skipped if already
present.

Run:
    python -m app.seed_social_demo

Safe to run multiple times.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .database import AsyncSessionLocal, init_models
from .models import (
    Campaign,
    Client,
    ClientSocialAccount,
    DistributionPost,
    Shop,
    SocialAutomationRule,
    SocialPostTemplate,
)
from .services.distribution import generate_post_image


async def _get_nike(session) -> tuple[Client, Campaign, list[Shop]]:
    client = (await session.execute(select(Client).where(Client.company_name == "Nike"))).scalar_one_or_none()
    if client is None:
        raise RuntimeError("Nike client not found — run app.seed first")
    campaign = (
        await session.execute(select(Campaign).where(Campaign.name == "Nike Mumbai Store Audit"))
    ).scalar_one_or_none()
    if campaign is None:
        raise RuntimeError("Nike Mumbai Store Audit campaign not found — run app.seed first")
    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars().all()
    return client, campaign, shops


async def _build_accounts(session, client: Client) -> list[str]:
    existing = {
        p for p in (
            await session.execute(
                select(ClientSocialAccount.platform).where(ClientSocialAccount.client_id == client.id)
            )
        ).scalars().all()
    }
    created = []
    for platform, account_name in [
        ("facebook", "Nike India Retail Careers"),
        ("instagram", "@nike.india.careers"),
    ]:
        if platform in existing:
            continue
        session.add(
            ClientSocialAccount(
                client_id=client.id,
                platform=platform,
                account_name=account_name,
                connected_by="Nike Brand Team",
                status="connected",
                external_account_id=f"demo-{platform}-page-id",
            )
        )
        created.append(platform)
    return created


async def _build_templates(session, client: Client) -> list[str]:
    existing = {
        n for n in (
            await session.execute(
                select(SocialPostTemplate.name).where(SocialPostTemplate.client_id == client.id)
            )
        ).scalars().all()
    }
    created = []
    templates = [
        (
            "New Shop Opening — Recruitment",
            "facebook",
            "We're hiring mystery shoppers for {{shop_name}} in {{city}}! "
            "Earn {{currency}} {{compensation}} for a quick visit. "
            "Apply now — spots are limited. #{{campaign_name}}",
        ),
        (
            "Campaign Launch Announcement",
            None,
            "{{campaign_name}} is now live across {{city}}! We're looking for "
            "shoppers to help us evaluate the in-store experience. "
            "Sign up today and get paid to shop.",
        ),
    ]
    for name, platform, body in templates:
        if name in existing:
            continue
        session.add(
            SocialPostTemplate(
                client_id=client.id,
                name=name,
                platform=platform,
                body_template=body,
                created_by="Nike Brand Team",
            )
        )
        created.append(name)
    return created


async def _build_posts(session, campaign: Campaign, shops: list[Shop]) -> int:
    existing_count = (
        await session.execute(select(DistributionPost).where(DistributionPost.campaign_id == campaign.id))
    ).scalars().all()
    if existing_count:
        return 0  # idempotent: only ever seed once per campaign

    now = datetime.now(timezone.utc)
    shop = shops[0] if shops else None
    shop2 = shops[1] if len(shops) > 1 else shop

    posts = [
        # Already posted, a few days ago.
        DistributionPost(
            campaign=campaign,
            source_type="shop",
            source_shop=shop,
            region=shop.city if shop else "Mumbai",
            destination_type="facebook",
            destination_name="Nike India Retail Careers",
            target_kind="page",
            target_ref="demo-facebook-page-id",
            message=(
                f"We're hiring mystery shoppers for {shop.shop_name if shop else 'our Mumbai store'}! "
                f"Earn INR {int(shop.compensation) if shop and shop.compensation else 1500} for a quick visit. "
                "Apply now — spots are limited."
            ),
            status="posted",
            posted_by="Nike Brand Team",
            posted_at=now - timedelta(days=4),
            external_post_id="demo-fb-post-1001",
        ),
        # Posted to Instagram, a couple days ago.
        DistributionPost(
            campaign=campaign,
            source_type="campaign",
            region="Mumbai",
            destination_type="instagram",
            destination_name="@nike.india.careers",
            target_kind="page",
            target_ref="demo-instagram-page-id",
            message="Nike Mumbai Store Audit is live! Get paid to shop and share your experience. Sign up in bio.",
            status="posted",
            posted_by="Nike Brand Team",
            posted_at=now - timedelta(days=2),
            external_post_id="demo-ig-post-1002",
        ),
        # Scheduled for tomorrow — shows up on the Calendar as upcoming.
        DistributionPost(
            campaign=campaign,
            source_type="shop",
            source_shop=shop2,
            region=shop2.city if shop2 else "Pune",
            destination_type="facebook",
            destination_name="Nike India Retail Careers",
            target_kind="page",
            target_ref="demo-facebook-page-id",
            message=(
                f"Last call for shoppers at {shop2.shop_name if shop2 else 'our Pune store'} — "
                "quick visit, real pay, flexible timing. Apply today!"
            ),
            status="scheduled",
            posted_by="Nike Brand Team",
            scheduled_at=now + timedelta(days=1, hours=3),
            timezone="Asia/Kolkata",
        ),
        # Pending approval — from an automation rule, awaiting review.
        DistributionPost(
            campaign=campaign,
            source_type="campaign",
            region="Nashik",
            destination_type="instagram",
            destination_name="@nike.india.careers",
            target_kind="page",
            target_ref="demo-instagram-page-id",
            message="New opportunity in Nashik! Join our mystery shopper program for Nike Mumbai Store Audit.",
            status="pending_approval",
            posted_by="Automation: New Shop Opening",
        ),
        # A Facebook Group post — always manual per Meta's API limits.
        DistributionPost(
            campaign=campaign,
            source_type="campaign",
            region="Mumbai",
            destination_type="facebook",
            destination_name="Mumbai Gig Workers Community",
            target_kind="group",
            target_ref="https://facebook.com/groups/mumbai-gig-workers-demo",
            message="Looking for mystery shoppers in Mumbai — flexible hours, quick payout. DM for details.",
            status="manual_required",
            posted_by="Nike Brand Team",
        ),
    ]
    session.add_all(posts)
    return len(posts)


async def _build_rules(session, client: Client, templates_by_name: dict[str, object]) -> list[str]:
    existing = {
        n for n in (
            await session.execute(
                select(SocialAutomationRule.name).where(SocialAutomationRule.client_id == client.id)
            )
        ).scalars().all()
    }
    created = []
    rules = [
        SocialAutomationRule(
            client_id=client.id,
            name="New Shop Opening",
            enabled=True,
            trigger="shop_created",
            conditions={"status": "open"},
            destination_type="facebook",
            target_kind="page",
            target_ref="demo-facebook-page-id",
            template_id=templates_by_name.get("New Shop Opening — Recruitment"),
            use_ai=False,
            requires_approval=True,
            created_by="Nike Brand Team",
        ),
        SocialAutomationRule(
            client_id=client.id,
            name="Campaign Launch — AI Post",
            enabled=True,
            trigger="campaign_created",
            conditions={},
            destination_type="instagram",
            target_kind="page",
            target_ref="demo-instagram-page-id",
            use_ai=True,
            ai_tone="friendly",
            ai_language="English",
            requires_approval=False,
            schedule_time="09:00",
            timezone="Asia/Kolkata",
            created_by="Nike Brand Team",
        ),
    ]
    for rule in rules:
        if rule.name in existing:
            continue
        session.add(rule)
        created.append(rule.name)
    return created


async def _build_images(session, campaign: Campaign) -> int:
    """Generates a real DALL-E promotional graphic (same call the live
    "Generate Image" button on a post makes) for every seeded post that
    doesn't have one yet. Skipped entirely if OPENAI_API_KEY isn't set, and
    a per-post failure never aborts the rest — same "one call's failure
    can't break the batch" posture used throughout this app's background
    workers."""
    stmt = (
        select(DistributionPost)
        .where(DistributionPost.campaign_id == campaign.id, DistributionPost.image_url.is_(None))
    )
    posts = (await session.execute(stmt)).scalars().all()
    generated = 0
    for post in posts:
        try:
            post.image_url = await generate_post_image(campaign.name, post.message)
            generated += 1
        except Exception as exc:  # noqa: BLE001 — one image failing shouldn't block the others
            print(f"  (image generation skipped for one post: {exc})")
    return generated


async def run() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        client, campaign, shops = await _get_nike(session)
        accounts_created = await _build_accounts(session, client)
        templates_created = await _build_templates(session, client)
        await session.flush()

        templates_by_name = {
            t.name: t.id
            for t in (
                await session.execute(
                    select(SocialPostTemplate).where(SocialPostTemplate.client_id == client.id)
                )
            ).scalars().all()
        }
        posts_created = await _build_posts(session, campaign, shops)
        rules_created = await _build_rules(session, client, templates_by_name)
        await session.commit()

        images_generated = await _build_images(session, campaign)
        await session.commit()

    print(f"Connected accounts created: {accounts_created or 'none (already present)'}")
    print(f"Templates created: {templates_created or 'none (already present)'}")
    print(f"Posts created: {posts_created}")
    print(f"Automation rules created: {rules_created or 'none (already present)'}")
    print(f"Post images generated: {images_generated}")


if __name__ == "__main__":
    asyncio.run(run())
