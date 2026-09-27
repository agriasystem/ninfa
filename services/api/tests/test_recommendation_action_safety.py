"""Recommendation Engine V1 safety boundary (review items 29-33): NINFA proposes, never decides
autonomously. Primarily STRUCTURAL (the closed `ActionCode` enum a rule can ever produce), with a
natural-language scan of the actual rendered `title_key`/`description_key`/action codes as a
second, defence-in-depth layer - never the only check, since prose alone is fragile (a future
copy layer could phrase things differently without this test ever running against it).
"""

import pytest

from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.engine import RecommendationEngine
from app.modules.recommendations.types import ActionCode
from tests.recommendation_support import build_decision, build_observation

ENGINE = RecommendationEngine()

# The exact, closed set of codes each type's rule is allowed to ever produce - anything outside
# this set is, by construction, impossible; this is the STRUCTURAL half of the safety guarantee.
_ALLOWED_CODES: dict[PriorityDecisionType, set[ActionCode]] = {
    PriorityDecisionType.REV_PICKUP_LOW: {
        ActionCode.REVIEW_PRICING_AND_AVAILABILITY,
        ActionCode.CHECK_CHANNEL_VISIBILITY,
        ActionCode.CHECK_BOOKING_RESTRICTIONS,
    },
    PriorityDecisionType.REV_OCCUPANCY_RISK: {
        ActionCode.REVIEW_DEMAND_POSITIONING,
        ActionCode.CHECK_PRICING,
        ActionCode.CHECK_AVAILABILITY_AND_RESTRICTIONS,
    },
    PriorityDecisionType.REV_OTA_DEPENDENCY: {
        ActionCode.REVIEW_DISTRIBUTION_MIX,
        ActionCode.CHECK_DIRECT_CHANNEL_AVAILABILITY,
        ActionCode.CHECK_DISTRIBUTION_CONFIGURATION,
    },
    PriorityDecisionType.COST_CPOR_ANOMALY: {
        ActionCode.REVIEW_COST_DRIVERS,
        ActionCode.CHECK_RECENT_COST_ENTRIES,
        ActionCode.CHECK_VOLUME_VS_COST,
    },
    PriorityDecisionType.LABOR_OVERSTAFFING: {
        ActionCode.REVIEW_STAFFING_PLAN,
        ActionCode.CHECK_SHIFT_COVERAGE,
        ActionCode.CHECK_SCHEDULED_HOURS,
    },
}

# Never allowed anywhere, for ANY type - a closed denylist of the exact codes the spec forbids.
_NEVER_ALLOWED = {
    "LOWER_PRICE",
    "DISCOUNT_PRICE",
    "CLOSE_OTA",
    "REMOVE_CHANNEL",
    "CHANGE_SUPPLIER",
    "FIRE_STAFF",
    "SEND_HOME",
    "REDUCE_STAFF",
    "CONTACT_SUPPLIER",
}

_FORBIDDEN_PHRASES = [
    "lower price",
    "abbassa il prezzo",
    "discount",
    "sconto",
    "close booking",
    "chiudi booking",
    "remove expedia",
    "riduci expedia",
    "change supplier",
    "cambia fornitore",
    "fire",
    "send home",
    "manda a casa",
    "reduce staff",
    "taglia personale",
    "riduci dipendenti",
    "contact the supplier",
    "contatta il fornitore",
]


def _all_codes(result: object) -> set[str]:
    codes = set()
    if result.primary_action is not None:  # type: ignore[attr-defined]
        codes.add(result.primary_action.action_code.value)  # type: ignore[attr-defined]
    for check in result.supporting_checks:  # type: ignore[attr-defined]
        codes.add(check.action_code.value)
    return codes


@pytest.mark.parametrize("decision_type", list(PriorityDecisionType), ids=lambda t: t.value)
def test_only_allowed_action_codes_for_each_type(decision_type: PriorityDecisionType) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    produced = _all_codes(result)
    assert produced <= {code.value for code in _ALLOWED_CODES[decision_type]}
    assert not (produced & _NEVER_ALLOWED)


def test_action_code_enum_itself_contains_no_forbidden_verb() -> None:
    """Even before any rule runs: the closed enum of POSSIBLE codes never contains a forbidden
    verb - a future rule literally cannot produce one without first adding it here, in the open."""
    all_defined = {code.value for code in ActionCode}
    assert not (all_defined & _NEVER_ALLOWED)


@pytest.mark.parametrize("decision_type", list(PriorityDecisionType), ids=lambda t: t.value)
def test_no_forbidden_natural_language_phrase_in_rendered_keys(
    decision_type: PriorityDecisionType,
) -> None:
    """Defence in depth: scan the actual template keys this decision_type can ever render -
    never the ONLY check (see module docstring), but still real, run against real output."""
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    rendered = " ".join(
        [result.primary_action.title_key, result.primary_action.description_key]
        if result.primary_action is not None
        else []
    ) + " ".join(f"{c.title_key} {c.description_key}" for c in result.supporting_checks)
    lowered = rendered.lower()
    for phrase in _FORBIDDEN_PHRASES:
        assert phrase not in lowered, (decision_type.value, phrase)


def test_pickup_never_says_lower_price() -> None:
    result = ENGINE.evaluate(
        build_decision(PriorityDecisionType.REV_PICKUP_LOW),
        build_observation(build_decision(PriorityDecisionType.REV_PICKUP_LOW)),
    )
    assert result.primary_action is not None
    assert result.primary_action.action_code is ActionCode.REVIEW_PRICING_AND_AVAILABILITY
    assert "LOWER_PRICE" not in _all_codes(result)


def test_occupancy_never_says_discount() -> None:
    result = ENGINE.evaluate(
        build_decision(PriorityDecisionType.REV_OCCUPANCY_RISK),
        build_observation(build_decision(PriorityDecisionType.REV_OCCUPANCY_RISK)),
    )
    assert result.primary_action is not None
    assert "DISCOUNT" not in result.primary_action.action_code.value


def test_ota_never_says_close_or_remove_a_specific_ota() -> None:
    result = ENGINE.evaluate(
        build_decision(PriorityDecisionType.REV_OTA_DEPENDENCY),
        build_observation(build_decision(PriorityDecisionType.REV_OTA_DEPENDENCY)),
    )
    assert result.primary_action is not None
    assert result.primary_action.action_code is ActionCode.REVIEW_DISTRIBUTION_MIX
    for fact_key in result.primary_action.supporting_facts:
        assert "booking.com" not in fact_key.lower() and "expedia" not in fact_key.lower()


def test_cost_never_says_change_supplier() -> None:
    result = ENGINE.evaluate(
        build_decision(PriorityDecisionType.COST_CPOR_ANOMALY),
        build_observation(build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)),
    )
    assert result.primary_action is not None
    assert "SUPPLIER" not in result.primary_action.action_code.value
    assert not any("supplier" in key.lower() for key in result.primary_action.supporting_facts)


def test_labor_never_says_fire_or_send_home_or_reduce_staff() -> None:
    result = ENGINE.evaluate(
        build_decision(PriorityDecisionType.LABOR_OVERSTAFFING),
        build_observation(build_decision(PriorityDecisionType.LABOR_OVERSTAFFING)),
    )
    assert result.primary_action is not None
    assert result.primary_action.action_code is ActionCode.REVIEW_STAFFING_PLAN
    for forbidden in ("FIRE", "SEND_HOME", "REDUCE_STAFF"):
        assert forbidden not in _all_codes(result)
