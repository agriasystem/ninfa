"""Gate 23B: `DecisionService.sync()`'s new `provenance` parameter, at the persistence level -
how it round-trips through `DecisionRun.input_provenance`, and CRITICALLY, how it participates in
run identity/idempotency (see the module docstring of `decisions/fingerprint.py`). CLI-level
provenance resolution is `test_pilot_analysis_provenance_cli.py`'s own concern; this file never
touches `app/cli/analysis.py`.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_support import CLEAR, Evaluation, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)

SOURCE_A = uuid4()
SOURCE_B = uuid4()
JOB_1 = uuid4()
JOB_2 = uuid4()
FINISHED_1 = datetime(2026, 9, 29, 9, 15, tzinfo=UTC)
FINISHED_2 = FINISHED_1 + timedelta(hours=3)


def _provenance(
    *,
    data_source_id: UUID = SOURCE_A,
    import_job_id: UUID | None = JOB_1,
    finished_at: datetime | None = FINISHED_1,
) -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=data_source_id,
            import_job_id=import_job_id,
            last_successful_import_finished_at=finished_at,
        )
    )


def _unknown_provenance(data_source_id: UUID = SOURCE_A) -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=data_source_id,
            import_job_id=None,
            last_successful_import_finished_at=None,
        )
    )


def _clear_evaluation(tenant: Tenant) -> Evaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )


# --- 1/2: round-trip -----------------------------------------------------------------------------


def test_known_provenance_round_trips_through_the_repository(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    provenance = _provenance()
    outcome = sync_run(
        db_session, TenantContext(tenant.workspace.id), context, [evaluation], None, provenance
    )

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.input_provenance == provenance.to_json()
    assert RunInputProvenance.from_json(run.input_provenance) == provenance


def test_unknown_freshness_provenance_round_trips_through_the_repository(
    db_session: Session, factory: BookingFactory
) -> None:
    """Source identity known, but no SUCCEEDED import existed yet at analysis time - this is a
    REAL, persisted provenance fact (not the historical-omission NULL case below)."""
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    provenance = _unknown_provenance()
    outcome = sync_run(
        db_session, TenantContext(tenant.workspace.id), context, [evaluation], None, provenance
    )

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.input_provenance is not None
    restored = RunInputProvenance.from_json(run.input_provenance)
    assert restored.bookings.import_job_id is None
    assert restored.bookings.last_successful_import_finished_at is None


# --- 3: historical omitted provenance -> NULL -----------------------------------------------------


def test_omitted_provenance_persists_as_null(db_session: Session, factory: BookingFactory) -> None:
    """Every pre-Gate-23B caller (and any test that never passes `provenance=`) must keep
    writing NULL - "not recorded", never a fabricated historical freshness fact."""
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])

    run = db_session.get(DecisionRun, outcome.result.decision_run_id)
    assert run is not None
    assert run.input_provenance is None


# --- CASE A: identical provenance -> idempotent replay ---------------------------------------


def test_case_a_same_evaluations_and_same_provenance_is_an_idempotent_replay(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)
    provenance = _provenance()

    first = sync_run(db_session, tenant_context, context, [evaluation], None, provenance).result
    second = sync_run(db_session, tenant_context, context, [evaluation], None, provenance).result

    assert second.decision_run_id == first.decision_run_id
    assert second.is_idempotent_replay is True


# --- CASE B: same scope, newer successful import -> new DecisionRun --------------------------


def test_case_b_a_newer_successful_import_of_the_same_source_is_not_collapsed(
    db_session: Session, factory: BookingFactory
) -> None:
    """The critical Gate 23B replay requirement: the EVALUATIONS list is byte-identical between
    the two calls below - only the frozen freshness fact changed - and that alone must still
    produce a DISTINCT run, so Oggi can show the new import's own timestamp."""
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    older = sync_run(
        db_session, tenant_context, context, [evaluation], None, _provenance(finished_at=FINISHED_1)
    ).result
    newer = sync_run(
        db_session,
        tenant_context,
        context,
        [evaluation],
        None,
        _provenance(import_job_id=JOB_2, finished_at=FINISHED_2),
    ).result

    assert newer.decision_run_id != older.decision_run_id
    assert newer.is_idempotent_replay is False

    older_run = db_session.get(DecisionRun, older.decision_run_id)
    newer_run = db_session.get(DecisionRun, newer.decision_run_id)
    assert older_run is not None and newer_run is not None
    assert older_run.input_provenance == _provenance(finished_at=FINISHED_1).to_json()
    assert (
        newer_run.input_provenance
        == _provenance(import_job_id=JOB_2, finished_at=FINISHED_2).to_json()
    )


