"""Gate 19 review items 41-49: every provider failure fails closed to
`LanguageModelUnavailableError` - never the vendor's own stack trace, HTTP body, request id, or
API key.
"""

import logging

import anthropic
import httpx2
import pytest

from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelRequest
from tests.anthropic_provider_support import (
    FAKE_API_KEY,
    FakeMessagesTransport,
    provider_with_fake_transport,
)

_REQUEST = LanguageModelRequest(
    system_instructions="ISTRUZIONI", context="{}", question="Perché?", max_answer_chars=1200
)

_VENDOR_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(
    cls: type[anthropic.APIStatusError], status: int, secret_in_body: str
) -> anthropic.APIStatusError:
    response = httpx2.Response(
        status, request=_VENDOR_REQUEST, json={"error": {"message": f"failure {secret_in_body}"}}
    )
    return cls(f"failure {secret_in_body}", response=response, body={"secret": secret_in_body})


# --- 41-43: timeout, network, rate limit ----------------------------------------------------------


def test_41_timeout_becomes_unavailable() -> None:
    transport = FakeMessagesTransport(error=anthropic.APITimeoutError(request=_VENDOR_REQUEST))
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError):
        provider.generate(_REQUEST)


def test_42_network_connection_error_becomes_unavailable() -> None:
    transport = FakeMessagesTransport(
        error=anthropic.APIConnectionError(message="Connection error.", request=_VENDOR_REQUEST)
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError):
        provider.generate(_REQUEST)


def test_43_rate_limit_becomes_unavailable() -> None:
    transport = FakeMessagesTransport(
        error=_status_error(anthropic.RateLimitError, 429, "RATE_LIMIT_SECRET_DETAIL")
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError):
        provider.generate(_REQUEST)


# --- 44-46: vendor 4xx/5xx/auth errors, sanitized -------------------------------------------------


def test_44_vendor_4xx_is_sanitized() -> None:
    transport = FakeMessagesTransport(
        error=_status_error(anthropic.BadRequestError, 400, "BAD_REQUEST_SECRET_DETAIL")
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)
    assert "BAD_REQUEST_SECRET_DETAIL" not in str(excinfo.value)


def test_45_vendor_5xx_is_sanitized() -> None:
    transport = FakeMessagesTransport(
        error=_status_error(anthropic.InternalServerError, 500, "SERVER_ERROR_SECRET_DETAIL")
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)
    assert "SERVER_ERROR_SECRET_DETAIL" not in str(excinfo.value)


def test_46_auth_error_is_sanitized() -> None:
    transport = FakeMessagesTransport(
        error=_status_error(anthropic.AuthenticationError, 401, FAKE_API_KEY)
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)
    assert FAKE_API_KEY not in str(excinfo.value)


# --- 47-49: raw body, vendor request id, and API key never exposed - in the exception OR the log --


def test_47_raw_vendor_body_never_exposed_in_the_raised_exception() -> None:
    transport = FakeMessagesTransport(
        error=_status_error(anthropic.APIStatusError, 502, "RAW_BODY_SECRET_XYZ")
    )
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)
    assert "RAW_BODY_SECRET_XYZ" not in str(excinfo.value)


def test_48_vendor_request_id_never_exposed(caplog: pytest.LogCaptureFixture) -> None:
    response = httpx2.Response(
        500,
        request=_VENDOR_REQUEST,
        headers={"request-id": "req_vendor_internal_id_12345"},
        json={"error": {"message": "internal error"}},
    )
    error = anthropic.APIStatusError("internal error", response=response, body=None)
    transport = FakeMessagesTransport(error=error)
    provider = provider_with_fake_transport(transport)

    with caplog.at_level(logging.DEBUG), pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)

    assert "req_vendor_internal_id_12345" not in str(excinfo.value)
    assert "req_vendor_internal_id_12345" not in caplog.text


def test_49_api_key_never_exposed_in_exception_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    # Adversarial: even if the VENDOR's own exception message happened to embed the key (a
    # hypothetical vendor bug), this adapter's raised error is a static string, never derived from
    # `str(exc)` - see `AnthropicLanguageModelProvider.generate`'s own error handling.
    error = anthropic.AuthenticationError(
        f"invalid x-api-key {FAKE_API_KEY}",
        response=httpx2.Response(401, request=_VENDOR_REQUEST, json={"error": {}}),
        body=None,
    )
    transport = FakeMessagesTransport(error=error)
    provider = provider_with_fake_transport(transport)

    with caplog.at_level(logging.DEBUG), pytest.raises(LanguageModelUnavailableError) as excinfo:
        provider.generate(_REQUEST)

    assert FAKE_API_KEY not in str(excinfo.value)
    assert FAKE_API_KEY not in caplog.text
