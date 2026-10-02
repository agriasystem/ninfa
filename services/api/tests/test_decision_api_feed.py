"""Decision API V1: the decision-feed endpoint (Gate 12 review items 13-29)."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.service import RevenueDecisionService
from tests.decision_api_support import assert_error, authed_tenant, feed_url
from tests.decision_support import (
    CLEAR,
    INSUFFICIENT,
    NOT_APPLICABLE,
    SUPPRESSED,
    Evaluation,
    RunOutcome,
    cost_evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"
STAY = date(2026, 8, 15)


def _sync(
    db_session: Session,
    tenant: Tenant,
    evaluations: list[Evaluation],
    as_of: date = D1,
    coverage: AnalysisCoverage | None = None,
    provenance: RunInputProvenance | None = None,
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(
        db_session, TenantContext(tenant.workspace.id), context, evaluations, coverage, provenance
    )


def _booking_only_coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, DomainCoverageStatus.EVALUATED),
            DomainCoverage(
                AnalysisDomain.COSTS, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
            DomainCoverage(
                AnalysisDomain.LABOR, DomainCoverageStatus.SKIPPED, DomainSkipReason.NOT_REQUESTED
            ),
        )
    )


# --- 13-14: no run --------------------------------------------------------------------------


def test_no_run_is_not_processed(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(at.tenant.property.id, D1_ISO))
    body = response.json()
    assert body["feed_state"] == "NOT_PROCESSED"
    assert body["feed_state"] != "NO_ACTION_REQUIRED"
    assert body["decision_run_id"] is None
    assert body["run_sequence"] is None
    count_fields = (
        "triggered_count",
        "clear_count",
        "insufficient_count",
        "not_applicable_count",
        "suppressed_count",
    )
    for count in count_fields:
        assert body[count] is None, count
    assert body["items"] == []
    # Gate 22: no run at all -> coverage UNKNOWN, never inferred as FULL or PARTIAL.
    assert body["analysis_coverage"] == {"summary": "UNKNOWN", "domains": []}


# --- 15-18: ACTION_REQUIRED ------------------------------------------------------------------


def test_run_with_triggered_evaluations_is_action_required(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    pickup = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=date(2026, 7, 1),
    )
    outcome = _sync(db_session, tenant, [pickup, cost])

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    assert body["feed_state"] == "ACTION_REQUIRED"
    assert body["decision_run_id"] == str(outcome.result.decision_run_id)
    assert body["triggered_count"] == 2  # exact count (item 16)
    assert len(body["items"]) == 2

    ranks = [item["priority"]["rank"] for item in body["items"]]
    assert ranks == sorted(ranks)  # priority_rank ASC (item 17)

    # scores copied verbatim from the persisted Observation/PriorityCandidate (item 18)
    fingerprints = {item["priority"]["candidate_fingerprint"] for item in body["items"]}
    assert len(fingerprints) == 2
    for item in body["items"]:
        assert isinstance(item["priority"]["priority_score"], str)
        float(item["priority"]["priority_score"])  # a canonical numeric string


def test_feed_never_calls_priority_service_or_a_detector(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Items 19-20: the feed reads exactly what Gate 11 persisted - it never re-ranks and never
    re-evaluates a detector to build its response."""
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    pickup = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    _sync(db_session, tenant, [pickup])

    with (
        patch.object(
            PriorityService, "rank", side_effect=AssertionError("PriorityService.rank called")
        ),
        patch.object(
            RevenueDecisionService,
            "evaluate_revenue_signals",
            side_effect=AssertionError("a detector was called"),
        ),
    ):
        response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    assert response.status_code == 200, response.text
    assert response.json()["feed_state"] == "ACTION_REQUIRED"


# --- 21-23: DATA_QUALITY_LIMITED / NO_ACTION_REQUIRED ----------------------------------------


def test_zero_triggered_with_insufficient_is_data_quality_limited(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=INSUFFICIENT,
    )
    _sync(db_session, tenant, [evaluation])
    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    assert body["feed_state"] == "DATA_QUALITY_LIMITED"
    assert body["feed_state"] != "NO_ACTION_REQUIRED"
    assert body["items"] == []


def test_zero_triggered_with_suppressed_is_data_quality_limited(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=SUPPRESSED,
    )
    _sync(db_session, tenant, [evaluation])
    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    assert body["feed_state"] == "DATA_QUALITY_LIMITED"
    assert body["feed_state"] != "NO_ACTION_REQUIRED"


def test_zero_triggered_only_clear_and_not_applicable_is_no_action_required(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    not_applicable = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY + timedelta(days=1),
        snapshot_local_date=D1,
        status=NOT_APPLICABLE,
    )
    _sync(db_session, tenant, [clear, not_applicable])
    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    assert body["feed_state"] == "NO_ACTION_REQUIRED"


# --- 24-26: multiple same-day runs ------------------------------------------------------------


