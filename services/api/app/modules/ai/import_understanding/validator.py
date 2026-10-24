"""A model's answer is checked, never believed.

Two kinds of failure, treated differently:

* A STRUCTURAL one - the answer is not the closed shape, names a field or a domain nobody offered,
  uses a field twice, claims more than MEDIUM, points at a column that does not exist, places a
  personal-data column or one the rules already placed. The answer cannot be trusted at all: it is
  INVALID (the only reason a second call is ever made).
* A VALUES one - the answer is well formed but the VALUES of that column do not fit the field it
  names ("Data" over a column of names). That suggestion alone is dropped and counted.

What is left is capped at MEDIUM by construction: nothing here can produce a certainty.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.modules.ai.import_understanding.types import (
    NO_FIELD,
    UNKNOWN,
    AnswerGuess,
    ColumnGuess,
    Confidence,
    UnderstandingEvidence,
    UnderstandingGuess,
)

# A field is believed for a column when its values fit at least this well (0..1). Below it, the
# suggestion is dropped. (The deterministic layer needs 0.85 for HIGH; a model can never reach it.)
MIN_FIT = 0.6

# How well the values of column `index` fit `field` of a kind of data (`domain`), 0..1; None = the
# values say nothing about it.
FitOf = Callable[[str, int, str], float | None]

_KEYS = frozenset({"domain", "columns", "answers"})
_COLUMN_KEYS = frozenset({"index", "field", "confidence"})
_ANSWER_KEYS = frozenset({"question", "choice"})
_MAX_ITEMS = 200


class InvalidGuessError(Exception):
    """The answer broke a structural rule. `codes` are stable words, never any of its content."""

    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__(",".join(codes))
        self.codes = codes


@dataclass(frozen=True, slots=True)
class CheckedGuess:
    domain: str | None
    columns: Mapping[int, str]
    answers: Mapping[str, str]
    rejected: int


def parse_guess(payload: object, evidence: UnderstandingEvidence) -> UnderstandingGuess:
    """The raw answer as a typed guess, or `InvalidGuessError` naming the rules it broke."""
    codes: list[str] = []
    if not isinstance(payload, dict) or set(payload) != _KEYS:
        raise InvalidGuessError(("SHAPE",))
    domain = payload["domain"]
    if not isinstance(domain, str) or (domain != UNKNOWN and domain not in evidence.fields):
        codes.append("UNKNOWN_DOMAIN")
    raw_columns, raw_answers = payload["columns"], payload["answers"]
    if not isinstance(raw_columns, list) or not isinstance(raw_answers, list):
        raise InvalidGuessError(("SHAPE",))
    if len(raw_columns) > _MAX_ITEMS or len(raw_answers) > _MAX_ITEMS:
        raise InvalidGuessError(("TOO_MANY",))

    columns: list[ColumnGuess] = []
    seen_indexes: set[int] = set()
    seen_fields: set[str] = set()
    offered = set(evidence.fields.get(domain, ())) if isinstance(domain, str) else set()
    for item in raw_columns:
        parsed = _column(item, evidence, offered, seen_indexes, seen_fields, codes)
        if parsed is not None:
            columns.append(parsed)

    answers: list[AnswerGuess] = []
    questions = {q.id: q for q in evidence.questions}
    seen_questions: set[str] = set()
    for item in raw_answers:
        if not isinstance(item, dict) or set(item) != _ANSWER_KEYS:
            codes.append("SHAPE")
            continue
        question, choice = item["question"], item["choice"]
        if not isinstance(question, str) or not isinstance(choice, str):
            codes.append("SHAPE")
        elif question not in questions or question in seen_questions:
            codes.append("UNKNOWN_QUESTION")
        elif choice not in questions[question].choices:
            codes.append("UNKNOWN_CHOICE")
        else:
            seen_questions.add(question)
            answers.append(AnswerGuess(question, choice))

    if codes:
        raise InvalidGuessError(tuple(dict.fromkeys(codes)))
    return UnderstandingGuess(str(domain), tuple(columns), tuple(answers))


def _column(
    item: Any,
    evidence: UnderstandingEvidence,
    offered: set[str],
    seen_indexes: set[int],
    seen_fields: set[str],
    codes: list[str],
) -> ColumnGuess | None:
    if not isinstance(item, dict) or set(item) != _COLUMN_KEYS:
        codes.append("SHAPE")
        return None
    index, field, confidence = item["index"], item["field"], item["confidence"]
    if isinstance(index, bool) or not isinstance(index, int) or not isinstance(field, str):
        codes.append("SHAPE")
        return None
    try:
        level = Confidence(confidence)
    except ValueError:
        codes.append("OVERCONFIDENT" if confidence == "HIGH" else "SHAPE")
        return None
    column = evidence.column(index)
    if column is None:
        codes.append("UNKNOWN_COLUMN")
        return None
    if index in seen_indexes:
        codes.append("DUPLICATE_COLUMN")
        return None
    seen_indexes.add(index)
    if field == NO_FIELD:
        return ColumnGuess(index, NO_FIELD, level)
    if field not in offered:
        codes.append("UNKNOWN_FIELD")
        return None
    if column.pii is not None:
        codes.append("PERSONAL_DATA_COLUMN")
        return None
    if column.assigned is not None:
        codes.append("ALREADY_PLACED")
        return None
    if field in seen_fields:
        codes.append("DUPLICATE_FIELD")
        return None
    seen_fields.add(field)
    return ColumnGuess(index, field, level)


def check_guess(
    guess: UnderstandingGuess, evidence: UnderstandingEvidence, fit_of: FitOf
) -> CheckedGuess:
    """A well-formed guess against the VALUES of the columns it names. The result can only ever be a
    suggestion: a field per column the values support, the model's choice for a question."""
    taken = {c.assigned for c in evidence.columns if c.assigned is not None}
    columns: dict[int, str] = {}
    rejected = 0
    for item in guess.columns:
        if item.field == NO_FIELD:
            continue
        if item.field in taken:
            rejected += 1  # the rules placed that field elsewhere in the meantime
            continue
        fit = fit_of(guess.domain, item.index, item.field)
        if fit is not None and fit < MIN_FIT:
            rejected += 1
            continue
        columns[item.index] = item.field
    return CheckedGuess(
        None if guess.domain == UNKNOWN else guess.domain,
        columns,
        {a.question: a.choice for a in guess.answers},
        rejected,
    )


__all__ = ["MIN_FIT", "CheckedGuess", "FitOf", "InvalidGuessError", "check_guess", "parse_guess"]
