"""CRUD for reusable, PostgreSQL-backed email templates used by the
Outreach composer's Template dropdown and "Save as Template" action."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import require_operator
from ..models import EmailTemplate, User
from ..serializers import iso

router = APIRouter(prefix="/api/email-templates", tags=["Email Templates"])


class EmailTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=500)
    html_body: str = Field(min_length=1)
    active: bool = True


class EmailTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    html_body: str | None = None
    active: bool | None = None


def _out(t: EmailTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "subject": t.subject,
        "html_body": t.html_body,
        "active": t.active,
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
    }


@router.get("")
async def list_templates(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    stmt = select(EmailTemplate).order_by(EmailTemplate.updated_at.desc())
    templates = (await session.execute(stmt)).scalars().all()
    return {"items": [_out(t) for t in templates], "total": len(templates)}


@router.post("")
async def create_template(
    body: EmailTemplateIn,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    t = EmailTemplate(name=body.name, subject=body.subject, html_body=body.html_body, active=body.active)
    session.add(t)
    await session.commit()
    return _out(t)


@router.put("/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    body: EmailTemplateUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    t = await session.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    for field in ("name", "subject", "html_body", "active"):
        value = getattr(body, field)
        if value is not None:
            setattr(t, field, value)
    await session.commit()
    return _out(t)


@router.post("/{template_id}/duplicate")
async def duplicate_template(
    template_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    t = await session.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    copy = EmailTemplate(name=f"{t.name} (Copy)", subject=t.subject, html_body=t.html_body, active=t.active)
    session.add(copy)
    await session.commit()
    return _out(copy)


@router.delete("/{template_id}")
async def delete_template(
    template_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    t = await session.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await session.delete(t)
    await session.commit()
    return {"deleted": True}
