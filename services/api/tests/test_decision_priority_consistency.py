"""Priority/source consistency validation (tests 67-76): DecisionService never trusts a ranking
result and its source evaluations without checking they are the coherent output of ONE Priority
Engine run."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.errors import DecisionError, DecisionErrorCode
from app.modules.decisions.identity import SourceEvaluation
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionSyncResult
from app.modules.intelligence.priority.types import (
    PriorityContext,
    PriorityRankingResult,
    RankedPriorityCandidate,
)
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation
from tests.decision_support import candidate_for, revenue_evaluation
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _setup(
    factory: BookingFactory,
) -> tuple[Tenant, PriorityContext, RevenueDecisionEvaluation, PriorityRankingResult]:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    candidate = candidate_for(evaluation)

    ranking = PriorityRankingResult(
        workspace_id=context.workspace_id,
        property_id=context.property_id,
        as_of_local_date=context.as_of_local_date,
        candidate_count=1,
        excluded_clear_count=0,
        excluded_insufficient_count=0,
        excluded_not_applicable_count=0,
        excluded_suppressed_count=0,
        duplicate_input_count=0,
        ranked_candidates=(RankedPriorityCandidate(1, candidate),),
        calculation_fingerprint="c" * 64,
    )
    return tenant, context, evaluation, ranking


def _sync(
    db_session: Session,
    tenant: Tenant,
    context: PriorityContext,
    ranking: PriorityRankingResult,
    evaluations: Sequence[SourceEvaluation],
) -> DecisionSyncResult:
    return DecisionService(db_session, TenantContext(tenant.workspace.id)).sync(
        context, ranking, evaluations
    )


def test_every_triggered_evaluation_maps_to_a_candidate(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    result = _sync(db_session, tenant, context, ranking, [evaluation])
    assert result.created_decision_count == 1  # succeeds: the mapping is coherent


def test_a_triggered_evaluation_without_a_matching_candidate_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    empty_ranking = replace(ranking, candidate_count=0, ranked_candidates=())
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, empty_ranking, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_a_candidate_without_a_matching_triggered_evaluation_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, ranking, [])  # no evaluations at all
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_ranking_workspace_mismatch_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    mismatched = replace(ranking, workspace_id=uuid4())
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, mismatched, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_ranking_property_mismatch_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    mismatched = replace(ranking, property_id=uuid4())
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, mismatched, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_ranking_as_of_mismatch_is_rejected(db_session: Session, factory: BookingFactory) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    mismatched = replace(ranking, as_of_local_date=date(2026, 8, 2))
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, mismatched, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_an_evaluation_of_another_workspace_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    foreign = replace(evaluation, workspace_id=uuid4())
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, ranking, [foreign])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_an_evaluation_of_another_property_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    foreign = replace(evaluation, property_id=uuid4())
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, ranking, [foreign])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


@pytest.mark.parametrize(
    "tampered_ranking_factory",
    [
        lambda ranking: replace(ranking, excluded_clear_count=1),
        lambda ranking: replace(ranking, excluded_insufficient_count=1),
        lambda ranking: replace(ranking, excluded_not_applicable_count=1),
        lambda ranking: replace(ranking, excluded_suppressed_count=1),
    ],
    ids=["clear", "insufficient", "not_applicable", "suppressed"],
)
def test_status_counts_mismatch_between_ranking_and_evaluations_is_rejected(
    db_session: Session,
    factory: BookingFactory,
    tampered_ranking_factory: Callable[[PriorityRankingResult], PriorityRankingResult],
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    tampered = tampered_ranking_factory(ranking)  # claims an exclusion that never happened
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, tampered, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_candidate_fingerprint_not_matching_any_evaluation_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    [ranked] = ranking.ranked_candidates
    tampered_candidate = replace(ranked.candidate, source_evaluation_fingerprint="9" * 64)
    tampered = replace(ranking, ranked_candidates=(replace(ranked, candidate=tampered_candidate),))
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, tampered, [evaluation])
    assert info.value.error_code == DecisionErrorCode.DECISION_PRIORITY_INPUT_MISMATCH


def test_conflicting_source_evaluation_same_identity_is_rejected(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant, context, evaluation, ranking = _setup(factory)
    conflicting = replace(evaluation, calculation_fingerprint="f" * 64)
    with pytest.raises(DecisionError) as info:
        _sync(db_session, tenant, context, ranking, [evaluation, conflicting])
    assert info.value.error_code == DecisionErrorCode.DECISION_CONFLICTING_SOURCE_EVALUATION
