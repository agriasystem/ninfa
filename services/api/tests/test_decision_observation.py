"""DecisionObservation content and immutability (tests 77-95)."""

import inspect
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decisions.fingerprint import observation_fingerprint
from app.modules.decisions.models import DecisionObservation, DecisionRun
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionSyncResult, LifecycleTransition, SourceStatus
from app.modules.intelligence.priority.types import (
    PriorityContext,
    PriorityRankingResult,
    RankedPriorityCandidate,
)
from tests.decision_support import (
    CLEAR,
    INSUFFICIENT,
    NOT_APPLICABLE,
    SUPPRESSED,
    TRIGGERED,
    candidate_for,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Rejects, Tenant

D1 = date(2026, 8, 1)
D2 = date(2026, 8, 2)
D3 = date(2026, 8, 3)
STAY = date(2026, 8, 15)


def _sync_one(
    db_session: Session, tenant: Tenant, as_of: date, status: SourceStatus
) -> DecisionSyncResult:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=as_of,
        status=status,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    return outcome.result


def _open(db_session: Session, tenant: Tenant, as_of: date = D1) -> DecisionSyncResult:
    return _sync_one(db_session, tenant, as_of, TRIGGERED)


def _last_observation(
    db_session: Session, tenant: Tenant, decision_id: UUID
) -> DecisionObservation:
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    return memory.get_history(decision_id)[-1]


# --- 77-84: a TRIGGERED observation carries the full Priority snapshot -------------------------


def test_triggered_observation_stores_the_full_priority_snapshot(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    candidate = candidate_for(evaluation, impact=Decimal("77.50"), urgency=Decimal("80.00"))
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
        calculation_fingerprint="d" * 64,
    )
    sync_result = DecisionService(db_session, TenantContext(tenant.workspace.id)).sync(
        context, ranking, [evaluation]
    )
    observation = _last_observation(db_session, tenant, sync_result.touched_decision_ids[0])

    assert observation.priority_rank == 1
    assert observation.priority_score == candidate.priority_score_exact
    assert observation.impact_score == candidate.impact_score_exact
    assert observation.urgency_score == candidate.urgency_score
    assert observation.confidence_score == candidate.confidence_score
    assert observation.actionability_score == candidate.actionability_score
    assert observation.priority_candidate_fingerprint == candidate.calculation_fingerprint
    assert observation.source_evaluation_fingerprint == evaluation.calculation_fingerprint


# --- 85-88: a non-TRIGGERED observation has every priority field NULL --------------------------


@pytest.mark.parametrize("status", [CLEAR, INSUFFICIENT, SUPPRESSED, NOT_APPLICABLE])
def test_non_triggered_observation_priority_fields_are_null(
    db_session: Session, factory: BookingFactory, status: SourceStatus
) -> None:
    tenant = factory.tenant()
    opened = _open(db_session, tenant, D1)
    [decision_id] = opened.touched_decision_ids

    result = _sync_one(db_session, tenant, D2, status)
    assert result.touched_decision_ids == (decision_id,)

    observation = _last_observation(db_session, tenant, decision_id)
    assert observation.source_status == status
    assert observation.priority_candidate_fingerprint is None
    assert observation.priority_rank is None
    assert observation.impact_score is None
    assert observation.urgency_score is None
    assert observation.actionability_score is None
    assert observation.priority_score is None
    assert observation.confidence_score is not None  # confidence always comes from the detector


# --- 89-91: immutability / mutability -----------------------------------------------------------


def test_decision_observation_cannot_be_updated(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant = factory.tenant()
    result = _open(db_session, tenant)
    [decision_id] = result.touched_decision_ids
    observation = _last_observation(db_session, tenant, decision_id)

    with rejects(psycopg.errors.IntegrityConstraintViolation):
        db_session.execute(
            update(DecisionObservation)
            .where(DecisionObservation.id == observation.id)
            .values(priority_rank=99)
        )


def test_decision_run_cannot_be_updated(
    db_session: Session, factory: BookingFactory, rejects: Rejects
) -> None:
    tenant = factory.tenant()
    result = _open(db_session, tenant)

    with rejects(psycopg.errors.IntegrityConstraintViolation):
        db_session.execute(
            update(DecisionRun)
            .where(DecisionRun.id == result.decision_run_id)
            .values(triggered_count=999)
        )


def test_decision_row_is_mutated_only_on_its_expected_lifecycle_fields(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    result = _open(db_session, tenant, D1)
    [decision_id] = result.touched_decision_ids
    memory = DecisionMemoryService(db_session, TenantContext(tenant.workspace.id))
    before = memory.get_decision(decision_id)
    assert before is not None
    identity_snapshot = (
        before.decision_type,
        before.identity_version,
        before.identity_key,
        before.identity_payload,
        before.workspace_id,
        before.property_id,
        before.created_at,
    )

    _sync_one(db_session, tenant, D2, CLEAR)  # resolves it
    _open(db_session, tenant, D3)  # reopens it

    after = memory.get_decision(decision_id)
    assert after is not None
    after_snapshot = (
        after.decision_type,
        after.identity_version,
        after.identity_key,
        after.identity_payload,
        after.workspace_id,
        after.property_id,
        after.created_at,
    )
    assert after_snapshot == identity_snapshot  # identity columns never move
    assert after.episode_count == 2  # the lifecycle fields DID move


# --- 92-95: observation fingerprint determinism --------------------------------------------------


def _fingerprint_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        decision_identity_key="a" * 64,
        run_input_fingerprint="b" * 64,
        as_of_local_date=D1,
        source_status=SourceStatus.TRIGGERED,
        lifecycle_transition=LifecycleTransition.OPENED,
        source_evaluation_fingerprint="c" * 64,
        source_target_key="stay:2026-08-15|snapshot:x",
        priority_candidate_fingerprint="d" * 64,
        priority_rank=1,
        impact_score=Decimal("80.00"),
        urgency_score=Decimal("70.00"),
        confidence_score=Decimal("90.00"),
        actionability_score=Decimal("90.00"),
        priority_score=Decimal("82.50"),
        source_reason_codes=("TRIGGER_PICKUP_SHORTFALL",),
        facts_payload={"a": 1},
        evidence_payload={"b": 2},
    )
    base.update(overrides)
    return base


def test_observation_fingerprint_is_deterministic() -> None:
    kwargs = _fingerprint_kwargs()
    fingerprints = {observation_fingerprint(**kwargs) for _ in range(5)}
    assert len(fingerprints) == 1
    assert len(next(iter(fingerprints))) == 64


def test_observation_fingerprint_does_not_depend_on_anything_not_passed_in() -> None:
    """There is no `created_at`/db-id PARAMETER at all: the function's signature itself proves
    runtime timestamps and database ids can never enter the hash."""
    parameters = set(inspect.signature(observation_fingerprint).parameters)
    assert "created_at" not in parameters
    assert "id" not in parameters
    assert "observation_id" not in parameters


def test_observation_fingerprint_changes_when_the_payload_changes() -> None:
    base = observation_fingerprint(**_fingerprint_kwargs())
    changed = observation_fingerprint(**_fingerprint_kwargs(facts_payload={"a": 2}))
    assert base != changed

    changed_evidence = observation_fingerprint(**_fingerprint_kwargs(evidence_payload={"b": 3}))
    assert base != changed_evidence

    changed_transition = observation_fingerprint(
        **_fingerprint_kwargs(lifecycle_transition=LifecycleTransition.OBSERVED)
    )
    assert base != changed_transition
