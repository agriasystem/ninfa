"""Decision API V1: the authorization test matrix (Gate 12 review items 1-12)."""

from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.tenancy.models import MembershipRole
from tests.decision_api_support import (
    assert_error,
    authed_tenant,
    detail_url,
    feed_url,
    history_url,
    list_url,
)
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory

AS_OF = "2026-08-01"
STAY_DATE = date(2026, 8, 15)


def _open_a_decision(db_session: Session, factory: BookingFactory) -> tuple[UUID, UUID]:
    """A real, persisted, OPEN Decision on a FRESH tenant. Returns (property_id, decision_id)."""
    tenant = factory.tenant()
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY_DATE,
        snapshot_local_date=date(2026, 8, 1),
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, date(2026, 8, 1))
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    return tenant.property.id, decision_id


# --- 1-4: unauthenticated ------------------------------------------------------------------


def test_unauthenticated_feed_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.get(feed_url(tenant.property.id, AS_OF))
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


def test_unauthenticated_list_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.get(list_url(tenant.property.id))
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


def test_unauthenticated_detail_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.get(detail_url(tenant.property.id, uuid4()))
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


def test_unauthenticated_history_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.get(history_url(tenant.property.id, uuid4()))
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


# --- 5: authorized member -------------------------------------------------------------------


def test_member_of_the_same_workspace_property_gets_200(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(at.tenant.property.id, AS_OF))
    assert response.status_code == 200, response.text
    assert response.json()["feed_state"] == "NOT_PROCESSED"  # no run yet - still 200, not an error


# --- 6-8: unauthorized property access is 404, never 403 ------------------------------------


def test_non_member_of_the_property_workspace_gets_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    tenant = factory.tenant()  # a property the caller has no membership on
    other_user = factory.user()
    authenticated_as(other_user.id)  # authenticated, but no WorkspaceMembership row anywhere
    response = api_client.get(feed_url(tenant.property.id, AS_OF))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_member_of_a_different_workspace_gets_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    foreign_tenant = factory.tenant()
    authed_tenant(factory, authenticated_as)  # a member, but of ITS OWN workspace only
    response = api_client.get(feed_url(foreign_tenant.property.id, AS_OF))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


def test_random_nonexistent_property_id_gets_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(uuid4(), AS_OF))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


# --- 9-10: a decision from another property/workspace is 404 --------------------------------


def test_decision_of_another_property_is_404(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    _foreign_property_id, foreign_decision_id = _open_a_decision(db_session, factory)
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(detail_url(at.tenant.property.id, foreign_decision_id))
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


def test_decision_of_another_workspace_is_404_even_with_membership_there(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    foreign_property_id, foreign_decision_id = _open_a_decision(db_session, factory)
    other_user = factory.user()
    # A membership on the FOREIGN workspace exists, but the caller is authenticated as someone
    # ELSE (no membership at all) - the path's own property must still resolve through THAT
    # caller's membership, not anyone's.
    factory.membership(factory.tenant().workspace, other_user, MembershipRole.MEMBER)
    authed_tenant(factory, authenticated_as)
    response = api_client.get(history_url(foreign_property_id, foreign_decision_id))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


# --- 11: resource enumeration is impossible via status distinction --------------------------


def test_missing_and_foreign_decision_ids_answer_identically(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    _foreign_property_id, foreign_decision_id = _open_a_decision(db_session, factory)

    missing = api_client.get(detail_url(at.tenant.property.id, uuid4()))
    foreign = api_client.get(detail_url(at.tenant.property.id, foreign_decision_id))

    assert missing.status_code == foreign.status_code == 404
    missing_code = missing.json()["error"]["code"]
    foreign_code = foreign.json()["error"]["code"]
    assert missing_code == foreign_code == "DECISION_NOT_FOUND"


# --- 12: an authenticated principal with no membership anywhere is coherent (404) -----------


def test_authenticated_unknown_user_id_is_404_not_a_crash(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    tenant = factory.tenant()
    authenticated_as(uuid4())  # a syntactically valid, but entirely unknown, user id
    response = api_client.get(feed_url(tenant.property.id, AS_OF))
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")
