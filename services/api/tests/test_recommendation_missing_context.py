"""Recommendation Engine V1 (review items 34-38): missing or malformed facts must drive
INSUFFICIENT_CONTEXT, never a guess, a default, or a crash. Every rule in `rules.py` treats a
missing/wrong-typed/unparseable fact as absent (see its own `_text`/`_int`/`_bool` helpers) -
these tests exercise that boundary from the engine's own public surface, one per decision type
plus the cross-cutting malformation modes (wrong JSON type, non-Decimal string, empty payload,
missing confidence).
"""

from decimal import Decimal

import pytest

from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.engine import RecommendationEngine
from app.modules.recommendations.types import RecommendationStatus
from tests.recommendation_support import VALID_FACTS, build_decision, build_observation

ENGINE = RecommendationEngine()

# --- 34-38: one required key removed per type -----------------------------------------------

_REQUIRED_KEYS_BY_TYPE = {
    PriorityDecisionType.REV_PICKUP_LOW: ("actual_pickup", "expected_pickup"),
    PriorityDecisionType.REV_OCCUPANCY_RISK: ("forecast_rooms", "expected_final_rooms"),
    PriorityDecisionType.REV_OTA_DEPENDENCY: ("ota_share_exact", "expected_ota_share_exact"),
    PriorityDecisionType.COST_CPOR_ANOMALY: ("actual_cpor_exact", "expected_cpor_exact"),
    PriorityDecisionType.LABOR_OVERSTAFFING: (
        "scheduled_hours_exact",
        "expected_labor_hours_exact",
    ),
}


@pytest.mark.parametrize(
    ("decision_type", "missing_key"),
    [(t, key) for t, keys in _REQUIRED_KEYS_BY_TYPE.items() for key in keys],
    ids=lambda v: v.value if isinstance(v, PriorityDecisionType) else v,
)
def test_missing_required_fact_is_insufficient_context(
    decision_type: PriorityDecisionType, missing_key: str
) -> None:
    decision = build_decision(decision_type)
    facts = dict(VALID_FACTS[decision_type])
    del facts[missing_key]
    observation = build_observation(decision, facts_payload=facts)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT
    assert result.primary_action is None
    assert result.supporting_checks == ()


@pytest.mark.parametrize(
    ("decision_type", "malformed_key"),
    [(t, keys[0]) for t, keys in _REQUIRED_KEYS_BY_TYPE.items()],
    ids=lambda v: v.value if isinstance(v, PriorityDecisionType) else v,
)
def test_malformed_required_fact_is_insufficient_context(
    decision_type: PriorityDecisionType, malformed_key: str
) -> None:
    """A key that IS present but wrong-typed or unparseable is treated exactly like absent -
    never coerced, never guessed."""
    decision = build_decision(decision_type)
    facts = dict(VALID_FACTS[decision_type])
    facts[malformed_key] = "not-a-number"
    observation = build_observation(decision, facts_payload=facts)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT


@pytest.mark.parametrize("decision_type", list(PriorityDecisionType), ids=lambda t: t.value)
def test_empty_facts_payload_is_insufficient_context(
    decision_type: PriorityDecisionType,
) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision, facts_payload={})

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT
    assert result.primary_action is None


def test_bool_disguised_as_int_is_rejected_for_an_int_fact() -> None:
    """`actual_pickup` must be a real int - Python's `bool` is an `int` subclass, and the
    engine's own `_int()` helper explicitly excludes it (a detector could never emit a bool
    here, but the rule must not silently accept one if it ever did)."""
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    facts = dict(VALID_FACTS[PriorityDecisionType.REV_PICKUP_LOW])
    facts["actual_pickup"] = True
    observation = build_observation(decision, facts_payload=facts)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT


def test_wrong_type_for_a_decimal_text_fact_is_rejected() -> None:
    """A rule requires a Decimal-as-string, never a raw float/int JSON value - even a
    numerically sensible float must not be silently stringified."""
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)
    facts = dict(VALID_FACTS[PriorityDecisionType.COST_CPOR_ANOMALY])
    facts["actual_cpor_exact"] = 12.4
    observation = build_observation(decision, facts_payload=facts)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT


def test_missing_confidence_score_is_insufficient_context_even_with_valid_facts() -> None:
    """Confidence is a required, verbatim-copied input - a defensively `None` value (the DB
    itself forbids it, but the ORM does not enforce that in Python) must still degrade
    gracefully rather than emit a recommendation with no confidence attached."""
    decision = build_decision(PriorityDecisionType.LABOR_OVERSTAFFING)
    observation = build_observation(decision, confidence_score=None)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.INSUFFICIENT_CONTEXT
    assert result.primary_action is None
    assert result.confidence is None


def test_insufficient_context_still_carries_no_human_review_override() -> None:
    """Even in the degraded path, nothing about `requires_human_review` semantics changes -
    there is simply no action to attach it to."""
    decision = build_decision(PriorityDecisionType.REV_OTA_DEPENDENCY)
    observation = build_observation(decision, facts_payload={})

    result = ENGINE.evaluate(decision, observation)

    assert result.primary_action is None
    assert result.supporting_checks == ()


def test_insufficient_context_fingerprint_still_deterministic() -> None:
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision, facts_payload={})

    first = ENGINE.evaluate(decision, observation)
    second = ENGINE.evaluate(decision, observation)

    assert first.fingerprint == second.fingerprint
    assert first.status is RecommendationStatus.INSUFFICIENT_CONTEXT


def test_confidence_score_zero_is_not_treated_as_missing() -> None:
    """`Decimal("0.00")` is a real, valid (if extreme) confidence value - only `None` means
    missing; the engine must never treat falsy-but-present as absent. `canonical_text()`
    normalises it to "0" (see `revenue/precision.py`), never to "0.00" - a deliberate, existing
    codebase convention, not something this test should second-guess."""
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)
    observation = build_observation(decision, confidence_score=Decimal("0.00"))

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.AVAILABLE
    assert result.confidence == "0"
