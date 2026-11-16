"""The structured interpretation a language model may return about a file (contract `semantic-v1`).

A model is asked to READ a file's semantics - what kind of data it is, what each column means, what
it cannot tell - never to decide anything. The shape below is therefore closed in every direction:

* every free choice is an ENUM: the kinds of data and the canonical fields are the ones NINFA really
  has (built from the registries it is handed, never invented), and the "evidence" of a reading is a
  CODE from a short list ("the header is an abbreviation"), not a sentence - so it can neither carry
  a personal value nor repeat a sentence that a cell tried to plant;
* "I do not know" is a first-class answer at every level (a status of its own, a field
  `NONE`, a list of columns it cannot place, a list of ambiguities it sees): a model is
  never made to choose;
* there is no place for a number, a date, a name or a free text - no value of the file
  can come back;
* a claim is `LOW` or `MEDIUM` and never more: a model's own certainty is not what makes a column
  certain in NINFA.

Nothing here validates a reading against the file. `to_payload` turns an interpretation into the
shape the validator of the port already checks (`validator.parse_guess` / `check_guess`), setting
aside - never silently applying - what the model says about a column NINFA has already placed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, create_model

from app.modules.ai.import_understanding.types import (
    NO_FIELD,
    UNKNOWN,
    Confidence,
    UnderstandingEvidence,
)

SCHEMA_VERSION = "semantic-v1"


class InterpretationStatus(StrEnum):
    """How far the model got. Anything but INTERPRETED / PARTIAL means: do not use what follows."""

    INTERPRETED = "INTERPRETED"  # the file reads clearly as one kind of data
    PARTIAL = "PARTIAL"  # some columns are clear, others are not
    AMBIGUOUS = "AMBIGUOUS"  # more than one reading is plausible and the evidence does not choose
    INCOMPATIBLE = "INCOMPATIBLE"  # it does not look like any kind of data NINFA reads
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # the evidence is too thin to say anything


class Reason(StrEnum):
    """WHY the model reads a column as it does: the only "evidence" a model may give."""

    HEADER_SYNONYM = "HEADER_SYNONYM"  # the header is another word for the field
    HEADER_ABBREVIATION = "HEADER_ABBREVIATION"  # the header is an abbreviation of it
    HEADER_TRANSLATION = "HEADER_TRANSLATION"  # the header is the field's word in another language
    VALUE_SHAPE = "VALUE_SHAPE"  # the kind / range of the values
    VALUE_WORDS = "VALUE_WORDS"  # the example words
    NEIGHBOUR_COLUMNS = "NEIGHBOUR_COLUMNS"  # the columns around it
    SHEET_CONTEXT = "SHEET_CONTEXT"  # the sheet name or the title


class HeaderAssessment(StrEnum):
    """Does the row taken as the header look like one? (It can only say so: choosing another row
    would take rows of the file, which never leave NINFA.)"""

    PLAUSIBLE = "PLAUSIBLE"
    LOOKS_LIKE_DATA = "LOOKS_LIKE_DATA"  # the "headers" read like values of a row
    MISSING_OR_GENERIC = "MISSING_OR_GENERIC"  # "Column 1", "Unnamed", blanks
    UNDETERMINED = "UNDETERMINED"


class AmbiguityKind(StrEnum):
    TWO_FIELDS_POSSIBLE = "TWO_FIELDS_POSSIBLE"  # the column could be either of two fields
    NO_FIELD_FITS = "NO_FIELD_FITS"  # it is meaningful but none of the offered fields is it
    VALUES_CONTRADICT_HEADER = "VALUES_CONTRADICT_HEADER"
    UNCLEAR_BASIS = "UNCLEAR_BASIS"  # net or gross, planned or actual: the column does not say


class Warning(StrEnum):  # noqa: A001 - the vocabulary of the contract, not the builtin
    NOTES_COLUMN = "NOTES_COLUMN"
    TOTALS_OR_SUBTOTALS = "TOTALS_OR_SUBTOTALS"
    LOOKS_LIKE_OTHER_KIND = "LOOKS_LIKE_OTHER_KIND"
    MIXED_LANGUAGES = "MIXED_LANGUAGES"
    NOT_HOSPITALITY = "NOT_HOSPITALITY"
    PERSONAL_DATA_PRESENT = "PERSONAL_DATA_PRESENT"
    # the model noticed text in the evidence that reads like an instruction to itself
    INSTRUCTION_LIKE_TEXT = "INSTRUCTION_LIKE_TEXT"


# the statuses by which the model itself says there is nothing here to use
_NO_READING = frozenset({"INCOMPATIBLE", "INSUFFICIENT_DATA"})


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AmbiguityReading(_Closed):
    columns: list[int]
    kind: AmbiguityKind


class AnswerReading(_Closed):
    question: str
    choice: str


class ColumnReading(_Closed):
    index: int
    field: str
    confidence: Confidence
    reason: Reason


class SemanticInterpretation(_Closed):
    """The base of the contract; `contract_model` narrows `domain` and `field` to what exists."""

    status: InterpretationStatus
    domain: str
    domain_confidence: Confidence
    overall_confidence: Confidence
    header: HeaderAssessment
    columns: list[ColumnReading]
    unknown_columns: list[int]
    ambiguities: list[AmbiguityReading]
    answers: list[AnswerReading]
    warnings: list[Warning]
    questions_required: bool


@lru_cache(maxsize=8)
def _model_for(domains: tuple[str, ...], fields: tuple[str, ...]) -> type[SemanticInterpretation]:
    column = create_model(
        "ColumnReading",
        __base__=ColumnReading,
        field=(Literal[fields], ...),
    )
    model = create_model(
        "SemanticInterpretation",
        __base__=SemanticInterpretation,
        domain=(Literal[domains], ...),
        columns=(list[column], ...),
    )
    return cast("type[SemanticInterpretation]", model)


def contract_model(vocabulary: Mapping[str, Sequence[str]]) -> type[SemanticInterpretation]:
    """The contract for THESE kinds of data and fields: a model cannot name one that is not here."""
    domains = (*sorted(vocabulary), UNKNOWN)
    fields = (*sorted({f for names in vocabulary.values() for f in names}), NO_FIELD)
    return _model_for(domains, fields)


# --- what is made of an interpretation -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InterpretationSummary:
    """What the model said that is not a mapping: kept for the audit, the shadow comparison and the
    decision whether anything it said may be used. Codes and column indexes only - never a value of
    the file, never the model's own words."""

    status: str
    overall: str
    domain_claim: str
    header: str
    questions_required: bool = False
    warnings: tuple[str, ...] = ()
    unknown: frozenset[int] = frozenset()
    ambiguous: frozenset[int] = frozenset()
    # a column NINFA already placed: the model agrees (its index) or says another field
    agreements: tuple[int, ...] = ()
    # (index, the field NINFA placed, the field the model said)
    conflicts: tuple[tuple[int, str, str], ...] = ()
    reasons: Mapping[int, str] | None = None

    @property
    def stands_down(self) -> bool:
        """The model itself says its reading is not to be used: nothing of it is applied."""
        return (
            self.status in _NO_READING
            or self.overall == Confidence.LOW.value
            or Warning.INSTRUCTION_LIKE_TEXT.value in self.warnings
        )

    @property
    def clear(self) -> bool:
        """A reading clear enough to let its columns be CORROBORATED (see `understanding_ai`): the
        model says the file reads as one kind of data, with nothing left for the person."""
        return (
            not self.stands_down
            and self.status == InterpretationStatus.INTERPRETED.value
            and self.overall == Confidence.MEDIUM.value
            and not self.questions_required
            and self.header
            in (HeaderAssessment.PLAUSIBLE.value, HeaderAssessment.UNDETERMINED.value)
            and not self.ambiguous
        )