def test_multiple_same_day_runs_use_the_highest_run_sequence(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    older = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=date(2026, 6, 1),
    )
    older_outcome = _sync(db_session, tenant, [older])

    newer = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=uuid4(),  # a different logical input: a new real run
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    newer_outcome = _sync(db_session, tenant, [newer])
    assert newer_outcome.result.decision_run_id != older_outcome.result.decision_run_id

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    assert body["decision_run_id"] == str(newer_outcome.result.decision_run_id)  # item 24
    assert body["decision_run_id"] != str(older_outcome.result.decision_run_id)  # item 25
    # item 26: every item belongs to the selected (newer) run's own Decision
    [item] = body["items"]
    assert item["decision_type"] == "REV_PICKUP_LOW"


# --- 27-29: as_of is mandatory, validated, never a server clock default ---------------------


def test_as_of_is_mandatory(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(f"/api/v1/properties/{at.tenant.property.id}/decision-feed")
    assert response.status_code == 422  # FastAPI's own required-query-param contract


def test_malformed_as_of_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(at.tenant.property.id, "not-a-date"))
    assert_error(response, status_code=400, code="INVALID_AS_OF_DATE")


def test_no_server_clock_default_in_the_feed_route_source() -> None:
    import inspect

    from app.api.v1.decisions import router as decisions_router_module

    source = inspect.getsource(decisions_router_module)
    assert "date.today()" not in source
    assert "datetime.now()" not in source


# --- Gate 22: analysis coverage, typed and API-visible ----------------------------------------


def test_partial_coverage_is_typed_and_never_raw_db_json(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    _sync(db_session, tenant, [evaluation], coverage=_booking_only_coverage())

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    body = response.json()
    coverage = body["analysis_coverage"]
    assert coverage["summary"] == "PARTIAL"
    by_domain = {item["domain"]: item for item in coverage["domains"]}
    assert by_domain["REVENUE"] == {"domain": "REVENUE", "status": "EVALUATED", "reason": None}
    assert by_domain["COSTS"] == {
        "domain": "COSTS",
        "status": "SKIPPED",
        "reason": "NOT_REQUESTED",
    }
    # never a raw pass-through of the stored JSONB shape (no top-level "version" key leaks out)
    assert "version" not in coverage


def test_full_coverage_summary(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    full = AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, DomainCoverageStatus.EVALUATED),
            DomainCoverage(AnalysisDomain.LABOR, DomainCoverageStatus.EVALUATED),
        )
    )
    _sync(db_session, tenant, [evaluation], coverage=full)

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    assert response.json()["analysis_coverage"]["summary"] == "FULL"


def test_historical_run_without_coverage_is_unknown_never_inferred(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """A run synced with no `coverage` at all (every pre-Gate-22 caller) must read back as
    UNKNOWN through the API - never FULL (nothing was actually recorded as evaluated) and never
    PARTIAL (nothing was recorded as skipped either)."""
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    _sync(db_session, tenant, [evaluation])  # coverage=None, the pre-Gate-22 default

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    assert response.json()["analysis_coverage"] == {"summary": "UNKNOWN", "domains": []}


# --- Gate 23B: input freshness, typed and API-visible ------------------------------------------


def _known_provenance() -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=uuid4(),
            import_job_id=uuid4(),
            last_successful_import_finished_at=datetime(2026, 9, 29, 9, 15, tzinfo=UTC),
        )
    )


def test_known_freshness_is_typed_and_never_leaks_internal_uuids(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    provenance = _known_provenance()
    _sync(db_session, tenant, [evaluation], provenance=provenance)

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    freshness = response.json()["input_freshness"]
    assert freshness["bookings"]["status"] == "KNOWN"
    returned_raw = freshness["bookings"]["last_successful_import_finished_at"]
    returned_instant = datetime.fromisoformat(returned_raw)
    assert returned_instant == provenance.bookings.last_successful_import_finished_at
    # never a raw pass-through of the stored JSONB shape - no internal UUID leaks out
    assert "data_source_id" not in freshness["bookings"]
    assert "last_successful_import_job_id" not in freshness["bookings"]
    assert str(provenance.bookings.data_source_id) not in response.text
    assert str(provenance.bookings.import_job_id) not in response.text


def test_unknown_freshness_when_source_known_but_no_successful_import_yet(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    provenance = RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=tenant.data_source.id,
            import_job_id=None,
            last_successful_import_finished_at=None,
        )
    )
    _sync(db_session, tenant, [evaluation], provenance=provenance)

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    freshness = response.json()["input_freshness"]
    assert freshness == {
        "bookings": {"status": "UNKNOWN", "last_successful_import_finished_at": None}
    }


def test_historical_run_without_provenance_is_unknown_never_inferred(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """A run synced with no `provenance` at all (every pre-Gate-23B caller) must read back as
    UNKNOWN through the API - never a crash, never a guessed historical timestamp."""
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        status=CLEAR,
    )
    _sync(db_session, tenant, [evaluation])  # provenance=None, the pre-Gate-23B default

    response = api_client.get(feed_url(tenant.property.id, D1_ISO))
    freshness = response.json()["input_freshness"]
    assert freshness == {
        "bookings": {"status": "UNKNOWN", "last_successful_import_finished_at": None}
    }


def test_no_run_at_all_reports_unknown_freshness(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(at.tenant.property.id, D1_ISO))
    assert response.json()["input_freshness"] == {
        "bookings": {"status": "UNKNOWN", "last_successful_import_finished_at": None}
    }
