"""Gate 24B: `DecisionRepository.latest_run_overall()` and `DecisionMemoryService.get_feed()`'s
new `last_successful_analysis` - the one fact that distinguishes `NOT_PROCESSED`'s two real
meanings ("never analysed" vs. "not analysed today, but a previous run exists") without
inventing a cause for today's own absence. API-level serialization/contract is
`test_decision_api_feed.py`'s own concern; this file is the repository/service level.
"""

from datetime import date
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.repository import DecisionRepository
from app.modules.decisions.types import DecisionSyncResult
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import RevenueDecisionEvaluation
from tests.decision_support import CLEAR, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D_OLD = date(2026, 8, 1)
D_RECENT = date(2026, 8, 10)
TODAY = date(2026, 8, 20)
STAY = date(2026, 8, 25)


def _clear_evaluation(tenant: Tenant, as_of: date) -> RevenueDecisionEvaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=as_of,
        status=CLEAR,
    )


def _sync_on(db_session: Session, tenant: Tenant, as_of: date) -> DecisionSyncResult:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    evaluation = _clear_evaluation(tenant, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation]).result


# --- 1: no DecisionRun ever -> last_successful_analysis is None -------------------------------


def test_no_run_ever_last_successful_analysis_is_none(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)

    assert (
        DecisionRepository(db_session, tenant_context).latest_run_overall(tenant.property.id)
        is None
    )

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, TODAY)
    assert feed.state == FeedState.NOT_PROCESSED
    assert feed.last_successful_analysis is None


# --- 2: previous-day run exists, no run requested for today -----------------------------------


def test_previous_day_run_is_returned_for_todays_not_processed_feed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    previous = _sync_on(db_session, tenant, D_OLD)

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, TODAY)
    assert feed.state == FeedState.NOT_PROCESSED
    assert feed.last_successful_analysis is not None
    assert feed.last_successful_analysis.as_of_local_date == D_OLD

    previous_run = db_session.get(DecisionRun, previous.decision_run_id)
    assert previous_run is not None
    assert feed.last_successful_analysis.completed_at == previous_run.created_at


# --- 3/4: multiple historical runs -> highest run_sequence wins, even when as_of_local_date ----
# ordering disagrees with it ---------------------------------------------------------------------


def test_run_sequence_wins_over_as_of_local_date_when_they_disagree(
    db_session: Session, factory: BookingFactory
) -> None:
    """Deliberately constructs the exact scenario Gate 24A's audit warned about: a LATER
    `run_sequence` with an EARLIER `as_of_local_date` than another already-persisted run. Both
    evaluations use brand-new identities (a fresh random `target_snapshot_id` each,
    `revenue_evaluation()`'s own default) so Gate 11's per-identity `DECISION_OUT_OF_ORDER_RUN`
    guard - which only fires for an identity that already has an existing Decision - never
    fires; nothing in the schema otherwise forbids this ordering (see
    `DecisionRepository.latest_run_overall`'s own docstring)."""
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)

    recent_as_of_run = _sync_on(db_session, tenant, D_RECENT)  # run_sequence N,   as_of = D_RECENT
    old_as_of_run = _sync_on(
        db_session, tenant, D_OLD
    )  # run_sequence N+1, as_of = D_OLD (earlier!)
    assert old_as_of_run.decision_run_id != recent_as_of_run.decision_run_id

    overall = DecisionRepository(db_session, tenant_context).latest_run_overall(tenant.property.id)
    assert overall is not None
    # The run with the LATER run_sequence wins, even though its OWN as_of_local_date is earlier
    # than the other run's - MAX(as_of_local_date) would have picked the wrong row here.
    assert overall.id == old_as_of_run.decision_run_id
    assert overall.as_of_local_date == D_OLD

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, TODAY)
    assert feed.last_successful_analysis is not None
    assert feed.last_successful_analysis.as_of_local_date == D_OLD


# --- 5: current-day run exists -> normal processed feed semantics unchanged, no extra query ---


def test_current_day_run_never_triggers_the_overall_lookup(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    _sync_on(db_session, tenant, D_OLD)  # a real historical run exists
    _sync_on(db_session, tenant, TODAY)  # and today itself has one too

    with patch.object(
        DecisionRepository,
        "latest_run_overall",
        side_effect=AssertionError("latest_run_overall must not run for a processed feed"),
    ):
        feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, TODAY)

    assert feed.state != FeedState.NOT_PROCESSED
    assert feed.last_successful_analysis is None


# --- 6: tenant/property isolation ---------------------------------------------------------------


def test_latest_run_overall_stays_inside_the_tenant_and_property(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant_a = factory.tenant()
    tenant_b = factory.tenant()
    _sync_on(db_session, tenant_b, D_RECENT)

    repo_a = DecisionRepository(db_session, TenantContext(tenant_a.workspace.id))
    assert repo_a.latest_run_overall(tenant_a.property.id) is None
    # tenant A cannot see tenant B's run even by (incorrectly) passing B's own property id under
    # A's own tenant context - the workspace_id filter must be what actually protects this.
    assert repo_a.latest_run_overall(tenant_b.property.id) is None

    repo_b = DecisionRepository(db_session, TenantContext(tenant_b.workspace.id))
    overall_b = repo_b.latest_run_overall(tenant_b.property.id)
    assert overall_b is not None
    assert overall_b.as_of_local_date == D_RECENT


def test_latest_run_overall_does_not_cross_properties_of_the_same_workspace(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    other_property = factory.property(tenant.workspace)
    factory.data_source(other_property)

    _sync_on(db_session, tenant, D_RECENT)  # belongs to tenant.property, not other_property

    repo = DecisionRepository(db_session, tenant_context)
    assert repo.latest_run_overall(other_property.id) is None


# --- 9: existing four FeedState values unchanged ------------------------------------------------


def test_feed_state_values_are_unchanged_by_this_gate(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    tenant_context = TenantContext(tenant.workspace.id)
    _sync_on(db_session, tenant, TODAY)

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, TODAY)
    assert feed.state == FeedState.NO_ACTION_REQUIRED  # a CLEAR evaluation with no prior history
    assert set(FeedState) == {
        FeedState.NOT_PROCESSED,
        FeedState.ACTION_REQUIRED,
        FeedState.NO_ACTION_REQUIRED,
        FeedState.DATA_QUALITY_LIMITED,
    }
