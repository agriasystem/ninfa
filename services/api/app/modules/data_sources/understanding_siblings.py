"""A column nobody read that moves with one somebody did: never lost in silence.

Some things are measured in two ways: hours planned and hours worked, what a room cost and what the
whole stay cost. An import can run with ONE of them, and so a file that carries both, with one
header the rules know and the other they do not ("Impegno reale", "Incasso"), used to be READY with
the second column quietly left out: the numbers of a business decision gone, and nothing on the
screen to say so. Finding this took a benchmark (41 of 290 files), not a person.

The rule is about the VALUES, never about the header (the header is, by definition, what NINFA could
not read) and never about a provider (the rules alone decide, with the model off, with any model):

    one of two measures of the same thing is read, a column nobody read holds numbers that are
    close to it row after row, and they would be a valid reading of the other one
    -> the file is not READY: hours are asked about ("Is this the actual hours?"), and money is
       never put as a yes or no, so the person matches the columns by hand.

A column that merely sits nearby (nights, guests, a commission, a per-night price) does not move
with the sibling and is not asked about: most of the unread columns of a file are innocent, and a
rule that questioned them all would be a rule nobody could live with.
"""

from collections.abc import Sequence
from decimal import Decimal

from app.modules.data_sources.column_profile import ColumnSample
from app.modules.data_sources.proposal import ColumnProposal, Proposal
from app.modules.data_sources.semantics import DomainSem, name_candidates
from app.modules.data_sources.understanding_types import (
    Choice,
    OriginKind,
    Question,
    QuestionKind,
)
from app.modules.document_understanding.structure import as_decimal
from app.modules.document_understanding.text import tokens

# Enough rows for two columns to agree by chance only rarely.
MIN_PAIRS = 3
# A column "moves with" its sibling when this share of the rows have a ratio inside the band: a few
# stray rows are a typing slip, not a different kind of column.
HOLDS_AT_LEAST = 0.9
# Actual hours are close to the planned ones, a whole stay costs a little more than its room: the
# band is wide enough for both and too narrow for a count of nights or a commission.
RATIO_FROM = Decimal("0.6")
RATIO_TO = Decimal("1.7")
# The most unread siblings a person is asked about one by one: more, and they match by hand.
MAX_QUESTIONS = 2
# A column is a candidate only when it is (nearly) all numbers.
MIN_NUMERIC = 0.9
# The whole is never smaller than its part: a rounding is the only slack.
ROUNDING = Decimal("0.02")


def _numbers(column: ColumnSample) -> list[Decimal | None]:
    return [as_decimal(cell) for cell in column.rows]


def moves_with(
    unread: ColumnSample,
    read: ColumnSample,
    *,
    floor: Decimal = RATIO_FROM,
    ceiling: Decimal = RATIO_TO,
) -> bool:
    """Do the values of two columns stay in proportion row after row (both read the same rows)?
    The band is the ratio `unread / read` they must stay inside."""
    if not unread.rows or len(unread.rows) != len(read.rows):
        return False
    pairs = [
        (a, b)
        for a, b in zip(_numbers(unread), _numbers(read), strict=True)
        if a is not None and b is not None and a > 0 and b > 0
    ]
    if len(pairs) < MIN_PAIRS:
        return False
    inside = sum(1 for a, b in pairs if floor <= a / b <= ceiling)
    return inside / len(pairs) >= HOLDS_AT_LEAST


def _band(sem: DomainSem, column: ColumnProposal, other: str) -> dict[str, Decimal]:
    """The ratio an unread column may have to the read one (`column`) to be `other`. Planned and
    worked hours can be either side of each other. A whole is never smaller than its part: when
    the part is read, a column that would be the whole must not be smaller than it (a net after
    commission, 87% of the room, is not the stay's total). Unless the read column's OWN name is
    also a name of `other` ("Totale soggiorno" is a room total and a stay total alike): then
    NINFA does not know which half it holds, and the unread column may be either side of it."""
    read = column.field
    if read is None or any(c.field == other for c in name_candidates(sem, column.header)):
        return {}
    if (read, other) in sem.parts:
        return {"floor": 1 - ROUNDING}
    return {}


def _free(sem: DomainSem, column: ColumnProposal) -> bool:
    """A column nobody read, that is not personal data, not left out on purpose, not already a
    question of its own and not NAMED as another kind of the same measure (contract hours),
    with numbers in it."""
    return (
        column.field is None
        and not tokens(column.header) & sem.other_kinds
        and column.locked is None
        and column.pii is None
        and column.ambiguous_group is None
        and column.stats.enough()
        and column.stats.numeric_fraction >= MIN_NUMERIC
    )


def unread_siblings(
    sem: DomainSem, proposal: Proposal, samples: Sequence[ColumnSample]
) -> tuple[list[Question], bool]:
    """The questions about unread columns that may be the other half of a measure the file does
    read, and whether the file must go to the matching screen (money, or too many to ask one by
    one). Deterministic and provider-free: it reads the proposal and the values, nothing else."""
    placed = {c.field: c for c in proposal.columns if c.field is not None}
    questions: list[Question] = []
    hold = False
    seen: set[int] = set()
    for family in sem.siblings:
        read = [name for name in family if name in placed]
        missing = [name for name in family if name not in placed]
        if not read or not missing:
            continue
        for column in proposal.columns:
            if column.position in seen or not _free(sem, column):
                continue
            by_position = samples[column.position] if column.position < len(samples) else None
            if by_position is None:
                continue
            for other in missing:
                spec = sem.fields.get(other)
                if spec is None or (spec.fit is not None and spec.fit(column.stats) < 0.9):
                    continue
                if not any(
                    placed[name].position < len(samples)
                    and moves_with(
                        by_position,
                        samples[placed[name].position],
                        **_band(sem, placed[name], other),
                    )
                    for name in read
                ):
                    continue
                if other in sem.financial and any(
                    placed[name].position < len(samples)
                    and moves_with(
                        by_position,
                        samples[placed[name].position],
                        floor=1 - ROUNDING,
                        ceiling=1 + ROUNDING,
                    )
                    for name in read
                ):
                    continue  # the same amounts, row after row: nothing the import lacks
                seen.add(column.position)
                if other in sem.financial:
                    hold = True  # money is never put as a yes or no
                else:
                    questions.append(
                        Question(
                            id=f"CONFIRM:{column.header}",
                            kind=QuestionKind.COLUMN_MEANING,
                            column=column.header,
                            field=other,
                            candidate=other,
                            origin=OriginKind.COLUMN,
                            choices=(Choice(other),),
                        )
                    )
                break
    if len(questions) > MAX_QUESTIONS:
        return [], True
    return questions, hold


__all__ = ["MAX_QUESTIONS", "moves_with", "unread_siblings"]
