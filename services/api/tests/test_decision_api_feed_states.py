"""Decision API V1: the four feed states are mutually exclusive and their JSON null-contract is
unambiguous (Gate 12 final contract integrity review, items 1/4/9/10).

Golden proof that each state is reachable through the REAL detector pipeline lives in
`test_decision_api_golden.py`; this module is the unit-level completeness/exclusivity matrix and
the explicit null-vs-non-null contract check, using Gate 11's own `decision_support.py` builders
(status is set directly, not derived from real data - the state LOGIC is what is under test here).
"""

from collections.abc import Callable
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.intelligence.revenue.types import EvaluationStatus
from tests.decision_api_support import authed_tenant, feed_url
from tests.decision_support import (
    CLEAR,
    INSUFFICIENT,
    NOT_APPLICABLE,
    SUPPRESSED,
    TRIGGERED,
    Evaluation,
    revenue_evaluation,
    sync_run,
)
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"
STAY = date(2026, 8, 15)

_ALL_STATES = {"NOT_PROCESSED", "ACTION_REQUIRED", "DATA_QUALITY_LIMITED", "NO_ACTION_REQUIRED"}


def _sync(db_session: Session, tenant: Tenant, evaluations: list[Evaluation]) -> None:
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    sync_run(db_session, TenantContext(tenant.workspace.id), context, evaluations)


def _evaluation(tenant: Tenant, status: EvaluationStatus, stay_offset: int = 0) -> Evaluation:
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY + timedelta(days=stay_offset),
        snapshot_local_date=D1,
        status=status,
    )


@pytest.mark.parametrize(
    ("run_exists", "statuses", "expected_state"),
    [
        (False, (), "NOT_PROCESSED"),
        (True, (TRIGGERED,), "ACTION_REQUIRED"),
        (True, (TRIGGERED, INSUFFICIENT), "ACTION_REQUIRED"),  # any triggered wins
        (True, (INSUFFICIENT,), "DATA_QUALITY_LIMITED"),
        (True, (SUPPRESSED,), "DATA_QUALITY_LIMITED"),
        (True, (INSUFFICIENT, SUPPRESSED), "DATA_QUALITY_LIMITED"),
        (True, (CLEAR,), "NO_ACTION_REQUIRED"),
        (True, (NOT_APPLICABLE,), "NO_ACTION_REQUIRED"),
        (True, (CLEAR, NOT_APPLICABLE), "NO_ACTION_REQUIRED"),
    ],
    ids=[
        "no-run",
        "triggered-only",
        "triggered-plus-insufficient",
        "insufficient-only",
        "suppressed-only",
        "insufficient-and-suppressed",
        "clear-only",
        "not-applicable-only",
        "clear-and-not-applicable",
    ],
)
def test_feed_state_matrix(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
    run_exists: bool,
    statuses: tuple[EvaluationStatus, ...],
    expected_state: str,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    if run_exists:
        evaluations = [
            _evaluation(at.tenant, status, offset) for offset, status in enumerate(statuses)
        ]
        _sync(db_session, at.tenant, evaluations)

    body = api_client.get(feed_url(at.tenant.property.id, D1_ISO)).json()
    assert body["feed_state"] == expected_state
    # mutual exclusivity: exactly one of the four states matches, never more, never zero.
    other_states = _ALL_STATES - {expected_state}
    assert body["feed_state"] not in other_states


# --- explicit null-vs-non-null contract per state (items 9-10) --------------------------------


def test_not_processed_has_null_run_and_null_counts(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    body = api_client.get(feed_url(at.tenant.property.id, D1_ISO)).json()
    assert body["feed_state"] == "NOT_PROCESSED"
    assert body["decision_run_id"] is None
    assert body["run_sequence"] is None
    for field in (
        "triggered_count",
        "clear_count",
        "insufficient_count",
        "not_applicable_count",
        "suppressed_count",
    ):
        assert body[field] is None, field


def test_no_action_required_has_non_null_run_and_numeric_counts(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    _sync(db_session, at.tenant, [_evaluation(at.tenant, CLEAR)])
    body = api_client.get(feed_url(at.tenant.property.id, D1_ISO)).json()
    assert body["feed_state"] == "NO_ACTION_REQUIRED"
    assert body["decision_run_id"] is not None
    assert body["run_sequence"] is not None
    assert body["triggered_count"] == 0
    assert body["clear_count"] == 1
    assert body["insufficient_count"] == 0
    assert body["suppressed_count"] == 0


def test_data_quality_limited_has_non_null_run_zero_triggered_and_empty_items(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    _sync(db_session, at.tenant, [_evaluation(at.tenant, INSUFFICIENT)])
    body = api_client.get(feed_url(at.tenant.property.id, D1_ISO)).json()
    assert body["feed_state"] == "DATA_QUALITY_LIMITED"
    assert body["decision_run_id"] is not None
    assert body["triggered_count"] == 0
    assert body["insufficient_count"] == 1
    assert body["items"] == []
