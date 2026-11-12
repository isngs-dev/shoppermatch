"""A database seeded when the demo client was still "Nike" is renamed to "MS" once, and only the demo client's own rows."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import Campaign, Client, Shop, Shopper, User
from app.security import hash_password
from app.services.demo_rename import (
    NEW_EMAIL,
    NEW_PASSWORD,
    OLD_EMAIL,
    OLD_PASSWORD,
    refresh_demo_client_password,
    rename_demo_client,
)
from tests.test_acceptance import _fresh_db


async def _make_legacy_database() -> dict:
    """Turn a freshly seeded (MS) database back into what an older one looked like, plus two decoys."""
    async with AsyncSessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == NEW_EMAIL))
        assert user is not None, "the seed should create the MS demo login"
        client = await s.get(Client, user.client_id)
        user.email, user.name = OLD_EMAIL, "Nike Brand Team"
        client.company_name = "Nike"

        own = (await s.execute(select(Campaign).where(Campaign.client_id == client.id, Campaign.client_name == "MS"))).scalars().all()
        assert own, "the demo client should own MS campaigns"
        for c in own:
            c.name, c.client_name, c.description = c.name.replace("MS", "Nike", 1), "Nike", "Audit across Nike stores."
            for shop in (await s.execute(select(Shop).where(Shop.campaign_id == c.id))).scalars():
                shop.shop_name = shop.shop_name.replace("MS", "Nike", 1)

        # Decoys: a re-owned campaign of another brand, and a real, different client that merely contains "Nike".
        other_brand = Campaign(name="Dunkin' Audit", client_name="Dunkin'", client_id=client.id, status="active")
        rival = Client(company_name="Nike Realty Partners", status="active")
        s.add_all([other_brand, rival])
        await s.flush()
        rival_campaign = Campaign(name="Nike Realty Audit", client_name="Nike Realty Partners", client_id=rival.id, status="active")
        s.add(rival_campaign)

        shopper = (await s.execute(select(Shopper).limit(1))).scalar_one()
        shopper.previous_clients = ["Starbucks", "Nike"]
        shopper.experience_description = "Previous client work includes Nike."
        await s.commit()
        return {"shopper": shopper.id, "rival_campaign": rival_campaign.id, "other_brand": other_brand.id, "client": client.id}


@pytest.mark.asyncio
async def test_an_old_database_is_renamed_once_and_only_for_the_demo_client():
    await _fresh_db()
    ids = await _make_legacy_database()

    async with AsyncSessionLocal() as s:
        assert await rename_demo_client(s) is True
        await s.commit()

    async with AsyncSessionLocal() as s:
        user = await s.scalar(select(User).where(User.client_id == ids["client"]))
        assert user.email == NEW_EMAIL and user.name == "MS Brand Team"
        assert (await s.get(Client, ids["client"])).company_name == "MS"
        renamed = (await s.execute(select(Campaign).where(Campaign.client_id == ids["client"], Campaign.client_name == "MS"))).scalars().all()
        assert renamed and all(c.name.startswith("MS ") and "Nike" not in (c.description or "") for c in renamed)
        shops = (await s.execute(select(Shop).where(Shop.campaign_id.in_([c.id for c in renamed])))).scalars().all()
        assert shops and not any("Nike" in sh.shop_name for sh in shops)
        shopper = await s.get(Shopper, ids["shopper"])
        assert shopper.previous_clients == ["Starbucks", "MS"] and "Nike" not in shopper.experience_description
        # Decoys untouched.
        assert (await s.get(Campaign, ids["other_brand"])).client_name == "Dunkin'"
        assert (await s.get(Campaign, ids["rival_campaign"])).name == "Nike Realty Audit"

        # One-shot: nothing left to do the second time.
        assert await rename_demo_client(s) is False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        ok = await c.post("/api/auth/login", json={"email": NEW_EMAIL, "password": NEW_PASSWORD})
        old_email = await c.post("/api/auth/login", json={"email": OLD_EMAIL, "password": OLD_PASSWORD})
        old_password = await c.post("/api/auth/login", json={"email": NEW_EMAIL, "password": OLD_PASSWORD})
        assert ok.status_code == 200 and old_email.status_code == 401 and old_password.status_code == 401


@pytest.mark.asyncio
async def test_a_fresh_database_is_already_ms_and_nothing_is_renamed():
    await _fresh_db()
    async with AsyncSessionLocal() as s:
        assert await rename_demo_client(s) is False
        assert await s.scalar(select(User).where(User.email == NEW_EMAIL)) is not None
        assert (await s.scalar(select(Client).where(Client.company_name == "MS"))) is not None
        assert (await s.scalar(select(Client).where(Client.company_name == "Nike"))) is None


@pytest.mark.asyncio
async def test_a_renamed_login_with_the_old_default_password_moves_to_the_ms_password():
    await _fresh_db()
    async with AsyncSessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == NEW_EMAIL))
        user.password_hash = hash_password(OLD_PASSWORD)  # renamed earlier, password not yet
        await s.commit()
    async with AsyncSessionLocal() as s:
        assert await refresh_demo_client_password(s) is True
        await s.commit()
    async with AsyncSessionLocal() as s:
        assert await refresh_demo_client_password(s) is False  # once only
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.post("/api/auth/login", json={"email": NEW_EMAIL, "password": NEW_PASSWORD})).status_code == 200
        assert (await c.post("/api/auth/login", json={"email": NEW_EMAIL, "password": OLD_PASSWORD})).status_code == 401


@pytest.mark.asyncio
async def test_a_password_someone_chose_is_never_overwritten():
    await _fresh_db()
    async with AsyncSessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == NEW_EMAIL))
        user.password_hash = hash_password("my-own-password-1")
        await s.commit()
    async with AsyncSessionLocal() as s:
        assert await refresh_demo_client_password(s) is False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.post("/api/auth/login", json={"email": NEW_EMAIL, "password": "my-own-password-1"})).status_code == 200


def test_the_app_shell_is_never_served_from_a_stale_browser_cache(tmp_path, monkeypatch):
    """After a deploy, index.html must be revalidated (so the new login page and its hints show up), while hashed
    build assets can be cached for good."""
    from fastapi.testclient import TestClient

    from app import main as app_main

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    monkeypatch.setattr(app_main, "STATIC_DIR", str(tmp_path))
    monkeypatch.setattr(app_main, "INDEX_HTML", str(tmp_path / "index.html"))
    with TestClient(app_main.app) as client:  # runs startup against the test database
        shell = client.get("/login")
        asset = client.get("/assets/index-abc123.js")
    assert shell.status_code == 200 and shell.headers["cache-control"] == "no-cache"
    assert "immutable" in asset.headers["cache-control"]
