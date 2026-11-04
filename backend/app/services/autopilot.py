"""AI Autopilot — recruits for every open shop on its own, inside guardrails.

For each shop that still needs shoppers it:
  1. asks the matching engine for exactly the shoppers needed;
  2. if there aren't enough, closes the gap the cheap way first — widen the radius (up to the guardrail
     `max_radius_km`), then add / raise a bonus (up to `max_bonus_multiplier` x the shop's pay, and only when
     that bonus really brings the missing shoppers into reach) — re-matching after every step;
  3. creates the invitations (mode "review": they wait, approved, in Outreach) or creates *and emails* them
     (mode "auto"), with each email's opening written for that shopper by the configured OpenAI model.

What it will never do: invite more shoppers than a shop needs, invite someone who already holds / declined an
invitation for that shop, email an opted-out shopper (the outbox also refuses those), go past a guardrail, or
change a bonus that was already awarded. When a shop can't be filled inside the guardrails it is reported as
"needs attention" (with whether local recruiting is the only way out) instead of being forced.

The decisions are deterministic and auditable (matching engine + staffing rules + guardrails); the model is
used where language matters — the per-shopper email copy. Everything is written to the audit log, and the last
report is kept on the campaign so the UI can show exactly what happened.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import AsyncSessionLocal
from ..models import (
    AutopilotSetting,
    Campaign,
    EmailComposition,
    EventType,
    Invitation,
    Shop,
    ShopBonus,
    Shopper,
)
from .ai.email_personalizer import _personalization_sentence, ai_intro, build_autopilot_email
from .audit import record_audit
from .outbox import enqueue_email
from .selection import active_invitation_count, mark_recommended
from .semantic_matching import run_matching
from .staffing import KM_PER_BONUS_DOLLAR, bonus_ceiling, bonus_reach_km, effective_radius, gap_options
from .tracking import add_event

log = logging.getLogger("app.autopilot")

MODES = ("off", "review", "auto")
DEFAULT_START_RADIUS_KM = 25.0
MAX_PLAN_STEPS = 14
# "Anywhere": the furthest the radius is ever stretched, and only when fill_every_shop has to.
HARD_MAX_RADIUS_KM = 5000.0
ACTOR = "AI Autopilot"
_FIELDS = (
    "mode",
    "max_radius_km",
    "max_bonus_multiplier",
    "min_match_score",
    "max_invitations_per_run",
    "fill_every_shop",
    "max_shops_per_shopper",
)


# --------------------------------------------------------------------------- #
# Guardrails: campaign override > client default > global default > environment
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Guardrails:
    mode: str
    max_radius_km: float
    max_bonus_multiplier: float
    min_match_score: int
    max_invitations_per_run: int
    fill_every_shop: bool = True
    max_shops_per_shopper: int = 3
    sources: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "max_radius_km": self.max_radius_km,
            "max_bonus_multiplier": self.max_bonus_multiplier,
            "min_match_score": self.min_match_score,
            "max_invitations_per_run": self.max_invitations_per_run,
            "fill_every_shop": self.fill_every_shop,
            "max_shops_per_shopper": self.max_shops_per_shopper,
            "max_open_invitations_per_shopper": settings.autopilot_max_open_per_shopper,
            "sources": self.sources,
        }


def _env_defaults() -> dict:
    mode = (settings.autopilot_default_mode or "off").lower()
    return {
        "mode": mode if mode in MODES else "off",
        "max_radius_km": float(settings.autopilot_max_radius_km),
        "max_bonus_multiplier": float(settings.autopilot_max_bonus_multiplier),
        "min_match_score": int(settings.autopilot_min_match_score),
        "max_invitations_per_run": int(settings.autopilot_max_invitations_per_run),
        "fill_every_shop": bool(settings.autopilot_fill_every_shop),
        "max_shops_per_shopper": int(settings.autopilot_max_shops_per_shopper),
    }


async def load_scopes(session: AsyncSession, campaign: Campaign):
    """(campaign override, client default, global default) rows — each may be None."""
    rows = (
        await session.execute(
            select(AutopilotSetting).where(
                (AutopilotSetting.campaign_id == campaign.id)
                | (AutopilotSetting.campaign_id.is_(None))
            )
        )
    ).scalars().all()
    camp = next((r for r in rows if r.campaign_id == campaign.id), None)
    client = next(
        (r for r in rows if r.campaign_id is None and campaign.client_id is not None and r.client_id == campaign.client_id),
        None,
    )
    glob = next((r for r in rows if r.campaign_id is None and r.client_id is None), None)
    return camp, client, glob


async def resolve_guardrails(session: AsyncSession, campaign: Campaign) -> Guardrails:
    camp, client, glob = await load_scopes(session, campaign)
    env = _env_defaults()
    values: dict = {}
    sources: dict = {}
    for name in _FIELDS:
        for scope, row in (("campaign", camp), ("client", client), ("global", glob)):
            v = getattr(row, name, None) if row is not None else None
            if v is not None:
                values[name], sources[name] = v, scope
                break
        else:
            values[name], sources[name] = env[name], "default"
    return Guardrails(**values, sources=sources)


# --------------------------------------------------------------------------- #
# Planning one shop (pure decision-making — writes nothing)
# --------------------------------------------------------------------------- #
@dataclass
class ShopPlan:
    shop: Shop
    required: int
    already_selected: int
    slots_open: int
    start_radius_km: float
    radius_km: float
    existing_bonus: int | None
    bonus_amount: int | None
    picks: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    state: str = "already_filled"
    reason: str | None = None
    recruit_locally: bool = False

    @property
    def bonus_change(self) -> dict | None:
        if (self.bonus_amount or 0) == (self.existing_bonus or 0):
            return None
        return {"amount": self.bonus_amount, "previous": self.existing_bonus, "currency": self.shop.currency or "USD"}


async def _shoppers_with_any_invitation(session: AsyncSession, shop_id) -> set:
    """Everyone who ever got an invitation for this shop — including those who declined: a decline frees the
    slot, but the same person must not be asked again."""
    rows = await session.execute(select(Invitation.shopper_id).where(Invitation.shop_id == shop_id))
    return {r[0] for r in rows}


async def plan_shop(
    session: AsyncSession,
    campaign: Campaign,
    shop: Shop,
    shoppers: list[Shopper],
    parsed: dict,
    guard: Guardrails,
    bonus: ShopBonus | None,
    taken: set[str] | None = None,
    load: dict[str, int] | None = None,
    open_now: dict[str, int] | None = None,
) -> ShopPlan:
    """Plan one shop. `taken` are shoppers already lined up for another shop in this run (a person is not
    double-booked unless the plan has to share shoppers); `load` is how many shops each shopper is already on in
    this campaign, so sharing never goes past `max_shops_per_shopper`. `open_now` is how many invitations each
    shopper holds without having answered, across every campaign: nobody past `autopilot_max_open_per_shopper`
    is invited, however many shops are still open.

    The ladder, cheapest and most natural first, re-matching after every step:
      1. widen the radius up to the comfortable limit (free)
      2. "Fill every shop": let nearby shoppers take more than one shop
      3. add / raise a bonus (within its ceiling) when that brings the missing shoppers into reach
      4. "Fill every shop": stretch the radius beyond the limit, with a bonus that pays for the trip
      5. "Fill every shop": accept weaker matches
    What is left after that is reported as still being searched for (retried every cycle), or — with "fill every
    shop" off — as needing attention."""
    selected = await active_invitation_count(session, shop.id)
    slots_open = max(0, int(shop.required_shoppers or 0) - selected)
    # The comfortable limit also caps where the search starts, not just how far it is widened first.
    start = min(float(parsed.get("maximum_distance_km") or DEFAULT_START_RADIUS_KM), guard.max_radius_km)
    existing = bonus.amount if bonus is not None else None
    plan = ShopPlan(
        shop=shop,
        required=int(shop.required_shoppers or 0),
        already_selected=selected,
        slots_open=slots_open,
        start_radius_km=start,
        radius_km=start,
        existing_bonus=existing,
        bonus_amount=existing,
    )
    if slots_open == 0:
        return plan

    asked = await _shoppers_with_any_invitation(session, shop.id)
    taken = taken or set()
    load = load or {}
    cap = settings.autopilot_max_open_per_shopper
    swamped = {sid for sid, n in (open_now or {}).items() if n >= cap}
    fill = guard.fill_every_shop
    bonus_locked = bonus is not None and bonus.completed_at is not None  # already awarded — never touched
    ceiling = bonus_ceiling(shop.compensation, guard.max_bonus_multiplier)
    radius = start
    amount = existing or 0
    min_score = guard.min_match_score
    sharing = False
    picks: list = []
    gap: dict = {}

    for _ in range(MAX_PLAN_STEPS):
        busy = {sid for sid, n in load.items() if n >= guard.max_shops_per_shopper} if sharing else taken
        result = run_matching(
            shoppers,
            shop,
            campaign,
            radius_km=effective_radius(radius, amount or None),
            requirements=parsed,
            exclude_ids=asked | set(busy) | swamped,
        )
        ranked = [r for r in result["recommendations"] if r["match_score"] >= min_score]
        mark_recommended(ranked, set(), slots_open)
        picks = [r for r in ranked if r["recommended"]]
        if len(picks) >= slots_open:
            gap = {}
            break

        gap = gap_options(
            shop,
            base_radius=radius,
            bonus=SimpleNamespace(amount=amount) if amount else None,
            distances=result["outside_distances"],
            eligible=len(ranked),
            slots_open=slots_open,
            shortfall=slots_open - len(picks),
            ceiling=ceiling,
        )

        # 1) Widening is free, so it goes first — up to the comfortable limit.
        if gap["can_expand_radius"] and radius < guard.max_radius_km:
            target = min(guard.max_radius_km, gap["next_radius_km"])
            if target > radius:
                plan.actions.append({"type": "widen_radius", "from": radius, "to": target})
                radius = target
                continue

        # 2) Nearby shoppers can take another shop: cheaper and more natural than flying someone in.
        if fill and not sharing:
            sharing = True
            plan.actions.append({"type": "share_shoppers", "max_shops": guard.max_shops_per_shopper})
            continue

        # 3) A bonus is money: only inside the ceiling, and only when it really brings the missing shoppers in.
        sug = gap["suggested_bonus"]
        if sug and not bonus_locked and sug["fills_gap"] and amount < sug["amount"] <= ceiling:
            plan.actions.append(
                {
                    "type": "bonus",
                    "amount": sug["amount"],
                    "previous": amount or None,
                    "currency": shop.currency or "USD",
                    "reach_km": bonus_reach_km(sug["amount"]),
                }
            )
            amount = sug["amount"]
            continue

        # 4) Stretch the radius past the limit; a bonus pays for the trip so the far shopper has a reason to say yes.
        if fill and gap["can_expand_radius"] and radius < HARD_MAX_RADIUS_KM:
            target = min(HARD_MAX_RADIUS_KM, gap["next_radius_km"])
            if target > radius:
                plan.actions.append({"type": "widen_radius", "from": radius, "to": target, "stretch": True})
                radius = target
                if not bonus_locked and ceiling >= 10:
                    trip = max(10, -(-int((target - guard.max_radius_km) / KM_PER_BONUS_DOLLAR) // 5) * 5)
                    want = min(ceiling, trip)
                    if want > amount:
                        plan.actions.append(
                            {
                                "type": "bonus",
                                "amount": want,
                                "previous": amount or None,
                                "currency": shop.currency or "USD",
                                "reach_km": bonus_reach_km(want),
                                "reason": "travel",
                            }
                        )
                        amount = want
                continue

        # 5) Last resort: a weaker match is better than an empty slot.
        if fill and min_score > 0:
            plan.actions.append({"type": "accept_weaker_matches", "from": min_score, "to": 0})
            min_score = 0
            continue

        break  # nothing left to try

    plan.radius_km = radius
    plan.bonus_amount = amount or None
    plan.picks = picks[:slots_open]
    missing = slots_open - len(plan.picks)
    if missing <= 0:
        plan.state = "staffed"
    elif fill:
        # Not an error: no eligible shopper is left right now. It is retried every cycle and fills the moment one
        # appears (a new sign-up, a shopper freed by a decline).
        plan.state = "searching"
        plan.recruit_locally = bool(gap.get("recruit_locally", True))
        plan.reason = (
            f"{missing} shopper(s) still being searched for — every eligible shopper is already invited, has too many "
            "invitations waiting for an answer, or is unavailable right now. Autopilot keeps trying and fills this shop "
            "as soon as one appears."
        )
    else:
        plan.state = "partial" if plan.picks else "needs_attention"
        plan.recruit_locally = bool(gap.get("recruit_locally", True))
        why = []
        if radius >= guard.max_radius_km and gap.get("can_expand_radius"):
            why.append(f"the {guard.max_radius_km:g} km radius limit is reached")
        if bonus_locked:
            why.append("the bonus was already awarded")
        elif amount and amount >= ceiling:
            why.append(f"the bonus is at its limit ({shop.currency or 'USD'} {ceiling})")
        plan.reason = (
            f"{missing} shopper(s) still missing"
            + (f" — {'; '.join(why)}" if why else " — no other eligible shopper is available for this shop")
            + ("; recruit shoppers near this shop" if plan.recruit_locally else "")
            + "."
        )
    return plan


# --------------------------------------------------------------------------- #
# Running a campaign
# --------------------------------------------------------------------------- #
def _candidates(shoppers) -> list[Shopper]:
    return [s for s in shoppers if s.active and s.email and not s.opted_out_email]


def _pick_json(r: dict) -> dict:
    return {
        "shopper_id": r["shopper_id"],
        "name": r["name"],
        "match_score": r["match_score"],
        "distance_km": r.get("distance_km"),
    }


async def run_autopilot(
    session: AsyncSession,
    campaign: Campaign,
    *,
    actor: str = ACTOR,
    dry_run: bool = False,
    mode: str | None = None,
    trigger: str = "manual",
) -> dict:
    """Plan (and unless `dry_run`, carry out) the recruiting for every open shop of the campaign. The caller
    commits. `mode` overrides the configured mode for this run only ("review" / "auto")."""
    guard = await resolve_guardrails(session, campaign)
    eff_mode = mode if mode in MODES else guard.mode
    report: dict = {
        "campaign_id": str(campaign.id),
        "campaign_name": campaign.name,
        "mode": eff_mode,
        "dry_run": dry_run,
        "trigger": trigger,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "guardrails": guard.as_dict(),
        "shops": [],
        "totals": {},
        "ai_email_personalization": False,
    }
    if eff_mode == "off" and not dry_run:
        report["skipped"] = "Autopilot is off for this campaign."
        return report

    shops = (await session.execute(select(Shop).where(Shop.campaign_id == campaign.id).order_by(Shop.shop_name))).scalars().all()
    shoppers = _candidates((await session.execute(select(Shopper))).scalars().all())
    shopper_by_id = {str(s.id): s for s in shoppers}
    bonuses = {
        b.shop_id: b
        for b in (await session.execute(select(ShopBonus).where(ShopBonus.campaign_id == campaign.id))).scalars().all()
    }
    parsed = (campaign.parsed_requirements or {}).get("parsed_fields", {}) if campaign.parsed_requirements else {}

    budget = guard.max_invitations_per_run
    totals = dict(
        shops_checked=0, already_filled=0, staffed=0, partial=0, needs_attention=0, searching=0, deferred=0,
        invited=0, emailed=0, radius_widened=0, bonuses_set=0, bonus_total=0,
    )
    send = eff_mode == "auto" and not dry_run

    live = [s for s in shops if (s.status or "").lower() not in ("completed", "cancelled")]
    start = min(float(parsed.get("maximum_distance_km") or DEFAULT_START_RADIUS_KM), guard.max_radius_km)
    # Hardest shop first (fewest candidates in reach) so the scarce shoppers go where they are needed most.
    def _reach_count(shop: Shop) -> int:
        found = run_matching(shoppers, shop, campaign, radius_km=start, requirements=parsed)["recommendations"]
        return sum(1 for r in found if r["match_score"] >= guard.min_match_score)

    live.sort(key=_reach_count)
    taken: set[str] = set()
    # How many shops each shopper is already on in this campaign — sharing is capped by max_shops_per_shopper.
    load_rows = await session.execute(
        select(Invitation.shopper_id, func.count(Invitation.id))
        .where(Invitation.campaign_id == campaign.id, func.coalesce(Invitation.response, "") != "declined")
        .group_by(Invitation.shopper_id)
    )
    load: dict[str, int] = {str(sid): n for sid, n in load_rows}
    # Invitations each shopper holds without having answered, across ALL campaigns (the global cap).
    open_rows = await session.execute(
        select(Invitation.shopper_id, func.count(Invitation.id)).where(Invitation.response.is_(None)).group_by(Invitation.shopper_id)
    )
    open_now: dict[str, int] = {str(sid): n for sid, n in open_rows}

    for shop in live:
        totals["shops_checked"] += 1
        plan = await plan_shop(session, campaign, shop, shoppers, parsed, guard, bonuses.get(shop.id), taken, load, open_now)
        picks = plan.picks
        state = plan.state
        if len(picks) > budget:
            picks = picks[: max(0, budget)]
            state = "deferred" if not picks else "partial"
            plan.reason = f"Run limit of {guard.max_invitations_per_run} invitation(s) reached — the rest follow in the next run."
        budget -= len(picks)
        taken.update(p["shopper_id"] for p in picks)
        for p in picks:
            load[p["shopper_id"]] = load.get(p["shopper_id"], 0) + 1
            open_now[p["shopper_id"]] = open_now.get(p["shopper_id"], 0) + 1

        entry = {
            "shop_id": str(shop.id),
            "shop_name": shop.shop_name,
            "city": shop.city,
            "state": state,
            "required": plan.required,
            "already_selected": plan.already_selected,
            "slots_open": plan.slots_open,
            "start_radius_km": plan.start_radius_km,
            "radius_km": plan.radius_km,
            "actions": plan.actions,
            "bonus": plan.bonus_change,
            "invited": [_pick_json(p) for p in picks],
            "emailed": 0,
            "reason": plan.reason,
            "recruit_locally": plan.recruit_locally,
        }

        if not dry_run:
            change = plan.bonus_change
            if change and (picks or state in ("partial", "needs_attention")) and change["amount"]:
                _upsert_bonus(session, campaign, shop, bonuses.get(shop.id), change["amount"], actor)
            if picks:
                emailed = await _invite(
                    session, campaign, shop, [shopper_by_id[p["shopper_id"]] for p in picks if p["shopper_id"] in shopper_by_id],
                    picks, bonus_amount=plan.bonus_amount, actor=actor, send=send, report=report,
                )
                entry["emailed"] = emailed
                totals["emailed"] += emailed

        totals[state] = totals.get(state, 0) + 1
        totals["invited"] += len(picks)
        totals["radius_widened"] += sum(1 for a in plan.actions if a["type"] == "widen_radius")
        if plan.bonus_change and plan.bonus_change["amount"]:
            totals["bonuses_set"] += 1
            totals["bonus_total"] += plan.bonus_change["amount"] - (plan.bonus_change["previous"] or 0)
        if state != "already_filled" or plan.actions:
            report["shops"].append(entry)

    report["totals"] = totals

    if not dry_run:
        row = await _campaign_row(session, campaign)
        row.last_run_at = datetime.now(timezone.utc)
        row.last_report = _trim_report(report)
        await record_audit(
            session,
            action="autopilot.run",
            actor=actor,
            entity_type="campaign",
            entity_id=str(campaign.id),
            summary=(
                f"AI Autopilot ({eff_mode}, {trigger}) for {campaign.name}: invited {totals['invited']}, "
                f"emailed {totals['emailed']}, widened {totals['radius_widened']}, "
                f"bonuses {totals['bonuses_set']}, still searching/attention {totals['needs_attention'] + totals['partial'] + totals['searching']}"
            ),
            meta={k: v for k, v in totals.items()},
        )
    return report


def _trim_report(report: dict) -> dict:
    """What is stored on the campaign: everything the UI shows, minus bulk (long invitee lists are capped)."""
    out = dict(report)
    out["shops"] = [{**s, "invited": s["invited"][:20]} for s in report["shops"][:200]]
    return out


async def _campaign_row(session: AsyncSession, campaign: Campaign) -> AutopilotSetting:
    row = await session.scalar(select(AutopilotSetting).where(AutopilotSetting.campaign_id == campaign.id))
    if row is None:
        row = AutopilotSetting(campaign_id=campaign.id, client_id=campaign.client_id)
        session.add(row)
    return row


def _upsert_bonus(session: AsyncSession, campaign: Campaign, shop: Shop, existing: ShopBonus | None, amount: int, actor: str) -> None:
    note = "Set by AI Autopilot to attract enough shoppers within the radius guardrail."
    if existing is not None:
        existing.amount = amount
        existing.note = note
    else:
        session.add(
            ShopBonus(
                shop_id=shop.id,
                campaign_id=campaign.id,
                amount=amount,
                currency=shop.currency or "USD",
                note=note,
                created_by=ACTOR,  # who ran it is in the audit log; the pledge itself is the autopilot's
            )
        )


async def _invite(
    session: AsyncSession,
    campaign: Campaign,
    shop: Shop,
    people: list[Shopper],
    picks: list[dict],
    *,
    bonus_amount: int | None,
    actor: str,
    send: bool,
    report: dict,
) -> int:
    """Create one invitation per picked shopper (and queue the email when `send`). Returns how many were queued."""
    from ..routers.invitations import _slug, next_reference

    composed: dict[str, dict] = {}
    if send:
        gate = asyncio.Semaphore(5)

        async def write(shopper: Shopper) -> None:
            async with gate:
                intro = await ai_intro(shopper, campaign, shop, bonus_amount)
            if intro:
                report["ai_email_personalization"] = True
            composed[str(shopper.id)] = build_autopilot_email(
                shopper, campaign, shop, intro or _personalization_sentence(shopper, campaign, shop), bonus_amount
            )

        await asyncio.gather(*(write(s) for s in people))

    queued = 0
    for shopper in people:
        inv = Invitation(
            tracking_token=_new_token(),
            reference=await next_reference(session),
            campaign_id=campaign.id,
            shop_id=shop.id,
            shopper_id=shopper.id,
            email=shopper.email,
            subject=f"You're invited: {campaign.name}",
            status="created",
            source="AI Autopilot",
            utm_source="ai_autopilot",
            utm_medium="email",
            utm_campaign=_slug(campaign.name),
        )
        inv.campaign, inv.shop, inv.shopper = campaign, shop, shopper
        session.add(inv)
        await session.flush()
        await add_event(
            session, inv, EventType.INVITATION_CREATED, {"source": "AI Autopilot", "campaign": campaign.name, "actor": actor}
        )
        mail = composed.get(str(shopper.id))
        if mail:
            session.add(EmailComposition(invitation_id=inv.id, subject_template=mail["subject"], html_template=mail["html"]))
            inv.subject = mail["subject"]
            job = await enqueue_email(session, inv)
            await add_event(session, inv, EventType.EMAIL_QUEUED, {"provider": job.provider, "actor": actor})
            queued += 1
    return queued


def _new_token():
    import uuid

    return uuid.uuid4()


# --------------------------------------------------------------------------- #
# Background scheduler — every campaign, including ones added later (e.g. via the SASSIE API sync)
# --------------------------------------------------------------------------- #
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def run_autopilot_cycle() -> dict:
    """One pass over every live campaign whose resolved mode is on. Each campaign runs in its own transaction,
    at most once per `autopilot_min_interval_minutes`, so one failure never affects another."""
    ran = skipped = failed = 0
    async with AsyncSessionLocal() as session:
        campaigns = (
            await session.execute(
                select(Campaign).where(func.lower(Campaign.status).notin_(("completed", "cancelled")))
            )
        ).scalars().all()
        for campaign in campaigns:
            try:
                guard = await resolve_guardrails(session, campaign)
                if guard.mode == "off":
                    skipped += 1
                    continue
                camp_row, _, _ = await load_scopes(session, campaign)
                last = _aware(camp_row.last_run_at) if camp_row else None
                if last and datetime.now(timezone.utc) - last < timedelta(minutes=settings.autopilot_min_interval_minutes):
                    skipped += 1
                    continue
                await run_autopilot(session, campaign, actor=ACTOR, dry_run=False, trigger="scheduler")
                await session.commit()
                ran += 1
            except Exception:  # noqa: BLE001 - one campaign must not stop the others
                await session.rollback()
                failed += 1
                log.exception("autopilot failed for campaign %s", campaign.id)
    return {"ran": ran, "skipped": skipped, "failed": failed}


async def run_autopilot_scheduler() -> None:
    """Runs for the FastAPI process lifetime, browser-independent (same pattern as the other workers)."""
    if not settings.autopilot_scheduler:
        return
    while True:
        try:
            await run_autopilot_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"WARNING: ShopperMatch autopilot scheduler error: {exc}")
        await asyncio.sleep(settings.autopilot_poll_seconds)


_MODE_RE = re.compile(r"^(off|review|auto)$")


def valid_mode(value: str | None) -> bool:
    return value is None or bool(_MODE_RE.match(value))
