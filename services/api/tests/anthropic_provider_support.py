"""Shared helpers for the Gate 19 (Anthropic provider adapter) tests.

Builds REAL `anthropic.types` response objects (`Message`/`TextBlock`/`ThinkingBlock`/`Usage`),
never a loose `unittest.mock.Mock` standing in for the SDK's own shape - the same "real types,
never a guessed approximation" discipline `tests.decision_support` already applies to this
codebase's OWN domain types. `FakeMessagesTransport` is installed directly onto a real
`AnthropicLanguageModelProvider`'s `_client.messages.create` - no real network call, no real API
key, ever, in the automated suite (see ADR 0025, "why no live API in CI").
"""

import json
from dataclasses import dataclass, field
from typing import Any

from anthropic.types import ContentBlock, Message, TextBlock, Usage

from app.modules.ai.gateway.anthropic_provider import AnthropicLanguageModelProvider

FAKE_API_KEY = "sk-ant-test-not-a-real-key"


def make_message(
    payload: dict[str, Any],
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    extra_blocks: list[ContentBlock] | None = None,
    text_blocks: list[str] | None = None,
) -> Message:
    """A realistic `Message` whose final text block is `json.dumps(payload)` - or, if
    `text_blocks` is given, exactly those raw strings as separate text blocks instead (for the
    "zero or more than one text block" tests)."""
    content: list[ContentBlock] = list(extra_blocks or [])
    if text_blocks is not None:
        content.extend(TextBlock(type="text", text=text) for text in text_blocks)
    else:
        content.append(TextBlock(type="text", text=json.dumps(payload)))
    return Message(
        id="msg_test",
        content=content,
        model="claude-sonnet-5",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def answered_message(
    answer: str = "Risposta basata sui dati disponibili.",
    *,
    extra_blocks: list[ContentBlock] | None = None,
    **payload_overrides: Any,
) -> Message:
    payload = {
        "status": "ANSWERED",
        "answer": answer,
        "grounding_refs": ["LATEST_FACTS"],
        "limitations": [],
    }
    payload.update(payload_overrides)
    return make_message(payload, extra_blocks=extra_blocks)


@dataclass
class FakeMessagesTransport:
    """Records every call verbatim (`calls`), returns a canned `Message` or raises a canned
    exception - the ONLY thing standing in for `anthropic.Anthropic().messages.create` anywhere in
    this test suite."""

    response: Message | None = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None, "FakeMessagesTransport needs a response or an error"
        return self.response

    @property
    def last_call(self) -> dict[str, Any]:
        return self.calls[-1]


def provider_with_fake_transport(
    transport: FakeMessagesTransport,
) -> AnthropicLanguageModelProvider:
    """A REAL `AnthropicLanguageModelProvider`, with only its underlying HTTP call swapped out -
    every other line of the adapter (request building, response parsing, error mapping, logging)
    runs for real."""
    provider = AnthropicLanguageModelProvider(api_key=FAKE_API_KEY)
    provider._client.messages.create = transport.create  # type: ignore[method-assign,assignment]
    return provider


__all__ = [
    "FAKE_API_KEY",
    "FakeMessagesTransport",
    "answered_message",
    "make_message",
    "provider_with_fake_transport",
]
