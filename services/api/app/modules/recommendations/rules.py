"""Per-`decision_type` recommendation rules: real, whitelisted facts in - a primary Action plus
0-2 supporting checks out, or `None` when the facts a rule needs are missing/malformed.

Every rule reads ONLY from `facts_payload` (never `evidence_payload`, never a raw operational
row) and NEVER recomputes a delta/threshold/expected value - it only checks whether the specific
fact(s) it needs are present and well-typed, then copies them, as canonical strings, into the
Action's own `supporting_facts`. See ADR 0022, "why no business recalculation".

Copy/semantics audited against each detector's own trigger condition (see
`app/modules/intelligence/*/detector.py`): `REV_PICKUP_LOW`/`REV_OCCUPANCY_RISK` only ever
TRIGGER on a shortfall, `LABOR_OVERSTAFFING` only on an excess, `COST_CPOR_ANOMALY` only above its
own upper fence - so no rule below ever needs to branch on a sign to phrase its risk notes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.modules.recommendations.types import (
    Action,
    ActionCategory,
    ActionCode,
    ActionScope,
    RiskNote,
)


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    primary: Action
    supporting: tuple[Action, ...]


Facts = Mapping[str, object]


def _text(facts: Facts, key: str) -> str | None:
    """A whitelisted fact that must already be a Decimal-as-string (or `None`): anything else -
    missing, wrong type, or not a parseable Decimal - is treated as absent, never guessed."""
    value = facts.get(key)
    if not isinstance(value, str):
        return None
    try:
        Decimal(value)
    except InvalidOperation:
        return None
    return value


def _int(facts: Facts, key: str) -> int | None:
    value = facts.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bool(facts: Facts, key: str) -> bool | None:
    value = facts.get(key)
    return value if isinstance(value, bool) else None


# --- REV_PICKUP_LOW --------------------------------------------------------------------------


def pickup_rule(facts: Facts) -> RuleOutcome | None:
    actual_pickup = _int(facts, "actual_pickup")
    expected_pickup = _text(facts, "expected_pickup")
    if actual_pickup is None or expected_pickup is None:
        return None

    primary = Action(
        action_code=ActionCode.REVIEW_PRICING_AND_AVAILABILITY,
        category=ActionCategory.REVIEW_PRICING,
        scope=ActionScope.STAY_DATE,
        supporting_facts={"actual_pickup": str(actual_pickup), "expected_pickup": expected_pickup},
        risk_notes=(RiskNote.PRICING_CHANGE_MAY_AFFECT_REVENUE,),
    )
    supporting: list[Action] = []
    rooms_condition = _bool(facts, "rooms_condition")
    if rooms_condition is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_CHANNEL_VISIBILITY,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.STAY_DATE,
                supporting_facts={"rooms_condition": str(rooms_condition)},
            )
        )
    missing_rooms = _text(facts, "missing_rooms")
    if missing_rooms is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_BOOKING_RESTRICTIONS,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.STAY_DATE,
                supporting_facts={"missing_rooms": missing_rooms},
            )
        )
    return RuleOutcome(primary=primary, supporting=tuple(supporting))


# --- REV_OCCUPANCY_RISK ----------------------------------------------------------------------


def occupancy_rule(facts: Facts) -> RuleOutcome | None:
    forecast_rooms = _text(facts, "forecast_rooms")
    expected_final_rooms = _text(facts, "expected_final_rooms")
    if forecast_rooms is None or expected_final_rooms is None:
        return None

    primary = Action(
        action_code=ActionCode.REVIEW_DEMAND_POSITIONING,
        category=ActionCategory.REVIEW_AVAILABILITY,
        scope=ActionScope.STAY_DATE,
        supporting_facts={
            "forecast_rooms": forecast_rooms,
            "expected_final_rooms": expected_final_rooms,
        },
        risk_notes=(RiskNote.PRICING_CHANGE_MAY_AFFECT_REVENUE,),
    )
    supporting: list[Action] = []
    occupancy_gap = _text(facts, "occupancy_gap_pp_exact")
    if occupancy_gap is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_PRICING,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.STAY_DATE,
                supporting_facts={"occupancy_gap_pp_exact": occupancy_gap},
            )
        )
    room_shortfall = _text(facts, "room_shortfall")
    if room_shortfall is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_AVAILABILITY_AND_RESTRICTIONS,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.STAY_DATE,
                supporting_facts={"room_shortfall": room_shortfall},
            )
        )
    return RuleOutcome(primary=primary, supporting=tuple(supporting))


# --- REV_OTA_DEPENDENCY ----------------------------------------------------------------------


def ota_rule(facts: Facts) -> RuleOutcome | None:
    ota_share = _text(facts, "ota_share_exact")
    expected_ota_share = _text(facts, "expected_ota_share_exact")
    if ota_share is None or expected_ota_share is None:
        return None

    primary = Action(
        action_code=ActionCode.REVIEW_DISTRIBUTION_MIX,
        category=ActionCategory.REVIEW_DISTRIBUTION,
        scope=ActionScope.DISTRIBUTION_WINDOW,
        supporting_facts={
            "ota_share_exact": ota_share,
            "expected_ota_share_exact": expected_ota_share,
        },
        risk_notes=(RiskNote.DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY,),
    )
    supporting: list[Action] = []
    structural_condition = _bool(facts, "structural_condition")
    if structural_condition is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_DIRECT_CHANNEL_AVAILABILITY,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.DISTRIBUTION_WINDOW,
                supporting_facts={"structural_condition": str(structural_condition)},
            )
        )
    rising_condition = _bool(facts, "rising_condition")
    if rising_condition is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_DISTRIBUTION_CONFIGURATION,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.DISTRIBUTION_WINDOW,
                supporting_facts={"rising_condition": str(rising_condition)},
            )
        )
    return RuleOutcome(primary=primary, supporting=tuple(supporting))


# --- COST_CPOR_ANOMALY -----------------------------------------------------------------------


def cost_rule(facts: Facts) -> RuleOutcome | None:
    actual_cpor = _text(facts, "actual_cpor_exact")
    expected_cpor = _text(facts, "expected_cpor_exact")
    if actual_cpor is None or expected_cpor is None:
        return None

    primary = Action(
        action_code=ActionCode.REVIEW_COST_DRIVERS,
        category=ActionCategory.REVIEW_COST_DRIVERS,
        scope=ActionScope.COST_PERIOD,
        supporting_facts={"actual_cpor_exact": actual_cpor, "expected_cpor_exact": expected_cpor},
        # No stable risk note fits "review cost drivers" among the closed set (it is a data
        # verification step, not a pricing/staffing/distribution change) - an empty tuple is the
        # honest answer, never a forced, ill-fitting category.
        risk_notes=(),
    )
    supporting: list[Action] = []
    delta_cpor = _text(facts, "delta_cpor_exact")
    if delta_cpor is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_RECENT_COST_ENTRIES,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.COST_PERIOD,
                supporting_facts={"delta_cpor_exact": delta_cpor},
            )
        )
    delta_percent = _text(facts, "delta_percent_exact")
    if delta_percent is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_VOLUME_VS_COST,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.COST_PERIOD,
                supporting_facts={"delta_percent_exact": delta_percent},
            )
        )
    return RuleOutcome(primary=primary, supporting=tuple(supporting))


# --- LABOR_OVERSTAFFING ----------------------------------------------------------------------


def labor_rule(facts: Facts) -> RuleOutcome | None:
    scheduled_hours = _text(facts, "scheduled_hours_exact")
    expected_hours = _text(facts, "expected_labor_hours_exact")
    if scheduled_hours is None or expected_hours is None:
        return None

    primary = Action(
        action_code=ActionCode.REVIEW_STAFFING_PLAN,
        category=ActionCategory.REVIEW_STAFFING,
        scope=ActionScope.WORK_DATE,
        supporting_facts={
            "scheduled_hours_exact": scheduled_hours,
            "expected_labor_hours_exact": expected_hours,
        },
        risk_notes=(RiskNote.STAFFING_CHANGE_MAY_AFFECT_SERVICE,),
    )
    supporting: list[Action] = []
    excess_hours = _text(facts, "excess_hours_exact")
    if excess_hours is not None:
        supporting.append(
            Action(
                action_code=ActionCode.CHECK_SHIFT_COVERAGE,
                category=ActionCategory.VERIFY_DATA,
                scope=ActionScope.WORK_DATE,
                supporting_facts={"excess_hours_exact": excess_hours},
            )
        )
    # scheduled_hours_exact is already required above for the primary action itself; it is also
    # exactly what CHECK_SCHEDULED_HOURS is about, so its presence is already guaranteed here.
    supporting.append(
        Action(
            action_code=ActionCode.CHECK_SCHEDULED_HOURS,
            category=ActionCategory.VERIFY_DATA,
            scope=ActionScope.WORK_DATE,
            supporting_facts={"scheduled_hours_exact": scheduled_hours},
        )
    )
    return RuleOutcome(primary=primary, supporting=tuple(supporting))


__all__ = [
    "Facts",
    "RuleOutcome",
    "cost_rule",
    "labor_rule",
    "occupancy_rule",
    "ota_rule",
    "pickup_rule",
]
