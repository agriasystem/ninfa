"""Deterministic ranking: 8-key sort, unique ranks, input order irrelevance (spec part Q).

Hand-built `PriorityCandidate`s (not full evaluations) are used here on purpose: the tie-break
chain can only be exercised by candidates whose upstream scores are freely controlled, including
combinations (equal priority score, one differing component) a real detector could never itself
produce identically across two different signals.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.modules.intelligence.priority.ranking import rank_candidates
from app.modules.intelligence.priority.types import PriorityCandidate, PriorityDecisionType

_AS_OF = date(2026, 9, 1)
_WORKSPACE_ID = UUID(int=1)
_PROPERTY_ID = UUID(int=2)


def _candidate(
    *,
    decision_type: PriorityDecisionType = PriorityDecisionType.REV_PICKUP_LOW,
    priority_score_exact: Decimal = Decimal(50),
    impact_score_exact: Decimal = Decimal(50),
    urgency_score: Decimal = Decimal(50),
    confidence_score: Decimal = Decimal(50),
    actionability_score: Decimal = Decimal(50),
    source_target_key: str = "key-a",
    source_evaluation_fingerprint: str = "fingerprint-a",
) -> PriorityCandidate:
    return PriorityCandidate(
        decision_type=decision_type,
        workspace_id=_WORKSPACE_ID,
        property_id=_PROPERTY_ID,
        priority_as_of_date=_AS_OF,
        source_evaluation_fingerprint=source_evaluation_fingerprint,
        source_target_key=source_target_key,
        impact_score_exact=impact_score_exact,
        impact_score_display=impact_score_exact,
        urgency_score=urgency_score,
        confidence_score=confidence_score,
        actionability_score=actionability_score,
        priority_score_exact=priority_score_exact,
        priority_score_display=priority_score_exact,
        impact_basis={},
        urgency_basis={},
        actionability_policy="priority-actionability-v1",
        economic_proxy_exact=None,
        economic_proxy_currency=None,
        economic_proxy_label=None,
        source_reason_codes=(),
    )


def test_priority_score_decides_first() -> None:
    high = _candidate(priority_score_exact=Decimal(80), source_target_key="a")
    low = _candidate(priority_score_exact=Decimal(20), source_target_key="b")
    ranked = rank_candidates([low, high])
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]


def test_impact_is_the_first_tie_break() -> None:
    higher_impact = _candidate(impact_score_exact=Decimal(80), source_target_key="a")
    lower_impact = _candidate(impact_score_exact=Decimal(20), source_target_key="b")
    ranked = rank_candidates([lower_impact, higher_impact])
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]


def test_urgency_is_the_second_tie_break() -> None:
    higher = _candidate(
        impact_score_exact=Decimal(50), urgency_score=Decimal(80), source_target_key="a"
    )
    lower = _candidate(
        impact_score_exact=Decimal(50), urgency_score=Decimal(20), source_target_key="b"
    )
    ranked = rank_candidates([lower, higher])
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]


def test_confidence_is_the_third_tie_break() -> None:
    higher = _candidate(
        impact_score_exact=Decimal(50),
        urgency_score=Decimal(50),
        confidence_score=Decimal(80),
        source_target_key="a",
    )
    lower = _candidate(
        impact_score_exact=Decimal(50),
        urgency_score=Decimal(50),
        confidence_score=Decimal(20),
        source_target_key="b",
    )
    ranked = rank_candidates([lower, higher])
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]


def test_actionability_is_the_fourth_tie_break() -> None:
    higher = _candidate(
        impact_score_exact=Decimal(50),
        urgency_score=Decimal(50),
        confidence_score=Decimal(50),
        actionability_score=Decimal(80),
        source_target_key="a",
    )
    lower = _candidate(
        impact_score_exact=Decimal(50),
        urgency_score=Decimal(50),
        confidence_score=Decimal(50),
        actionability_score=Decimal(20),
        source_target_key="b",
    )
    ranked = rank_candidates([lower, higher])
    assert [r.candidate.source_target_key for r in ranked] == ["a", "b"]


def test_decision_type_is_the_fifth_purely_technical_tie_break() -> None:
    # Same everything else: REV_OCCUPANCY_RISK sorts before REV_PICKUP_LOW
    # (DECISION_TYPE_TIE_ORDER), a technical convention, never a semantic ranking of detectors.
    pickup = _candidate(decision_type=PriorityDecisionType.REV_PICKUP_LOW, source_target_key="a")
    occupancy = _candidate(
        decision_type=PriorityDecisionType.REV_OCCUPANCY_RISK, source_target_key="a"
    )
    ranked = rank_candidates([pickup, occupancy])
    assert ranked[0].candidate.decision_type == PriorityDecisionType.REV_OCCUPANCY_RISK
    assert ranked[1].candidate.decision_type == PriorityDecisionType.REV_PICKUP_LOW


def test_source_target_key_is_the_sixth_tie_break() -> None:
    a = _candidate(source_target_key="aaa")
    b = _candidate(source_target_key="bbb")
    ranked = rank_candidates([b, a])
    assert [r.candidate.source_target_key for r in ranked] == ["aaa", "bbb"]


def test_source_evaluation_fingerprint_is_the_final_tie_break() -> None:
    a = _candidate(source_target_key="same", source_evaluation_fingerprint="aaa")
    b = _candidate(source_target_key="same", source_evaluation_fingerprint="bbb")
    ranked = rank_candidates([b, a])
    assert [r.candidate.source_evaluation_fingerprint for r in ranked] == ["aaa", "bbb"]


def test_every_rank_is_unique_from_one_to_n_never_dense_or_shared() -> None:
    candidates = [_candidate(source_target_key=f"key-{i}") for i in range(5)]
    ranked = rank_candidates(candidates)
    assert [r.rank for r in ranked] == [1, 2, 3, 4, 5]


def test_the_input_order_never_changes_the_output_order() -> None:
    candidates = [
        _candidate(priority_score_exact=Decimal(10), source_target_key="a"),
        _candidate(priority_score_exact=Decimal(90), source_target_key="b"),
        _candidate(priority_score_exact=Decimal(50), source_target_key="c"),
    ]
    forward = rank_candidates(candidates)
    backward = rank_candidates(list(reversed(candidates)))
    assert [r.candidate.source_target_key for r in forward] == ["b", "c", "a"]
    assert [r.candidate.source_target_key for r in backward] == ["b", "c", "a"]
