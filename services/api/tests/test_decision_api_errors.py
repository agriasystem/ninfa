"""Decision API V1: the stable error contract (Gate 12 review items 94-102)."""

from collections.abc import Callable
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.modules.decision_memory.service import DecisionMemoryService
from tests.decision_api_support import authed_tenant, detail_url, feed_url, list_url
from tests.support import BookingFactory

_ENVELOPE_KEYS = {"code", "message", "details", "request_id"}


def _assert_stable_envelope(response: Any, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body["error"].keys()) == _ENVELOPE_KEYS
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# --- 94: stable 401 -------------------------------------------------------------------------


def test_stable_401_envelope(api_client: TestClient, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    response = api_client.get(feed_url(tenant.property.id, "2026-08-01"))
    _assert_stable_envelope(response, 401, "AUTHENTICATION_REQUIRED")


# --- 95-96: stable 404 -----------------------------------------------------------------------


def test_stable_404_property_envelope(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    authed_tenant(factory, authenticated_as)
    response = api_client.get(feed_url(uuid4(), "2026-08-01"))
    _assert_stable_envelope(response, 404, "PROPERTY_NOT_FOUND")


def test_stable_404_decision_envelope(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(detail_url(at.tenant.property.id, uuid4()))
    _assert_stable_envelope(response, 404, "DECISION_NOT_FOUND")


# --- 97-98: stable 400 for invalid cursor / enum ---------------------------------------------


def test_stable_invalid_cursor_envelope(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, cursor="!!not-base64!!"))
    _assert_stable_envelope(response, 400, "INVALID_CURSOR")


def test_stable_invalid_enum_envelope(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    response = api_client.get(list_url(at.tenant.property.id, status="NOT_A_STATUS"))
    _assert_stable_envelope(response, 400, "INVALID_DECISION_STATUS")
    assert response.json()["error"]["details"] == {"value": "NOT_A_STATUS"}


# --- 99-102: no internals ever leak, even on a genuine 500 ------------------------------------


def test_unexpected_error_leaks_no_internals(
    api_client: TestClient, factory: BookingFactory, authenticated_as: Callable[[UUID], None]
) -> None:
    at = authed_tenant(factory, authenticated_as)
    with patch.object(
        DecisionMemoryService,
        "get_feed",
        side_effect=RuntimeError(
            "SELECT * FROM decisions WHERE secret_path='C:\\Users\\dev\\.env'"
        ),
    ):
        response = api_client.get(feed_url(at.tenant.property.id, "2026-08-01"))

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal server error"  # 99: no stack trace
    text = response.text
    assert "SELECT" not in text  # 100: no SQL text
    assert "Traceback" not in text
    assert "C:\\Users" not in text and "/home/" not in text  # 101: no filesystem path
    assert "RuntimeError" not in text  # 102: no raw exception representation
    assert "secret_path" not in text
