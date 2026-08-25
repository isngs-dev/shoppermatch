"""SASSIE integration: adapter interface + demo provider + sync service.

Architecture (per spec):

    FastAPI Router  ->  SassieIntegrationService  ->  SassieClient  ->  PostgreSQL Repository

`SassieClient` is the adapter boundary. `RealSassieClient` calls an actually-
configured SASSIE-compatible HTTP API and never fabricates a response.
`MockSassieClient` is the demo provider — a small, clearly-synthetic,
deterministic dataset (tagged source="sassie", distinct external_ids) so the
whole pipeline (sync -> Campaigns -> AI Recommendations -> Outreach ->
Tracking) is demonstrable without real SASSIE credentials, while never being
reported to the UI as a real CONNECTED state (see IntegrationStatus.DEMO).
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models import Campaign, Shop, Shopper, SyncLog


# --------------------------------------------------------------------------- #
# Adapter interface
# --------------------------------------------------------------------------- #
class SassieClient(ABC):
    @abstractmethod
    async def test_connection(self) -> dict: ...

    @abstractmethod
    async def fetch_campaigns(self) -> list[dict]: ...

    @abstractmethod
    async def fetch_shops(self) -> list[dict]: ...

    @abstractmethod
    async def fetch_shoppers(self) -> list[dict]: ...

    @abstractmethod
    async def fetch_assignments(self) -> list[dict]: ...


class RealSassieClient(SassieClient):
    """Talks to an actually-configured SASSIE-compatible HTTP API. Only used
    when SASSIE_API_BASE_URL is set. Real docs/credentials were not
    available while building this, so the exact paths below are a
    best-effort REST convention — this is the one piece to adjust against
    real SASSIE API documentation; nothing else in the pipeline changes."""

    def __init__(self, base_url: str, api_key: str | None, client_id: str | None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_id = client_id

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.client_id:
            headers["X-Client-Id"] = self.client_id
        return headers

    async def test_connection(self) -> dict:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
            return {
                "connected": resp.status_code < 400,
                "status_code": resp.status_code,
                "detail": "Reached the configured SASSIE API." if resp.status_code < 400 else resp.text[:300],
            }
        except Exception as exc:  # noqa: BLE001 — report, don't crash the request
            return {"connected": False, "detail": f"Could not reach SASSIE API: {exc}"}

    async def _get(self, path: str) -> list[dict]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self.base_url}{path}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def fetch_campaigns(self) -> list[dict]:
        return await self._get("/campaigns")

    async def fetch_shops(self) -> list[dict]:
        return await self._get("/shops")

    async def fetch_shoppers(self) -> list[dict]:
        return await self._get("/shoppers")

    async def fetch_assignments(self) -> list[dict]:
        return await self._get("/assignments")


class MockSassieClient(SassieClient):
    """Demo provider behind the same interface. Fixed, deterministic dataset
    — repeated syncs fetch the same records (idempotent upsert), and it is
    entirely separate from the existing 50-shopper demo cohort (different
    client, different external_ids, source="sassie" vs "demo")."""

    async def test_connection(self) -> dict:
        return {"connected": True, "detail": "Demo SASSIE adapter responding (no external API configured)."}

    async def fetch_campaigns(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            {
                "external_id": "SASSIE-CAMP-1001",
                "name": "Walmart Store Experience Audit",
                "client": "Walmart",
                "description": "Multi-region retail experience and compliance audit sourced from SASSIE.",
                "status": "active",
                "start_date": (now - timedelta(days=5)).isoformat(),
                "end_date": (now + timedelta(days=25)).isoformat(),
            },
            {
                "external_id": "SASSIE-CAMP-1002",
                "name": "Walmart Pune Upcoming Rollout",
                "client": "Walmart",
                "description": "Upcoming rollout audit for newly opened Pune-region stores.",
                "status": "upcoming",
                "start_date": (now + timedelta(days=20)).isoformat(),
                "end_date": (now + timedelta(days=40)).isoformat(),
            },
        ]

    async def fetch_shops(self) -> list[dict]:
        return [
            {
                "external_id": "SASSIE-SHOP-2001",
                "campaign_external_id": "SASSIE-CAMP-1001",
                "name": "Walmart Mumbai — Kurla",
                "address": "12 Kurla High Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "latitude": 19.0728,
                "longitude": 72.8826,
                "category": "Grocery",
                "required_shoppers": 2,
            },
            {
                "external_id": "SASSIE-SHOP-2002",
                "campaign_external_id": "SASSIE-CAMP-1001",
                "name": "Walmart Pune — Hadapsar",
                "address": "45 Hadapsar Main Road",
                "city": "Pune",
                "state": "Maharashtra",
                "latitude": 18.5089,
                "longitude": 73.9260,
                "category": "Grocery",
                "required_shoppers": 2,
            },
            {
                "external_id": "SASSIE-SHOP-2003",
                "campaign_external_id": "SASSIE-CAMP-1001",
                "name": "Walmart Nashik — Panchavati",
                "address": "8 Panchavati Circle",
                "city": "Nashik",
                "state": "Maharashtra",
                "latitude": 20.0059,
                "longitude": 73.7903,
                "category": "Grocery",
                "required_shoppers": 1,
            },
            {
                "external_id": "SASSIE-SHOP-2004",
                "campaign_external_id": "SASSIE-CAMP-1002",
                "name": "Walmart Pune — Wakad (New)",
                "address": "3 Wakad Bypass",
                "city": "Pune",
                "state": "Maharashtra",
                "latitude": 18.5978,
                "longitude": 73.7649,
                "category": "Grocery",
                "required_shoppers": 2,
            },
        ]

    async def fetch_shoppers(self) -> list[dict]:
        names_cities = [
            ("Anita Kulkarni", "Mumbai", 19.0821, 72.8416),
            ("Rakesh Pillai", "Mumbai", 19.0330, 72.8697),
            ("Sunita Rao", "Pune", 18.5314, 73.8446),
            ("Deepa Nayak", "Pune", 18.5642, 73.9124),
            ("Vishal Oberoi", "Nashik", 19.9615, 73.7929),
            ("Farida Sheikh", "Mumbai", 19.1136, 72.8697),
            ("Om Prakash", "Pune", 18.4967, 73.8306),
            ("Latika Menon", "Nashik", 20.0208, 73.7644),
            ("Sameer Dutta", "Mumbai", 19.1663, 72.8526),
            ("Radhika Iyengar", "Pune", 18.5511, 73.7799),
        ]
        shoppers = []
        for i, (name, city, lat, lon) in enumerate(names_cities, start=1):
            shoppers.append(
                {
                    "external_id": f"SASSIE-SHOPPER-{3000 + i}",
                    "name": name,
                    "email": "vinithshetty96@gmail.com",  # same controlled test inbox as the rest of the demo
                    "city": city,
                    "state": "Maharashtra",
                    "latitude": lat,
                    "longitude": lon,
                    "categories": ["Grocery", "Retail"],
                    "availability_status": "available" if i % 4 != 0 else "limited",
                    "rating": round(3.6 + (i % 5) * 0.28, 1),
                    "completion_rate": round(0.72 + (i % 6) * 0.045, 3),
                    "previous_assignments": (i * 3) % 22,
                    "previous_clients": ["Walmart"] if i % 2 == 0 else ["Walmart", "Amazon"],
                }
            )
        return shoppers

    async def fetch_assignments(self) -> list[dict]:
        # Not consumed by sync_assignments in this demo — assignments map
        # 1:1 onto ShopperMatch's own Invitation lifecycle once outreach is
        # sent, so there is nothing external to reconcile here yet.
        return []


def get_sassie_client(config: dict) -> SassieClient:
    """Chooses the real adapter when SASSIE_API_BASE_URL is actually
    configured, the demo adapter otherwise. Never silently swaps a real
    connection for a fake one — the caller (test_connection/sync) is
    responsible for reporting DEMO vs CONNECTED honestly."""
    base_url = config.get("api_base_url") or settings.sassie_api_base_url
    if base_url:
        return RealSassieClient(
            base_url=base_url,
            api_key=config.get("_secret_api_key") or settings.sassie_api_key,
            client_id=config.get("client_id") or settings.sassie_client_id,
        )
    return MockSassieClient()


STATUS_MAP = {"active": "active", "upcoming": "upcoming", "completed": "completed"}


async def sync_campaigns(session: AsyncSession, campaigns: list[dict], log: SyncLog) -> dict[str, str]:
    """Upsert by (source='sassie', external_id). Returns {external_id: campaign_uuid}."""
    id_map: dict[str, str] = {}
    log.campaigns_fetched = len(campaigns)
    for c in campaigns:
        ext_id = c["external_id"]
        existing = (
            await session.execute(
                select(Campaign).where(Campaign.source == "sassie", Campaign.external_id == ext_id)
            )
        ).scalar_one_or_none()
        end_date = c.get("end_date")
        deadline = datetime.fromisoformat(end_date) if end_date else None

        if existing is None:
            existing = Campaign(
                id=uuid.uuid4(),
                source="sassie",
                external_id=ext_id,
                name=c["name"],
                client_name=c["client"],
                description=c.get("description"),
                status=STATUS_MAP.get(c.get("status"), "active"),
                deadline=deadline,
            )
            session.add(existing)
            log.campaigns_created += 1
        else:
            existing.name = c["name"]
            existing.client_name = c["client"]
            existing.description = c.get("description")
            existing.status = STATUS_MAP.get(c.get("status"), existing.status)
            existing.deadline = deadline
            log.campaigns_updated += 1

        await session.flush()
        id_map[ext_id] = existing.id
    return id_map


async def sync_shops(session: AsyncSession, shops: list[dict], campaign_id_map: dict[str, str], log: SyncLog) -> dict[str, str]:
    id_map: dict[str, str] = {}
    log.shops_fetched = len(shops)
    for s in shops:
        ext_id = s["external_id"]
        campaign_id = campaign_id_map.get(s["campaign_external_id"])
        if campaign_id is None:
            log.errors = [*(log.errors or []), f"Shop {ext_id} references unknown campaign {s['campaign_external_id']}"]
            continue

        existing = (
            await session.execute(select(Shop).where(Shop.source == "sassie", Shop.external_id == ext_id))
        ).scalar_one_or_none()

        if existing is None:
            existing = Shop(
                id=uuid.uuid4(),
                source="sassie",
                external_id=ext_id,
                campaign_id=campaign_id,
                shop_name=s["name"],
                address=s.get("address"),
                city=s.get("city"),
                state=s.get("state"),
                latitude=s.get("latitude"),
                longitude=s.get("longitude"),
                category=s.get("category"),
                required_shoppers=s.get("required_shoppers", 1),
                status="open",
            )
            session.add(existing)
            log.shops_created += 1
        else:
            # Never silently reassign a shop to a different campaign on sync.
            if existing.campaign_id != campaign_id:
                log.errors = [*(log.errors or []), f"Shop {ext_id} campaign mismatch — kept existing assignment"]
            existing.shop_name = s["name"]
            existing.address = s.get("address")
            existing.city = s.get("city")
            existing.state = s.get("state")
            existing.latitude = s.get("latitude")
            existing.longitude = s.get("longitude")
            existing.category = s.get("category")
            existing.required_shoppers = s.get("required_shoppers", existing.required_shoppers)
            log.shops_updated += 1

        await session.flush()
        id_map[ext_id] = existing.id
    return id_map


async def sync_shoppers(session: AsyncSession, shoppers: list[dict], log: SyncLog) -> None:
    log.shoppers_fetched = len(shoppers)
    for sh in shoppers:
        ext_id = sh["external_id"]
        existing = (
            await session.execute(
                select(Shopper).where(Shopper.source == "sassie", Shopper.external_id == ext_id)
            )
        ).scalar_one_or_none()

        if existing is None:
            existing = Shopper(
                id=uuid.uuid4(),
                shopper_code=ext_id,
                source="sassie",
                external_id=ext_id,
                name=sh["name"],
                email=sh["email"],
                city=sh.get("city"),
                state=sh.get("state"),
                latitude=sh.get("latitude"),
                longitude=sh.get("longitude"),
                categories=sh.get("categories", []),
                availability_status=sh.get("availability_status", "available"),
                rating=sh.get("rating", 0.0),
                completion_rate=sh.get("completion_rate", 0.0),
                previous_assignments=sh.get("previous_assignments", 0),
                previous_clients=sh.get("previous_clients", []),
                active=True,
            )
            session.add(existing)
            log.shoppers_created += 1
        else:
            existing.name = sh["name"]
            existing.city = sh.get("city")
            existing.state = sh.get("state")
            existing.latitude = sh.get("latitude")
            existing.longitude = sh.get("longitude")
            existing.categories = sh.get("categories", existing.categories)
            existing.availability_status = sh.get("availability_status", existing.availability_status)
            existing.rating = sh.get("rating", existing.rating)
            existing.completion_rate = sh.get("completion_rate", existing.completion_rate)
            existing.previous_assignments = sh.get("previous_assignments", existing.previous_assignments)
            existing.previous_clients = sh.get("previous_clients", existing.previous_clients)
            log.shoppers_updated += 1

        await session.flush()
        # Every synced shopper is immediately visible to the AI recommendation
        # engine — it queries the Shopper table directly on every request, so
        # there is no separate embedding index to rebuild (see semantic_matching.py).


async def run_sync(session: AsyncSession, client: SassieClient, log: SyncLog) -> None:
    campaigns = await client.fetch_campaigns()
    campaign_id_map = await sync_campaigns(session, campaigns, log)

    shops = await client.fetch_shops()
    await sync_shops(session, shops, campaign_id_map, log)

    shoppers = await client.fetch_shoppers()
    await sync_shoppers(session, shoppers, log)

    # Recompute each synced campaign's shop-completion counters from the
    # shops that now exist (mirrors the existing seed scripts' convention).
    for campaign_id in campaign_id_map.values():
        shops_result = await session.execute(select(Shop).where(Shop.campaign_id == campaign_id))
        campaign_shops = shops_result.scalars().all()
        campaign = await session.get(Campaign, campaign_id)
        if campaign:
            campaign.total_shops = len(campaign_shops)
