"""Gate 22: `DecisionService.sync()`'s new `coverage` parameter, at the persistence level - how
it round-trips through `DecisionRun.analysis_coverage`, and CRITICALLY, how it participates in
run identity/idempotency (see the module docstring of `decisions/fingerprint.py`). CLI-level
coverage construction is `test_pilot_analysis_cli.py`'s own concern; this file never touches
`app/cli/analysis.py`.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.models import DecisionRun
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_support import CLEAR, revenue_evaluation, sync_run
from tests.support import BookingFactory

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)

EVALUATED = DomainCoverageStatus.EVALUATED
SKIPPED = DomainCoverageStatus.SKIPPED
NOT_REQUESTED = DomainSkipReason.NOT_REQUESTED


def _full_coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, EVALUATED),
            DomainCoverage(AnalysisDomain.LABOR, EVALUATED),
        )
    )


def _booking_only_coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, SKIPPED, NOT_REQUESTED),
            DomainCoverage(AnalysisDomain.LABOR, SKIPPED, NOT_REQUESTED),
        )
    )


# --- 7: repository round-trip -------------------------------------------------------------------


def test_coverage_round_trips_through_the_repository(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    coverage = _booking_only_coverage()
    outcome = sync_run(
        db_session, TenantContext(tenant.workspace.id), context, [evaluation], coverage
    )

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.analysis_coverage == coverage.to_json()
    assert AnalysisCoverage.from_json(run.analysis_coverage) == coverage


def test_omitted_coverage_persists_as_null(db_session: Session, factory: BookingFactory) -> None:
    """Every pre-Gate-22 caller (and any test that never passes `coverage=`) must keep writing
    NULL - "not recorded", never a fabricated "nothing was evaluated"."""
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.analysis_coverage is None


# --- 11: same input + same scope -> idempotent replay -------------------------------------------


def test_same_evaluations_and_same_coverage_is_an_idempotent_replay(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)
    coverage = _booking_only_coverage()

    first = sync_run(db_session, tenant_context, context, [evaluation], coverage).result
    second = sync_run(db_session, tenant_context, context, [evaluation], coverage).result

    assert second.decision_run_id == first.decision_run_id
    assert second.is_idempotent_replay is True


# --- 12: same input + materially different scope -> NOT collapsed -------------------------------


def test_same_evaluations_but_different_coverage_is_not_collapsed(
    db_session: Session, factory: BookingFactory
) -> None:
    """The critical Gate 22 replay requirement, isolated from evaluation-content changes on
    purpose: the EVALUATIONS list is byte-identical between the two calls below (in real
    production usage a coverage change always co-occurs with an evaluations change too, since
    domains are strictly additive - see app/cli/analysis.py - but this test proves scope
    participates in run identity EXPLICITLY, not merely as an accident of evaluation counts)."""
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    partial = sync_run(
        db_session, tenant_context, context, [evaluation], _booking_only_coverage()
    ).result
    full = sync_run(db_session, tenant_context, context, [evaluation], _full_coverage()).result

    assert full.decision_run_id != partial.decision_run_id
    assert full.is_idempotent_replay is False

    partial_run = db_session.get(DecisionRun, partial.decision_run_id)
    full_run = db_session.get(DecisionRun, full.decision_run_id)
    assert partial_run is not None
    assert full_run is not None
    assert partial_run.analysis_coverage == _booking_only_coverage().to_json()
    assert full_run.analysis_coverage == _full_coverage().to_json()


def test_none_coverage_and_a_real_coverage_are_also_not_collapsed(
    db_session: Session, factory: BookingFactory
) -> None:
    """The same guarantee at its other edge: an old-style caller (`coverage=None`, persisted as
    NULL) and a Gate-22-aware caller of the identical evaluations must not collide either."""
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    without_coverage = sync_run(db_session, tenant_context, context, [evaluation]).result
    with_coverage = sync_run(
        db_session, tenant_context, context, [evaluation], _full_coverage()
    ).result

    assert with_coverage.decision_run_id != without_coverage.decision_run_id
    assert with_coverage.is_idempotent_replay is False


# --- 13: FeedState derivation unchanged -----------------------------------------------------


def test_feed_state_derivation_is_unaffected_by_coverage(
    db_session: Session, factory: BookingFactory
) -> None:
    """Coverage is an orthogonal, additive dimension (Gate 22A's own conclusion): a run with
    PARTIAL coverage and zero triggers must still resolve to the SAME FeedState a full-coverage
    equivalent would - `get_feed()` itself is untouched by this gate."""
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)
    sync_run(db_session, tenant_context, context, [evaluation], _booking_only_coverage())

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, D1)
    assert feed.state == FeedState.NO_ACTION_REQUIRED
    assert feed.run is not None
    assert feed.run.analysis_coverage == _booking_only_coverage().to_json()
