"""Where the deterministic understanding and the optional AI step meet.

`build_evidence` turns what the rules found into the small, cleaned document a model is shown (no
file name, no personal data - a personal-data column is only its class - no free text beyond a few
cleaned words); `apply_resolution` puts what survived the checks back as SUGGESTIONS: a field at
MEDIUM confidence ("to be checked"), a likely answer on a question the person will still answer.
Nothing here can make a column certain, and with no provider the whole step is skipped.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.modules.ai.import_understanding.sanitize import clean_text
from app.modules.ai.import_understanding.types import (
    AiResolution,
    ColumnEvidence,
    OfferedQuestion,
    UnderstandingEvidence,
)
from app.modules.ai.import_understanding.validator import FitOf
from app.modules.data_sources.proposal import CONTESTED, ColumnProposal, Proposal
from app.modules.data_sources.semantics import DomainSem, Level, NameMatch
from app.modules.data_sources.understanding_types import OriginKind, Question, QuestionKind
from app.modules.document_understanding.lexicon import HEADER_STEMS, SECTION_WORDS
from app.modules.document_understanding.stats import ColumnStats
from app.modules.document_understanding.text import fold, stem
from app.modules.document_understanding.values import CellKind
from app.modules.ingestion.models import DataSourceDomain

MAX_COLUMNS = 60
MAX_SAMPLES = 6
MAX_SAMPLE_CHARS = 40
# A column is shown by example only when it repeats a few words (a channel, a department).
MAX_DISTINCT_FOR_SAMPLES = 12
MAX_AVG_LENGTH_FOR_SAMPLES = 30
_ASKABLE = frozenset(
    {QuestionKind.DOMAIN, QuestionKind.TABLE, QuestionKind.GRID_HOURS, QuestionKind.COLUMN_MEANING}
)


def _kind_of(stats: ColumnStats) -> str:
    if stats.n == 0:
        return "EMPTY"
    for kind, name in (
        (CellKind.TEXT, "TEXT"),
        (CellKind.NUMBER, "NUMBER"),
        (CellKind.DATE, "DATE"),
    ):
        if stats.fraction(kind) >= 0.8:
            return name
    return "MIXED"


def _pii_class(column: ColumnProposal) -> str | None:
    if column.pii is not None:
        return f"PII_{column.pii.value}"
    if column.locked == "HOURLY_RATE":
        return "PII_HOURLY_RATE"
    if column.locked is not None:
        return "PII_PERSON_NAME"
    return None


def _evidence_of_column(column: ColumnProposal) -> ColumnEvidence:
    stats = column.stats
    kind = _kind_of(stats)
    pii = _pii_class(column)
    samples: tuple[str, ...] = ()
    if (
        pii is None
        and kind == "TEXT"
        and 0 < stats.distinct <= MAX_DISTINCT_FOR_SAMPLES
        and stats.avg_len <= MAX_AVG_LENGTH_FOR_SAMPLES
    ):
        samples = tuple(clean_text(text, MAX_SAMPLE_CHARS) for text in stats.texts[:MAX_SAMPLES])
    number_range = None
    if pii is None and kind == "NUMBER" and stats.minimum is not None and stats.maximum is not None:
        number_range = (format(stats.minimum, "f"), format(stats.maximum, "f"))
    return ColumnEvidence(
        index=column.position,
        header=clean_text(column.header),
        kind=kind,
        values=stats.n,
        distinct=stats.distinct,
        pii=pii,
        samples=samples,
        number_range=number_range,
        assigned=column.field,
    )


def known_words(text: str, vocabulary: frozenset[str]) -> str:
    """Of a free text (a sheet name, a title), ONLY the words NINFA's own vocabulary knows
    ("turni", "personale", "reception"): the rest - a hotel's name, a person's name, anything
    typed by hand - never leaves. The model learns what kind of document this is, not who it is
    about."""
    kept = [word for word in fold(text).split() if stem(word) in vocabulary]
    return " ".join(dict.fromkeys(kept))


def _vocabulary(semantics: Mapping[DataSourceDomain, DomainSem]) -> frozenset[str]:
    words: set[str] = set(HEADER_STEMS) | set(SECTION_WORDS)
    for sem in semantics.values():
        words |= sem.title_words
    return frozenset(words)


def build_evidence(
    *,
    expected: DataSourceDomain,
    semantics: Mapping[DataSourceDomain, DomainSem],
    sheets: Sequence[tuple[str, str, int]],
    title: str | None,
    proposal: Proposal,
    questions: Sequence[Question],
) -> UnderstandingEvidence:
    """The cleaned document the model sees. Never the file name, never a cell of a personal-data
    column, never a long free text: sheet names and the title are reduced to the words NINFA's own
    vocabulary knows."""
    vocabulary = _vocabulary(semantics)
    offered = tuple(
        OfferedQuestion(q.id, q.kind.value, tuple(c.value for c in q.choices))
        for q in questions
        if q.kind in _ASKABLE and q.choices and q.candidate is None
    )
    return UnderstandingEvidence(
        expected_domain=expected.value,
        fields={kind.value: tuple(sem.fields) for kind, sem in semantics.items()},
        sheets=tuple((known_words(name, vocabulary), role, rows) for name, role, rows in sheets),
        title=None if title is None else (known_words(title, vocabulary) or None),
        columns=tuple(_evidence_of_column(c) for c in proposal.columns[:MAX_COLUMNS]),
        questions=offered,
    )


def fit_function(semantics: Mapping[DataSourceDomain, DomainSem], proposal: Proposal) -> FitOf:
    """How well the VALUES of a column fit a field of a kind of data (the model's say-so alone is
    never enough: a header guessed as a date over a column of names is dropped)."""
    by_index = {c.position: c for c in proposal.columns}
    by_name = {kind.value: sem for kind, sem in semantics.items()}

    def fit_of(domain: str, index: int, field: str) -> float | None:
        sem = by_name.get(domain)
        column = by_index.get(index)
        if sem is None or column is None or field not in sem.fields:
            return None
        spec = sem.fields[field]
        return None if spec.fit is None else spec.fit(column.stats)

    return fit_of


def needs_help(
    proposal: Proposal,
    groups: Sequence[tuple[str, ...]],
    questions: Sequence[Question],
) -> bool:
    """Is something unresolved that a model could help with: a required piece of information with
    no column yet and a column left over, or a question about the kind of data?"""
    assigned = {c.field for c in proposal.columns if c.field is not None}
    missing = any(not any(field in assigned for field in group) for group in groups)
    left_over = any(
        c.field is None
        and c.locked is None
        and c.pii is None
        and c.ambiguous_group is None
        and c.stats.n >= 1
        for c in proposal.columns
    )
    asks_kind = any(q.kind == QuestionKind.DOMAIN for q in questions)
    return (missing and left_over) or asks_kind


def apply_resolution(
    proposal: Proposal,
    questions: list[Question],
    resolution: AiResolution,
    expected: DataSourceDomain,
) -> tuple[Proposal, list[Question], frozenset[str]]:
    """What the model suggested, as suggestions: fields at MEDIUM on columns the rules left alone,
    a likely answer on the questions that were still open. Returns the headers it filled."""
    if not resolution.used:
        return proposal, questions, frozenset()
    same_domain = resolution.domain in (None, expected.value)
    filled: set[str] = set()
    columns: list[ColumnProposal] = []
    taken = {c.field for c in proposal.columns if c.field is not None}
    for column in proposal.columns:
        field = resolution.columns.get(column.position) if same_domain else None
        if (
            field is not None
            and column.field is None
            and column.locked is None
            and column.pii is None
            and column.ambiguous_group != CONTESTED  # a choice between look-alikes is the person's
            and field not in taken
        ):
            taken.add(field)
            filled.add(column.header)
            columns.append(
                replace(
                    column,
                    field=field,
                    level=Level.MEDIUM,
                    name=NameMatch.VALUES,
                    ambiguous_group=None,
                    ambiguous_fields=(),
                )
            )
        else:
            columns.append(column)

    suggested: list[Question] = []
    for question in questions:
        choice = resolution.answers.get(question.id)
        if question.kind == QuestionKind.DOMAIN and question.candidate is None:
            choice = choice or (resolution.domain if resolution.domain != expected.value else None)
        if (
            choice is not None
            and question.candidate is None
            and any(c.value == choice for c in question.choices)
        ):
            question = replace(question, candidate=choice, origin=OriginKind.ASSISTANT)
        suggested.append(question)
    return Proposal(tuple(columns)), suggested, frozenset(filled)


__all__ = ["apply_resolution", "build_evidence", "fit_function", "needs_help"]
