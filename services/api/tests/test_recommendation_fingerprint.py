"""Recommendation Engine V1 fingerprint (review items 39-44): the same semantic input always
produces the same 64-hex-char SHA-256, independent of DB-generated identity (`decision.id`,
`observation.id`) and of wall-clock time, and any real change to the recommendation's own
substance (facts, confidence, status, rule/version) changes it.
"""

import inspect
from typing import Any
from uuid import uuid4

import pytest

from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.recommendations import engine as engine_module
from app.modules.recommendations import fingerprint as fingerprint_module
from app.modules.recommendations.engine import RecommendationEngine
from app.modules.recommendations.fingerprint import recommendation_fingerprint
from app.modules.recommendations.types import (
    Action,
    ActionCategory,
    ActionCode,
    ActionScope,
    RecommendationStatus,
)
from tests.recommendation_support import build_decision, build_observation

ENGINE = RecommendationEngine()


def _base_kwargs() -> dict[str, Any]:
    action = Action(
        action_code=ActionCode.REVIEW_COST_DRIVERS,
        category=ActionCategory.REVIEW_COST_DRIVERS,
        scope=ActionScope.COST_PERIOD,
        supporting_facts={"actual_cpor_exact": "12.40", "expected_cpor_exact": "9.00"},
    )
    return {
        "recommendation_version": "recommendation-engine-v1",
        "decision_type": PriorityDecisionType.COST_CPOR_ANOMALY,
        "identity_version": "decision-identity-v1",
        "identity_key": "a" * 64,
        "source_evaluation_fingerprint": "b" * 64,
        "status": RecommendationStatus.AVAILABLE,
        "primary_action": action,
        "supporting_checks": (),
        "confidence": "81.23",
    }


# --- 39: same input, same fingerprint ---------------------------------------------------------


def test_same_input_produces_same_fingerprint_directly() -> None:
    kwargs = _base_kwargs()
    assert recommendation_fingerprint(**kwargs) == recommendation_fingerprint(**kwargs)


def test_same_decision_and_observation_produce_same_fingerprint_via_engine() -> None:
    decision = build_decision(PriorityDecisionType.REV_PICKUP_LOW)
    observation = build_observation(decision)

    assert (
        ENGINE.evaluate(decision, observation).fingerprint
        == ENGINE.evaluate(decision, observation).fingerprint
    )


# --- 40: supporting-fact key order never affects the fingerprint --------------------------------


def test_supporting_facts_key_insertion_order_does_not_affect_fingerprint() -> None:
    facts_a = {"actual_cpor_exact": "12.40", "expected_cpor_exact": "9.00"}
    facts_b = {"expected_cpor_exact": "9.00", "actual_cpor_exact": "12.40"}
    action_a = Action(
        action_code=ActionCode.REVIEW_COST_DRIVERS,
        category=ActionCategory.REVIEW_COST_DRIVERS,
        scope=ActionScope.COST_PERIOD,
        supporting_facts=facts_a,
    )
    action_b = Action(
        action_code=ActionCode.REVIEW_COST_DRIVERS,
        category=ActionCategory.REVIEW_COST_DRIVERS,
        scope=ActionScope.COST_PERIOD,
        supporting_facts=facts_b,
    )
    kwargs_a = {**_base_kwargs(), "primary_action": action_a}
    kwargs_b = {**_base_kwargs(), "primary_action": action_b}

    assert recommendation_fingerprint(**kwargs_a) == recommendation_fingerprint(**kwargs_b)


# --- 41: a changed observation (different facts/confidence) changes the fingerprint -------------


def test_different_confidence_changes_fingerprint() -> None:
    kwargs_a = _base_kwargs()
    kwargs_b = {**_base_kwargs(), "confidence": "50.00"}

    assert recommendation_fingerprint(**kwargs_a) != recommendation_fingerprint(**kwargs_b)


