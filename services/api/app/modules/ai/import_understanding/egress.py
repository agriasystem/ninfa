"""THE AI EGRESS CONTRACT - what may leave the server towards a language model, and the gate that
enforces it.

The model is shown a small document about the SHAPE of a file, never the file. What may be in it:

* the kinds of data and the canonical fields NINFA offers (static vocabulary);
* the file's structure: how many rows, the role of each sheet, and sheet names / a title reduced to
  words NINFA's own vocabulary knows;
* for every column: its index, a SAFE header label (short, free of anything shaped like personal
  data, not the name of a person), the kind of its values, how many there are and how many are
  distinct, the class of personal data it carries (NEVER a value of it), a few cleaned example words
  of a column that repeats only a few of them, the range of a column of small numbers, and the
  field the rules already gave it;
* the questions NINFA will ask, with their closed choices.

What may NOT be in it, ever: a name, a surname, a guest, an e-mail address, a telephone number, a
tax code, an IBAN, a cell of a personal-data column, a whole row, the file name, a long free text, a
note, a number long enough to be somebody's telephone number.

This module is the gate, and it does not trust the code that built the evidence: `prepare` cleans
EVERY free-text field again from scratch and keeps nothing it cannot account for, `fit_budget`
shrinks the document deterministically under a hard size limit (it never sends MORE), and `verify`
reads the final serialised text one last time - if anything recognisably personal is still there,
no call is made at all. A provider therefore receives text that has already been through all three;
it is never asked to protect anything.
"""

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace

from app.modules.ai.import_understanding.prompt import evidence_json
from app.modules.ai.import_understanding.sanitize import (
    MAX_TEXT,
    REMOVED,
    flatten,
    personal_shapes_in,
    truncate,
)
from app.modules.ai.import_understanding.types import (
    PII_CLASSES,
    ColumnEvidence,
    OfferedQuestion,
    UnderstandingEvidence,
)
from app.modules.document_understanding.pii import looks_like_person
from app.modules.document_understanding.pii_text import normalize

# The hard limit of what is sent for ONE file (characters of the serialised evidence). The real
# documents of the benchmark are 1.4k - 3.4k characters; this leaves room for a wide workbook and
# stops a pathological one. Above it the evidence is reduced; if it cannot be, nothing is sent.
MAX_PAYLOAD_CHARS = 6000
# What an answer may weigh before it is ignored unread.
MAX_RESPONSE_CHARS = 8000
# A rough price list for the report: one token ~ three characters of compact JSON, in or out.
CHARS_PER_TOKEN = 3.0
MAX_SAMPLE_CHARS = 40
MAX_SAMPLES = 6
MAX_CHOICE_CHARS = 120

