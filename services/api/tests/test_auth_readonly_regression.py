"""Authentication & Session V1: Gate 12's read-only guarantees still hold with a REAL session
cookie authenticating the request (review items 97-102), and the session endpoint itself writes
nothing and has no `last_seen` concept at all.
"""

from datetime import date
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.auth.models import AuthSession
from app.modules.auth.tokens import hash_session_token
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.tenancy.models import MembershipRole
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    SESSION_PATH,
    login_json,
    provision_user_with_password,
)
from tests.decision_api_support import decision_table_counts
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant


def _login(api_client: TestClient, email: str) -> None:
    response = api_client.post(LOGIN_PATH, json=login_json(email, DEFAULT_PASSWORD))
    assert response.status_code == 200, response.text


def _authed_property(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> tuple[Tenant, UUID]:
    tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    _login(api_client, user.email)

    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=date(2026, 8, 15),
        snapshot_local_date=date(2026, 8, 1),
    )
    outcome = sync_run(
        db_session,
        TenantContext(tenant.workspace.id),
        PriorityContext(tenant.workspace.id, tenant.property.id, date(2026, 8, 1)),
        [evaluation],
    )
    [decision_id] = outcome.result.touched_decision_ids
    return tenant, decision_id


# --- 97-100: feed/list/detail/history make zero writes, real cookie -----------------------------


def test_authenticated_feed_makes_zero_writes(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant, _decision_id = _authed_property(api_client, factory, db_session)
    before = decision_table_counts(db_session)
    response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decision-feed?as_of=2026-08-01"
    )
    assert response.status_code == 200
    assert decision_table_counts(db_session) == before


def test_authenticated_list_makes_zero_writes(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant, _decision_id = _authed_property(api_client, factory, db_session)
    before = decision_table_counts(db_session)
    response = api_client.get(f"/api/v1/properties/{tenant.property.id}/decisions")
    assert response.status_code == 200
    assert decision_table_counts(db_session) == before


def test_authenticated_detail_makes_zero_writes(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant, decision_id = _authed_property(api_client, factory, db_session)
    before = decision_table_counts(db_session)
    response = api_client.get(f"/api/v1/properties/{tenant.property.id}/decisions/{decision_id}")
    assert response.status_code == 200
    assert decision_table_counts(db_session) == before


def test_authenticated_history_makes_zero_writes(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant, decision_id = _authed_property(api_client, factory, db_session)
    before = decision_table_counts(db_session)
    response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decisions/{decision_id}/history"
    )
    assert response.status_code == 200
    assert decision_table_counts(db_session) == before


# --- 101: the session endpoint never extends its own session's expiry ---------------------------


def test_session_get_never_extends_its_own_expiry(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    raw_token = api_client.cookies["ninfa_session"]
    token_hash = hash_session_token(raw_token)
    before = db_session.scalar(
        select(AuthSession.expires_at).where(AuthSession.token_hash == token_hash)
    )
    for _ in range(3):
        api_client.get(SESSION_PATH)
    db_session.expire_all()
    after = db_session.scalar(
        select(AuthSession.expires_at).where(AuthSession.token_hash == token_hash)
    )
    assert before == after


# --- 102: there is no last_seen column at all (V1 design, not just "unused") ---------------------


def test_auth_session_has_no_last_seen_column() -> None:
    columns = {col.name for col in inspect(AuthSession).columns}
    assert "last_seen" not in columns
    assert "last_seen_at" not in columns
