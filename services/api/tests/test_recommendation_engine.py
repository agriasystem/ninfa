"""Recommendation Engine V1: core engine behaviour (review items 1-17, 24-28).

Pure unit tests: `Decision`/`DecisionObservation` are built by hand (`recommendation_support.py`),
never persisted, never touching a database - `RecommendationEngine.evaluate()` itself takes no
session and calls no detector/PriorityService/Expected service (see `test_recommendation_scope.py`
for the source-scan proof of that boundary).
"""

from decimal import Decimal

import pytest

from app.modules.decisions.types import DecisionStatus, LifecycleTransition, SourceStatus
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations.engine import RecommendationEngine
from app.modules.recommendations.types import ActionCode, RecommendationStatus
from tests.recommendation_support import build_decision, build_observation

ENGINE = RecommendationEngine()

_PRIMARY_BY_TYPE = {
    PriorityDecisionType.REV_PICKUP_LOW: ActionCode.REVIEW_PRICING_AND_AVAILABILITY,
    PriorityDecisionType.REV_OCCUPANCY_RISK: ActionCode.REVIEW_DEMAND_POSITIONING,
    PriorityDecisionType.REV_OTA_DEPENDENCY: ActionCode.REVIEW_DISTRIBUTION_MIX,
    PriorityDecisionType.COST_CPOR_ANOMALY: ActionCode.REVIEW_COST_DRIVERS,
    PriorityDecisionType.LABOR_OVERSTAFFING: ActionCode.REVIEW_STAFFING_PLAN,
}

ALL_TYPES = list(PriorityDecisionType)


# --- 1-6: all five types, AVAILABLE, correct primary action ----------------------------------


@pytest.mark.parametrize("decision_type", ALL_TYPES, ids=lambda t: t.value)
def test_available_with_correct_primary_action(decision_type: PriorityDecisionType) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.AVAILABLE
    assert result.primary_action is not None
    assert result.primary_action.action_code is _PRIMARY_BY_TYPE[decision_type]


# --- 7: max 3 total actions -------------------------------------------------------------------


@pytest.mark.parametrize("decision_type", ALL_TYPES, ids=lambda t: t.value)
def test_max_three_actions_total(decision_type: PriorityDecisionType) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    total = (1 if result.primary_action is not None else 0) + len(result.supporting_checks)
    assert total <= 3


# --- 8: human review always true ---------------------------------------------------------------


@pytest.mark.parametrize("decision_type", ALL_TYPES, ids=lambda t: t.value)
def test_human_review_always_true(decision_type: PriorityDecisionType) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    assert result.primary_action is not None
    assert result.primary_action.requires_human_review is True
    for check in result.supporting_checks:
        assert check.requires_human_review is True


def test_no_auto_apply_or_execute_field_exists_anywhere() -> None:
    """Structural, not just behavioural: the dataclasses themselves have no field that could
    mean "apply automatically"."""
    from dataclasses import fields

    from app.modules.recommendations.types import Action, RecommendationResult

    forbidden = {"auto_apply", "execute", "approved_by_default", "apply", "autonomous"}
    action_fields = {f.name for f in fields(Action)}
    result_fields = {f.name for f in fields(RecommendationResult)}
    assert not (action_fields & forbidden)
    assert not (result_fields & forbidden)


# --- 9: deterministic ordering ------------------------------------------------------------------


def test_deterministic_ordering_of_supporting_checks() -> None:
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision)

    first = ENGINE.evaluate(decision, observation)
    second = ENGINE.evaluate(decision, observation)

    assert [a.action_code for a in first.supporting_checks] == [
        a.action_code for a in second.supporting_checks
    ]


# --- 10: deterministic fingerprint --------------------------------------------------------------


def test_deterministic_fingerprint_for_the_same_input() -> None:
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)
    observation = build_observation(decision)

    first = ENGINE.evaluate(decision, observation)
    second = ENGINE.evaluate(decision, observation)

    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in first.fingerprint)


# --- 11-15: source status controls availability -------------------------------------------------


