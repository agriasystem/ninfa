"""Authentication & Session V1: logout and revocation (review items 60-66)."""

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.modules.auth.models import AuthSession
from app.modules.auth.service import SESSION_ABSOLUTE_LIFETIME
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


def _login(api_client: TestClient, email: str) -> str:
    response = api_client.post(LOGIN_PATH, json=login_json(email, DEFAULT_PASSWORD))
    assert response.status_code == 200, response.text
    token: str = response.cookies["ninfa_session"]
    return token


# --- 60-61: revokes the current session, clears the cookie -------------------------------------


def test_logout_revokes_the_current_session(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    raw_token = _login(api_client, user.email)

    response = api_client.post(LOGOUT_PATH)
    assert response.status_code == 204

    db_session.expire_all()
    session_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
    )
    assert session_row is not None
    assert session_row.revoked_at is not None


def test_logout_clears_the_cookie(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    response = api_client.post(LOGOUT_PATH)
    set_cookie = response.headers.get("set-cookie", "")
    assert "ninfa_session=" in set_cookie
    # A cleared cookie: empty value and an immediately-past/zero Max-Age (starlette's own
    # `delete_cookie` convention), never the still-live value.
    assert 'ninfa_session=""' in set_cookie or "ninfa_session=;" in set_cookie


# --- 62: another session of the same user is unaffected -----------------------------------------


def test_logout_does_not_revoke_other_sessions(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    first_token = _login(api_client, user.email)
    api_client.cookies.clear()
    second_token = _login(api_client, user.email)

    # Log out the SECOND session only (it is the one currently in the client's cookie jar).
    api_client.post(LOGOUT_PATH)

    db_session.expire_all()
    first_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(first_token))
    )
    second_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(second_token))
    )
    assert first_row is not None and first_row.revoked_at is None
    assert second_row is not None and second_row.revoked_at is not None


# --- 63-65: logout is always safe, never leaks, never crashes -----------------------------------


def test_repeated_logout_is_safe(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    first = api_client.post(LOGOUT_PATH)
    second = api_client.post(LOGOUT_PATH)  # the cookie the client still has is now revoked
    assert first.status_code == second.status_code == 204


def test_logout_with_an_invalid_cookie_is_safe(api_client: TestClient) -> None:
    api_client.cookies.set("ninfa_session", "not-a-real-token-at-all")
    response = api_client.post(LOGOUT_PATH)
    assert response.status_code == 204


def test_logout_with_an_expired_cookie_is_safe(
    api_client: TestClient, app: FastAPI, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    clock = MutableClock.starting_now()
    app.dependency_overrides[get_clock] = lambda: clock
    _login(api_client, user.email)
    clock.now += SESSION_ABSOLUTE_LIFETIME + timedelta(seconds=1)

    response = api_client.post(LOGOUT_PATH)
    assert response.status_code == 204


# --- 66: after logout, a business-API-shaped request is 401 -------------------------------------


def test_after_logout_the_session_endpoint_is_401(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    api_client.post(LOGOUT_PATH)

    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
