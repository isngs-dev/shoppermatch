"""ISN Admin — User Management (spec section 25/26): client-portal logins
and the shopper directory, each with real activity stats aggregated from
`invitations` — no second identity table, no fabricated numbers. Exports
never include `password_hash` or any other secret (the row dicts built here
never read that column in the first place)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..deps import require_admin
from ..models import AuditLog, Campaign, Client, Invitation, Shopper, User
from ..schemas import AdminCreateClientRequest
from ..security import hash_password
from ..serializers import iso
from ..services import exporters
from ..services.audit import record_audit

router = APIRouter(prefix="/api/admin/users", tags=["Admin User Management"])


def _as_report(title: str, headers: list[str], rows: list[list]) -> dict:
    return {
        "title": title,
        "subtitle": "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": [("Total rows", len(rows))],
        "sections": [],
        "tables": [(title, headers, rows)],
    }


async def _client_user_items(session: AsyncSession) -> list[dict]:
    stmt = select(User).where(User.role == "client").options(selectinload(User.client))
    users = (await session.execute(stmt)).scalars().all()

    campaign_counts = dict(
        (await session.execute(select(Campaign.client_id, func.count(Campaign.id)).group_by(Campaign.client_id))).all()
    )
    outreach_counts = dict(
        (
            await session.execute(
                select(Campaign.client_id, func.count(Invitation.id))
                .join(Invitation, Invitation.campaign_id == Campaign.id)
                .group_by(Campaign.client_id)
            )
        ).all()
    )

    items = []
    for u in users:
        items.append(
            {
                "id": str(u.id),
                "company": u.client.company_name if u.client else None,
                "email": u.email,
                "role": u.role,
                "status": u.client.status if u.client else "unknown",
                "last_login": iso(u.last_login_at),
                "campaign_count": campaign_counts.get(u.client_id, 0),
                "outreach_activity": outreach_counts.get(u.client_id, 0),
            }
        )
    return items


async def _shopper_user_items(session: AsyncSession) -> list[dict]:
    shoppers = (await session.execute(select(Shopper))).scalars().all()

    agg_stmt = select(
        Invitation.shopper_id,
        func.count(Invitation.id),
        func.sum(case((Invitation.response == "accepted", 1), else_=0)),
        func.sum(case((Invitation.response == "declined", 1), else_=0)),
        func.count(func.distinct(Invitation.campaign_id)),
        func.max(Invitation.responded_at),
        func.max(Invitation.created_at),
    ).group_by(Invitation.shopper_id)
    by_shopper = {row[0]: row for row in (await session.execute(agg_stmt)).all()}

    items = []
    for s in shoppers:
        row = by_shopper.get(s.id)
        assignments = int(row[1]) if row else 0
        accepts = int(row[2] or 0) if row else 0
        declines = int(row[3] or 0) if row else 0
        campaigns_invited = int(row[4]) if row else 0
        last_activity = (row[5] or row[6]) if row else None
        items.append(
            {
                "id": str(s.id),
                "name": s.name,
                "email": s.email,
                "location": ", ".join(filter(None, [s.city, s.state])) or None,
                "status": s.availability_status,
                "campaigns_invited": campaigns_invited,
                "assignments": assignments,
                "accepts": accepts,
                "declines": declines,
                "last_activity": iso(last_activity),
            }
        )
    return items


@router.get("/clients")
async def list_client_users(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin)):
    items = await _client_user_items(session)
    return {"items": items, "total": len(items)}


@router.post("/clients")
async def create_client_user(
    body: AdminCreateClientRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """ISN admin provisions a client-portal login directly (as opposed to the
    client self-registering via /api/auth/register). The client can change
    this password themselves afterwards from their Profile page."""
    email = str(body.email).lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    client = Client(
        company_name=body.company_name.strip(),
        contact_name=body.contact_name.strip(),
        contact_email=email,
        status="active",
    )
    session.add(client)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A client account with this company name already exists.")

    new_user = User(
        name=body.contact_name.strip(),
        email=email,
        role="client",
        client_id=client.id,
        password_hash=hash_password(body.password),
    )
    new_user.client = client
    session.add(new_user)
    await session.flush()

    await record_audit(
        session,
        action="client.created_by_admin",
        actor=user.email,
        entity_type="client",
        entity_id=str(client.id),
        summary=f"Client account created by ISN admin: {body.company_name} ({email})",
        meta={"company_name": body.company_name},
    )
    await session.commit()
    return {
        "id": str(new_user.id),
        "client_id": str(client.id),
        "company_name": client.company_name,
        "email": new_user.email,
    }


@router.get("/clients/export")
async def export_client_users(
    format: str = Query(default="csv", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    items = await _client_user_items(session)
    headers = ["Company", "Email", "Role", "Status", "Last Login", "Campaigns", "Outreach Activity"]
    rows = [[i["company"], i["email"], i["role"], i["status"], i["last_login"] or "never", i["campaign_count"], i["outreach_activity"]] for i in items]
    report = _as_report("ISN Admin — Client Users", headers, rows)
    content = exporters.EXPORTERS[format](report)
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="client_users.{format}"'},
    )


@router.get("/shoppers")
async def list_shopper_users(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin)):
    items = await _shopper_user_items(session)
    return {"items": items, "total": len(items)}


@router.get("/shoppers/export")
async def export_shopper_users(
    format: str = Query(default="csv", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    items = await _shopper_user_items(session)
    headers = ["Name", "Email", "Location", "Status", "Campaigns Invited", "Assignments", "Accepts", "Declines", "Last Activity"]
    rows = [
        [i["name"], i["email"], i["location"] or "—", i["status"], i["campaigns_invited"], i["assignments"], i["accepts"], i["declines"], i["last_activity"] or "—"]
        for i in items
    ]
    report = _as_report("ISN Admin — Shopper Directory", headers, rows)
    content = exporters.EXPORTERS[format](report)
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="shopper_users.{format}"'},
    )


@router.get("/export-all")
async def export_all_users(
    format: str = Query(default="csv", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Spec section 26: 'Export All Users' — both rosters in one file, still
    never including passwords/API keys/tokens/secrets."""
    client_items = await _client_user_items(session)
    shopper_items = await _shopper_user_items(session)
    report = {
        "title": "ISN Admin — All Users",
        "subtitle": "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": [("Client Users", len(client_items)), ("Shoppers", len(shopper_items))],
        "sections": [],
        "tables": [
            (
                "Client Users",
                ["Company", "Email", "Role", "Status", "Last Login", "Campaigns", "Outreach Activity"],
                [[i["company"], i["email"], i["role"], i["status"], i["last_login"] or "never", i["campaign_count"], i["outreach_activity"]] for i in client_items],
            ),
            (
                "Shopper Directory",
                ["Name", "Email", "Location", "Status", "Campaigns Invited", "Assignments", "Accepts", "Declines", "Last Activity"],
                [
                    [i["name"], i["email"], i["location"] or "—", i["status"], i["campaigns_invited"], i["assignments"], i["accepts"], i["declines"], i["last_activity"] or "—"]
                    for i in shopper_items
                ],
            ),
        ],
    }
    content = exporters.EXPORTERS[format](report)
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="all_users.{format}"'},
    )


