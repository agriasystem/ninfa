"""Decision API V1: the decision detail endpoint (Gate 12 review items 50-64)."""

from collections.abc import Callable
from datetime import date, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import authed_tenant, detail_url
from tests.decision_support import CLEAR, Evaluation, RunOutcome, revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _sync(
    db_session: Session, tenant: Tenant, evaluations: list[Evaluation], as_of: date
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


# --- 50: an OPEN decision detail ---------------------------------------------------------------


def test_open_decision_detail(
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
    )
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    response = api_client.get(detail_url(tenant.property.id, decision_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_id"] == str(decision_id)
    assert body["status"] == "OPEN"
    assert body["decision_type"] == "REV_PICKUP_LOW"
    assert body["decision_api_version"] == "decision-api-v1"


# --- 51: a RESOLVED decision detail ------------------------------------------------------------


def test_resolved_decision_detail(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    triggered = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    outcome = _sync(db_session, tenant, [triggered], D1)
    [decision_id] = outcome.result.touched_decision_ids
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1 + timedelta(days=1),
        status=CLEAR,
    )
    _sync(db_session, tenant, [clear], D1 + timedelta(days=1))

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    assert body["status"] == "RESOLVED"
    assert body["resolved_local_date"] == (D1 + timedelta(days=1)).isoformat()
    # 56: latest is CLEAR -> priority is null
    assert body["latest_observation"]["priority"] is None
    assert body["latest_observation"]["source_status"] == "CLEAR"


# --- 52-53: a REOPENED decision and its lifecycle counters --------------------------------------


def test_reopened_decision_detail_and_lifecycle_counters(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    day1 = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    outcome = _sync(db_session, tenant, [day1], D1)
    [decision_id] = outcome.result.touched_decision_ids
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1 + timedelta(days=1),
        status=CLEAR,
    )
    _sync(db_session, tenant, [clear], D1 + timedelta(days=1))
    reopen = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1 + timedelta(days=2),
    )
    _sync(db_session, tenant, [reopen], D1 + timedelta(days=2))

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    assert body["status"] == "OPEN"
    assert body["resolved_local_date"] is None
    assert body["episode_count"] == 2  # 53: lifecycle counters
    assert body["triggered_observation_count"] == 2
    assert body["first_seen_local_date"] == D1.isoformat()
    assert body["latest_observation"]["lifecycle_transition"] == "REOPENED"


# --- 54: target DTO -----------------------------------------------------------------------------


def test_target_dto_is_correct(
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
    )
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    target = body["target"]
    assert target["type"] == "REV_PICKUP_LOW"
    assert target["booking_data_source_id"] == str(tenant.data_source.id)
    assert target["stay_date"] == STAY.isoformat()
    assert set(target.keys()) == {"type", "booking_data_source_id", "stay_date"}  # 62: no raw leak


# --- 55-58: priority presence rules -------------------------------------------------------------


def test_latest_triggered_observation_includes_priority(
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
    )
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids
    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    priority = body["latest_observation"]["priority"]
    assert priority is not None
    assert priority["rank"] == 1
    for field in (
        "impact_score",
        "urgency_score",
        "confidence_score",
        "actionability_score",
        "priority_score",
        "candidate_fingerprint",
    ):
        assert isinstance(priority[field], str)


def test_latest_insufficient_observation_has_null_priority(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    from tests.decision_support import INSUFFICIENT

    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    triggered = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    outcome = _sync(db_session, tenant, [triggered], D1)
    [decision_id] = outcome.result.touched_decision_ids
    insufficient = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1 + timedelta(days=1),
        status=INSUFFICIENT,
    )
    _sync(db_session, tenant, [insufficient], D1 + timedelta(days=1))

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    assert body["latest_observation"]["source_status"] == "INSUFFICIENT_DATA"
    assert body["latest_observation"]["priority"] is None


# --- 58, 59-61: reason codes, exact Decimal-as-string, UUID/date canonical ----------------------


def test_reason_codes_decimal_uuid_date_encoding(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    from app.modules.intelligence.revenue.types import ReasonCode

    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
        reason_codes=(ReasonCode.TRIGGER_PICKUP_SHORTFALL,),
    )
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    latest = body["latest_observation"]
    assert latest["reason_codes"] == ["TRIGGER_PICKUP_SHORTFALL"]  # 58

    # 59: exact Decimal serialized as a canonical string, never a float
    assert isinstance(latest["priority"]["priority_score"], str)
    assert isinstance(latest["confidence_score"], str)

    # 60: UUID canonical lowercase string
    assert body["decision_id"] == str(decision_id).lower()
    assert UUID(body["decision_id"]) == decision_id

    # 61: date canonical ISO
    assert body["first_seen_local_date"] == D1.isoformat()
    date.fromisoformat(body["first_seen_local_date"])  # round-trips


# --- 62-64: no raw leak ---------------------------------------------------------------------


def test_detail_never_leaks_identity_payload_orm_or_unrelated_tenant_fields(
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
    )
    outcome = _sync(db_session, tenant, [evaluation], D1)
    [decision_id] = outcome.result.touched_decision_ids

    body = api_client.get(detail_url(tenant.property.id, decision_id)).json()
    raw = str(body)
    for forbidden in (
        "identity_payload",
        "identity_version",
        "_sa_instance_state",
        str(tenant.workspace.id),  # workspace id is never part of the public contract
        "workspace_id",
    ):
        assert forbidden not in raw, forbidden
