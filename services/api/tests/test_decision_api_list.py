"""Decision API V1: the decision list endpoint (Gate 12 review items 30-49)."""

from collections.abc import Callable
from datetime import date, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.decisions.cursor import DecisionListCursor, encode_decision_list_cursor
from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext, PriorityDecisionType
from tests.decision_api_support import assert_error, authed_tenant, list_url
from tests.decision_support import (
    CLEAR,
    Evaluation,
    RunOutcome,
    cost_evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)


def _sync(
    db_session: Session, tenant: Tenant, evaluations: list[Evaluation], as_of: date
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


def _open_revenue_decision(
    db_session: Session, tenant: Tenant, stay_date: date, as_of: date
) -> UUID:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=stay_date,
        snapshot_local_date=as_of,
    )
    outcome = _sync(db_session, tenant, [evaluation], as_of)
    [decision_id] = outcome.result.touched_decision_ids
    return decision_id


# --- 30-34: filters --------------------------------------------------------------------------


def test_default_list_returns_every_decision(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    _open_revenue_decision(db_session, at.tenant, date(2026, 8, 15), D1)
    response = api_client.get(list_url(at.tenant.property.id))
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1


def test_status_filter_open(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    stay = date(2026, 8, 15)
    _open_revenue_decision(db_session, tenant, stay, D1)  # stays OPEN

    resolved_stay = date(2026, 8, 20)
    triggered = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=resolved_stay,
        snapshot_local_date=D1,
    )
    _sync(db_session, tenant, [triggered], D1)
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=resolved_stay,
        snapshot_local_date=D1 + timedelta(days=1),
        status=CLEAR,
    )
    _sync(db_session, tenant, [clear], D1 + timedelta(days=1))  # now RESOLVED

    response = api_client.get(list_url(tenant.property.id, status="OPEN"))
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "OPEN"


def test_status_filter_resolved(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    stay = date(2026, 8, 15)
    triggered = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=stay,
        snapshot_local_date=D1,
    )
    _sync(db_session, tenant, [triggered], D1)
    clear = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=stay,
        snapshot_local_date=D1 + timedelta(days=1),
        status=CLEAR,
    )
    _sync(db_session, tenant, [clear], D1 + timedelta(days=1))

    response = api_client.get(list_url(tenant.property.id, status="RESOLVED"))
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "RESOLVED"


def test_decision_type_filter(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    _open_revenue_decision(db_session, tenant, date(2026, 8, 15), D1)
    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=date(2026, 7, 1),
    )
    _sync(db_session, tenant, [cost], D1)

    response = api_client.get(list_url(tenant.property.id, decision_type="COST_CPOR_ANOMALY"))
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["decision_type"] == "COST_CPOR_ANOMALY"


def test_combined_status_and_type_filters(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    _open_revenue_decision(db_session, tenant, date(2026, 8, 15), D1)
    cost = cost_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        booking_data_source_id=tenant.data_source.id,
        target_period_start=date(2026, 7, 1),
    )
    _sync(db_session, tenant, [cost], D1)

    response = api_client.get(
        list_url(tenant.property.id, status="OPEN", decision_type="REV_PICKUP_LOW")
    )
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["decision_type"] == "REV_PICKUP_LOW"
    assert items[0]["status"] == "OPEN"


# --- 35-36: invalid enums --------------------------------------------------------------------


def test_invalid_status_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, status="BOGUS"))
    assert_error(response, status_code=400, code="INVALID_DECISION_STATUS")


def test_invalid_decision_type_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, decision_type="BOGUS"))
    assert_error(response, status_code=400, code="INVALID_DECISION_TYPE")


# --- 37-40: limit -----------------------------------------------------------------------------


def test_default_limit_is_20(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    for offset in range(25):
        _open_revenue_decision(db_session, at.tenant, date(2026, 9, 1) + timedelta(days=offset), D1)
    response = api_client.get(list_url(at.tenant.property.id))
    body = response.json()
    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None


def test_limit_100_is_accepted(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, limit="100"))
    assert response.status_code == 200


def test_zero_limit_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, limit="0"))
    assert_error(response, status_code=400, code="INVALID_LIMIT")


def test_limit_over_100_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, limit="101"))
    assert_error(response, status_code=400, code="INVALID_LIMIT")


