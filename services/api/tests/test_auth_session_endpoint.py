"""Authentication & Session V1: `GET /auth/session` response contract (review items 48-59)."""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import AuthSession
from app.modules.auth.tokens import hash_session_token
from app.modules.tenancy.models import MembershipRole
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    SESSION_PATH,
    login_json,
    provision_user_with_password,
)
from tests.support import BookingFactory


def _login(api_client: TestClient, email: str) -> str:
    response = api_client.post(LOGIN_PATH, json=login_json(email, DEFAULT_PASSWORD))
    assert response.status_code == 200, response.text
    token: str = response.cookies["ninfa_session"]
    return token


# --- 48-51: authenticated context, user id/email, expiry ---------------------------------------


def test_authenticated_session_context_returns_200(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    response = api_client.get(SESSION_PATH)
    assert response.status_code == 200, response.text


def test_user_id_and_email_are_correct(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    body = api_client.get(SESSION_PATH).json()
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["email"] == user.email  # 50: email exists on the real User model


def test_session_expiry_is_returned(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    raw_token = _login(api_client, user.email)
    body = api_client.get(SESSION_PATH).json()

    expected = db_session.scalar(
        select(AuthSession.expires_at).where(
            AuthSession.token_hash == hash_session_token(raw_token)
        )
    )
    assert expected is not None
    assert datetime.fromisoformat(body["session"]["expires_at"]) == expected


# --- 52-54: workspace/property access, cross-workspace membership -------------------------------


def test_accessible_workspaces_and_properties_are_correct(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant.workspace, user, MembershipRole.ADMIN)
    _login(api_client, user.email)

    body = api_client.get(SESSION_PATH).json()
    [workspace] = body["workspaces"]
    assert workspace["id"] == str(tenant.workspace.id)
    assert workspace["slug"] == tenant.workspace.slug
    assert workspace["role"] == "ADMIN"
    [prop] = workspace["properties"]
    assert prop["id"] == str(tenant.property.id)
    assert prop["slug"] == tenant.property.slug


def test_cross_workspace_memberships_all_appear(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant_a = factory.tenant()
    tenant_b = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant_a.workspace, user)
    factory.membership(tenant_b.workspace, user)
    _login(api_client, user.email)

    body = api_client.get(SESSION_PATH).json()
    workspace_ids = {w["id"] for w in body["workspaces"]}
    assert workspace_ids == {str(tenant_a.workspace.id), str(tenant_b.workspace.id)}


def test_a_user_with_no_membership_sees_no_workspaces(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    body = api_client.get(SESSION_PATH).json()
    assert body["workspaces"] == []


# --- 55-58: no credential/session internals, no unpermitted PII ---------------------------------


def test_response_never_contains_credential_or_session_secrets(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    raw_token = _login(api_client, user.email)
    response = api_client.get(SESSION_PATH)
    raw_text = response.text

    assert DEFAULT_PASSWORD not in raw_text
    assert raw_token not in raw_text  # 56: no session token
    assert hash_session_token(raw_token) not in raw_text  # 57: no token hash
    assert "$argon2id$" not in raw_text  # 55: no credential hash
    assert "password" not in raw_text.lower()


def test_no_pii_beyond_the_explicitly_permitted_account_fields(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    body = api_client.get(SESSION_PATH).json()
    assert set(body["user"].keys()) == {"id", "email", "display_name"}


# --- 59: Cache-Control: no-store -----------------------------------------------------------------


def test_session_response_is_never_cached(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    user = provision_user_with_password(factory, db_session)
    _login(api_client, user.email)
    response = api_client.get(SESSION_PATH)
    assert response.headers.get("cache-control") == "no-store"
