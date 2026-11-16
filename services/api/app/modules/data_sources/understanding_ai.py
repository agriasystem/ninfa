"""Where the deterministic understanding and the optional AI step meet.

`build_evidence` turns what the rules found into the small, cleaned document a model is shown (no
file name, no personal data - a personal-data column is only its class - no free text beyond a few
cleaned words); `apply_resolution` puts what survived the checks back as SUGGESTIONS: a field at
MEDIUM confidence ("to be checked"), a likely answer on a question the person will still answer.
Nothing here can make a column certain on the model's word alone, and with no provider the whole
step is skipped.

There is ONE exception, and it is narrow (`corroborate`): a column the model named and whose VALUES
NINFA recognises from its own closed vocabulary (booking statuses, channels, departments, cost
categories). That is the same two proofs - a name that says it and values that confirm it - that
let a rule take a column as certain; here the model reads the name and NINFA's vocabulary reads the
values. Dates, hours, amounts, identifiers and counts are never promoted: their values cannot tell
one such column from another, so the person still confirms them.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from app.modules.ai.import_understanding.egress import EgressGuard
from app.modules.ai.import_understanding.sanitize import clean_text
from app.modules.ai.import_understanding.types import (
    AiResolution,
    ColumnEvidence,
    LevelCounts,
    OfferedQuestion,
    UnderstandingEvidence,
)
from app.modules.ai.import_understanding.validator import MIN_FIT, FitOf
from app.modules.data_sources.proposal import ColumnProposal, Proposal
from app.modules.data_sources.semantics import DomainSem, Level, NameMatch
from app.modules.data_sources.understanding_types import (
    Choice,
    OriginKind,
    Question,
    QuestionKind,
)
from app.modules.document_understanding.lexicon import HEADER_STEMS, SECTION_WORDS
from app.modules.document_understanding.pii import looks_like_person
from app.modules.document_understanding.redaction import PersonalDataGuard
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
# The fields whose VALUES NINFA can read for itself: a booking status, a channel, a department, a
# cost category are recognised from closed vocabularies (`fit_vocabulary`, `fit_channel`), so a name
# the model read for them is confirmed by what the column holds. For every other field the values
# say too little to tell it from its neighbours (two date columns, two amounts, two counts).
# The most columns a model may name in one file, whichever model it is: a file that needs more is
# the person's to match.
MAX_ASSISTED = 6
CORROBORATED_FIELDS = frozenset({"status", "channel", "role", "cost_category"})
# The vocabulary fits return exactly 1.0 when most of the distinct values are known words, and at
# most 0.8 of a base fit otherwise: only the first is a recognition.
RECOGNISED = 1.0


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


def egress_guard(
    personal: PersonalDataGuard, semantics: Mapping[DataSourceDomain, DomainSem]
) -> EgressGuard:
    """What the egress gate needs to know about THIS file: its personal values (so none can ride in
    a header, a sheet name or an example) and what a header that is a person's name looks like (a
    staff grid has one column per employee) - but a label made of words NINFA knows is a header,
    whatever it resembles ("Booker Name", "Book Number")."""
    vocabulary = _vocabulary(semantics)
    return EgressGuard(
        scrub=personal.clean,
        is_name=lambda label: looks_like_person(label) and not known_words(label, vocabulary),
    )


def build_evidence(
    *,
    expected: DataSourceDomain,
    semantics: Mapping[DataSourceDomain, DomainSem],
    sheets: Sequence[tuple[str, str, int]],
    title: str | None,
    proposal: Proposal,
    questions: Sequence[Question],
    confirmable: bool = False,
) -> UnderstandingEvidence:
    """The cleaned document the model sees. Never the file name, never a cell of a personal-data
    column, never a long free text: sheet names and the title are reduced to the words NINFA's own
    vocabulary knows."""
    vocabulary = _vocabulary(semantics)
    position = {c.header: c.position for c in reversed(proposal.columns)}
    offered = tuple(
        OfferedQuestion(
            q.id,
            q.kind.value,
            tuple(c.value for c in q.choices),
            column=position.get(q.column) if q.column is not None else None,
        )
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
        confirmable=_confirmable(proposal) if confirmable else frozenset(),
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


def _confirmable(proposal: Proposal) -> frozenset[int]:
    """The columns the rules put on a field NINFA's vocabulary can prove, without being sure."""
    return frozenset(
        c.position
        for c in proposal.columns
        if c.field in CORROBORATED_FIELDS
        and c.level is not None
        and c.level != Level.HIGH
        and c.ambiguous_group is None
        and c.locked is None
        and c.pii is None
    )


