"""AI Orchestrator — one router fronting the services/ai/* modules. Every
endpoint here reads from (and, where explicitly noted, writes to) the
existing Campaign/Shop/Shopper/Invitation tables. Nothing here maintains a
separate dataset.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import require_admin, require_operator
from ..models import Campaign, Shop, Shopper, User
from ..services.audit import record_audit
from ..services.semantic_matching import haversine_km
from ..services.tenancy import enforce_campaign_access
from ..services.ai import (
    acceptance_predictor,
    anomaly_detector,
    assignment_optimizer,
    campaign_predictor,
    data_quality,
    email_personalizer,
    insights_agent,
    integration_awareness,
    next_best_action,
    operations_engine,
    outreach_priority,
    report_analysis,
    requirement_parser,
    template_generator,
)
from ..services.semantic_matching import run_matching

router = APIRouter(prefix="/api/ai", tags=["AI"])


# --------------------------------------------------------------------------- #
# A. Campaign Requirement Parser
# --------------------------------------------------------------------------- #
class ParseRequirementsRequest(BaseModel):
    text: str
    campaign_id: str | None = None


@router.post("/parse-requirements")
async def parse_requirements(
    body: ParseRequirementsRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    result = requirement_parser.parse_requirements(body.text)

    if body.campaign_id:
        try:
            campaign = await session.get(Campaign, uuid.UUID(body.campaign_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid campaign_id")
        campaign = enforce_campaign_access(campaign, user)
        campaign.requirements_text = body.text
        campaign.parsed_requirements = result
        await record_audit(
            session,
            action="ai.requirements_parsed",
            actor=user.email,
            entity_type="campaign",
            entity_id=str(campaign.id),
            summary=f"AI parsed requirements for {campaign.name}",
            meta={"parsed_fields": result["parsed_fields"]},
        )
        await session.commit()

    return result


# --------------------------------------------------------------------------- #
# F. Acceptance Probability
# --------------------------------------------------------------------------- #
@router.get("/acceptance-probability")
async def acceptance_probability(
    shopper_id: uuid.UUID,
    shop_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_operator),
):
    shopper = await session.get(Shopper, shopper_id)
    if shopper is None:
        raise HTTPException(status_code=404, detail="Shopper not found")
    distance_km = None
    if shop_id:
        shop = await session.get(Shop, shop_id)
        if shop:
            distance_km = haversine_km(shopper.latitude, shopper.longitude, shop.latitude, shop.longitude)
    return await acceptance_predictor.predict_acceptance(session, shopper, distance_km)


# --------------------------------------------------------------------------- #
# Outreach prioritization — ranks candidates by who to contact first,
# combining match score, acceptance probability and campaign urgency.
# --------------------------------------------------------------------------- #
@router.get("/campaigns/{campaign_id}/shops/{shop_id}/outreach-priority")
async def outreach_priority_endpoint(
    campaign_id: uuid.UUID,
    shop_id: uuid.UUID,
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = enforce_campaign_access(await session.get(Campaign, campaign_id), user)
    shop = await session.get(Shop, shop_id)
    if shop is None or shop.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Shop not found in this campaign")

    shoppers = (await session.execute(select(Shopper))).scalars().all()
    parsed = (campaign.parsed_requirements or {}).get("parsed_fields", {}) if campaign.parsed_requirements else {}
    matched = run_matching(list(shoppers), shop, campaign, requirements=parsed)
    top = matched["recommendations"][: max(limit, 10)]

    ranked = await outreach_priority.prioritize_outreach(session, campaign, top)
    return {"items": ranked[:limit], "total": len(ranked)}


# --------------------------------------------------------------------------- #
# G/12/27/28. Campaign health / readiness / performance
# --------------------------------------------------------------------------- #
@router.get("/campaigns/{campaign_id}/health")
async def campaign_health_endpoint(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = enforce_campaign_access(await session.get(Campaign, campaign_id), user)
    result = await campaign_predictor.campaign_health(session, campaign)
    await record_audit(
        session,
        action="ai.campaign_prediction_generated",
        actor=user.email,
        entity_type="campaign",
        entity_id=str(campaign.id),
        summary=f"AI campaign readiness computed for {campaign.name}: {result['readiness']}%",
        meta={"readiness": result["readiness"]},
    )
    await session.commit()
    return result


@router.get("/campaigns/{campaign_id}/performance")
async def campaign_performance_endpoint(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = enforce_campaign_access(await session.get(Campaign, campaign_id), user)
    return await campaign_predictor.performance_summary(session, campaign)


# --------------------------------------------------------------------------- #
# D. Assignment Optimization (proposal only — never auto-assigns)
# --------------------------------------------------------------------------- #
@router.post("/campaigns/{campaign_id}/optimize-assignments")
async def optimize_assignments_endpoint(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = enforce_campaign_access(await session.get(Campaign, campaign_id), user)
    result = await assignment_optimizer.optimize_assignments(session, campaign)
    await record_audit(
        session,
        action="ai.assignment_optimization_generated",
        actor=user.email,
        entity_type="campaign",
        entity_id=str(campaign.id),
        summary=f"AI assignment proposal generated for {campaign.name}: {len(result['proposals'])} proposed",
        meta={"coverage": result["summary"]["coverage"]},
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# I. Anomaly detection
# --------------------------------------------------------------------------- #
@router.get("/anomalies")
async def anomalies_endpoint(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    flags = await anomaly_detector.detect_anomalies(session)
    if flags:
        await record_audit(
            session,
            action="ai.anomaly_detected",
            actor=user.email,
            entity_type="shopper",
            entity_id=None,
            summary=f"AI flagged {len(flags)} shopper(s) for review",
            meta={"count": len(flags)},
        )
        await session.commit()
    return {"items": flags, "total": len(flags)}


# --------------------------------------------------------------------------- #
# J. Data quality
# --------------------------------------------------------------------------- #
@router.get("/data-quality")
async def data_quality_endpoint(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    return await data_quality.run_data_quality_check(session)


# --------------------------------------------------------------------------- #
# K/L/M. Response feedback analysis (summarization, sentiment, QA)
# --------------------------------------------------------------------------- #
@router.get("/campaigns/{campaign_id}/feedback-analysis")
async def feedback_analysis_endpoint(
    campaign_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    campaign = enforce_campaign_access(await session.get(Campaign, campaign_id), user)
    notes = await report_analysis.collect_campaign_notes(session, campaign_id)
    summary = report_analysis.summarize_notes(notes)
    qa_flags = report_analysis.qa_flag_notes(notes)
    if notes:
        await record_audit(
            session,
            action="ai.report_summary_generated",
            actor=user.email,
            entity_type="campaign",
            entity_id=str(campaign.id),
            summary=f"AI summarized {len(notes)} feedback note(s) for {campaign.name}",
            meta={},
        )
        await session.commit()
    return {"notes": notes, "summary": summary, "qa_flags": qa_flags}


# --------------------------------------------------------------------------- #
# N/P. Natural language insights + Operations Assistant
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask_endpoint(
    body: AskRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    result = await insights_agent.answer_question(session, body.question)
    await record_audit(
        session,
        action="ai.insight_queried",
        actor=user.email,
        entity_type="insight",
        entity_id=None,
        summary=f"AI insight queried: {body.question[:150]}",
        meta={"intent": result.get("intent")},
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# O. Next best actions
# --------------------------------------------------------------------------- #
@router.get("/next-best-actions")
async def next_best_actions_endpoint(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    actions = await next_best_action.get_next_best_actions(session)
    return {"items": actions, "total": len(actions)}


# --------------------------------------------------------------------------- #
# Phase 23/26. AI Operations Engine + AI Action Center
# --------------------------------------------------------------------------- #
@router.get("/action-center")
async def action_center_endpoint(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    items = await operations_engine.campaign_action_items(session)
    notes = await integration_awareness.integration_notes(session)

    attention = [i for i in items if i["status"] == "attention"]
    if attention:
        await record_audit(
            session,
            action="ai.action_recommended",
            actor=user.email,
            entity_type="campaign",
            entity_id=None,
            summary=f"AI Action Center surfaced {len(attention)} campaign(s) needing attention",
            meta={"campaign_ids": [i["campaign_id"] for i in attention]},
        )
        await session.commit()

    return {"items": items, "needs_attention": len(attention), "integration_notes": notes}


# --------------------------------------------------------------------------- #
# E. Email personalization
# --------------------------------------------------------------------------- #
class PersonalizeEmailRequest(BaseModel):
    campaign_id: str
    shop_id: str
    shopper_id: str


@router.post("/personalize-email")
async def personalize_email_endpoint(
    body: PersonalizeEmailRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    try:
        campaign = await session.get(Campaign, uuid.UUID(body.campaign_id))
        shop = await session.get(Shop, uuid.UUID(body.shop_id))
        shopper = await session.get(Shopper, uuid.UUID(body.shopper_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    campaign = enforce_campaign_access(campaign, user)
    if not shop or not shopper:
        raise HTTPException(status_code=404, detail="Shop or shopper not found")

    result = email_personalizer.generate_personalized_email(shopper, campaign, shop)
    await record_audit(
        session,
        action="ai.email_generated",
        actor=user.email,
        entity_type="shopper",
        entity_id=str(shopper.id),
        summary=f"AI generated a personalized email draft for {shopper.name} ({campaign.name})",
        meta={},
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# Generate a reusable Email Template draft (Email Templates page "Generate
# with AI"). Unlike personalize-email above, this isn't tied to one
# invitation — it produces a generic {{token}}-based template the client can
# save, edit, and reuse across campaigns/automations.
# --------------------------------------------------------------------------- #
class GenerateTemplateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    tone: str = "professional"


@router.post("/generate-template")
async def generate_template_endpoint(
    body: GenerateTemplateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_operator),
):
    result = template_generator.generate_template_draft(body.goal, body.tone)
    await record_audit(
        session,
        action="ai.template_generated",
        actor=user.email,
        entity_type="email_template",
        entity_id=None,
        summary=f"AI generated a template draft: \"{result['name']}\"",
        meta={"goal": body.goal, "tone": result["tone"]},
    )
    await session.commit()
    return result
