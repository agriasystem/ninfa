"""Recommendation Engine V1 read-only guarantee (review items 60-64): ZERO persistence - no new
table, no mutation of `Decision`/`DecisionObservation`/`DecisionRun`, not even on repeated GETs.
Reuses `test_decision_api_readonly.py`'s own `decision_table_counts()` unmodified - the
recommendation is computed fresh on every request, never written anywhere.
"""

import ast
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.modules.recommendations as recommendations_package
from app.core.tenant import TenantContext
from app.modules.decisions.models import Decision
from app.modules.intelligence.priority.types import PriorityContext
from tests.decision_api_support import authed_tenant, decision_table_counts, detail_url
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)

PACKAGE_DIR = Path(recommendations_package.__file__).parent
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))


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


# --- 60: no recommendation table exists in the schema at all ------------------------------------


def test_no_recommendation_table_exists_in_the_database(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename ILIKE '%recommendation%'"
        )
    ).all()
    assert rows == []


def test_no_orm_model_in_the_package_declares_a_tablename() -> None:
    """Structural, without a database: no `__tablename__` assignment anywhere in the package's
    own source - the module could not persist even if a session were smuggled in."""
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                assert "__tablename__" not in names, path.name


# --- 61-64: repeated detail GETs never mutate Decision Memory -----------------------------------


def test_detail_get_with_recommendation_makes_zero_writes(
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

    response = api_client.get(detail_url(at.tenant.property.id, decision_id))
    assert response.status_code == 200, response.text
    assert "recommendation" in response.json()

    assert decision_table_counts(db_session) == before_counts
    db_session.expire_all()
    after_decision = db_session.get(Decision, decision_id)
    assert after_decision is not None
    assert after_decision.updated_at == before_updated_at


def test_repeated_detail_gets_never_create_a_new_observation_or_run(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    before = decision_table_counts(db_session)

    for _ in range(5):
        response = api_client.get(detail_url(at.tenant.property.id, decision_id))
        assert response.json()["recommendation"]["fingerprint"]  # engine runs fresh each time

    after = decision_table_counts(db_session)
    assert after == before
    assert after["decision_runs"] == before["decision_runs"]


def test_repeated_detail_gets_produce_the_identical_recommendation(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    """Never memoised, never drifting across requests - the same persisted row, read twice,
    yields byte-identical recommendation JSON."""
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)

    first = api_client.get(detail_url(at.tenant.property.id, decision_id)).json()
    second = api_client.get(detail_url(at.tenant.property.id, decision_id)).json()

    assert first["recommendation"] == second["recommendation"]