def test_case_b_prior_run_keeps_reporting_its_own_frozen_provenance_after_a_newer_run_exists(
    db_session: Session, factory: BookingFactory
) -> None:
    """Proves post-run imports cannot retroactively rewrite history: once the OLDER run exists,
    persisting a NEWER run must never mutate the older run's own already-stored fact."""
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    older = sync_run(
        db_session, tenant_context, context, [evaluation], None, _provenance(finished_at=FINISHED_1)
    ).result
    older_run_id = older.decision_run_id
    before = db_session.get(DecisionRun, older_run_id)
    assert before is not None
    frozen_snapshot = before.input_provenance

    sync_run(
        db_session,
        tenant_context,
        context,
        [evaluation],
        None,
        _provenance(import_job_id=JOB_2, finished_at=FINISHED_2),
    )

    after = db_session.get(DecisionRun, older_run_id)
    assert after is not None
    assert after.input_provenance == frozen_snapshot


# --- CASE C: identical provenance repeated -> no spurious duplicate ---------------------------


def test_case_c_identical_source_job_and_finished_at_never_creates_a_spurious_duplicate(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)
    provenance = _provenance(data_source_id=SOURCE_A, import_job_id=JOB_1, finished_at=FINISHED_1)
    identical_again = _provenance(
        data_source_id=SOURCE_A, import_job_id=JOB_1, finished_at=FINISHED_1
    )

    first = sync_run(db_session, tenant_context, context, [evaluation], None, provenance).result
    second = sync_run(
        db_session, tenant_context, context, [evaluation], None, identical_again
    ).result

    assert second.decision_run_id == first.decision_run_id
    assert second.is_idempotent_replay is True


# --- CASE D: different booking_data_source_id -> new DecisionRun -----------------------------


def test_case_d_a_different_booking_data_source_id_is_not_collapsed(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    from_a = sync_run(
        db_session,
        tenant_context,
        context,
        [evaluation],
        None,
        _provenance(data_source_id=SOURCE_A, finished_at=FINISHED_1),
    ).result
    from_b = sync_run(
        db_session,
        tenant_context,
        context,
        [evaluation],
        None,
        _provenance(data_source_id=SOURCE_B, finished_at=FINISHED_1),
    ).result

    assert from_b.decision_run_id != from_a.decision_run_id
    assert from_b.is_idempotent_replay is False


# --- omitted provenance maintains legacy fingerprint behaviour --------------------------------


def test_none_provenance_and_a_real_provenance_are_also_not_collapsed(
    db_session: Session, factory: BookingFactory
) -> None:
    """The same guarantee at its other edge: an old-style caller (`provenance=None`, persisted as
    NULL) and a Gate-23B-aware caller of the identical evaluations/coverage must not collide."""
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    without_provenance = sync_run(db_session, tenant_context, context, [evaluation]).result
    with_provenance = sync_run(
        db_session, tenant_context, context, [evaluation], None, _provenance()
    ).result

    assert with_provenance.decision_run_id != without_provenance.decision_run_id
    assert with_provenance.is_idempotent_replay is False


def test_omitted_provenance_fingerprint_matches_a_pre_gate_23b_run(
    db_session: Session, factory: BookingFactory
) -> None:
    """Legacy compatibility, asserted directly on the fingerprint (not just inferred from "a new
    run was created" above): a run synced with `coverage=None, provenance=None` must produce the
    EXACT SAME `input_fingerprint` a pre-Gate-22 caller would have produced for identical
    evaluations - omitting the new parameter must never, by itself, change identity."""
    from app.modules.decisions.fingerprint import run_input_fingerprint

    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)

    legacy = sync_run(db_session, tenant_context, context, [evaluation]).result
    run = db_session.get(DecisionRun, legacy.decision_run_id)
    assert run is not None
    assert run.analysis_coverage is None
    assert run.input_provenance is None

    expected = run_input_fingerprint(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        as_of_local_date=D1,
        source_evaluation_fingerprints=(evaluation.calculation_fingerprint,),
        priority_ranking_fingerprint=run.priority_ranking_fingerprint,
        evaluation_count=run.evaluation_count,
        triggered_count=run.triggered_count,
        clear_count=run.clear_count,
        insufficient_count=run.insufficient_count,
        not_applicable_count=run.not_applicable_count,
        suppressed_count=run.suppressed_count,
        duplicate_input_count=run.duplicate_input_count,
        # coverage/provenance both omitted - the exact pre-Gate-22/pre-Gate-23B call shape.
    )
    assert run.input_fingerprint == expected


# --- FeedState derivation unaffected ------------------------------------------------------------


def test_feed_state_derivation_is_unaffected_by_provenance(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    evaluation = _clear_evaluation(tenant)
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    tenant_context = TenantContext(tenant.workspace.id)
    sync_run(db_session, tenant_context, context, [evaluation], None, _provenance())

    feed = DecisionMemoryService(db_session, tenant_context).get_feed(tenant.property.id, D1)
    assert feed.state == FeedState.NO_ACTION_REQUIRED
    assert feed.run is not None
    assert feed.run.input_provenance == _provenance().to_json()