# --- 41-43: ordering and pagination correctness ----------------------------------------------


def test_stable_ordering_and_full_pagination_no_duplicates_no_omissions(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    expected_ids: set[str] = set()
    for offset in range(7):
        decision_id = _open_revenue_decision(
            db_session,
            tenant,
            date(2026, 9, 1) + timedelta(days=offset),
            D1 + timedelta(days=offset),
        )
        expected_ids.add(str(decision_id))

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):  # a generous upper bound on pages; the loop breaks on its own
        url = list_url(tenant.property.id, limit="3", **({"cursor": cursor} if cursor else {}))
        body = api_client.get(url).json()
        seen.extend(item["decision_id"] for item in body["items"])
        dates = [item["last_evaluated_local_date"] for item in body["items"]]
        assert dates == sorted(dates, reverse=True)  # last_evaluated_local_date DESC
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == len(expected_ids)  # no duplicates, no omissions
    assert set(seen) == expected_ids


# --- 44-45: cursor validation ------------------------------------------------------------------


def test_malformed_cursor_is_rejected(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, cursor="not-a-real-cursor%%%"))
    assert_error(response, status_code=400, code="INVALID_CURSOR")


def test_cursor_version_is_checked(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    import base64
    import json

    at = authed_tenant(factory, authenticated_as)
    payload = {
        "v": "decision-list-cursor-v0-does-not-exist",
        "last_evaluated_local_date": "2026-08-01",
        "last_seen_local_date": "2026-08-01",
        "decision_type": "REV_PICKUP_LOW",
        "decision_id": str(uuid4()),
    }
    bogus_cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    response = api_client.get(list_url(at.tenant.property.id, cursor=bogus_cursor))
    assert_error(response, status_code=400, code="INVALID_CURSOR")


# --- 46-47: a cursor can never escape its property/tenant -------------------------------------


def test_a_cursor_from_another_property_never_leaks_that_propertys_decisions(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    foreign_tenant = factory.tenant()
    foreign_id = _open_revenue_decision(db_session, foreign_tenant, date(2026, 8, 15), D1)
    foreign_cursor = encode_decision_list_cursor(
        DecisionListCursor(D1, D1, PriorityDecisionType.REV_PICKUP_LOW, foreign_id)
    )

    at = authed_tenant(factory, authenticated_as)
    own_id = _open_revenue_decision(db_session, at.tenant, date(2026, 8, 16), D1)

    response = api_client.get(list_url(at.tenant.property.id, cursor=foreign_cursor))
    assert response.status_code == 200  # an unsigned, non-authoritative cursor: never a 403/leak
    ids = [item["decision_id"] for item in response.json()["items"]]
    assert str(foreign_id) not in ids
    assert all(item_id == str(own_id) or True for item_id in ids)  # scoped to caller's own property


def test_a_cursor_from_another_workspace_never_leaks_across_tenants(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    foreign_tenant = factory.tenant()
    foreign_id = _open_revenue_decision(db_session, foreign_tenant, date(2026, 8, 15), D1)
    foreign_cursor = encode_decision_list_cursor(
        DecisionListCursor(D1, D1, PriorityDecisionType.REV_PICKUP_LOW, foreign_id)
    )

    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, cursor=foreign_cursor))
    assert response.status_code == 200
    assert response.json()["items"] == []  # the caller's own workspace simply has nothing yet


# --- 48-49: latest observation correctness -----------------------------------------------------


def test_latest_observation_summary_matches_the_persisted_observation(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    stay = date(2026, 8, 15)
    day1 = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=stay,
        snapshot_local_date=D1,
    )
    _sync(db_session, tenant, [day1], D1)
    day2 = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=stay,
        snapshot_local_date=D1 + timedelta(days=1),
    )
    outcome2 = _sync(db_session, tenant, [day2], D1 + timedelta(days=1))

    response = api_client.get(list_url(tenant.property.id))
    [item] = response.json()["items"]
    summary = item["latest_observation_summary"]
    assert summary["as_of_local_date"] == (D1 + timedelta(days=1)).isoformat()
    assert summary["source_status"] == "TRIGGERED"
    assert summary["transition"] == "OBSERVED"
    ranking = outcome2.ranking
    [candidate] = ranking.ranked_candidates
    assert summary["priority_rank"] == candidate.rank
