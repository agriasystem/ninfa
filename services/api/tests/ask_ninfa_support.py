"""Shared helpers for the Gate 18 (Ask NINFA Core V1) tests.

`DeterministicFakeLanguageModelProvider` is the ONE test-only implementation of
`LanguageModelProvider` this codebase has - production ships none but
`UnconfiguredLanguageModelProvider` (see `app.modules.ai.gateway.unconfigured`). It captures the
exact `LanguageModelRequest` it was called with (prompt capture SOLO in test - production code has
no equivalent) so a test can assert system instructions/context/question stayed on three separate
fields, never concatenated.

`sample_ask_context`/`sample_ask_observation` (Gate 19.1) are the ONE shared builder of the
already-semantic `AskDecisionContext` shape (`app.modules.ai.ask_ninfa.semantic_labels`'s own
output shape) - every test that used to hand-build one with raw `decision_type`/`action_code`/
`reason_codes` now goes through here instead, so a future context-shape change touches one place,
never a dozen near-identical literals.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import FastAPI

from app.modules.ai.ask_ninfa.types import (
    AskActionContext,
    AskDataPoint,
    AskDecisionContext,
    AskObservationContext,
    AskRecommendationContext,
)
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import (
    LanguageModelAnswer,
    LanguageModelProvider,
    LanguageModelRequest,
)


def sample_ask_observation(**overrides: object) -> AskObservationContext:
    """A real REV_PICKUP_LOW observation's own already-semantic shape - never a raw
    `source_status`/`reason_codes`/`priority_rank` (Gate 19.1 dropped all three from this type)."""
    base = AskObservationContext(
        as_of_local_date="2026-08-01",
        status_label="Rilevata",
        confidence="81.23",
        facts=(
            AskDataPoint(label="Pickup rilevato", value="3", unit="camere"),
            AskDataPoint(label="Pickup atteso", value="7.50", unit="camere"),
        ),
        evidence=(),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def sample_ask_context(**overrides: object) -> AskDecisionContext:
    """A real REV_PICKUP_LOW decision's own already-semantic shape - see `sample_ask_observation`.
    `overrides` may replace any top-level field, e.g. `sample_ask_context(latest=sample_ask_
    observation(status_label="Ancora presente"))`."""
    base = AskDecisionContext(
        decision_label="Pickup sotto le attese",
        decision_status="Aperta",
        first_seen_local_date="2026-08-01",
        last_seen_local_date="2026-08-01",
        last_evaluated_local_date="2026-08-01",
        resolved_local_date=None,
        episode_count=1,
        target={"stay_date": "2026-08-15"},
        latest=sample_ask_observation(),
        recommendation=AskRecommendationContext(
            primary_action=AskActionContext(
                title="Rivedi prezzi e disponibilità",
                description=(
                    "Verifica se prezzi, disponibilità e restrizioni sono coerenti con "
                    "l'andamento della data."
                ),
                risk_notes=("Le variazioni di prezzo possono incidere sui ricavi.",),
            ),
            supporting_checks=(),
        ),
        history=(),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


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


__all__ = [
    "DeterministicFakeLanguageModelProvider",
    "ask_url",
    "sample_ask_context",
    "sample_ask_observation",
    "with_fake_provider",
]
