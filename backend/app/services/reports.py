"""Shared reporting data layer.

Builds one format-agnostic `Report` dict (kpis + sections + tables) per
campaign, for both the Client Portal and ISN Admin. All the underlying
numbers are pulled through the exact same helpers the on-screen dashboards
already use (`_campaign_outreach`, `_campaign_shops_with_coverage`,
`campaign_predictor`) — this module only re-shapes them for export, it never
recomputes a metric a different way. `services/exporters.py` turns this one
structure into CSV/XLSX/PDF, so there is exactly one place that assembles
report content and one place that formats it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AuditLog,
    Campaign,
    EmailAutomation,
    EmailJob,
    Invitation,
    IntegrationConfig,
)
from ..routers.campaigns import (
    _campaign_outreach,
    _campaign_shops_with_coverage,
    _start_date,
    status_bucket,
)
from .ai import campaign_predictor


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100) if denominator else 0


async def build_campaign_report(session: AsyncSession, campaign: Campaign, *, admin: bool) -> dict:
    """Returns {title, subtitle, generated_at, kpis, sections, tables}.

    `admin=False` produces the client-safe report (no shopper identity, no
    provider/technical detail — same fields client_portal.reports() already
    exposes). `admin=True` adds the technical section from spec section 23:
    SendGrid delivery status, automation state, integration status, recent
    audit activity — never shown to the client report.
    """
    bucket = status_bucket(campaign.status)
    outreach = await _campaign_outreach(session, campaign.id)
    shops = await _campaign_shops_with_coverage(session, campaign.id)
    required = sum(s["required_shoppers"] for s in shops)

    kpis = [
        ("Total Shops", campaign.total_shops or 0),
        ("Completed Shops", campaign.completed_shops or 0),
        ("Completion Rate", f"{round((campaign.completed_shops / campaign.total_shops) * 100) if campaign.total_shops else 0}%"),
        ("Required Shoppers", required),
        ("Confirmed Shoppers", outreach["accepted"]),
        ("Response Rate", f"{_rate(outreach['accepted'] + outreach['declined'], outreach['sent'])}%"),
    ]

    outreach_table_headers = ["Metric", "Count"]
    outreach_table_rows = [
        ["Sent", outreach["sent"]],
        ["Delivered", outreach["delivered"]],
        ["Opened", outreach["opened"]],
        ["Clicked", outreach["clicked"]],
        ["Accepted", outreach["accepted"]],
        ["Declined", outreach["declined"]],
        ["Delivery Rate", f"{_rate(outreach['delivered'], outreach['sent'])}%"],
        ["Open Rate", f"{_rate(outreach['opened'], outreach['delivered'])}%"],
        ["Click Rate", f"{_rate(outreach['clicked'], outreach['opened'])}%"],
    ]

    shop_table_headers = ["Shop", "City", "Required", "Invited", "Coverage", "Status"]
    shop_table_rows = [
        [s["shop_name"], s["city"] or "—", s["required_shoppers"], s["invited_shoppers"], s["coverage"], s["status"]]
        for s in shops
    ]

    sections = [("Campaign", [
        ("Client", campaign.client_name),
        ("Status", campaign.status),
        ("Bucket", bucket),
        ("Start Date", _start_date(campaign)),
        ("Deadline", campaign.deadline.date().isoformat() if campaign.deadline else None),
    ])]

    tables = [
        ("Outreach Funnel", outreach_table_headers, outreach_table_rows),
        ("Shop Performance", shop_table_headers, shop_table_rows),
    ]

    if bucket == "completed":
        perf = await campaign_predictor.performance_summary(session, campaign)
        sections.append(("Completion Summary", [("AI Summary", perf["summary"])]))

    if admin:
        job_counts = dict(
            (
                await session.execute(
                    select(EmailJob.status, func.count(EmailJob.id))
                    .join(Invitation, Invitation.id == EmailJob.invitation_id)
                    .where(Invitation.campaign_id == campaign.id)
                    .group_by(EmailJob.status)
                )
            ).all()
        )
        delivery_table_rows = [[status, count] for status, count in sorted(job_counts.items())] or [["—", 0]]
        tables.append(("Email Delivery Status (SendGrid/Provider)", ["Status", "Count"], delivery_table_rows))

        automations = (
            await session.execute(select(EmailAutomation).where(EmailAutomation.campaign_id == campaign.id))
        ).scalars().all()
        automation_rows = [[a.name, a.status, a.wait_days, a.max_steps] for a in automations]
        if automation_rows:
            tables.append(("Automation State", ["Automation", "Status", "Wait Days", "Max Steps"], automation_rows))

        integrations = (await session.execute(select(IntegrationConfig))).scalars().all()
        tables.append(
            (
                "Integration Status",
                ["Provider", "Status", "Last Tested"],
                [[i.display_name, i.status, i.last_tested_at.isoformat() if i.last_tested_at else "never"] for i in integrations],
            )
        )

        recent_audit = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.entity_id == str(campaign.id))
                .order_by(AuditLog.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        if recent_audit:
            tables.append(
                (
                    "Recent Audit Activity",
                    ["Timestamp", "Actor", "Action", "Summary"],
                    [[a.created_at.isoformat(), a.actor, a.action, a.summary or ""] for a in recent_audit],
                )
            )

    return {
        "title": f"{campaign.name} — {'Admin' if admin else 'Client'} Report",
        "subtitle": campaign.client_name or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": kpis,
        "sections": sections,
        "tables": tables,
    }