@pytest.mark.parametrize(
    "source_status",
    [
        SourceStatus.CLEAR,
        SourceStatus.INSUFFICIENT_DATA,
        SourceStatus.SUPPRESSED_LOW_CONFIDENCE,
        SourceStatus.NOT_APPLICABLE,
    ],
    ids=lambda s: s.value,
)
def test_non_triggered_source_status_is_never_available(source_status: SourceStatus) -> None:
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(
        decision,
        source_status=source_status,
        lifecycle_transition=LifecycleTransition.NO_STATE_CHANGE,
    )

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.NOT_AVAILABLE
    assert result.primary_action is None
    assert result.supporting_checks == ()
    assert result.confidence is None


def test_triggered_is_available() -> None:
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision, source_status=SourceStatus.TRIGGERED)

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.AVAILABLE


# --- 16-17: Decision status is not a substitute for the latest source status --------------------


def test_open_decision_with_insufficient_latest_is_not_available() -> None:
    """A Decision can stay OPEN while its CURRENT observation is INSUFFICIENT_DATA - the
    recommendation must NOT be available even though the decision itself is open."""
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY, status=DecisionStatus.OPEN)
    observation = build_observation(
        decision,
        source_status=SourceStatus.INSUFFICIENT_DATA,
        lifecycle_transition=LifecycleTransition.NO_STATE_CHANGE,
    )

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.NOT_AVAILABLE


def test_resolved_decision_with_clear_latest_is_not_available() -> None:
    decision = build_decision(
        PriorityDecisionType.REV_OCCUPANCY_RISK, status=DecisionStatus.RESOLVED
    )
    observation = build_observation(
        decision,
        source_status=SourceStatus.CLEAR,
        lifecycle_transition=LifecycleTransition.RESOLVED,
    )

    result = ENGINE.evaluate(decision, observation)

    assert result.status is RecommendationStatus.NOT_AVAILABLE
    assert result.primary_action is None


# --- 24-28: no business recalculation -------------------------------------------------------------


def test_confidence_is_copied_verbatim_never_recomputed() -> None:
    decision = build_decision(PriorityDecisionType.LABOR_OVERSTAFFING)
    observation = build_observation(decision, confidence_score=Decimal("73.45"))

    result = ENGINE.evaluate(decision, observation)

    assert result.confidence == "73.45"  # exactly the stored value, canonicalised - never scaled


def test_delta_facts_are_copied_verbatim_never_recalculated() -> None:
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    assert result.primary_action is not None
    # The exact same Decimal-as-string the fixture put in facts_payload - byte-identical, proving
    # nothing recomputed it.
    assert result.primary_action.supporting_facts["actual_cpor_exact"] == "12.40"
    assert result.primary_action.supporting_facts["expected_cpor_exact"] == "9.00"


def test_expected_values_are_not_recalculated() -> None:
    decision = build_decision(PriorityDecisionType.REV_OCCUPANCY_RISK)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    assert result.primary_action is not None
    assert result.primary_action.supporting_facts["expected_final_rooms"] == "34.00"


def test_priority_is_not_recalculated_the_engine_never_reads_the_score_fields() -> None:
    """The engine only ever reads `priority_rank`/scores through nothing at all - it has no
    dependency on Priority Engine math beyond what the CONFIDENCE field already copies."""
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision, priority_rank=3)

    result_a = ENGINE.evaluate(decision, observation)
    observation.priority_rank = 1  # mutate rank only - nothing recommendation-facing depends on it
    result_b = ENGINE.evaluate(decision, observation)

    assert result_a.fingerprint == result_b.fingerprint
    assert result_a.primary_action == result_b.primary_action


def test_economic_proxy_is_never_recalculated_or_referenced_by_the_engine() -> None:
    """The engine reads `facts_payload` only - `economic_proxy` lives on the observation as its
    own separate, already-decided field, and the engine never touches it (see
    `docs/architecture/recommendation-engine-v1.md`, "No business recalculation")."""
    import inspect

    from app.modules.recommendations import engine as engine_module

    source = inspect.getsource(engine_module)
    assert "economic_proxy" not in source