_KINDS = frozenset({"TEXT", "NUMBER", "DATE", "MIXED", "EMPTY"})
# A number is shown only when it cannot be somebody's telephone number: at most seven digits.
_SMALL_NUMBER = re.compile(r"^-?\d{1,7}(?:\.\d{1,4})?$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
# The kinds of question whose choices are NINFA's own words. (Not TABLE: its choices are sheets.)
_QUESTION_KINDS = frozenset({"DOMAIN", "COLUMN_MEANING", "GRID_HOURS"})


def approx_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


class EgressViolationError(Exception):
    """Something recognisably personal is still in what was about to be sent. `codes` are stable
    words, never any of the content."""

    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__(",".join(codes))
        self.codes = codes


class EgressTooLargeError(Exception):
    """The evidence cannot be reduced under the hard limit: nothing is sent."""


def _keep(text: str) -> str:
    return text


@dataclass(frozen=True, slots=True)
class EgressGuard:
    """What the gate knows about THIS file.

    `scrub` replaces the personal values of the file (the names, numbers and addresses of the
    columns that were found to carry them) with a mark: anything it changes is a leak.
    `is_name` says that a short label is the name of a person ("Mario Rossi"), not a header."""

    scrub: Callable[[str], str] = _keep
    is_name: Callable[[str], bool] = looks_like_person


@dataclass(frozen=True, slots=True)
class EgressReport:
    """What went out, for the audit and the cost report. Never any of the content."""

    payload_chars: int = 0
    approx_tokens: int = 0
    columns_sent: int = 0
    columns_dropped: int = 0
    redactions: int = 0
    reduced: bool = False


# --- 1. every free-text field, cleaned again from scratch -----------------------------------------


@dataclass(slots=True)
class _Count:
    removed: int = 0


def _text(text: str, guard: EgressGuard, count: _Count, limit: int = MAX_TEXT) -> str:
    """One free text: read as a person reads it, personal shapes removed, the personal values of the
    file removed, and only THEN cut short (a name cut in half would escape the file's own list)."""
    flat = flatten(text)
    scrubbed = guard.scrub(flat)
    if scrubbed != flat:
        count.removed += 1
        return REMOVED
    if REMOVED in flat:
        count.removed += 1
    return truncate(flat, limit)


def _label(text: str, guard: EgressGuard, count: _Count) -> str:
    """A header: cleaned, and not the name of a person (a staff grid has a column per employee)."""
    cleaned = _text(text, guard, count)
    if cleaned != REMOVED and guard.is_name(" ".join(normalize(text).split())):
        count.removed += 1
        return REMOVED
    return cleaned


def _range(value: tuple[str, str] | None) -> tuple[str, str] | None:
    if value is not None and all(_SMALL_NUMBER.match(bound) for bound in value):
        return value
    return None


def _column(
    column: ColumnEvidence, known_fields: frozenset[str], guard: EgressGuard, count: _Count
) -> ColumnEvidence:
    pii = column.pii
    if pii is not None and pii not in PII_CLASSES:
        pii = "PII_PERSON_NAME"  # anything unaccounted for is treated as the worst it could be
    samples: tuple[str, ...] = ()
    if pii is None:
        samples = tuple(
            _text(sample, guard, count, MAX_SAMPLE_CHARS) for sample in column.samples[:MAX_SAMPLES]
        )
    return ColumnEvidence(
        index=int(column.index),
        header=_label(column.header, guard, count),
        kind=column.kind if column.kind in _KINDS else "MIXED",
        values=max(0, int(column.values)),
        distinct=max(0, int(column.distinct)),
        pii=pii,
        samples=samples,
        number_range=None if pii is not None else _range(column.number_range),
        assigned=column.assigned if column.assigned in known_fields else None,
    )


def _question(
    question: OfferedQuestion,
    opaque: str,
    sent_columns: frozenset[int],
    guard: EgressGuard,
    count: _Count,
) -> OfferedQuestion | None:
    """A question is offered only if it is of a kind whose choices are NINFA's own vocabulary (a
    kind of data, a field, planned or actual hours) and every choice is a plain identifier and is
    untouched by cleaning: a model must answer with exactly what NINFA holds, and a choice made of
    something typed in the file - the key of a table is its sheet names - never goes out. The id
    of a question about a column holds that column's header (free text): what goes out is an
    opaque id and the column's index."""
    if question.kind not in _QUESTION_KINDS:
        return None
    if not all(_IDENTIFIER.match(choice) for choice in question.choices):
        return None
    choices = tuple(_text(choice, guard, count, MAX_CHOICE_CHARS) for choice in question.choices)
    if choices != question.choices:
        return None
    column = question.column if question.column in sent_columns else None
    if question.kind == "COLUMN_MEANING" and column is None:
        return None  # a question about a column the model is not shown cannot be asked
    return OfferedQuestion(opaque, question.kind, question.choices, column)


def prepare(
    evidence: UnderstandingEvidence, guard: EgressGuard
) -> tuple[UnderstandingEvidence, int]:
    """The same document with every free-text field cleaned again, anything not accounted for
    dropped, and how many pieces had to be replaced."""
    count = _Count()
    known_fields = frozenset(name for names in evidence.fields.values() for name in names)
    title = None if evidence.title is None else _text(evidence.title, guard, count)
    sheets = tuple(
        (
            _text(name, guard, count),
            role if _IDENTIFIER.match(role) else "OTHER",
            max(0, int(rows)),
        )
        for name, role, rows in evidence.sheets
    )
    columns = tuple(_column(c, known_fields, guard, count) for c in evidence.columns)
    sent_columns = frozenset(c.index for c in columns)
    questions: list[OfferedQuestion] = []
    aliases: dict[str, str] = {}
    for item in evidence.questions:
        offered = _question(item, f"Q{len(questions) + 1}", sent_columns, guard, count)
        if offered is not None:
            questions.append(offered)
            aliases[offered.id] = item.id
    clean = UnderstandingEvidence(
        expected_domain=evidence.expected_domain,
        fields=evidence.fields,
        sheets=sheets,
        title=title or None,
        columns=columns,
        questions=tuple(questions),
        aliases=aliases,
    )
    return clean, count.removed


# --- 2. a hard size limit, reached by sending LESS ------------------------------------------------


def _placed_lose_detail(evidence: UnderstandingEvidence) -> UnderstandingEvidence:
    """A column the rules placed (or locked as personal) keeps its label and nothing else."""
    return replace(
        evidence,
        columns=tuple(
            replace(c, samples=(), number_range=None) if c.assigned is not None or c.pii else c
            for c in evidence.columns
        ),
    )


def _fewer_samples(evidence: UnderstandingEvidence, keep: int) -> UnderstandingEvidence:
    return replace(
        evidence, columns=tuple(replace(c, samples=c.samples[:keep]) for c in evidence.columns)
    )


def fit_budget(
    evidence: UnderstandingEvidence, limit: int = MAX_PAYLOAD_CHARS
) -> tuple[UnderstandingEvidence, bool]:
    """The evidence under the hard limit, and whether it had to be reduced. Always the same
    reduction for the same document: placed columns lose their detail, then the number ranges, then
    the examples shrink and go, then the sheets and the title, then columns leave from the right
    (the ones the rules already placed first). Raises `EgressTooLargeError` when even the minimum
    does not fit: in that case nothing is sent."""

    def fits(candidate: UnderstandingEvidence) -> bool:
        return len(evidence_json(candidate)) <= limit

    if fits(evidence):
        return evidence, False
    steps: list[Callable[[UnderstandingEvidence], UnderstandingEvidence]] = [
        _placed_lose_detail,
        lambda e: replace(e, columns=tuple(replace(c, number_range=None) for c in e.columns)),
        lambda e: _fewer_samples(e, 3),
        lambda e: _fewer_samples(e, 0),
        lambda e: replace(e, sheets=e.sheets[:3], title=None),
    ]
    current = evidence
    for step in steps:
        current = step(current)
        if fits(current):
            return current, True
    columns = list(current.columns)
    for placed in (True, False):
        while not fits(replace(current, columns=tuple(columns))):
            candidates = [
                i for i, c in enumerate(columns) if bool(c.assigned is not None or c.pii) == placed
            ]
            if not candidates:
                break
            columns.pop(candidates[-1])
    current = replace(current, columns=tuple(columns))
    if not columns or not fits(current):
        raise EgressTooLargeError
    return current, True


# --- 3. one last read of the final text -----------------------------------------------------------


def _leaves(node: object) -> Iterator[str]:
    """Every string of a decoded document - the keys and the values at any depth - one at a time."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, Mapping):
        for key, value in node.items():
            yield str(key)
            yield from _leaves(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _leaves(item)


def verify(document: str, guard: EgressGuard) -> None:
    """Reads the serialised evidence exactly as it would be sent, ONE STRING AT A TIME. Anything
    shaped like personal data, or any personal value of THIS file, in any single string makes the
    call impossible.

    The strings are never joined: two innocent neighbours in a list ("@cmd", "fdp.exe") are not an
    address, and reading the JSON as one text would make them one. Text that is not JSON is read
    whole (fail closed)."""
    try:
        decoded: object = json.loads(document)
    except ValueError:
        decoded = document
    codes: list[str] = []
    for leaf in _leaves(decoded):
        codes.extend(personal_shapes_in(leaf))
        if guard.scrub(leaf) != leaf:
            codes.append("FILE_VALUE")
    if codes:
        raise EgressViolationError(tuple(dict.fromkeys(codes)))


def report_of(
    document: str, *, columns_sent: int, columns_total: int, redactions: int
) -> EgressReport:
    return EgressReport(
        payload_chars=len(document),
        approx_tokens=approx_tokens(len(document)),
        columns_sent=columns_sent,
        columns_dropped=max(0, columns_total - columns_sent),
        redactions=redactions,
        reduced=columns_sent < columns_total,
    )


__all__ = [
    "CHARS_PER_TOKEN",
    "MAX_PAYLOAD_CHARS",
    "MAX_RESPONSE_CHARS",
    "EgressGuard",
    "EgressReport",
    "EgressTooLargeError",
    "EgressViolationError",
    "approx_tokens",
    "fit_budget",
    "prepare",
    "report_of",
    "verify",
]