def test_different_supporting_fact_value_changes_fingerprint() -> None:
    decision = build_decision(PriorityDecisionType.COST_CPOR_ANOMALY)
    facts_a = {
        "actual_cpor_exact": "12.40",
        "expected_cpor_exact": "9.00",
    }
    facts_b = {
        "actual_cpor_exact": "13.40",
        "expected_cpor_exact": "9.00",
    }
    result_a = ENGINE.evaluate(decision, build_observation(decision, facts_payload=facts_a))
    result_b = ENGINE.evaluate(decision, build_observation(decision, facts_payload=facts_b))

    assert result_a.fingerprint != result_b.fingerprint


def test_different_status_changes_fingerprint() -> None:
    kwargs_a = _base_kwargs()
    kwargs_b = {
        **_base_kwargs(),
        "status": RecommendationStatus.NOT_AVAILABLE,
        "primary_action": None,
        "confidence": None,
    }

    assert recommendation_fingerprint(**kwargs_a) != recommendation_fingerprint(**kwargs_b)


# --- 42: a changed rule/recommendation version changes the fingerprint --------------------------


def test_different_recommendation_version_changes_fingerprint() -> None:
    kwargs_a = _base_kwargs()
    kwargs_b = {**_base_kwargs(), "recommendation_version": "recommendation-engine-v2"}

    assert recommendation_fingerprint(**kwargs_a) != recommendation_fingerprint(**kwargs_b)


def test_different_identity_key_changes_fingerprint() -> None:
    kwargs_a = _base_kwargs()
    kwargs_b = {**_base_kwargs(), "identity_key": "z" * 64}

    assert recommendation_fingerprint(**kwargs_a) != recommendation_fingerprint(**kwargs_b)


# --- 43: DB-generated identity (UUIDs) never influences the fingerprint -------------------------


def test_decision_id_and_observation_id_do_not_influence_fingerprint() -> None:
    """`decision.id`/`observation.id` are DB-generated UUIDs, assigned only once persisted -
    two otherwise-identical rows with different random ids must fingerprint identically."""
    decision_type = PriorityDecisionType.LABOR_OVERSTAFFING
    decision_a = build_decision(decision_type, decision_id=uuid4())
    decision_b = build_decision(
        decision_type, decision_id=uuid4(), identity_key=decision_a.identity_key
    )
    observation_a = build_observation(decision_a)
    observation_b = build_observation(decision_b)

    result_a = ENGINE.evaluate(decision_a, observation_a)
    result_b = ENGINE.evaluate(decision_b, observation_b)

    assert decision_a.id != decision_b.id
    assert observation_a.id != observation_b.id
    assert result_a.fingerprint == result_b.fingerprint


def test_fingerprint_function_itself_never_receives_a_raw_uuid() -> None:
    """Structural: `recommendation_fingerprint()`'s own parameter ANNOTATIONS take only
    `str`/enum/Action types - a UUID could never even be passed in without a type error, by
    construction. (The module's own docstring legitimately discusses `decision.id`/`UUID` in
    prose while explaining the exclusion - this checks real annotations, not text.)"""
    signature = inspect.signature(recommendation_fingerprint)
    annotations = {str(p.annotation) for p in signature.parameters.values()}
    assert not any("UUID" in annotation for annotation in annotations)
    assert not any("uuid" in p.name.lower() for p in signature.parameters.values())


# --- 44: no wall-clock influence -----------------------------------------------------------------


def test_engine_and_fingerprint_source_never_reference_the_clock() -> None:
    for module in (engine_module, fingerprint_module):
        source = inspect.getsource(module)
        assert "datetime.now" not in source
        assert "date.today" not in source
        assert "utcnow" not in source
        assert "time.time" not in source


def test_recommendation_fingerprint_has_no_timestamp_parameter() -> None:
    signature = inspect.signature(recommendation_fingerprint)
    names = {name.lower() for name in signature.parameters}
    assert not any("time" in name or "date" in name or "clock" in name for name in names)


@pytest.mark.parametrize("decision_type", list(PriorityDecisionType), ids=lambda t: t.value)
def test_fingerprint_is_64_hex_chars_for_every_type(decision_type: PriorityDecisionType) -> None:
    decision = build_decision(decision_type)
    observation = build_observation(decision)

    result = ENGINE.evaluate(decision, observation)

    assert len(result.fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in result.fingerprint)