def needs_help(
    proposal: Proposal,
    groups: Sequence[tuple[str, ...]],
    questions: Sequence[Question],
    certainty: bool = False,
    never: frozenset[str] = frozenset(),
) -> bool:
    """Is something unresolved that a model could help with: a required piece of information with
    no column yet and a column left over, or a question about the kind of data?

    A model is asked ONLY when it can change what the person is shown (V1.1, measured on the 283
    real calls of V1):

    * a gap that only MONEY could fill is not one it can help with: a model never places money
      (`never`), so asking it about a missing amount changes nothing;
    * a column the rules placed without being sure (`doubtful`) is worth a question only when its
      reading could make the column certain (`certainty`): with that certainty withdrawn (ADR 0052)
      all it can say is "I agree", and none of the 23 such calls changed anything;
    * a column left over beside a pair of alternatives that is half read (`other_half`: planned OR
      actual hours) is no reason either: the sibling rule (ADR 0051) asks about it without any
      model, and a model's reading only relabels the column that question is already about
      (51 calls: no question, no level changed)."""
    assigned = {c.field for c in proposal.columns if c.field is not None}
    fillable = [group for group in groups if not all(field in never for field in group)]
    missing = any(not any(field in assigned for field in group) for group in fillable)
    left_over = any(
        c.field is None
        and c.locked is None
        and c.pii is None
        and c.ambiguous_group is None
        and c.stats.n >= 1
        for c in proposal.columns
    )
    asks_kind = any(q.kind == QuestionKind.DOMAIN for q in questions)
    # (a column the rules placed without being sure, on a field a vocabulary can prove: the name,
    # read by someone else, may be all that is missing - and only if that can make it certain)
    doubtful = certainty and bool(_confirmable(proposal))
    return (missing and left_over) or asks_kind or doubtful


def is_immaterial(
    column: ColumnProposal, field: str, sem: DomainSem, defaults: Mapping[str, object]
) -> bool:
    """Would IGNORING a reading of this column as this field change anything NINFA imports or
    decides? Whoever made the reading (a model, any model): nothing here knows about one.

    Two cases, and only these:

    * the field is DESCRIPTIVE (`DomainSem.descriptive`): stored with the record and read by no
      measure, no analysis, no decision;
    * the file may leave the field out and the import then assumes a value (`defaults`: the rooms
      of a booking, one) and the column holds exactly that value in every row it has - it says
      what the import already assumes. One row that says anything else, and it is not immaterial.

    Never a required field, money, a measure of a pair, or a field a vocabulary proves."""
    if field in sem.descriptive:
        return True
    default = defaults.get(field)
    stats = column.stats
    if default is None or not stats.enough():
        return False
    if isinstance(default, int | float):
        return (
            stats.numeric == stats.n
            and stats.minimum is not None
            and stats.minimum == stats.maximum == Decimal(str(default))
        )
    return stats.distinct == 1 and bool(stats.texts) and fold(stats.texts[0]) == fold(str(default))


