"""AskHomeService: one question, one grounded answer, over today's feed context of ONE property.

    AskHomeService(provider).ask(context, question) -> AskHomeResult

The twin of `AskNinfaService` (`service.py`) at feed scope, built from the SAME pieces on purpose -
the same `LanguageModelProvider` protocol (no vendor, no tools, no web, no streaming, no fallback
provider, exactly one call), the same deterministic guardrails, the same question bounds, the same
shape/length/technical-leak validation (`answer_validation.validate_model_answer_core`). What
differs is only the instructions, the context shape and the closed `grounding_refs` vocabulary
(`HomeGroundingRef`). Any provider failure or invalid output fails closed to `UNAVAILABLE`, never a
guess (see ADR 0028).
"""

from dataclasses import dataclass

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer_core
from app.modules.ai.ask_ninfa.guardrails import REFUSAL_COPY, classify_refusal
from app.modules.ai.ask_ninfa.home_instructions import ASK_MIA_HOME_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.home_serialization import serialize_home_context
from app.modules.ai.ask_ninfa.home_types import (
    MAX_HOME_ANSWER_CHARS,
    AskHomeContext,
    HomeGroundingRef,
)
from app.modules.ai.ask_ninfa.question import validate_question
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelProvider, LanguageModelRequest

_HOME_GROUNDING_VOCABULARY = tuple(ref.value for ref in HomeGroundingRef)


@dataclass(frozen=True, slots=True)
class AskHomeResult:
    """The API route maps this, field for field, onto the public `AskResponse` (the SAME response
    contract as the Decision Ask - `grounding_refs` simply carries `HomeGroundingRef` values)."""

    status: AskStatus
    answer: str | None
    grounding_refs: tuple[str, ...]
    limitations: tuple[str, ...]


_UNAVAILABLE = AskHomeResult(
    status=AskStatus.UNAVAILABLE, answer=None, grounding_refs=(), limitations=()
)


class AskHomeService:
    def __init__(self, provider: LanguageModelProvider) -> None:
        self._provider = provider

    def ask(self, context: AskHomeContext, question: str) -> AskHomeResult:
        cleaned_question = validate_question(question)

        refusal = classify_refusal(cleaned_question)
        if refusal is not None:
            return AskHomeResult(
                status=AskStatus.REFUSED,
                answer=None,
                grounding_refs=(),
                limitations=(REFUSAL_COPY[refusal],),
            )

        request = LanguageModelRequest(
            system_instructions=ASK_MIA_HOME_SYSTEM_INSTRUCTIONS,
            context=serialize_home_context(context),
            question=cleaned_question,
            max_answer_chars=MAX_HOME_ANSWER_CHARS,
            grounding_ref_values=_HOME_GROUNDING_VOCABULARY,
        )

        try:
            raw_answer = self._provider.generate(request)
        except LanguageModelUnavailableError:
            return _UNAVAILABLE
        except Exception:  # defense in depth: ANY unexpected provider failure fails closed too
            return _UNAVAILABLE

        validated = validate_model_answer_core(
            raw_answer, frozenset(_HOME_GROUNDING_VOCABULARY), MAX_HOME_ANSWER_CHARS
        )
        if validated is None:
            return _UNAVAILABLE

        return AskHomeResult(
            status=validated.status,
            answer=validated.answer,
            grounding_refs=validated.grounding_refs,
            limitations=validated.limitations,
        )


__all__ = ["AskHomeResult", "AskHomeService"]
