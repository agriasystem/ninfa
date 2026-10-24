"""What the values of ONE column say about it: counts and shapes, nothing that identifies anyone.

A column of dates looks like dates, a column of hours is made of small numbers, a column of channels
repeats a few words. That is EVIDENCE for what a column means, next to what its header says. The
statistics keep the (few) distinct text values the vocabulary checks need and never more than
`MAX_TEXTS` of them; they are computed in memory from the rows the caller reads and kept nowhere.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.bookings.parsers import Cell
from app.modules.document_understanding.structure import as_decimal
from app.modules.document_understanding.text import fold
from app.modules.document_understanding.values import CellKind, kind_of, text_of

MAX_TEXTS = 300
MIN_EVIDENCE = 3  # fewer values than this never make a column "certain" (one sample proves nothing)


@dataclass(frozen=True, slots=True)
class ColumnStats:
    n: int  # non-empty values
    kinds: dict[CellKind, int]
    distinct: int  # distinct values, case/accents folded (capped)
    avg_len: float  # average length of the text values
    numeric: int  # values that read as a number (a cell, or text such as "7,5")
    minimum: Decimal | None
    maximum: Decimal | None
    integral: int  # numeric values with no decimals
    negatives: int
    texts: tuple[str, ...]  # up to MAX_TEXTS distinct text values, as written
    # Up to MAX_TEXTS distinct cells that were WRITTEN as text, even when they read as a number
    # ("+39 333 1234567"): what the personal-data check needs, kept nowhere.
    strings: tuple[str, ...] = ()

    def fraction(self, kind: CellKind) -> float:
        return self.kinds.get(kind, 0) / self.n if self.n else 0.0

    @property
    def numeric_fraction(self) -> float:
        return self.numeric / self.n if self.n else 0.0

    @property
    def text_fraction(self) -> float:
        return self.fraction(CellKind.TEXT)

    @property
    def date_fraction(self) -> float:
        return self.fraction(CellKind.DATE)

    @property
    def distinct_ratio(self) -> float:
        return self.distinct / self.n if self.n else 0.0

    def enough(self) -> bool:
        return self.n >= MIN_EVIDENCE


def column_stats(values: Sequence[Cell]) -> ColumnStats:
    kinds: Counter[CellKind] = Counter()
    seen: set[str] = set()
    texts: dict[str, str] = {}
    strings: dict[str, str] = {}
    lengths: list[int] = []
    numbers: list[Decimal] = []
    n = 0
    for value in values:
        kind = kind_of(value)
        if kind == CellKind.EMPTY:
            continue
        n += 1
        kinds[kind] += 1
        shown = text_of(value)
        key = fold(shown)
        if isinstance(value, str) and len(strings) < MAX_TEXTS:
            strings.setdefault(value.strip(), value.strip())
        if len(seen) < 5000:
            seen.add(key)
        if kind == CellKind.TEXT:
            lengths.append(len(shown))
            if len(texts) < MAX_TEXTS:
                texts.setdefault(key, shown)
        elif kind == CellKind.NUMBER:
            number = as_decimal(value)
            if number is not None:
                numbers.append(number)
    return ColumnStats(
        n=n,
        kinds=dict(kinds),
        distinct=len(seen),
        avg_len=sum(lengths) / len(lengths) if lengths else 0.0,
        numeric=len(numbers),
        minimum=min(numbers) if numbers else None,
        maximum=max(numbers) if numbers else None,
        integral=sum(1 for number in numbers if number == number.to_integral_value()),
        negatives=sum(1 for number in numbers if number < 0),
        texts=tuple(texts.values()),
        strings=tuple(strings.values()),
    )


__all__ = ["MAX_TEXTS", "MIN_EVIDENCE", "ColumnStats", "column_stats"]
