"""The vocabulary of the optional AI step of Smart Import V3.

Smart Import works completely WITHOUT a language model: the deterministic understanding of the
document (structure, words, values) decides almost everything. A model may be asked about what is
left - a column whose meaning no rule found, a kind of data nothing points at - and what it says is
only ever a SUGGESTION: the closed shape below carries no business value at all (no text of its own,
no number, no date), only choices among what NINFA offered. A suggestion is capped at MEDIUM
confidence ("to be checked"), is checked against the values of the column, and a person still
confirms it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

# What the model is shown of a personal-data column: this class, nothing else.
PII_CLASSES = (
    "PII_PERSON_NAME",
    "PII_EMAIL",
    "PII_PHONE",
    "PII_TAX_CODE",
    "PII_IBAN",
    "PII_HOURLY_RATE",
)

UNKNOWN = "UNKNOWN"
NO_FIELD = "NONE"


class Confidence(StrEnum):
    """What a model may claim. There is no HIGH: only the deterministic rules plus the values (or
    the person) can make a column certain."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"


class ResolutionReason(StrEnum):
    OK = "OK"
    OFF = "OFF"  # no provider is configured (the default)
    NOT_NEEDED = "NOT_NEEDED"  # the deterministic reading left nothing to ask
    UNAVAILABLE = "UNAVAILABLE"  # the provider failed: the deterministic reading goes on alone
    INVALID = "INVALID"  # the answer broke the rules twice: it is ignored
    BLOCKED = "BLOCKED"  # the egress gate found personal data in what was about to be sent: no call
    TOO_LARGE = "TOO_LARGE"  # the evidence cannot be reduced under the hard limit: no call


@dataclass(frozen=True, slots=True)
class ColumnEvidence:
    """One column as the model sees it: its (cleaned) header and the SHAPE of its values."""

    index: int
    header: str
    kind: str  # TEXT | NUMBER | DATE | MIXED | EMPTY
    values: int
    distinct: int
    # The class of personal data the column carries, or None. When set, `samples` is always empty.
    pii: str | None = None
    # A few distinct values of a column with few of them (a channel, a department), cleaned; never
    # from a personal-data column, never from a free-text one.
    samples: tuple[str, ...] = ()
    number_range: tuple[str, str] | None = None
    # The field the deterministic rules already gave it (the model does not decide it again).
    assigned: str | None = None


@dataclass(frozen=True, slots=True)
class OfferedQuestion:
    """A question the person will be asked, with the choices; the model may name the likely one."""

    id: str
    kind: str
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnderstandingEvidence:
    """Everything the model is given. Built by NINFA from the deterministic reading; sheet names,
    titles and headers are free text from the file and are cleaned (length, control characters,
    anything shaped like an e-mail, a phone number, an IBAN or a tax code)."""

    expected_domain: str
    # The kinds of data and, for each, the fields a column may mean.
    fields: Mapping[str, tuple[str, ...]]
    sheets: tuple[tuple[str, str, int], ...] = ()
    title: str | None = None
    columns: tuple[ColumnEvidence, ...] = ()
    questions: tuple[OfferedQuestion, ...] = ()

    def column(self, index: int) -> ColumnEvidence | None:
        return next((c for c in self.columns if c.index == index), None)


@dataclass(frozen=True, slots=True)
class ColumnGuess:
    index: int
    field: str  # a field of the guessed domain, or NO_FIELD
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class AnswerGuess:
    question: str
    choice: str


@dataclass(frozen=True, slots=True)
class UnderstandingGuess:
    """The model's answer, once it has the right shape (and nothing yet checked against values)."""

    domain: str  # a kind of data, or UNKNOWN
    columns: tuple[ColumnGuess, ...] = ()
    answers: tuple[AnswerGuess, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportUnderstandingRequest:
    """What a provider is handed. The instructions are static and trusted; the evidence is DATA."""

    system_instructions: str
    evidence_json: str
    schema: Mapping[str, object]
    # 1 for the first call, 2 for the (only) repeat after an answer that broke the rules.
    attempt: int = 1
    # The rules the previous answer broke, as stable codes - never the previous answer itself.
    retry_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AiResolution:
    """What the model contributed, after every check. Empty when it contributed nothing."""

    reason: ResolutionReason
    calls: int = 0
    domain: str | None = None
    # column index -> field (always MEDIUM at most: a suggestion to confirm)
    columns: Mapping[int, str] = field(default_factory=dict)
    # question id -> the choice the model finds likely (the person still answers)
    answers: Mapping[str, str] = field(default_factory=dict)
    # Suggestions dropped because the values of the column do not fit the field.
    rejected: int = 0
    # What it cost and what went out (never any content): sizes of the one document sent and of
    # the answer, rough token counts, and whether the document had to be reduced to fit the limit.
    payload_chars: int = 0
    input_tokens: int = 0
    response_chars: int = 0
    output_tokens: int = 0
    reduced: bool = False
    redactions: int = 0

    @property
    def used(self) -> bool:
        return self.reason == ResolutionReason.OK and bool(
            self.columns or self.answers or self.domain
        )


def empty(reason: ResolutionReason, calls: int = 0) -> AiResolution:
    return AiResolution(reason, calls)


__all__ = [
    "NO_FIELD",
    "PII_CLASSES",
    "UNKNOWN",
    "AiResolution",
    "AnswerGuess",
    "ColumnEvidence",
    "ColumnGuess",
    "Confidence",
    "ImportUnderstandingRequest",
    "OfferedQuestion",
    "ResolutionReason",
    "UnderstandingEvidence",
    "UnderstandingGuess",
    "empty",
]
