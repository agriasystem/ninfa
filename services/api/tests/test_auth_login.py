"""Authentication & Session V1: login behaviour, cookie security, enumeration (review items
13-30)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.models import AuthSession
from app.modules.auth.tokens import hash_session_token
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    login_json,
    provision_user_with_password,
)
from tests.support import BookingFactory

# --- 13-18: successful login, cookie flags -----------------------------------------------------


def test_valid_login_returns_200(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert response.status_code == 200, response.text


def _set_cookie_header(response: Any) -> str:
    header = response.headers.get("set-cookie")
    assert header is not None, "no Set-Cookie header on the login response"
    return str(header)


def test_set_cookie_present_and_named_ninfa_session(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert "ninfa_session=" in _set_cookie_header(response)


def test_cookie_is_httponly(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert "httponly" in _set_cookie_header(response).lower()


def test_cookie_is_samesite_lax(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert "samesite=lax" in _set_cookie_header(response).lower()


def test_cookie_path_is_root(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert "path=/" in _set_cookie_header(response).lower()


def test_cookie_has_no_domain_attribute(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert "domain=" not in _set_cookie_header(response).lower()  # host-only


# --- 19-20: Secure flag config ------------------------------------------------------------------


def test_production_settings_require_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEBUG", "false")

    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        Settings()


def test_local_dev_can_explicitly_disable_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
        app_env="development",
        session_cookie_secure=False,
    )
    assert settings.session_cookie_secure is False


def test_default_prefers_secure_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.session_cookie_secure is True


# --- 21-24: generic invalid-credentials, no enumeration ----------------------------------------


def test_unknown_email_is_401_invalid_credentials(api_client: TestClient) -> None:
    response = api_client.post(LOGIN_PATH, json=login_json("nobody@example.com", "irrelevant-pw"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_wrong_password_is_the_same_response(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, "definitely-wrong-pw"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_user_with_no_credential_is_the_same_response(
    api_client: TestClient, factory: BookingFactory
) -> None:
    user = factory.user()  # no AuthService.set_password() call: no credential row exists
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, "any-password-at-all"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_no_enumeration_detail_all_failure_bodies_are_identical_shape(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    no_credential_user = factory.user()
    responses = [
        api_client.post(LOGIN_PATH, json=login_json("unknown@example.com", "whatever-password")),
        api_client.post(LOGIN_PATH, json=login_json(user.email, "wrong-password-value")),
        api_client.post(LOGIN_PATH, json=login_json(no_credential_user.email, "whatever-password")),
    ]
    bodies = [
        {"code": r.json()["error"]["code"], "message": r.json()["error"]["message"]}
        for r in responses
    ]
    assert len({str(body) for body in bodies}) == 1  # byte-identical code+message every time
    assert all(r.status_code == 401 for r in responses)


# --- 25-28: session creation, token hash contract ----------------------------------------------


def test_login_creates_a_session_row(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    before = db_session.scalar(select(func.count()).select_from(AuthSession)) or 0
    api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    after = db_session.scalar(select(func.count()).select_from(AuthSession)) or 0
    assert after == before + 1


def test_db_contains_only_the_token_hash_never_the_raw_token(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    raw_token = response.cookies["ninfa_session"]

    session_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
    )
    assert session_row is not None
    assert raw_token not in session_row.token_hash  # 27: raw token != DB value
    assert session_row.token_hash == hash_session_token(raw_token)
    assert len(session_row.token_hash) == 64  # 28: 64-char hex
    assert all(c in "0123456789abcdef" for c in session_row.token_hash)


# --- 29-30: session fixation hygiene, distinct sessions -----------------------------------------


def test_new_login_revokes_the_incoming_valid_session(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    first = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    first_token = first.cookies["ninfa_session"]
    first_hash = hash_session_token(first_token)

    # `api_client` (httpx TestClient) keeps the cookie jar across calls, so this second login
    # genuinely presents the FIRST session's own cookie as the "incoming" one.
    second = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert second.status_code == 200
    second_token = second.cookies["ninfa_session"]
    assert second_token != first_token

    db_session.expire_all()
    first_session_row = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == first_hash)
    )
    assert first_session_row is not None
    assert first_session_row.revoked_at is not None


def test_two_independent_logins_produce_distinct_sessions(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    first = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    api_client.cookies.clear()  # a second, independent client/browser: no shared cookie jar
    second = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert first.cookies["ninfa_session"] != second.cookies["ninfa_session"]
