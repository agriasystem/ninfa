"""Decision API V1: the decision history endpoint (Gate 12 review items 65-78)."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.decisions.cursor import DecisionHistoryCursor, encode_decision_history_cursor
from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import assert_error, authed_tenant, history_url
from tests.decision_support import (
    CLEAR,
    TRIGGERED,
    Evaluation,
    RunOutcome,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


def _sync(
    db_session: Session, tenant: Tenant, evaluations: list[Evaluation], as_of: date
) -> RunOutcome:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, as_of)
    return sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


def _full_lifecycle_decision(db_session: Session, tenant: Tenant) -> UUID:
    """OPENED (D1) -> OBSERVED (D1+7) -> RESOLVED (D1+14) -> REOPENED (D1+21)."""
    day0 = _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
            )
        ],
        D1,
    )
    [decision_id] = day0.result.touched_decision_ids
    for offset, status in ((7, TRIGGERED), (14, CLEAR), (21, TRIGGERED)):
        as_of = D1 + timedelta(days=offset)
        _sync(
            db_session,
            tenant,
            [
                revenue_evaluation(
                    workspace_id=tenant.workspace.id,
                    property_id=tenant.property.id,
                    data_source_id=tenant.data_source.id,
                    stay_date=STAY,
                    snapshot_local_date=as_of,
                    status=status,
                )
            ],
            as_of,
        )
    return decision_id


# --- 65-70: chronological data, newest-first, every transition preserved -----------------------


def test_history_returns_newest_first_with_every_transition_preserved(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _full_lifecycle_decision(db_session, at.tenant)

    body = api_client.get(history_url(at.tenant.property.id, decision_id)).json()
    items = body["items"]
    assert len(items) == 4

    as_of_dates = [item["as_of_local_date"] for item in items]
    assert as_of_dates == sorted(as_of_dates, reverse=True)  # 65: newest-first

    transitions = [item["lifecycle_transition"] for item in items]
    assert transitions == ["REOPENED", "RESOLVED", "OBSERVED", "OPENED"]  # 66-69
    assert "NO_STATE_CHANGE" not in transitions  # (none produced by this particular scenario)


def test_no_state_change_transition_is_preserved_in_history(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    from tests.decision_support import INSUFFICIENT

    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    day0 = _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
            )
        ],
        D1,
    )
    [decision_id] = day0.result.touched_decision_ids
    _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1 + timedelta(days=1),
                status=INSUFFICIENT,
            )
        ],
        D1 + timedelta(days=1),
    )
    body = api_client.get(history_url(tenant.property.id, decision_id)).json()
    assert body["items"][0]["lifecycle_transition"] == "NO_STATE_CHANGE"  # 70


# --- 71-72: previous ranks/scores preserved, never overwritten ---------------------------------


def test_previous_ranks_and_exact_scores_are_preserved_across_history(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    day0 = _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
                confidence_score=Decimal("60.00"),
            )
        ],
        D1,
    )
    [decision_id] = day0.result.touched_decision_ids
    _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1 + timedelta(days=1),
                confidence_score=Decimal("95.00"),
            )
        ],
        D1 + timedelta(days=1),
    )

    items = api_client.get(history_url(tenant.property.id, decision_id)).json()["items"]
    assert len(items) == 2
    day2_confidence, day1_confidence = (item["priority"]["confidence_score"] for item in items)
    assert day1_confidence != day2_confidence  # both real, both kept, never overwritten
    assert {"60", "95"} == {day1_confidence, day2_confidence}


# --- 73-74: default limit, pagination -----------------------------------------------------------


def test_history_default_limit_is_20_and_paginates(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    day0 = _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
            )
        ],
        D1,
    )
    [decision_id] = day0.result.touched_decision_ids
    for offset in range(1, 25):
        as_of = D1 + timedelta(days=offset)
        _sync(
            db_session,
            tenant,
            [
                revenue_evaluation(
                    workspace_id=tenant.workspace.id,
                    property_id=tenant.property.id,
                    data_source_id=tenant.data_source.id,
                    stay_date=STAY,
                    snapshot_local_date=as_of,
                )
            ],
            as_of,
        )

    first_page = api_client.get(history_url(tenant.property.id, decision_id)).json()
    assert len(first_page["items"]) == 20  # 73: default limit
    assert first_page["next_cursor"] is not None

    seen = {item["observation_id"] for item in first_page["items"]}
    cursor = first_page["next_cursor"]
    second_page = api_client.get(history_url(tenant.property.id, decision_id, cursor=cursor)).json()
    seen |= {item["observation_id"] for item in second_page["items"]}
    assert len(seen) == 25  # 74: pagination, no duplicates, no omissions
    assert second_page["next_cursor"] is None


# --- 75-76: same-day multiple-run ordering by run_sequence --------------------------------------


def test_same_day_multiple_runs_order_by_run_sequence_not_random(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    day0 = _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
                fingerprint="1" * 64,
            )
        ],
        D1,
    )
    [decision_id] = day0.result.touched_decision_ids
    # A second, genuinely different run of the SAME as-of (a changed fingerprint - never an
    # idempotent replay, see Gate 11's own `test_decision_run_idempotency.py`).
    _sync(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
                fingerprint="2" * 64,
            )
        ],
        D1,
    )

    items = api_client.get(history_url(tenant.property.id, decision_id)).json()["items"]
    assert len(items) == 2
    assert items[0]["as_of_local_date"] == items[1]["as_of_local_date"] == D1.isoformat()
    assert items[0]["source_evaluation_fingerprint"] == "2" * 64  # the LATER run_sequence first


# --- 77-78: cross-decision / cross-tenant history is 404 ----------------------------------------


def test_history_of_another_decision_id_is_404(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(history_url(at.tenant.property.id, uuid4()))
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


def test_history_cross_tenant_is_404(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    foreign_tenant = factory.tenant()
    foreign_decision_id = _full_lifecycle_decision(db_session, foreign_tenant)
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(history_url(at.tenant.property.id, foreign_decision_id))
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


# --- history cursor validation (mirrors the list endpoint's own) -------------------------------


def test_history_malformed_cursor_is_rejected(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """A REAL, in-scope decision id: existence/authorization is checked BEFORE the cursor is even
    decoded (see `router.py`'s own `get_decision_history`), so a malformed cursor against an
    unknown/foreign decision would answer `DECISION_NOT_FOUND`, never `INVALID_CURSOR` - this test
    isolates the cursor check itself."""
    at = authed_tenant(factory, authenticated_as)
    decision_id = _full_lifecycle_decision(db_session, at.tenant)
    response = api_client.get(
        history_url(at.tenant.property.id, decision_id, cursor="not-valid-base64!!!")
    )
    assert_error(response, status_code=400, code="INVALID_CURSOR")


def test_history_cursor_cannot_escape_its_decision(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _full_lifecycle_decision(db_session, at.tenant)
    foreign_cursor = encode_decision_history_cursor(DecisionHistoryCursor(D1, 999_999, uuid4()))
    response = api_client.get(
        history_url(at.tenant.property.id, decision_id, cursor=foreign_cursor)
    )
    assert response.status_code == 200  # unsigned cursor: never a leak, just an empty tail
