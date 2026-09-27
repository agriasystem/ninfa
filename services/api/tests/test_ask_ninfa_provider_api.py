"""Gate 19 review items 89-95: the real `POST /ask` endpoint, with `ASK_NINFA_PROVIDER=anthropic`
genuinely selected and wired all the way through `create_app()` - only the adapter's own network
call is swapped out (`FakeMessagesTransport`), everything else (`Settings` -> `build_language_model_
provider` -> `app.state` -> `get_language_model_provider` -> the route) runs for real.
"""

from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.tenant import TenantContext
from app.modules.ai.gateway.anthropic_provider import AnthropicLanguageModelProvider
from app.modules.intelligence.priority.types import PriorityContext
from tests.anthropic_provider_support import FAKE_API_KEY, FakeMessagesTransport, answered_message
from tests.decision_api_support import assert_error, authed_tenant
from tests.decision_support import revenue_evaluation, sync_run
from tests.support import BookingFactory, Tenant

D1 = date(2026, 8, 1)
STAY = date(2026, 8, 15)


@pytest.fixture
def settings() -> Settings:
    """Overrides `conftest.py`'s own `settings` fixture for this file only: Anthropic is
    EXPLICITLY selected, with a syntactically-real-looking but entirely fake key - no real network
    call is ever made (see `_install_fake_transport` below)."""
    return get_settings().model_copy(
        update={
            "session_cookie_secure": False,
            "ask_ninfa_provider": "anthropic",
            "anthropic_api_key": SecretStr(FAKE_API_KEY),
        }
    )


def _install_fake_transport(app: FastAPI, transport: FakeMessagesTransport) -> None:
    provider = app.state.language_model_provider
    assert isinstance(provider, AnthropicLanguageModelProvider)
    provider._client.messages.create = transport.create  # type: ignore[method-assign,assignment]


def _seed_open_decision(db_session: Session, tenant: Tenant) -> UUID:
    evaluation = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=D1,
    )
    context = PriorityContext(tenant.workspace.id, tenant.property.id, D1)
    outcome = sync_run(db_session, TenantContext(tenant.workspace.id), context, [evaluation])
    [decision_id] = outcome.result.touched_decision_ids
    db_session.flush()
    return decision_id


def _ask_url(property_id: UUID, decision_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/decisions/{decision_id}/ask"


# --- 89: authenticated ask, real Anthropic adapter class, fake transport -------------------------


def test_89_authenticated_ask_with_the_real_anthropic_adapter_wired_in(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    _install_fake_transport(app, FakeMessagesTransport(response=answered_message()))

    response = api_client.post(
        _ask_url(at.tenant.property.id, decision_id), json={"question": "Perché me lo mostri?"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ANSWERED"


# --- 90: unauthenticated -> 401 ------------------------------------------------------------------


def test_90_unauthenticated_ask_is_401(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.post(_ask_url(tenant.property.id, uuid4()), json={"question": "Perché?"})
    assert_error(response, status_code=401, code="AUTHENTICATION_REQUIRED")


# --- 91: foreign property -> 404 ------------------------------------------------------------------


def test_91_foreign_property_is_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    foreign_tenant = factory.tenant()
    authed_tenant(factory, authenticated_as)

    response = api_client.post(
        _ask_url(foreign_tenant.property.id, uuid4()), json={"question": "Perché?"}
    )
    assert_error(response, status_code=404, code="PROPERTY_NOT_FOUND")


# --- 92: foreign/unknown decision -> 404 --------------------------------------------------------


def test_92_foreign_decision_is_404(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.post(
        _ask_url(at.tenant.property.id, uuid4()), json={"question": "Perché?"}
    )
    assert_error(response, status_code=404, code="DECISION_NOT_FOUND")


# --- 93: provider outage -> UNAVAILABLE, contract unchanged from Gate 18 -------------------------


def test_93_provider_outage_still_answers_the_gate18_unavailable_contract(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    _install_fake_transport(
        app, FakeMessagesTransport(error=RuntimeError("simulated vendor outage"))
    )

    response = api_client.post(
        _ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    )

    assert response.status_code == 200  # UNAVAILABLE is a normal, controlled 200 - unchanged
    body = response.json()
    assert body["status"] == "UNAVAILABLE"
    assert body["answer"] is None
    assert "simulated vendor outage" not in response.text


# --- 94: Cache-Control: no-store is preserved -----------------------------------------------------


def test_94_cache_control_no_store_is_preserved(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    _install_fake_transport(app, FakeMessagesTransport(response=answered_message()))

    response = api_client.post(
        _ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    )

    assert response.headers["cache-control"] == "no-store"


# --- 95: no vendor metadata in the public response ------------------------------------------------


def test_95_public_response_carries_no_vendor_metadata(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    decision_id = _seed_open_decision(db_session, at.tenant)
    _install_fake_transport(app, FakeMessagesTransport(response=answered_message()))

    response = api_client.post(
        _ask_url(at.tenant.property.id, decision_id), json={"question": "Perché?"}
    )

    assert set(response.json().keys()) == {"status", "answer", "grounding_refs", "limitations"}
    lowered = response.text.lower()
    for forbidden in ("anthropic", "claude", "sonnet", FAKE_API_KEY.lower()):
        assert forbidden not in lowered
