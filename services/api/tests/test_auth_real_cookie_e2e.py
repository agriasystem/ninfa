"""Authentication & Session V1: the CRITICAL end-to-end test (review items 67-73).

NO dependency override of `get_current_principal` anywhere in this module: `api_client` only ever
overrides `get_session` (so the test's own `factory`-built rows are visible to the HTTP call, and
nothing outlives the test) - authentication itself goes through the REAL cookie -> session ->
User path, exactly as a real browser would.
"""

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.tenancy.models import MembershipRole
from tests.auth_support import (
    DEFAULT_PASSWORD,
    LOGIN_PATH,
    LOGOUT_PATH,
    login_json,
    provision_user_with_password,
)
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory


def test_real_cookie_authenticates_decision_api_end_to_end(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)

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

    # 67-68: login WITHOUT any override, receive a real Set-Cookie.
    login_response = api_client.post(LOGIN_PATH, json=login_json(user.email, DEFAULT_PASSWORD))
    assert login_response.status_code == 200, login_response.text
    assert "ninfa_session=" in login_response.headers.get("set-cookie", "")

    # 69-70: the REAL cookie authenticates the Decision API for the AUTHORIZED property.
    feed_response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decision-feed?as_of=2026-08-01"
    )
    assert feed_response.status_code == 200, feed_response.text
    assert feed_response.json()["feed_state"] == "ACTION_REQUIRED"

    detail_response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decisions/{decision_id}"
    )
    assert detail_response.status_code == 200, detail_response.text

    # 71: the SAME real cookie, an UNAUTHORIZED property -> still 404 (never 401/403).
    foreign_property_id = uuid4()
    unauthorized_response = api_client.get(
        f"/api/v1/properties/{foreign_property_id}/decision-feed?as_of=2026-08-01"
    )
    assert unauthorized_response.status_code == 404
    assert unauthorized_response.json()["error"]["code"] == "PROPERTY_NOT_FOUND"

    # 72: logout, still with no override.
    logout_response = api_client.post(LOGOUT_PATH)
    assert logout_response.status_code == 204

    # 73: the SAME cookie, after logout, is now 401.
    post_logout_response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decision-feed?as_of=2026-08-01"
    )
    assert post_logout_response.status_code == 401
    assert post_logout_response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