# --------------------------------------------------------------------------- #
# Client Activity Report (spec ask: "track every client's activity on the ISN
# admin page"). Reuses the exact same `audit_logs` table every other action in
# the app already writes to via record_audit(actor=user.email) — this is a
# client-focused *view* over that data, not a second logging system.
# --------------------------------------------------------------------------- #
async def _client_activity_items(session: AsyncSession) -> list[dict]:
    stmt = select(User).where(User.role == "client").options(selectinload(User.client))
    users = (await session.execute(stmt)).scalars().all()
    if not users:
        return []

    emails = [u.email for u in users]
    count_rows = dict(
        (
            await session.execute(
                select(AuditLog.actor, func.count(AuditLog.id)).where(AuditLog.actor.in_(emails)).group_by(AuditLog.actor)
            )
        ).all()
    )
    last_rows = dict(
        (
            await session.execute(
                select(AuditLog.actor, func.max(AuditLog.created_at)).where(AuditLog.actor.in_(emails)).group_by(AuditLog.actor)
            )
        ).all()
    )
    # One extra query per actor for the summary text of their most recent
    # action — cheap at demo scale, and keeps the two aggregates above as
    # simple GROUP BYs instead of a window-function query.
    latest_summary: dict[str, AuditLog] = {}
    for email, last_at in last_rows.items():
        if last_at is None:
            continue
        row = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.actor == email, AuditLog.created_at == last_at)
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if row is not None:
            latest_summary[email] = row

    items = []
    for u in users:
        last_log = latest_summary.get(u.email)
        items.append(
            {
                "user_id": str(u.id),
                "client_id": str(u.client_id) if u.client_id else None,
                "company": u.client.company_name if u.client else None,
                "email": u.email,
                "status": u.client.status if u.client else "unknown",
                "last_login": iso(u.last_login_at),
                "action_count": int(count_rows.get(u.email, 0)),
                "last_action": last_log.action if last_log else None,
                "last_action_summary": last_log.summary if last_log else None,
                "last_action_at": iso(last_log.created_at) if last_log else None,
            }
        )
    items.sort(key=lambda i: i["last_action_at"] or "", reverse=True)
    return items


