from app.core.exceptions import AppError


class InvalidAskQuestionError(AppError):
    """`question` is missing, blank, or outside the `[MIN_QUESTION_LENGTH, MAX_QUESTION_LENGTH]`
    bound (after trimming only leading/trailing whitespace) - a semantic 400, the same convention
    the Decision API's own `errors.py` already uses for an out-of-contract query value."""

    def __init__(self) -> None:
        super().__init__(
            "INVALID_ASK_QUESTION",
            "question must be between 1 and 1000 characters (after trimming whitespace)",
            status_code=400,
        )


class InvalidAskHistoryError(AppError):
    """The conversation history sent with a Mia Home question is malformed or out of bounds (too
    many exchanges, a message outside its length bound, roles that do not alternate user/assistant,
    or a user message that the deterministic guardrail would itself have refused). A semantic 400,
    exactly like `InvalidAskQuestionError`. `reason` is a short, static, safe label - never the
    offending text."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "INVALID_ASK_HISTORY",
            "history must be at most 4 complete user/assistant exchanges within the length bounds",
            status_code=400,
            details={"reason": reason},
        )


__all__ = ["InvalidAskHistoryError", "InvalidAskQuestionError"]