def apply_resolution(
    proposal: Proposal,
    questions: list[Question],
    resolution: AiResolution,
    expected: DataSourceDomain,
    domains: Sequence[str] = (),
    never: frozenset[str] = frozenset(),
    immaterial: Callable[[ColumnProposal, str], bool] | None = None,
) -> tuple[Proposal, list[Question], frozenset[str], int]:
    """What the model suggested, as suggestions: fields at MEDIUM on columns the rules left alone,
    a likely answer on the questions that were still open. Returns the headers it filled.

    `never` are fields a model does not place at all, whichever model it is: the fields that are
    MONEY. A choice about money is the person's, matched by hand, and never a yes or no on a model's
    word (the same rule the rules themselves keep).

    `immaterial` says that ignoring a reading changes nothing (`is_immaterial`): the reading is then
    neither applied nor asked about - the file stays as sure as it was - and only counted, for the
    audit. Returns the proposal, the questions, the headers it filled and that count."""
    if not resolution.used:
        return proposal, questions, frozenset(), 0
    same_domain = resolution.domain in (None, expected.value)
    filled: set[str] = set()
    ignored = 0
    columns: list[ColumnProposal] = []
    taken = {c.field for c in proposal.columns if c.field is not None}
    # a field that some OTHER column is still a candidate for (a hours/amount column that does not
    # say which, look-alikes for one field) is not given away: there is a competing candidate
    contended = {f for c in proposal.columns for f in c.ambiguous_fields}
    for column in proposal.columns:
        field = resolution.columns.get(column.position) if same_domain else None
        if (
            field is not None
            and len(filled) < MAX_ASSISTED
            and column.field is None
            and column.locked is None
            and column.pii is None
            and column.ambiguous_group is None  # a choice between candidates is the person's
            and field not in taken
            and field not in contended
            and field not in never
        ):
            if immaterial is not None and immaterial(column, field):
                ignored += 1
                columns.append(column)
                continue
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
        if (
            choice is not None
            and question.candidate is None
            and any(c.value == choice for c in question.choices)
        ):
            question = replace(question, candidate=choice, origin=OriginKind.ASSISTANT)
        suggested.append(question)
    guessed = resolution.answers.get("DOMAIN") or resolution.domain
    if (
        guessed in domains
        and guessed != expected.value
        and not any(q.kind == QuestionKind.DOMAIN for q in suggested)
    ):
        # the rules saw nothing that points anywhere, the model thinks this is ANOTHER kind of
        # data than the one the person chose: that is worth asking, as its suggestion
        suggested.append(
            Question(
                id="DOMAIN",
                kind=QuestionKind.DOMAIN,
                candidate=guessed,
                origin=OriginKind.ASSISTANT,
                choices=tuple(Choice(value) for value in domains),
            )
        )
    return Proposal(tuple(columns)), suggested, frozenset(filled), ignored


def levels_of(proposal: Proposal) -> LevelCounts:
    """How many columns are certain, probable, doubtful, or not placed at all."""
    counts = {Level.HIGH: 0, Level.MEDIUM: 0, Level.LOW: 0}
    open_columns = 0
    for column in proposal.columns:
        if column.field is None:
            if column.locked is None and column.pii is None and column.stats.n >= 1:
                open_columns += 1
            continue
        counts[column.level or Level.LOW] += 1
    return LevelCounts(
        high=counts[Level.HIGH],
        medium=counts[Level.MEDIUM],
        low=counts[Level.LOW],
        open=open_columns,
    )


def conflicts_with_confirmed(
    resolution: AiResolution, proposal: Proposal, confirmed: frozenset[str]
) -> int:
    """How many columns the model reads differently from what a PERSON confirmed (an answer just
    given, or what this source remembers from before). Counted, never applied: a confirmed column is
    nobody's to change but the person's."""
    summary = resolution.interpretation
    if summary is None:
        return 0
    by_index = {c.position: c for c in proposal.columns}
    return sum(
        1
        for index, _placed, _said in summary.conflicts
        if (column := by_index.get(index)) is not None and column.header in confirmed
    )


def _recognised(
    column: ColumnProposal, field: str, free: Sequence[ColumnProposal], sem: DomainSem
) -> bool:
    """Do the VALUES of this column prove the field, by NINFA's own vocabulary, with nobody else
    to be it? (The name was read by somebody else - a model, a person; this is the other half.)"""
    spec = sem.fields.get(field)
    return (
        field in CORROBORATED_FIELDS
        and field not in sem.financial
        and spec is not None
        and spec.fit is not None
        and column.pii is None
        and column.locked is None
        and column.ambiguous_group is None
        and column.stats.enough()
        and spec.fit(column.stats) >= RECOGNISED
        # if another column that is still free holds the same kind of words, the values cannot
        # tell which of the two it is: that is the person's to say
        and not any(
            other is not column and other.stats.enough() and spec.fit(other.stats) >= RECOGNISED
            for other in free
        )
    )


