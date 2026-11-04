"""Per-shop staffing status, and what to do when a shop can't be filled.

One definition shared by every screen (AI Recommendations, the shop picker, Auto Assign), so a shop is never
"short" on one page and "fine" on another:

  filled  every required shopper is already selected
  ready   the AI found exactly as many fresh shoppers as the shop still needs
  short   fewer eligible shoppers than open slots, for any reason

A short shop has two levers, and both really change who the AI recommends:
  - widen the radius          shoppers further out become eligible (free)
  - add / raise a bonus       a bonus pays for the trip, so it extends how far a shopper is expected to travel
                              (KM_PER_BONUS_DOLLAR km per dollar, see `effective_radius`)
and one fallback when the nearest shopper is a long way off: recruit shoppers who live near the shop.

A bonus is only a pledge — ShopperMatch never pays it (see models.ShopBonus); the client funds it.
"""
from __future__ import annotations

import math

FILLED = "filled"
READY = "ready"
SHORT = "short"

RADIUS_STEP_KM = 25
# A bonus offsets the cost of getting to the shop: every dollar extends the reach by this many km.
KM_PER_BONUS_DOLLAR = 10
# Past this distance a store visit is a long trip: still reachable, but flagged and paired with local recruiting.
FAR_KM = 150
# A bonus is an incentive on top of the shop's pay; past this multiple more money isn't what's missing.
BONUS_CEILING_X_PAY = 3
DEFAULT_PAY = 40


def _round5(n: float) -> int:
    return int(round(n / 5.0)) * 5


def _ceil5(n: float) -> int:
    return int(math.ceil(n / 5.0)) * 5


def bonus_ceiling(compensation: int | None, multiplier: float = BONUS_CEILING_X_PAY) -> int:
    """The most a bonus may reach for a shop: a multiple of its pay (the AI Autopilot passes its own, stricter,
    guardrail multiplier)."""
    if multiplier <= 0:
        return 0  # bonuses switched off by the guardrail
    base = compensation if compensation and compensation > 0 else DEFAULT_PAY
    return max(10, _round5(base * multiplier))


def bonus_reach_km(amount: int | float | None) -> float:
    return max(0, amount or 0) * KM_PER_BONUS_DOLLAR


def effective_radius(base_km: float | None, bonus_amount: int | float | None) -> float | None:
    """How far the matching looks for a shop: the chosen radius plus what its bonus pays for. None = no limit."""
    return None if base_km is None else base_km + bonus_reach_km(bonus_amount)


def _target_distance(distances: list[float], shortfall: int) -> float | None:
    """Distance of the farthest shopper needed to close the gap (the nearest `shortfall` ones outside reach)."""
    if not distances:
        return None
    return distances[min(max(shortfall, 1), len(distances)) - 1]


def suggest_bonus(
    *,
    compensation: int | None,
    currency: str,
    slots_open: int,
    shortfall: int,
    eligible: int,
    existing_amount: int | None = None,
    base_radius: float | None = None,
    needed_km: float | None = None,
    ceiling: int | None = None,
) -> dict | None:
    """A bonus sized to the shop's own pay and how much of the open slots can't be filled — and, when the
    shoppers that would fill it are known (`needed_km`), large enough that its reach gets to them.
    A bonus that is already set is raised, never past the ceiling (more money isn't the answer then, so there is
    nothing to suggest). Returns None when nothing is missing."""
    if shortfall <= 0 or slots_open <= 0:
        return None
    base = compensation if compensation and compensation > 0 else DEFAULT_PAY
    ceiling = ceiling if ceiling is not None else bonus_ceiling(compensation)
    share = 0.25 + 0.5 * min(1.0, shortfall / slots_open)
    amount = max(10, _round5(base * share))
    if needed_km is not None and base_radius is not None:
        reach_amount = max(10, _ceil5(max(0.0, needed_km - base_radius) / KM_PER_BONUS_DOLLAR))
        if reach_amount <= ceiling:
            amount = max(amount, reach_amount)
    if existing_amount is not None:
        if existing_amount >= ceiling:
            return None
        if amount <= existing_amount:
            amount = max(existing_amount + 5, _round5(existing_amount * 1.5))
    amount = min(amount, ceiling)
    fills_gap = (
        base_radius is not None and needed_km is not None and base_radius + bonus_reach_km(amount) >= needed_km
    )
    pool = (
        "no eligible shoppers could be found"
        if eligible == 0
        else f"only {eligible} eligible shopper(s) for {slots_open} open slot(s)"
    )
    return {
        "amount": amount,
        "currency": currency,
        "raises_existing": existing_amount is not None,
        # Whether this amount alone reaches the shoppers that fill the gap (otherwise widen the radius too).
        "fills_gap": bool(fills_gap),
        "reach_km": bonus_reach_km(amount),
        "note": f"AI-recommended — {pool}; the bonus pays for the trip and gives shoppers a reason to say yes.",
    }


