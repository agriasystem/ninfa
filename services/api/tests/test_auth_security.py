"""Authentication & Session V1: security guarantees (review items 88-96)."""

import ast
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.v1.auth as auth_api_package
import app.core.auth as core_auth_module
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    SESSION_PATH,
    login_json,
    provision_user_with_password,
)
from tests.support import BookingFactory

_SOURCE_FILES = [
    Path(core_auth_module.__file__),
    *Path(auth_api_package.__file__).parent.glob("*.py"),
]


def _all_source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _SOURCE_FILES)


def _all_identifiers() -> set[str]:
    identifiers: set[str] = set()
    for path in _SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                identifiers.add(node.value)
            elif isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
    return identifiers


# --- 88: no localStorage/sessionStorage anywhere in the backend's own auth source ---------------


def test_no_local_or_session_storage_reference_in_backend_auth_source() -> None:
    text = _all_source_text()
    assert "localStorage" not in text
    assert "sessionStorage" not in text


# --- 89-91: no spoofable header, no bearer fallback, ever -----------------------------------------


def test_no_x_user_id_or_custom_header_identifier_in_source() -> None:
    identifiers = {i.lower().replace("-", "").replace("_", "") for i in _all_identifiers()}
    for forbidden in ("xuserid", "xauthuser", "xworkspace", "xproperty"):
        assert forbidden not in identifiers, forbidden


def test_x_user_id_header_does_not_authenticate(
    api_client: TestClient, factory: BookingFactory
) -> None:
    user = factory.user()
    response = api_client.get(SESSION_PATH, headers={"X-User-Id": str(user.id)})
    assert response.status_code == 401


def test_custom_x_auth_user_header_does_not_authenticate(api_client: TestClient) -> None:
    response = api_client.get(SESSION_PATH, headers={"X-Auth-User": "someone@example.com"})
    assert response.status_code == 401


def test_bearer_authorization_header_does_not_authenticate(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    login = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    raw_token = login.cookies["ninfa_session"]
    api_client.cookies.clear()  # only the header remains, never the cookie

    response = api_client.get(SESSION_PATH, headers={"Authorization": f"Bearer {raw_token}"})
    assert response.status_code == 401


# --- 92-93: fail-closed by default, real cookie succeeds ------------------------------------------


def test_no_credentials_at_all_is_still_fail_closed(api_client: TestClient) -> None:
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_a_real_valid_cookie_now_succeeds_where_gate_12_always_failed(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    """Gate 12's own `get_current_principal` was UNCONDITIONALLY 401 in production - proving the
    seam is now real: the identical dependency, given a real cookie, answers 200."""
    user = provision_user_with_password(factory, db_session)
    api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 200


# --- 94-95: no request body / no secret ever logged or echoed in an error -----------------------


def test_login_request_body_is_never_logged(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = provision_user_with_password(factory, db_session)
    with caplog.at_level(logging.DEBUG):
        api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    for record in caplog.records:
        message = record.getMessage()
        assert DEFAULT_PASSWORD not in message
        assert user.email not in message


def test_error_responses_never_contain_a_hash_token_or_password(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    response = api_client.post(LOGIN_PATH, json=login_json(user.email, "totally-wrong-password"))
    text = response.text
    assert "$argon2id$" not in text
    assert "totally-wrong-password" not in text
    assert DEFAULT_PASSWORD not in text


# --- 96: OpenAPI never exposes a credential/session-secret field ----------------------------------


def test_openapi_schema_has_no_credential_or_token_fields(client: TestClient) -> None:
    """Checks actual SCHEMA FIELD NAMES, not prose: a docstring is free to explain the design
    rationale (and may legitimately name "argon2" while doing so - see `LoginRequest`'s own),
    but no response/request schema may declare a property named after a credential internal."""
    schema = client.get("/openapi.json").json()
    all_field_names = {
        name
        for definition in schema.get("components", {}).get("schemas", {}).values()
        for name in definition.get("properties", {})
    }
    # "password" itself is NOT forbidden: `LoginRequest.password` is the client's own input,
    # never a server secret echoed back. These are the actual internal/credential fields.
    forbidden_fields = {
        "password_hash",
        "token_hash",
        "raw_token",
        "locked_until",
        "failed_login_count",
    }
    assert not (all_field_names & forbidden_fields)
