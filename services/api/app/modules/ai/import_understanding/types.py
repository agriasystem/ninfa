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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.ai.import_understanding.interpretation import InterpretationSummary

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


class AiMode(StrEnum):
    """What NINFA does with the model's reading (`SMART_IMPORT_AI_MODE`).

    OFF     no model is ever asked: Smart Import reads files exactly as it always did.
    SHADOW  the model is asked and its reading is MEASURED against the rules' - nothing of it is
            applied: the result, the questions, the mapping and the import are those of OFF.
    ASSIST  the model's reading is applied as suggestions (and, where the file's own values prove
            the name, as a confirmed column) AFTER every check of the port - never instead of them.
    """

    OFF = "off"
    SHADOW = "shadow"
    ASSIST = "assist"


class FailureKind(StrEnum):
    """Why a model did not contribute, as one stable word: the audit and the fallback are told this
    and never the vendor's message (which can hold anything, a key included)."""

    NOT_CONFIGURED = "NOT_CONFIGURED"  # a mode is on but there is no key / provider
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    QUOTA = "QUOTA"  # the account has run out of credit
    CONNECTION = "CONNECTION"
    SERVER = "SERVER"  # a 5xx of the vendor
    AUTH = "AUTH"  # a refused key or a forbidden project
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"  # the model does not exist (for this account)
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    REFUSAL = "REFUSAL"  # the model declined to answer
    INCOMPLETE = "INCOMPLETE"  # the answer was cut short
    SCHEMA = "SCHEMA"  # the answer is not the closed shape that was asked
    EMPTY = "EMPTY"  # no answer at all
    PROVIDER_ERROR = "PROVIDER_ERROR"  # anything else a vendor can do wrong


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """What ONE call to a model cost and what it was, as the vendor reports it. Counts and words,
    never a content: this is what the audit keeps."""

    model: str = ""
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None
    reasoning_effort: str | None = None
    # how many times the adapter sent the request again after a transient failure
    retries: int = 0


@dataclass(frozen=True, slots=True)
class ProviderAnswer:
    """A provider may return its answer bare (the parsed JSON, as a test double does) or in this
    envelope, when it can say what the call cost. The resolver reads both."""

    payload: object
    usage: ProviderUsage = field(default_factory=ProviderUsage)


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
    # For a question about a column: the index of that column. (The id of a question holds the
    # header of the column, which is free text from the file; what goes out is an opaque id and
    # this index - see `egress.prepare`.)
    column: int | None = None


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
    # opaque question id -> the real one. Never serialised: it stays on this side.
    aliases: Mapping[str, str] = field(default_factory=dict)

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
    # Which closed shape the answer takes: "legacy" (domain / columns / answers) or "semantic-v1"
    # (`interpretation.SemanticInterpretation`). A provider declares the one it speaks.
    contract: str = "legacy"


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
    # What the model said that is not a mapping (status, ambiguities, conflicts with what NINFA
    # already placed...): only with the `semantic-v1` contract.
    interpretation: "InterpretationSummary | None" = None
    # Why the model did not contribute, when it did not.
    failure: FailureKind | None = None
    # One entry per call, as the vendor reported it.
    usages: tuple[ProviderUsage, ...] = ()

    @property
    def used(self) -> bool:
        return self.reason == ResolutionReason.OK and bool(
            self.columns or self.answers or self.domain
        )


def empty(
    reason: ResolutionReason, calls: int = 0, failure: FailureKind | None = None
) -> AiResolution:
    return AiResolution(reason, calls, failure=failure)


@dataclass(frozen=True, slots=True)
class LevelCounts:
    """How many columns are at each level of certainty (a way to see what a model changed)."""

    high: int = 0
    medium: int = 0
    low: int = 0
    open: int = 0  # not placed at all


@dataclass(frozen=True, slots=True)
class AiTrace:
    """One audit record per use of a model - for the log, the shadow comparison and the cost
    report. Words, counts and ids only: never a header, a value, a request or an answer, and never
    the model's reasoning (which is not asked for and not kept)."""

    mode: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    outcome: str  # a `ResolutionReason`
    calls: int = 0
    retries: int = 0
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_ids: tuple[str, ...] = ()
    fallback_reason: str | None = None  # a `FailureKind`
    status: str | None = None  # of the interpretation
    before: LevelCounts = field(default_factory=LevelCounts)
    after: LevelCounts = field(default_factory=LevelCounts)
    questions_before: int = 0
    questions_after: int = 0
    suggested: int = 0  # columns / answers the model offered that survived every check
    promoted: int = 0  # columns the file's own values confirmed (no question left for them)
    agreements: int = 0
    conflicts: int = 0
    source_learning_conflicts: int = 0


__all__ = [
    "NO_FIELD",
    "PII_CLASSES",
    "UNKNOWN",
    "AiMode",
    "AiResolution",
    "AiTrace",
    "AnswerGuess",
    "ColumnEvidence",
    "ColumnGuess",
    "Confidence",
    "FailureKind",
    "ImportUnderstandingRequest",
    "LevelCounts",
    "OfferedQuestion",
    "ProviderAnswer",
    "ProviderUsage",
    "ResolutionReason",
    "UnderstandingEvidence",
    "UnderstandingGuess",
    "empty",
]
