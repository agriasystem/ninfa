"""Authentication & Session V1: `get_current_principal`'s real cookie -> session -> User
resolution path (review items 39-47). `GET /auth/session` is used as the "protected resource"
throughout: it depends on the SAME cookie/hash/expiry/revocation logic as every Decision API
route (see `app.api.v1.auth.deps.get_current_auth_session`).
"""

import logging
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.modules.auth.models import AuthSession
from app.modules.auth.service import SESSION_ABSOLUTE_LIFETIME, AuthService
from app.modules.auth.tokens import hash_session_token
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    LOGOUT_PATH,
    SESSION_PATH,
    MutableClock,
    login_json,
    provision_user_with_password,
)
from tests.support import BookingFactory


def _login(api_client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> str:
    response = api_client.post(LOGIN_PATH, json=login_json(email, password))
    assert response.status_code == 200, response.text
    token: str = response.cookies["ninfa_session"]
    return token


# --- 39-41: valid / missing / random cookie -----------------------------------------------------


def test_valid_cookie_resolves_the_principal(db_session: Session, factory: BookingFactory) -> None:
    user = provision_user_with_password(factory, db_session)
    session_result = AuthService(db_session).login(user.email, DEFAULT_PASSWORD)
    principal = AuthService(db_session).resolve_principal(session_result.raw_token)
    assert principal is not None
    assert principal.user_id == user.id


def test_no_cookie_is_401(api_client: TestClient) -> None:
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_random_cookie_is_401(api_client: TestClient) -> None:
    api_client.cookies.set("ninfa_session", "a-syntactically-fine-but-entirely-made-up-token")
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


# --- 42-43: expired / revoked session -----------------------------------------------------------


def test_expired_session_is_401(
    api_client: TestClient, app: FastAPI, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    clock = MutableClock.starting_now()
    app.dependency_overrides[get_clock] = lambda: clock
    _login(api_client, user.email)

    clock.now += SESSION_ABSOLUTE_LIFETIME + timedelta(seconds=1)
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_revoked_session_is_401(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    logout = api_client.post(LOGOUT_PATH)
    assert logout.status_code == 204

    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401


# --- 44: an inactive user's otherwise-valid session is 401 --------------------------------------


def test_inactive_user_with_an_otherwise_valid_session_is_401(
    db_session: Session, factory: BookingFactory
) -> None:
    """A real `DELETE` on `users` would `CASCADE` and remove the session with it - there is no
    "missing user, session still present" state to reach that way. A deactivated (`is_active =
    False`) user IS a real, reachable state, and is this boundary's own version of "the user is
    gone" (see `AuthService._resolve_valid_session`)."""
    user = provision_user_with_password(factory, db_session)
    result = AuthService(db_session).login(user.email, DEFAULT_PASSWORD)
    user.is_active = False
    db_session.flush()

    principal = AuthService(db_session).resolve_principal(result.raw_token)
    assert principal is None


# --- 45: the raw session token is never logged ---------------------------------------------------


def test_raw_session_token_never_appears_in_logs(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = provision_user_with_password(factory, db_session)
    with caplog.at_level(logging.DEBUG):
        raw_token = _login(api_client, user.email)
        api_client.get(SESSION_PATH)
    for record in caplog.records:
        assert raw_token not in record.getMessage()


# --- 46: no DB write on a normal authenticated GET ------------------------------------------------


def test_authenticated_session_get_makes_zero_writes(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    before = db_session.scalar(select(func.count()).select_from(AuthSession)) or 0

    for _ in range(3):
        response = api_client.get(SESSION_PATH)
        assert response.status_code == 200

    after = db_session.scalar(select(func.count()).select_from(AuthSession)) or 0
    assert after == before


# --- 47: absolute expiry, never sliding -----------------------------------------------------------


def test_expiry_never_slides_on_repeated_authenticated_gets(
    api_client: TestClient, app: FastAPI, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    clock = MutableClock.starting_now()
    app.dependency_overrides[get_clock] = lambda: clock
    raw_token = _login(api_client, user.email)

    original_expiry = db_session.scalar(
        select(AuthSession.expires_at).where(
            AuthSession.token_hash == hash_session_token(raw_token)
        )
    )
    assert original_expiry is not None

    for days in (1, 2, 3):
        clock.now += timedelta(days=days)
        api_client.get(SESSION_PATH)

    db_session.expire_all()
    final_expiry = db_session.scalar(
        select(AuthSession.expires_at).where(
            AuthSession.token_hash == hash_session_token(raw_token)
        )
    )
    assert final_expiry == original_expiry  # unchanged: absolute, never sliding
