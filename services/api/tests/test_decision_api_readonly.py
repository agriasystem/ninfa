"""Decision API V1: every GET is read-only (Gate 12 review items 103-109)."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.decisions.models import Decision
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import (
    authed_tenant,
    decision_table_counts,
    detail_url,
    feed_url,
    history_url,
    list_url,
)
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
D1_ISO = "2026-08-01"
STAY = date(2026, 8, 15)


def _seed_open_decision(db_session: Session, tenant: Tenant) -> UUID:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    db_session.flush()
    return decision_id


def test_feed_makes_zero_writes(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    before_counts = decision_table_counts(db_session)
    before_decision = db_session.get(Decision, decision_id)
    assert before_decision is not None
    before_updated_at = before_decision.updated_at

    api_client.get(feed_url(at.tenant.property.id, D1_ISO))

    assert decision_table_counts(db_session) == before_counts  # 103
    db_session.expire_all()
    after_decision = db_session.get(Decision, decision_id)
    assert after_decision is not None
    assert after_decision.updated_at == before_updated_at  # 107


def test_list_makes_zero_writes(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    _seed_open_decision(db_session, at.tenant)
    before_counts = decision_table_counts(db_session)

    api_client.get(list_url(at.tenant.property.id))

    assert decision_table_counts(db_session) == before_counts  # 104


def test_detail_makes_zero_writes(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    before_counts = decision_table_counts(db_session)

    api_client.get(detail_url(at.tenant.property.id, decision_id))

    assert decision_table_counts(db_session) == before_counts  # 105


def test_history_makes_zero_writes(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    before_counts = decision_table_counts(db_session)

    api_client.get(history_url(at.tenant.property.id, decision_id))

    assert decision_table_counts(db_session) == before_counts  # 106


def test_get_never_creates_a_new_observation_or_run(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    before = decision_table_counts(db_session)

    for _ in range(3):  # repeated GETs: still nothing written
        api_client.get(feed_url(at.tenant.property.id, D1_ISO))
        api_client.get(list_url(at.tenant.property.id))
        api_client.get(detail_url(at.tenant.property.id, decision_id))
        api_client.get(history_url(at.tenant.property.id, decision_id))

    after = decision_table_counts(db_session)
    assert after == before  # 108: no new DecisionObservation
    assert after["decision_runs"] == before["decision_runs"]  # 109: no new DecisionRun
