"""AskNinfaService: one question, one grounded answer, over a single Decision's own context.

    AskNinfaService(provider).ask(context, question) -> AskResult

Depends on `LanguageModelProvider` (a `Protocol`, `app.modules.ai.gateway.protocol`) - never a
concrete SDK, never even knows one exists. Orchestration, in order:

1. Validate the question (length/whitespace) - the caller (API route) does this before building a
   context at all, so this step is effectively already done by the time `ask()` runs; kept here too
   as the service's own invariant, never assumed from the caller alone.
2. A deterministic guardrail check (`guardrails.classify_refusal`) - REFUSED, if matched, NEVER
   reaches the provider. No second LLM call classifies anything (see ADR 0024, "why a second model
   call was rejected for classification").
3. Build the provider request: static system instructions + the ALREADY-WHITELISTED context,
   serialized to canonical JSON (DATA) + the question (untrusted), as three separate fields.
4. Call the provider exactly once. Any exception at all (the documented
   `LanguageModelUnavailableError`, or anything else - defense in depth against a misbehaving
   provider) is caught and turned into `AskStatus.UNAVAILABLE`, never leaked.
5. Validate the raw response (`answer_validation.validate_model_answer`) - invalid output also
   fails closed to `UNAVAILABLE`.
"""

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer
from app.modules.ai.ask_ninfa.guardrails import REFUSAL_COPY, classify_refusal
from app.modules.ai.ask_ninfa.instructions import ASK_NINFA_SYSTEM_INSTRUCTIONS
from app.modules.ai.ask_ninfa.question import validate_question
from app.modules.ai.ask_ninfa.serialization import serialize_context
from app.modules.ai.ask_ninfa.types import (
    MAX_ANSWER_CHARS,
    AskDecisionContext,
    AskResult,
    AskStatus,
)
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelProvider, LanguageModelRequest

_UNAVAILABLE = AskResult(
    status=AskStatus.UNAVAILABLE, answer=None, grounding_refs=(), limitations=()
)


class AskNinfaService:
    def __init__(self, provider: LanguageModelProvider) -> None:
        self._provider = provider

    def ask(self, context: AskDecisionContext, question: str) -> AskResult:
        cleaned_question = validate_question(question)

        refusal = classify_refusal(cleaned_question)
        if refusal is not None:
            return AskResult(
                status=AskStatus.REFUSED,
                answer=None,
                grounding_refs=(),
                limitations=(REFUSAL_COPY[refusal],),
            )

        request = LanguageModelRequest(
            system_instructions=ASK_NINFA_SYSTEM_INSTRUCTIONS,
            context=serialize_context(context),
            question=cleaned_question,
            max_answer_chars=MAX_ANSWER_CHARS,
        )

        try:
            raw_answer = self._provider.generate(request)
        except LanguageModelUnavailableError:
            return _UNAVAILABLE
        except Exception:  # defense in depth: ANY unexpected provider failure fails closed too
            return _UNAVAILABLE

        validated = validate_model_answer(raw_answer)
        if validated is None:
            return _UNAVAILABLE

        return AskResult(
            status=validated.status,
            answer=validated.answer,
            grounding_refs=validated.grounding_refs,
            limitations=validated.limitations,
        )


__all__ = ["AskNinfaService"]
