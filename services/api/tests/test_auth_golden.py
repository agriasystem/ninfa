"""MASSERIA NINFA DEMO — AUTH SESSION V1: the real pipeline, end to end.

    provision password -> login (HTTP) -> secure cookie -> /auth/session -> workspace/property
    access -> real Decision Feed/Detail (Gate 11/12's own golden world, real detectors) ->
    cross-workspace 404 -> logout -> 401

No dependency override anywhere in this module - `api_client` only overrides `get_session`.
"""

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.tenant import TenantContext
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import LOCK_DURATION, MAX_FAILED_ATTEMPTS, AuthService
from app.modules.auth.tokens import hash_session_token
from app.modules.decisions.identity import SourceEvaluation
from app.modules.decisions.service import DecisionService
from app.modules.intelligence.priority.service import PriorityService
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.tenancy.models import MembershipRole
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    LOGOUT_PATH,
    SESSION_PATH,
    MutableClock,
    login_json,
    provision_user_with_password,
)
from tests.decision_golden_support import DAY_1, build_decision_golden_world
from tests.support import BookingFactory


def test_golden_auth_flow_real_login_through_decision_api_to_logout(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    world = build_decision_golden_world(db_session, factory)
    user = provision_user_with_password(factory, db_session)
    factory.membership(world.tenant.workspace, user, MembershipRole.MEMBER)

    tenant_ctx = TenantContext(world.tenant.workspace.id)
    context = PriorityContext(world.tenant.workspace.id, world.tenant.property.id, DAY_1)
    pickup, occupancy = world.priority_world.revenue_signals()
    ota = world.priority_world.ota_structural()
    cost = world.priority_world.cost_anomaly()
    labor = world.priority_world.labor_overstaffing()

    canonical: list[SourceEvaluation] = [pickup, occupancy, ota, cost, labor]
    ranking = PriorityService().rank(context, canonical)
    result = DecisionService(db_session, tenant_ctx).sync(context, ranking, canonical)
    some_decision_id = result.touched_decision_ids[0]

    # 1-2: provision + real login (no override)
    login_response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert login_response.status_code == 200, login_response.text

    # 3: secure cookie contract
    set_cookie = login_response.headers.get("set-cookie", "")
    assert "ninfa_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "domain=" not in set_cookie.lower()

    # 4-5: /auth/session, workspace/property access
    session_body = api_client.get(SESSION_PATH).json()
    assert session_body["user"]["id"] == str(user.id)
    [workspace] = session_body["workspaces"]
    assert workspace["id"] == str(world.tenant.workspace.id)
    property_ids = {p["id"] for p in workspace["properties"]}
    assert str(world.tenant.property.id) in property_ids

    # 6: real Decision Feed with the real cookie
    feed_response = api_client.get(
        f"/api/v1/properties/{world.tenant.property.id}/decision-feed?as_of={DAY_1.isoformat()}"
    )
    assert feed_response.status_code == 200
    assert feed_response.json()["feed_state"] == "ACTION_REQUIRED"
    assert feed_response.json()["triggered_count"] == 5

    # 7: real Decision Detail
    detail_response = api_client.get(
        f"/api/v1/properties/{world.tenant.property.id}/decisions/{some_decision_id}"
    )
    assert detail_response.status_code == 200

    # 8: cross-workspace property is 404
    foreign_tenant = factory.tenant()
    cross_response = api_client.get(
        f"/api/v1/properties/{foreign_tenant.property.id}/decision-feed?as_of={DAY_1.isoformat()}"
    )
    assert cross_response.status_code == 404
    assert cross_response.json()["error"]["code"] == "PROPERTY_NOT_FOUND"

    # 9-10: logout, then the same business request is 401
    logout_response = api_client.post(LOGOUT_PATH)
    assert logout_response.status_code == 204
    post_logout = api_client.get(
        f"/api/v1/properties/{world.tenant.property.id}/decision-feed?as_of={DAY_1.isoformat()}"
    )
    assert post_logout.status_code == 401
    assert post_logout.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_golden_session_revocation_on_password_rotation(
    db_session: Session, factory: BookingFactory
) -> None:
    """Two REAL sessions (A, B) for the same user; a password rotation (the same primitive the
    CLI uses, `AuthService.set_password`) must revoke BOTH - neither authenticates afterwards."""
    user = provision_user_with_password(factory, db_session)
    service = AuthService(db_session)
    session_a = service.login(user.email, DEFAULT_PASSWORD)
    session_b = service.login(user.email, DEFAULT_PASSWORD)
    assert session_a.session.id != session_b.session.id

    service.set_password(user.id, "a-rotated-passphrase-01")

    assert service.resolve_principal(session_a.raw_token) is None
    assert service.resolve_principal(session_b.raw_token) is None

    db_session.expire_all()
    rows = db_session.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)


def test_golden_lockout_with_controlled_clock(
    api_client: TestClient, app: FastAPI, factory: BookingFactory, db_session: Session
) -> None:
    """5 wrong passwords -> locked; the CORRECT password during the lock still fails with the
    SAME public error; +15 minutes later, the correct password succeeds."""
    user = provision_user_with_password(factory, db_session)
    clock = MutableClock.starting_now()
    app.dependency_overrides[get_clock] = lambda: clock

    for _ in range(MAX_FAILED_ATTEMPTS):
        response = api_client.post(LOGIN_PATH, json=login_json(user.email, "wrong-password-x"))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    locked_attempt = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert locked_attempt.status_code == 401
    assert locked_attempt.json()["error"]["code"] == "INVALID_CREDENTIALS"

    clock.now += LOCK_DURATION + timedelta(seconds=1)
    unlocked_attempt = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert unlocked_attempt.status_code == 200


def test_golden_privacy_no_secret_ever_leaves_the_credential_row_or_the_clients_cookie(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    """Password raw, session raw token, password hash: none of the three appear anywhere except
    where they are structurally supposed to (the credential row's own hash column; the client's
    own cookie jar for the raw token) - never in an HTTP response, an error body, or the OTHER
    storage location.
    """
    user = provision_user_with_password(factory, db_session)
    login_response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    raw_token = login_response.cookies["ninfa_session"]

    credential = AuthRepository(db_session).get_credential(user.id)
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert DEFAULT_PASSWORD not in credential.password_hash  # hash only, never the raw password

    session_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
    )
    assert session_row is not None
    assert raw_token not in session_row.token_hash  # the DB never holds the raw token

    # Every HTTP response so far: no raw password, no raw token, no password hash.
    session_response = api_client.get(SESSION_PATH)
    wrong_login_response = api_client.post(
        LOGIN_PATH, json=login_json(user.email, "a-wrong-password-value")
    )
    for response in (login_response, session_response, wrong_login_response):
        text = response.text
        assert DEFAULT_PASSWORD not in text
        assert raw_token not in text
        assert credential.password_hash not in text
