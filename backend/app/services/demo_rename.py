"""One-shot rename of the demo client "Nike" to "MS" on databases created before the rename.

New databases are seeded as "MS" directly (app/seed.py); this brings an existing one (local SQLite, or a deployed
Postgres that was seeded earlier) in line: the demo client login, its company, its own campaigns and their shops, its
social accounts, and the shopper profiles that mention it as previous client work (so the "worked for this client
before" match factor keeps working).

It is triggered by the old demo login (client@nike-demo.example) still existing, and that login is renamed as part of
the run, so it runs once and never again. It only touches rows that belong to that demo client, never a real client
that merely happens to be called Nike.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Campaign, Client, ClientSocialAccount, Shop, Shopper, User
from .audit import record_audit

log = logging.getLogger("app.demo_rename")

OLD_EMAIL = "client@nike-demo.example"
NEW_EMAIL = "client@ms-demo.example"
OLD_NAME, NEW_NAME = "Nike", "MS"


def _swap(text: str | None) -> str | None:
    if not text:
        return text
    return text.replace("NIKE", NEW_NAME).replace(OLD_NAME, NEW_NAME).replace(OLD_NAME.lower(), NEW_NAME.lower())


async def rename_demo_client(session: AsyncSession) -> bool:
    """Returns True if anything was renamed. The caller commits."""
    user = await session.scalar(select(User).where(User.email == OLD_EMAIL))
    if user is None:
        return False
    if await session.scalar(select(User.id).where(User.email == NEW_EMAIL)) is not None:
        return False  # the new login already exists: leave the old one alone rather than collide

    user.email = NEW_EMAIL
    user.name = _swap(user.name) or user.name

    client = await session.get(Client, user.client_id) if user.client_id else None
    if client is not None and client.company_name == OLD_NAME:
        if await session.scalar(select(Client.id).where(Client.company_name == NEW_NAME)) is None:
            client.company_name = NEW_NAME
            # Only the demo client's own campaigns (client_name "Nike"): the other campaigns re-owned by this
            # login keep their own brand names.
            campaigns = (
                await session.execute(
                    select(Campaign).where(Campaign.client_id == client.id, Campaign.client_name == OLD_NAME)
                )
            ).scalars().all()
            for campaign in campaigns:
                campaign.name = _swap(campaign.name) or campaign.name
                campaign.client_name = NEW_NAME
                campaign.description = _swap(campaign.description)
                for shop in (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id))).scalars():
                    shop.shop_name = _swap(shop.shop_name) or shop.shop_name
            for account in (
                await session.execute(select(ClientSocialAccount).where(ClientSocialAccount.client_id == client.id))
            ).scalars():
                account.account_name = _swap(account.account_name) or account.account_name

    for shopper in (await session.execute(select(Shopper))).scalars():
        prior = shopper.previous_clients or []
        if OLD_NAME in prior:
            shopper.previous_clients = [NEW_NAME if c == OLD_NAME else c for c in prior]
        if shopper.experience_description and OLD_NAME in shopper.experience_description:
            shopper.experience_description = _swap(shopper.experience_description)

    await record_audit(
        session,
        action="demo.client_renamed",
        actor="system",
        entity_type="client",
        entity_id=str(client.id) if client is not None else "-",
        summary=f"Renamed the demo client {OLD_NAME} to {NEW_NAME} (login {OLD_EMAIL} -> {NEW_EMAIL})",
        meta={"from": OLD_NAME, "to": NEW_NAME},
    )
    log.info("Renamed the demo client %s to %s (login is now %s)", OLD_NAME, NEW_NAME, NEW_EMAIL)
    return True
