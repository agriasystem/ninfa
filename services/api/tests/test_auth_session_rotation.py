"""Authentication & Session V1 rotation semantics (Gate 13 integrity-check follow-up).

The real contract, confirmed by reading `AuthService.login`/`logout_by_raw_token` and
`AuthRepository.revoke_session`/`revoke_all_sessions_for_user`:

    login WITH a valid incoming session cookie  -> revokes ONLY that one session (by its own
                                                     token hash), never every session of the user.
    login WITHOUT a cookie, or a FAILED login    -> revokes nothing at all.
    logout                                        -> revokes ONLY the session named by its cookie.
    password rotation (`AuthService.set_password`) -> the ONE operation that revokes EVERY
                                                        session of the user.

NO dependency override of `get_current_principal` anywhere in this module: like
`test_auth_real_cookie_e2e.py`, every session here is authenticated through the REAL
cookie -> session -> User path. A single `api_client` stands in for as many independent
browsers as a test needs; per-request `cookies=` is deprecated by httpx2 (ambiguous
persistence), so every simulated device switch goes through the client's OWN jar instead -
`.cookies.clear()` for "a different, cookie-less browser", `.cookies.set(...)` for "this
browser presents exactly this token" - the same technique `test_auth_login.py::
test_two_independent_logins_produce_distinct_sessions` already uses for the clear() half.
"""

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from app.core.auth import SESSION_COOKIE_NAME
from app.modules.auth.service import AuthService
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    LOGOUT_PATH,
    SESSION_PATH,
    login_json,
    provision_user_with_password,
)
from tests.support import BookingFactory

WRONG_PASSWORD = "definitely-the-wrong-passphrase"


def _present_only(client: TestClient, cookie: str | None) -> None:
    """Make the client's jar hold EXACTLY this one cookie (or none) - simulating "this browser's
    own cookie is X" without any risk of a stale value from an earlier call leaking in."""
    client.cookies.clear()
    if cookie is not None:
        client.cookies.set(SESSION_COOKIE_NAME, cookie)


def _login(client: TestClient, email: str, password: str, *, cookie: str | None = None) -> Response:
    _present_only(client, cookie)
    return client.post(LOGIN_PATH, json=login_json(email, password))


def _logout(client: TestClient, cookie: str) -> Response:
    _present_only(client, cookie)
    return client.post(LOGOUT_PATH)


def _get_session(client: TestClient, cookie: str) -> Response:
    _present_only(client, cookie)
    return client.get(SESSION_PATH)


# --- 4: multi-device sessions are simultaneously valid -------------------------------------------


def test_two_devices_logging_in_independently_both_stay_valid(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)

    login_a = _login(api_client, user.email, DEFAULT_PASSWORD)  # fresh browser: no cookie
    token_a = login_a.cookies[SESSION_COOKIE_NAME]

    login_b = _login(api_client, user.email, DEFAULT_PASSWORD)  # a second, independent browser
    token_b = login_b.cookies[SESSION_COOKIE_NAME]
    assert token_a != token_b

    assert _get_session(api_client, token_a).status_code == 200
    assert _get_session(api_client, token_b).status_code == 200


# --- 5: same-browser relogin rotates only that browser's own session -----------------------------


def test_relogin_from_the_same_browser_rotates_its_own_session_only(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)

    first = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_a = first.cookies[SESSION_COOKIE_NAME]

    login_b = _login(api_client, user.email, DEFAULT_PASSWORD)  # a different browser
    token_b = login_b.cookies[SESSION_COOKIE_NAME]

    # The SAME browser as the first login: its cookie is token_a, presented explicitly here -
    # exactly what a real browser would attach automatically.
    second = _login(api_client, user.email, DEFAULT_PASSWORD, cookie=token_a)
    assert second.status_code == 200
    token_a2 = second.cookies[SESSION_COOKIE_NAME]
    assert token_a2 != token_a

    assert _get_session(api_client, token_a).status_code == 401  # A: revoked
    assert _get_session(api_client, token_a2).status_code == 200  # A2: valid
    assert _get_session(api_client, token_b).status_code == 200  # B: untouched


# --- 6: logout is session-scoped ------------------------------------------------------------------


def test_logout_revokes_only_the_current_session(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)

    login_a = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_a = login_a.cookies[SESSION_COOKIE_NAME]

    login_b = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_b = login_b.cookies[SESSION_COOKIE_NAME]

    assert _logout(api_client, token_a).status_code == 204

    assert _get_session(api_client, token_a).status_code == 401
    assert _get_session(api_client, token_b).status_code == 200


# --- 7: password rotation revokes every active session of the user -------------------------------


def test_password_rotation_revokes_every_active_session_of_the_user(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)

    login_a = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_a = login_a.cookies[SESSION_COOKIE_NAME]

    login_b = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_b = login_b.cookies[SESSION_COOKIE_NAME]

    new_password = "a-brand-new-passphrase-9876"
    AuthService(db_session).set_password(user.id, new_password)  # the real service primitive

    assert _get_session(api_client, token_a).status_code == 401
    assert _get_session(api_client, token_b).status_code == 401

    stale = _login(api_client, user.email, DEFAULT_PASSWORD)
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "INVALID_CREDENTIALS"

    fresh = _login(api_client, user.email, new_password)
    assert fresh.status_code == 200


# --- 8: a failed login attempt never revokes an already-valid session ----------------------------


def test_failed_login_does_not_revoke_an_existing_valid_session(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)

    login_b = _login(api_client, user.email, DEFAULT_PASSWORD)
    token_b = login_b.cookies[SESSION_COOKIE_NAME]
    assert _get_session(api_client, token_b).status_code == 200

    # The SAME browser, its own valid cookie attached, tries again with the wrong password.
    failed = _login(api_client, user.email, WRONG_PASSWORD, cookie=token_b)
    assert failed.status_code == 401
    assert failed.json()["error"]["code"] == "INVALID_CREDENTIALS"

    assert _get_session(api_client, token_b).status_code == 200