@router.get("/clients/activity-summary")
async def client_activity_summary(session: AsyncSession = Depends(get_session), user: User = Depends(require_admin)):
    items = await _client_activity_items(session)
    return {"items": items, "total": len(items)}


@router.get("/clients/activity-summary/export")
async def export_client_activity_summary(
    format: str = Query(default="pdf", pattern="^(csv|xlsx|pdf)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    items = await _client_activity_items(session)
    headers = ["Company", "Status", "Last Login", "Actions", "Most Recent Activity"]
    rows = [
        [
            i["company"] or i["email"], i["status"],
            i["last_login"][:16].replace("T", " ") if i["last_login"] else "never",
            i["action_count"],
            (i["last_action_summary"][:70] + "…") if i["last_action_summary"] and len(i["last_action_summary"]) > 70 else (i["last_action_summary"] or "—"),
        ]
        for i in items
    ]
    report = _as_report("ISN Admin — Client Activity", headers, rows)
    report["kpis"] = [
        ("Client Logins", len(items)),
        ("Active Accounts", sum(1 for i in items if i["status"] == "active")),
        ("Total Actions Logged", sum(i["action_count"] for i in items)),
    ]
    content = exporters.EXPORTERS[format](report)
    return Response(
        content=content,
        media_type=exporters.MIME_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="client_activity.{format}"'},
    )


@router.get("/clients/{client_id}/activity")
async def client_activity_detail(
    client_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    client_users = (
        await session.execute(select(User).where(User.client_id == client_id, User.role == "client"))
    ).scalars().all()
    if not client_users:
        raise HTTPException(status_code=404, detail="Client not found or has no portal login")
    emails = [u.email for u in client_users]

    logs = (
        await session.execute(
            select(AuditLog).where(AuditLog.actor.in_(emails)).order_by(AuditLog.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    client = await session.get(Client, client_id)
    return {
        "client_id": client_id,
        "company_name": client.company_name if client else None,
        "items": [
            {
                "id": str(a.id),
                "actor": a.actor,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "summary": a.summary,
                "created_at": iso(a.created_at),
                "meta": a.meta or {},
            }
            for a in logs
        ],
        "total": len(logs),
    }
