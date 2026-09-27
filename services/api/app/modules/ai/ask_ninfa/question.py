from app.modules.ai.ask_ninfa.errors import InvalidAskQuestionError
from app.modules.ai.ask_ninfa.types import MAX_QUESTION_LENGTH, MIN_QUESTION_LENGTH


def validate_question(raw: str) -> str:
    """Trims ONLY leading/trailing whitespace (internal whitespace is part of the real question,
    never collapsed) and enforces the `[1, 1000]` character bound. Never accepts an oversized
    payload - this runs BEFORE any provider call or context assembly."""
    question = raw.strip()
    if not (MIN_QUESTION_LENGTH <= len(question) <= MAX_QUESTION_LENGTH):
        raise InvalidAskQuestionError()
    return question


__all__ = ["validate_question"]
