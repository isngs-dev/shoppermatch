"""ISN Admin report + export endpoints — /api/reports/*.

Technical/internal fields (SendGrid delivery status, automation state,
integration status, recent audit activity) only ever appear through this
admin-gated router, never through /api/client/reports* (see
`services/reports.py::build_campaign_report`'s `admin` flag and
`client_portal.py`'s client-safe export endpoint).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_admin
from ..models import Campaign, User
from ..services import exporters, reports

router = APIRouter(prefix="/api/reports", tags=["Reports"])


async def _require_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    stmt = select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.shops))
    campaign = (await session.execute(stmt)).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.get("/campaigns/{campaign_id}")
async def campaign_report(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    campaign = await _require_campaign(session, campaign_id)
    return await reports.build_campaign_report(session, campaign, admin=True)


@router.get("/campaigns/{campaign_id}/export")
async def export_campaign_report(
    campaign_id: uuid.UUID,
    format: str = Query(default="pdf", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    campaign = await _require_campaign(session, campaign_id)
    report = await reports.build_campaign_report(session, campaign, admin=True)
    content = exporters.EXPORTERS[format](report)
    filename = f"{campaign.name.replace(' ', '_')}_admin_report.{format}"
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
