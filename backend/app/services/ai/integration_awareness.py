"""Phase 28 — Integration awareness.

AI outputs must never claim an integration is connected when it isn't, and
must warn when stale/broken integrations could affect the accuracy of an AI
result. This module only reads `IntegrationConfig` + `SyncLog` (both already
maintained by the existing Integration Hub) — it never guesses a status.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IntegrationConfig, IntegrationStatus, SyncLog


async def integration_notes(session: AsyncSession) -> list[str]:
    notes: list[str] = []

    configs = {
        c.provider: c
        for c in (await session.execute(select(IntegrationConfig))).scalars().all()
    }

    sassie = configs.get("sassie")
    if sassie:
        last_sync = (
            await session.execute(
                select(SyncLog)
                .where(SyncLog.provider == "sassie")
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_sync and last_sync.status in ("failed", "partial"):
            notes.append(
                "Shopper and campaign data may be stale because the latest SASSIE "
                f"synchronization {last_sync.status}."
            )
        elif sassie.status == IntegrationStatus.DEMO:
            notes.append(
                "SASSIE is running in demo mode — shopper/campaign records are the "
                "existing local database, not a live external feed."
            )

    email = configs.get("email")
    if email and email.status in (IntegrationStatus.DISCONNECTED, IntegrationStatus.CONFIGURATION_REQUIRED, IntegrationStatus.ERROR):
        notes.append("Outreach cannot be sent until the Email integration is restored.")

    maps = configs.get("maps")
    if maps and maps.status != IntegrationStatus.CONNECTED:
        notes.append("Distance-based matching is using coordinate-based calculation (Google Maps is not connected).")

    sms = configs.get("sms")
    if sms and sms.status in (IntegrationStatus.DISCONNECTED, IntegrationStatus.CONFIGURATION_REQUIRED, IntegrationStatus.ERROR):
        notes.append("SMS outreach is unavailable until the SMS integration is configured.")

    return notes