def _km(n: float) -> str:
    return f"{n:,.0f} km"


def gap_options(
    shop,
    *,
    base_radius: float | None,
    bonus,
    distances: list[float],
    eligible: int,
    slots_open: int,
    shortfall: int,
    ceiling: int | None = None,
) -> dict:
    """What can close a shop's gap: the radius that reaches enough shoppers, a bonus that does, or — when the
    nearest shopper is far — recruiting locally. `distances` are the shoppers outside the current reach."""
    distances = sorted(distances)
    existing = bonus.amount if bonus is not None else None
    reach = bonus_reach_km(existing)
    needed = _target_distance(distances, shortfall)
    next_radius = None
    if needed is not None and base_radius is not None:
        step = math.ceil(max(0.0, needed - reach) / RADIUS_STEP_KM) * RADIUS_STEP_KM
        next_radius = float(max(step, base_radius + RADIUS_STEP_KM))
    far = needed is not None and needed > FAR_KM
    recruit_locally = next_radius is None or far

    suggestion = suggest_bonus(
        compensation=shop.compensation,
        currency=shop.currency or "USD",
        slots_open=slots_open,
        shortfall=shortfall,
        eligible=eligible,
        existing_amount=existing,
        base_radius=base_radius,
        needed_km=needed,
        ceiling=ceiling,
    )
    if (
        suggestion
        and not suggestion["fills_gap"]
        and recruit_locally
        and eligible == 0
        and bonus is not None
    ):
        # Nobody is in range to tempt and this raise wouldn't reach anyone, so it would only inflate the cost.
        suggestion = None
    return {
        "nearest_outside_km": round(distances[0], 1) if distances else None,
        "can_expand_radius": next_radius is not None,
        "next_radius_km": next_radius,
        "far": far,
        "recruit_locally": recruit_locally,
        "suggested_bonus": suggestion,
        "bonus_maxed": bonus is not None and bonus.amount >= (ceiling if ceiling is not None else bonus_ceiling(shop.compensation)),
        "bonus_ceiling": ceiling if ceiling is not None else bonus_ceiling(shop.compensation),
    }


def assess_staffing(
    shop,
    *,
    already_selected: int,
    recommended: int,
    eligible_count: int,
    outside_radius: int,
    radius_km: float | None,
    outside_distances: list[float] | None = None,
    bonus=None,
) -> dict:
    """`radius_km` is the radius the user chose; the matching actually ran with `effective_radius` (that plus
    what the bonus pays for), and `outside_distances` are the shoppers beyond that."""
    required = int(shop.required_shoppers or 0)
    slots_open = max(0, required - already_selected)
    shortfall = max(0, slots_open - recommended)
    state = FILLED if slots_open == 0 else (READY if shortfall == 0 else SHORT)

    gap = (
        gap_options(
            shop,
            base_radius=radius_km,
            bonus=bonus,
            distances=outside_distances or [],
            eligible=eligible_count,
            slots_open=slots_open,
            shortfall=shortfall,
        )
        if state == SHORT
        else {
            "nearest_outside_km": None,
            "can_expand_radius": False,
            "next_radius_km": None,
            "far": False,
            "recruit_locally": False,
            "suggested_bonus": None,
            "bonus_maxed": bonus is not None and bonus.amount >= bonus_ceiling(shop.compensation),
            "bonus_ceiling": bonus_ceiling(shop.compensation),
        }
    )

    reach = effective_radius(radius_km, bonus.amount if bonus is not None else None)
    reason = None
    if state == SHORT:
        where = f"within {_km(reach)}" if reach else "in range"
        reason = (
            f"No eligible shoppers were found {where}."
            if eligible_count == 0
            else f"Only {eligible_count} eligible shopper(s) were found {where} for {slots_open} open slot(s)."
        )
        if gap["can_expand_radius"] and gap["far"]:
            reason += (
                f" The nearest others are {_km(gap['nearest_outside_km'])} away — a long trip for a store visit; "
                f"widening to {_km(gap['next_radius_km'])} would reach them."
            )
        elif gap["can_expand_radius"]:
            reason += f" Widening to {_km(gap['next_radius_km'])} reaches more."
        else:
            reason += " There is nobody else who matches this shop."

    return {
        "state": state,
        "required": required,
        "already_selected": already_selected,
        "slots_open": slots_open,
        "recommended": min(recommended, slots_open),
        "shortfall": shortfall,
        "eligible_count": eligible_count,
        "radius_km": radius_km,
        "bonus_reach_km": bonus_reach_km(bonus.amount if bonus is not None else None),
        "reach_km": reach,
        "outside_radius": outside_radius,
        "reason": reason,
        "bonus_recommended": gap["suggested_bonus"] is not None,
        **gap,
    }
