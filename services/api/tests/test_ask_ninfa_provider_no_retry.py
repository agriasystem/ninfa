"""Gate 19 review items 96-98: a rate-limit or timeout produces exactly ONE SDK request attempt -
no application-level retry loop, and the SDK's own automatic retries are genuinely disabled
(`max_retries=0` at the client, not just documented intent).
"""

import ast
import inspect
import textwrap

import anthropic
import httpx2
import pytest

from app.modules.ai.gateway.anthropic_provider import _MAX_RETRIES, AnthropicLanguageModelProvider
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelRequest
from tests.anthropic_provider_support import FakeMessagesTransport, provider_with_fake_transport

_REQUEST = LanguageModelRequest(
    system_instructions="ISTRUZIONI", context="{}", question="Perché?", max_answer_chars=1200
)
_VENDOR_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# --- 96: rate limit -> exactly one attempt --------------------------------------------------------


def test_96_rate_limit_results_in_exactly_one_transport_call() -> None:
    response = httpx2.Response(
        429, request=_VENDOR_REQUEST, json={"error": {"message": "slow down"}}
    )
    error = anthropic.RateLimitError("slow down", response=response, body=None)
    transport = FakeMessagesTransport(error=error)
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError):
        provider.generate(_REQUEST)

    assert len(transport.calls) == 1


# --- 97: timeout -> exactly one attempt -----------------------------------------------------------


def test_97_timeout_results_in_exactly_one_transport_call() -> None:
    transport = FakeMessagesTransport(error=anthropic.APITimeoutError(request=_VENDOR_REQUEST))
    provider = provider_with_fake_transport(transport)

    with pytest.raises(LanguageModelUnavailableError):
        provider.generate(_REQUEST)

    assert len(transport.calls) == 1


# --- 98: no application-level retry loop, and the SDK's own retries are genuinely disabled -------


def test_98_no_application_retry_loop_in_the_adapter_source() -> None:
    """A real loop keyword (`for`/`while` as actual Python syntax, not prose in a comment) around
    the one `.messages.create(` call would be an application-level retry loop - checked via the
    AST, never a brittle text scan that a comment's own wording could trip."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(AnthropicLanguageModelProvider.generate)))
    loop_nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
    assert loop_nodes == []

    source = inspect.getsource(AnthropicLanguageModelProvider.generate)
    assert source.count(".messages.create(") == 1


def test_98_sdk_automatic_retries_are_genuinely_set_to_zero() -> None:
    provider = provider_with_fake_transport(FakeMessagesTransport())
    assert provider._client.max_retries == 0 == _MAX_RETRIES
