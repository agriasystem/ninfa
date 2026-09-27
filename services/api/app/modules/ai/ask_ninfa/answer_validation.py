"""Never trust a provider's response as-is - a real vendor is an external system, and even the
in-process fake used for tests can be told to return something malformed on purpose. Every field of
`LanguageModelAnswer` is re-validated here; anything that fails returns `None`, and the caller
(`AskNinfaService`) treats `None` exactly like a provider exception: `AskStatus.UNAVAILABLE`, fail
closed, never a guess at what the provider "probably meant".
"""

from dataclasses import dataclass

from app.modules.ai.ask_ninfa.types import MAX_ANSWER_CHARS, AskStatus, GroundingRef
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus

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


def _truncated(answer: str) -> str:
    """Documented policy: TRUNCATE, never reject, an overlong-but-otherwise-real answer - a real,
    grounded answer that ran a little long is still more useful than discarding it outright (see
    ADR 0024, "why truncation, not rejection")."""
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer
    return answer[:MAX_ANSWER_CHARS].rstrip() + "…"


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

    return ValidatedAnswer(
        status=status,
        answer=_truncated(answer),
        grounding_refs=_valid_grounding_refs(raw.grounding_refs),
        limitations=_valid_limitations(raw.limitations),
    )


__all__ = ["ValidatedAnswer", "validate_model_answer"]
