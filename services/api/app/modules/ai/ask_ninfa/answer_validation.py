"""Never trust a provider's response as-is - a real vendor is an external system, and even the
in-process fake used for tests can be told to return something malformed on purpose. Every field of
`LanguageModelAnswer` is re-validated here; anything that fails returns `None`, and the caller
(`AskNinfaService`) treats `None` exactly like a provider exception: `AskStatus.UNAVAILABLE`, fail
closed, never a guess at what the provider "probably meant".

Gate 19.1 (ADR 0026, "why leakage fails closed") added a SECOND, independent check on top of the
original shape/schema validation below: `technical_leak.contains_technical_leak`, run on the
answer AND every limitation before either ever leaves this module. A leak fails the WHOLE answer
closed to `None` (`AskStatus.UNAVAILABLE`) exactly like any other validation failure here - never a
partial/edited answer, never a retry.

Gate 19.1b (ADR 0026's own update, "why an overlong answer now fails closed") REVERSES ADR 0024's
original "truncate, never reject" policy: a live answer was cut mid-number ("...impatto sui ricavi
di 6" - the real figure was 600) by the old `_truncated()`, which sliced by raw character count
with no word/number-boundary awareness. On a product whose entire premise is "never show a wrong
number", a silently truncated one is worse than an honest `UNAVAILABLE`. `MAX_ANSWER_CHARS` (700)
remains a hard VALIDATION ceiling - it is never a style target; the ~300-500 character style target
lives in `instructions.py`'s own prompt-level guidance instead (rule 24).
"""

import logging
from dataclasses import dataclass

from app.modules.ai.ask_ninfa.technical_leak import contains_technical_leak
from app.modules.ai.ask_ninfa.types import MAX_ANSWER_CHARS, AskStatus, GroundingRef
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus

logger = logging.getLogger(__name__)

_MAX_LIMITATIONS = 5
_MAX_LIMITATION_CHARS = 300

_STATUS_MAP: dict[ModelAnswerStatus, AskStatus] = {
    ModelAnswerStatus.ANSWERED: AskStatus.ANSWERED,
    ModelAnswerStatus.INSUFFICIENT_CONTEXT: AskStatus.INSUFFICIENT_CONTEXT,
}

_VALID_GROUNDING_REFS = frozenset(ref.value for ref in GroundingRef)


@dataclass(frozen=True, slots=True)
class ValidatedAnswer:
    status: AskStatus
    answer: str
    grounding_refs: tuple[GroundingRef, ...]
    limitations: tuple[str, ...]


def _valid_grounding_refs(raw_refs: tuple[str, ...]) -> tuple[GroundingRef, ...]:
    """Drops (never crashes on) any ref outside the closed `GroundingRef` vocabulary, and any
    duplicate - a provider naming an unrecognised semantic area is a sign the answer was not fully
    grounded in a way this contract understands, not a reason to fail the whole answer."""
    seen: dict[str, None] = {}
    for ref in raw_refs:
        if ref in _VALID_GROUNDING_REFS:
            seen.setdefault(ref, None)
    return tuple(GroundingRef(ref) for ref in seen)


def _valid_limitations(raw_limitations: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = [limitation.strip()[:_MAX_LIMITATION_CHARS] for limitation in raw_limitations]
    return tuple(limitation for limitation in cleaned if limitation)[:_MAX_LIMITATIONS]


def validate_model_answer(raw: LanguageModelAnswer) -> ValidatedAnswer | None:
    status = _STATUS_MAP.get(raw.status)
    if status is None:
        return None  # defensive: unreachable while ModelAnswerStatus stays a 2-value StrEnum

    answer = raw.answer.strip()
    if not answer:
        return None

    if len(answer) > MAX_ANSWER_CHARS:
        # Gate 19.1b: fail closed, never truncate - a character-count slice can (and did, live)
        # land mid-number/mid-word, which reads as a wrong or incomplete fact, worse than an
        # honest UNAVAILABLE (see this module's own docstring, "why an overlong answer now fails
        # closed").
        logger.warning("ask_ninfa answer_exceeded_max_chars=true")
        return None

    limitations = _valid_limitations(raw.limitations)
    if contains_technical_leak(answer) or any(
        contains_technical_leak(note) for note in limitations
    ):
        # Fail closed, never a rewrite/retry (ADR 0026) - and never log the leaked text itself,
        # only the fact that this happened, the same "safe metadata only" discipline the Anthropic
        # adapter's own logging already follows (Gate 19).
        logger.warning("ask_ninfa technical_leak_detected=true")
        return None

    return ValidatedAnswer(
        status=status,
        answer=answer,
        grounding_refs=_valid_grounding_refs(raw.grounding_refs),
        limitations=limitations,
    )


__all__ = ["ValidatedAnswer", "validate_model_answer"]
