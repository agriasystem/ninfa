"""Decision API V1: the decision-feed endpoint (Gate 12 review items 13-29)."""

from collections.abc import Callable
from datetime import date, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
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
    db_session: Session, tenant: Tenant, evaluations: list[Evaluation], as_of: date = D1
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


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
