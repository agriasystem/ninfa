"""The provider-agnostic boundary `AskNinfaService` calls through - never a concrete vendor SDK.

`LanguageModelRequest` keeps `system_instructions` (static, versioned, trusted), `context` (the
already-whitelisted `AskDecisionContext`, serialized to canonical JSON - DATA, never instructions)
and `question` (untrusted user input) as three SEPARATE fields, never concatenated into one prompt
string here - a provider implementation decides how to hand them to its own API (e.g. a system
role, a tool/context block, a user role), but this boundary itself never blurs the three together
(see ADR 0024, "why user input is untrusted").

Synchronous by design, matching this codebase's own convention (every service in
`app/modules/*` is a plain, synchronous class - see `architecture-v1.md`, "Application services");
there is no `asyncio` anywhere else in this backend to make an async provider call meaningfully
concurrent with.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ModelAnswerStatus(StrEnum):
    """What the MODEL ITSELF decided about answerability, from inside the closed context it was
    given - never something the deterministic guardrail or the service infers. `ANSWERED`: a real,
    grounded answer exists. `INSUFFICIENT_CONTEXT`: the context does not support the question (e.g.
    an exact price/staffing change), so the model must say what it does not know rather than invent
    a number."""

    ANSWERED = "ANSWERED"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


@dataclass(frozen=True, slots=True)
class LanguageModelRequest:
    """`max_answer_chars` bounds the provider's OWN output budget; `AskNinfaService` still
    validates/truncates the response independently - a well-behaved provider respecting this field
    is a courtesy, never the actual enforcement boundary."""

    system_instructions: str
    context: str
    question: str
    max_answer_chars: int


@dataclass(frozen=True, slots=True)
class LanguageModelAnswer:
    """The provider's own structured output, exactly as it returned it - `AskNinfaService`'s
    `answer_validation.py` is what actually trusts (or rejects) this, never the provider adapter
    itself. `grounding_refs`/`limitations` are plain strings here (not yet the closed `GroundingRef`
    enum): validation, not this boundary, is what narrows them, so an unrecognised value fails safe
    downstream instead of crashing a provider adapter that cannot know about a frontend-only enum
    change."""

    status: ModelAnswerStatus
    answer: str
    grounding_refs: tuple[str, ...]
    limitations: tuple[str, ...]


class LanguageModelProvider(Protocol):
    """The ONE seam `AskNinfaService` depends on. A real implementation MUST enforce its own
    bounded timeout internally (see ADR 0024, "why timeout lives in the adapter, not the context
    builder") and MUST raise `LanguageModelUnavailableError`
    (`app.modules.ai.gateway.errors`) - never let a raw transport/SDK exception escape - on
    timeout, transport failure, or any other provider-side error. A production implementation must
    NEVER log the full `request` (see ADR 0024, "why no prompt logging")."""

    def generate(self, request: LanguageModelRequest) -> LanguageModelAnswer: ...


__all__ = [
    "LanguageModelAnswer",
    "LanguageModelProvider",
    "LanguageModelRequest",
    "ModelAnswerStatus",
]
