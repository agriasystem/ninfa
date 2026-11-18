"""The candidate score: why a column might be a field, in numbers a person can read.

Every (column, field) pair that could be a reading gets a `CandidateScore` made of named parts:

    header      how well the NAME says the field: 1.00 a known phrase, 0.97 the same words in
                another order, 0.95 the same plus a word naming the kind of file, 0.80-0.99 a
                spelling mistake of one, or the weight of a V3 word rule (<= 0.93)
    values      how well the VALUES fit the field (the field's own fit function), 0..1, or None
                when the values say nothing either way
    proof       how strongly the values ALONE name the field (a vocabulary or a shape), 0..1
    relational  what other columns add: +0.15 for a role their relation explains
    veto        why the column CANNOT be this field - when set, the pair is not a candidate

and one `total` in 0..1 that the global assignment maximises:

    with a name   total = header x (0.55 + 0.45 x values) + relational
    no name       total = 0.62 x proof + relational          (the values alone never beat a name)

A name carries most of the weight and the values scale it (a name over values that do not fit is
worth little); a field whose values prove it can be read with no name, but never above a name.
Nothing here decides: `breakdown()` is what a test, a report or a person debugging a reading sees.
"""

from dataclasses import dataclass

from app.modules.data_sources.semantics import NameMatch

# what a reading from the values alone can reach: below any decent name
VALUE_ONLY_CAP = 0.62
# what a value-less name is worth when the field's values say nothing either way
NEUTRAL_VALUES = 0.85
NAME_FLOOR = 0.55
NAME_SCALE = 0.45
# the least a candidate may total to be admitted at all
ADMIT = 0.30


@dataclass(frozen=True, slots=True)
class CandidateScore:
    column: int
    field: str
    name: NameMatch
    header: float
    header_kind: str  # EXACT / REORDERED / IN_CONTEXT / TYPO / RULE / ALIAS(V3) / VALUES
    phrase: str | None
    values: float | None
    proof: float
    relational: float
    veto: str | None
    total: float
    rule: int | None = None
    notes: tuple[str, ...] = ()

    def breakdown(self) -> dict[str, object]:
        """The score with its parts - never a value of the file."""
        return {
            "column": self.column,
            "field": self.field,
            "total": round(self.total, 3),
            "header": round(self.header, 3),
            "header_kind": self.header_kind,
            "phrase": self.phrase,
            "values": None if self.values is None else round(self.values, 3),
            "proof": round(self.proof, 3),
            "relational": round(self.relational, 3),
            "veto": self.veto,
        }


def combine(
    header: float, values: float | None, proof: float, relational: float, veto: str | None
) -> float:
    """The total of a candidate, in 0..1 (see the module docstring)."""
    if veto is not None:
        return 0.0
    if header > 0:
        fit = NEUTRAL_VALUES if values is None else values
        total = header * (NAME_FLOOR + NAME_SCALE * fit) + relational
    else:
        total = VALUE_ONLY_CAP * proof + relational if proof > 0 else 0.0
    return max(0.0, min(1.0, total))


__all__ = [
    "ADMIT",
    "NEUTRAL_VALUES",
    "VALUE_ONLY_CAP",
    "CandidateScore",
    "combine",
]
