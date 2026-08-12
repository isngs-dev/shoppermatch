"""Basic audit logging helper."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog


async def record_audit(
    session: AsyncSession,
    action: str,
    actor: str = "system",
    entity_type: str | None = None,
    entity_id: str | None = None,
    summary: str | None = None,
    meta: dict | None = None,
) -> AuditLog:
    log = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        meta=meta or {},
    )
    session.add(log)
    return log