def to_payload(
    interpretation: SemanticInterpretation, evidence: UnderstandingEvidence
) -> tuple[dict[str, object], InterpretationSummary]:
    """The interpretation in the shape the port's validator already checks, and what is left over.

    A reading of a column that NINFA has ALREADY placed (by its rules, by what a person confirmed
    earlier, by an answer just given) is not a mapping to apply: it is an agreement, or a CONFLICT,
    and either is only counted. It never changes the column and is never a structural fault of the
    answer (a model that voices a view on a placed column has not broken a rule). Anything else is
    left to the validator exactly as before: an unknown field or column, a personal-data column
    given a field, a field used twice - those make the whole answer invalid."""
    columns: list[dict[str, object]] = []
    agreements: list[int] = []
    conflicts: list[tuple[int, str, str]] = []
    reasons: dict[int, str] = {}
    for reading in interpretation.columns:
        placed = evidence.column(reading.index)
        reasons.setdefault(reading.index, reading.reason.value)
        if placed is not None and placed.pii is None and placed.assigned is not None:
            if reading.field == NO_FIELD:
                continue
            if reading.field == placed.assigned:
                agreements.append(reading.index)
            else:
                conflicts.append((reading.index, placed.assigned, reading.field))
            continue
        columns.append(
            {"index": reading.index, "field": reading.field, "confidence": reading.confidence.value}
        )
    columns.extend(
        {"index": index, "field": NO_FIELD, "confidence": Confidence.LOW.value}
        for index in interpretation.unknown_columns
    )
    payload: dict[str, object] = {
        "domain": interpretation.domain,
        "columns": columns,
        "answers": [{"question": a.question, "choice": a.choice} for a in interpretation.answers],
    }
    summary = InterpretationSummary(
        status=interpretation.status.value,
        overall=interpretation.overall_confidence.value,
        domain_claim=interpretation.domain,
        header=interpretation.header.value,
        questions_required=interpretation.questions_required,
        warnings=tuple(dict.fromkeys(w.value for w in interpretation.warnings)),
        unknown=frozenset(interpretation.unknown_columns),
        ambiguous=frozenset(i for a in interpretation.ambiguities for i in a.columns),
        agreements=tuple(agreements),
        conflicts=tuple(conflicts),
        reasons=reasons,
    )
    return payload, summary


def interpretation_from(
    payload: object, vocabulary: Mapping[str, Sequence[str]]
) -> SemanticInterpretation | None:
    """A payload (an instance already, or a plain mapping such as a test double sends) as a typed
    interpretation, or `None` when it is not one. A mapping is validated against the same closed
    contract a real answer is parsed with."""
    model = contract_model(vocabulary)
    if isinstance(payload, SemanticInterpretation):
        return payload
    if isinstance(payload, dict):
        try:
            return model.model_validate(payload)
        except ValueError:
            return None
    return None


__all__ = [
    "SCHEMA_VERSION",
    "AmbiguityKind",
    "AmbiguityReading",
    "AnswerReading",
    "ColumnReading",
    "HeaderAssessment",
    "InterpretationStatus",
    "InterpretationSummary",
    "Reason",
    "SemanticInterpretation",
    "Warning",
    "contract_model",
    "interpretation_from",
    "to_payload",
]
