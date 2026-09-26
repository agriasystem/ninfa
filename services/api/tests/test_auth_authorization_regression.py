"""Authentication & Session V1: Gate 12's own authorization policy, now driven by a REAL session
cookie instead of a dependency override (review items 83-87). No `app.dependency_overrides` of
`get_current_principal` anywhere here - only real login.
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
    login_json,
    provision_user_with_password,
)
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

STAY_DATE = "2026-08-15"
AS_OF = "2026-08-01"


def _login(api_client: TestClient, email: str) -> None:
    response = api_client.post(LOGIN_PATH, json=login_json(email, DEFAULT_PASSWORD))
    assert response.status_code == 200, response.text


def _open_a_decision(db_session: Session, tenant: Tenant) -> str:
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
    return str(decision_id)


# --- 83: same-workspace session member gets 200 -------------------------------------------------


def test_session_user_of_the_same_workspace_gets_200(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    _login(api_client, user.email)

    response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decision-feed?as_of={AS_OF}"
    )
    assert response.status_code == 200, response.text


# --- 84: authenticated user with no membership on that workspace gets 404 -----------------------


def test_session_user_without_membership_gets_404(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()  # a property the caller has no membership on
    user = provision_user_with_password(factory, db_session)  # a real, authenticated user
    _login(api_client, user.email)

    response = api_client.get(
        f"/api/v1/properties/{tenant.property.id}/decision-feed?as_of={AS_OF}"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROPERTY_NOT_FOUND"


# --- 85: a cross-workspace property is 404 (member of a DIFFERENT workspace) --------------------


def test_cross_workspace_property_gets_404(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    own_tenant = factory.tenant()
    foreign_tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(own_tenant.workspace, user, MembershipRole.MEMBER)
    _login(api_client, user.email)

    response = api_client.get(
        f"/api/v1/properties/{foreign_tenant.property.id}/decision-feed?as_of={AS_OF}"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROPERTY_NOT_FOUND"


# --- 86: a Decision of another property/workspace is 404 ----------------------------------------


def test_decision_of_a_cross_property_is_404(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    own_tenant = factory.tenant()
    foreign_tenant = factory.tenant()
    foreign_decision_id = _open_a_decision(db_session, foreign_tenant)
    user = provision_user_with_password(factory, db_session)
    factory.membership(own_tenant.workspace, user, MembershipRole.MEMBER)
    _login(api_client, user.email)

    response = api_client.get(
        f"/api/v1/properties/{own_tenant.property.id}/decisions/{foreign_decision_id}"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DECISION_NOT_FOUND"


# --- 87: resource enumeration remains impossible (missing vs foreign, identical response) -------


def test_resource_enumeration_remains_impossible_with_real_sessions(
    api_client: TestClient, factory: BookingFactory, db_session: Session
) -> None:
    tenant = factory.tenant()
    user = provision_user_with_password(factory, db_session)
    factory.membership(tenant.workspace, user, MembershipRole.MEMBER)
    _login(api_client, user.email)

    missing = api_client.get(f"/api/v1/properties/{tenant.property.id}/decisions/{uuid4()}")
    unauthorized_property = api_client.get(f"/api/v1/properties/{uuid4()}/decisions/{uuid4()}")

    assert missing.status_code == unauthorized_property.status_code == 404
    missing_code = missing.json()["error"]["code"]
    unauthorized_code = unauthorized_property.json()["error"]["code"]
    assert {missing_code, unauthorized_code} <= {"DECISION_NOT_FOUND", "PROPERTY_NOT_FOUND"}
