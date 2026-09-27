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


__all__ = ["InvalidAskQuestionError"]
