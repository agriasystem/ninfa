"""Shared helpers for the Gate 18 (Ask NINFA Core V1) tests.

`DeterministicFakeLanguageModelProvider` is the ONE test-only implementation of
`LanguageModelProvider` this codebase has - production ships none but
`UnconfiguredLanguageModelProvider` (see `app.modules.ai.gateway.unconfigured`). It captures the
exact `LanguageModelRequest` it was called with (prompt capture SOLO in test - production code has
no equivalent) so a test can assert system instructions/context/question stayed on three separate
fields, never concatenated.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import FastAPI

from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import (
    LanguageModelAnswer,
    LanguageModelProvider,
    LanguageModelRequest,
)


@dataclass
class DeterministicFakeLanguageModelProvider:
    """Configure exactly one of `answer`/`error` per test. `requests` accumulates every call this
    instance ever received, in order - a real vendor provider must never offer an equivalent, this
    exists ONLY so a test can inspect what `AskNinfaService` actually sent."""

    answer: LanguageModelAnswer | None = None
    error: Exception | None = None
    requests: list[LanguageModelRequest] = field(default_factory=list)

    def generate(self, request: LanguageModelRequest) -> LanguageModelAnswer:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.answer is None:
            raise LanguageModelUnavailableError(
                "DeterministicFakeLanguageModelProvider not configured"
            )
        return self.answer

    @property
    def last_request(self) -> LanguageModelRequest:
        return self.requests[-1]


def with_fake_provider(app: FastAPI) -> Callable[[LanguageModelProvider], None]:
    """`with_fake_provider(app)(provider)`: overrides `get_language_model_provider` for THIS
    test's `app` instance - the same `app.dependency_overrides` seam `authenticated_as`
    (`tests/conftest.py`) already uses for a different per-test dependency."""
    from app.api.v1.decisions.deps import get_language_model_provider

    def _set(provider: LanguageModelProvider) -> None:
        app.dependency_overrides[get_language_model_provider] = lambda: provider

    return _set


def ask_url(property_id: UUID, decision_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/decisions/{decision_id}/ask"


__all__ = ["DeterministicFakeLanguageModelProvider", "ask_url", "with_fake_provider"]