def _free(proposal: Proposal) -> list[ColumnProposal]:
    return [c for c in proposal.columns if c.field is None and c.locked is None and c.pii is None]


def sole_candidates(proposal: Proposal, named: frozenset[str], sem: DomainSem) -> frozenset[str]:
    """Of the columns whose name somebody else read, those that nobody else could be: no other
    column still free holds values the same field's vocabulary recognises. If two columns hold the
    same kind of words (two columns of booking statuses), the words cannot tell which is which, and
    that is the person's to say - whichever way the name was read."""
    free = _free(proposal)
    sole: set[str] = set()
    for column in proposal.columns:
        spec = sem.fields.get(column.field) if column.field is not None else None
        if column.header not in named or spec is None:
            continue
        if spec.fit is None or not any(
            other.stats.enough() and spec.fit(other.stats) >= RECOGNISED for other in free
        ):
            sole.add(column.header)
    return frozenset(sole)


def corroborate(
    proposal: Proposal, eligible: frozenset[str], sem: DomainSem
) -> tuple[Proposal, frozenset[str]]:
    """Columns whose name somebody else read (`eligible`) and that NINFA's own vocabulary recognises
    in the values: certain. Returns the proposal and the headers that became so.

    The conditions, each a way for a wrong reading to be stopped (`_recognised`): a field whose
    values NINFA reads for itself, not money; enough values; recognised by the field's
    vocabulary (fit 1.0); and nobody else still free that holds the same kind of words. (The
    caller has already required the model's whole reading to be clear.)"""
    if not eligible:
        return proposal, frozenset()
    free = _free(proposal)
    promoted: set[str] = set()
    columns: list[ColumnProposal] = []
    for column in proposal.columns:
        if (
            column.header in eligible
            and column.level in (Level.MEDIUM, Level.LOW)
            and column.field is not None
            and _recognised(column, column.field, free, sem)
        ):
            promoted.add(column.header)
            columns.append(replace(column, level=Level.HIGH))
        else:
            columns.append(column)
    return Proposal(tuple(columns)), frozenset(promoted)


def assist_named(
    proposal: Proposal, named: Mapping[str, str], sem: DomainSem
) -> tuple[Proposal, frozenset[str]]:
    """The NAMES a decision records as read by the semantic layer
    (`UnderstandAnswers.assisted_fields`), put on the columns they name - at MEDIUM, like any
    reading of a name by somebody else. The same
    chain that decided them the first time (the vocabulary of the values, the words NINFA knows)
    decides again whether they are certain, with no model: this is what the server runs to verify a
    decision a model helped to read. Only a free column, a free field NINFA's vocabulary reads and
    that is not money, and values that do not contradict the field, are given a name."""
    if not named:
        return proposal, frozenset()
    taken = {c.field for c in proposal.columns if c.field is not None}
    applied: set[str] = set()
    columns: list[ColumnProposal] = []
    for column in proposal.columns:
        field = named.get(column.header)
        spec = sem.fields.get(field) if field is not None else None
        if (
            field is not None
            and column.field == field
            and column.level in (Level.MEDIUM, Level.LOW)
            and field in CORROBORATED_FIELDS
        ):
            # the rules read it the same way, by its values, without being sure
            applied.add(column.header)
            columns.append(column)
        elif (
            field is not None
            and spec is not None
            and column.field is None
            and column.locked is None
            and column.pii is None
            and column.ambiguous_group is None
            and field in CORROBORATED_FIELDS
            and field not in sem.financial
            and field not in taken
            and (spec.fit is None or spec.fit(column.stats) >= MIN_FIT)
        ):
            taken.add(field)
            applied.add(column.header)
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
    return Proposal(tuple(columns)), frozenset(applied)


__all__ = [
    "CORROBORATED_FIELDS",
    "apply_resolution",
    "assist_named",
    "build_evidence",
    "conflicts_with_confirmed",
    "corroborate",
    "egress_guard",
    "fit_function",
    "levels_of",
    "needs_help",
    "sole_candidates",
]
