"""J. AI Data Quality Agent.

Read-only checks over the existing Shopper table — never modifies a record.
Flags are surfaced for human review (spec: "Do not modify records
automatically without confirmation").
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Shopper

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def run_data_quality_check(session: AsyncSession) -> dict:
    shoppers = (await session.execute(select(Shopper))).scalars().all()

    missing_experience: list[str] = []
    missing_location: list[str] = []
    invalid_email: list[str] = []
    incomplete_profile: list[str] = []

    seen_name_city: dict[tuple, list[str]] = {}
    seen_phone: dict[str, list[str]] = {}

    for s in shoppers:
        if not s.experience_description:
            missing_experience.append(s.name)
        if not s.city or not s.state or s.latitude is None or s.longitude is None:
            missing_location.append(s.name)
        if not s.email or not EMAIL_RE.match(s.email):
            invalid_email.append(s.name)
        if not s.categories or not s.rating:
            incomplete_profile.append(s.name)

        key = ((s.name or "").strip().lower(), (s.city or "").strip().lower())
        if key[0] and key[1]:
            seen_name_city.setdefault(key, []).append(s.name)
        if s.phone:
            seen_phone.setdefault(s.phone, []).append(s.name)

    duplicates = [names for names in seen_name_city.values() if len(names) > 1]
    duplicates += [names for names in seen_phone.values() if len(names) > 1]

    return {
        "total_shoppers": len(shoppers),
        "alerts": [
            {
                "type": "missing_experience",
                "count": len(missing_experience),
                "message": f"{len(missing_experience)} shoppers have incomplete experience data.",
                "sample": missing_experience[:10],
            },
            {
                "type": "duplicate_records",
                "count": len(duplicates),
                "message": f"{len(duplicates)} record groups appear potentially duplicated.",
                "sample": [names for names in duplicates[:5]],
            },
            {
                "type": "missing_location",
                "count": len(missing_location),
                "message": f"{len(missing_location)} shopper locations require review.",
                "sample": missing_location[:10],
            },
            {
                "type": "invalid_email",
                "count": len(invalid_email),
                "message": f"{len(invalid_email)} shoppers have an invalid or missing email address.",
                "sample": invalid_email[:10],
            },
            {
                "type": "incomplete_profile",
                "count": len(incomplete_profile),
                "message": f"{len(incomplete_profile)} shoppers have an incomplete profile (missing categories or rating).",
                "sample": incomplete_profile[:10],
            },
        ],
    }
