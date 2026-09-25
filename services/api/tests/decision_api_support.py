"""Shared helpers for the Gate 12 (Decision API V1) HTTP tests.

Builds on Gate 11's own `tests.decision_support` (never duplicates its evaluation builders): what
this module adds is purely HTTP-side - authenticating a `TestClient` as a real member of a tenant,
and small response-shape helpers every endpoint test reuses.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.identity.models import User
from app.modules.tenancy.models import MembershipRole
from tests.support import BookingFactory, Tenant


@dataclass
class AuthedTenant:
    """A `Tenant` (Gate 1-11's own chain) plus a real `User` who is a member of its workspace -
    the minimum a Gate 12 test needs to call an endpoint as an authorized caller."""

    tenant: Tenant
    user: User


def authed_tenant(
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    *,
    role: MembershipRole = MembershipRole.MEMBER,
) -> AuthedTenant:
    """A fresh tenant, a fresh user with real membership on its workspace, and the test client's
    `get_current_principal` override already wired to that user - one line per test."""
    tenant = factory.tenant()
    user = factory.user()
    factory.membership(tenant.workspace, user, role)
    authenticated_as(user.id)
    return AuthedTenant(tenant, user)


def decision_table_counts(session: Session) -> dict[str, int]:
    """A snapshot of the three Decision Layer tables' row counts - the read-only tests' own proof
    that an HTTP GET wrote nothing (see `test_decision_api_readonly.py`)."""
    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (DecisionRun, Decision, DecisionObservation)
    }


def assert_error(response: object, *, status_code: int, code: str) -> None:
    """A small, repeated shape check: `{"error": {"code": ..., ...}}` at the expected HTTP
    status. `response` is typed loosely (`httpx.Response`) to avoid importing httpx here."""
    assert response.status_code == status_code, response.text  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["error"]["code"] == code, body


def feed_url(property_id: UUID, as_of: str) -> str:
    return f"/api/v1/properties/{property_id}/decision-feed?as_of={as_of}"


def list_url(property_id: UUID, **query: str) -> str:
    base = f"/api/v1/properties/{property_id}/decisions"
    if not query:
        return base
    return base + "?" + "&".join(f"{key}={value}" for key, value in query.items())


def detail_url(property_id: UUID, decision_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/decisions/{decision_id}"


def history_url(property_id: UUID, decision_id: UUID, **query: str) -> str:
    base = f"/api/v1/properties/{property_id}/decisions/{decision_id}/history"
    if not query:
        return base
    return base + "?" + "&".join(f"{key}={value}" for key, value in query.items())


__all__ = [
    "AuthedTenant",
    "authed_tenant",
    "assert_error",
    "decision_table_counts",
    "detail_url",
    "feed_url",
    "history_url",
    "list_url",
]
