"""The best reading of the WHOLE file at once: columns to fields, each used at most once.

V3 took the best-looking pair first, then the next, and so on. That is greedy: it can spend a
column on a field it fits well and leave another column, which could only be that field, with
nothing. Here the readings are an assignment problem. With the candidate totals as a score matrix

    rows     the columns of the table (the ones that may be read at all)
    columns  one per canonical field, plus one private "left out" slot per column, worth `OUT`

`scipy.optimize.linear_sum_assignment` finds the assignment with the highest total. A column that
no field wants goes to its own "left out" slot, so extra columns (a notes column, a code nobody
needs) cost nothing and fields nobody supplies stay empty. Pairs below `ADMIT` are forbidden, so a
column is never forced onto a field it hardly fits. Required and optional fields are the same here:
whether a missing field blocks the import is NINFA's domain rule (`DataSourceAdapter.groups`), not
the solver's.

Ambiguity is read off the same machinery. For each pair the solver chose, the pair is forbidden and
the file is solved again: the total it loses is the pair's MARGIN. A pair worth 0.65 more than any
other way of reading the file is firm; a pair another reading matches within `MARGIN` is a coin the
person should flip, not NINFA.

Ties are broken the way V3 broke them (earlier column, then the field order), so the same file
always gives the same reading.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.data_sources.algorithmic.scoring import ADMIT

# what leaving a column unread is worth: just under the least a reading may total
OUT = ADMIT - 0.05
_FORBIDDEN = -1e6


@dataclass(frozen=True, slots=True)
class Assignment:
    pairs: dict[int, str]  # column -> field
    total: float
    # column -> the total the file loses when this pair is forbidden: how firm the pair is
    margins: dict[int, float]


def _matrix(
    scores: Mapping[tuple[int, str], float],
    columns: Sequence[int],
    fields: Sequence[str],
    forbidden: tuple[int, str] | None,
) -> Any:
    size = len(fields)
    import numpy as np

    reward = np.full((len(columns), size + len(columns)), _FORBIDDEN, dtype=float)
    for row, column in enumerate(columns):
        for slot, name in enumerate(fields):
            value = scores.get((column, name), 0.0)
            if value >= ADMIT and (column, name) != forbidden:
                # earlier columns and earlier fields win a tie, as in V3 (a tiny, fixed nudge)
                reward[row, slot] = value + 1e-7 / (1 + column) + 1e-9 / (1 + slot)
        reward[row, size + row] = OUT
    return reward


def _solve(
    scores: Mapping[tuple[int, str], float],
    columns: Sequence[int],
    fields: Sequence[str],
    forbidden: tuple[int, str] | None = None,
) -> tuple[dict[int, str], float]:
    if not columns or not fields:
        return {}, 0.0
    # SciPy is imported here, not at the top: it is a development dependency (the assignment is not
    # the default engine, see engine.py), so a process that never asks for it never loads it.
    from scipy.optimize import linear_sum_assignment

    reward = _matrix(scores, columns, fields, forbidden)
    rows, slots = linear_sum_assignment(reward, maximize=True)
    pairs: dict[int, str] = {}
    total = 0.0
    for row, slot in zip(rows, slots, strict=True):
        total += float(reward[row, slot])
        if slot < len(fields) and reward[row, slot] > _FORBIDDEN / 2:
            pairs[columns[row]] = fields[slot]
    return pairs, total


def assign(
    scores: Mapping[tuple[int, str], float],
    columns: Sequence[int],
    fields: Sequence[str],
) -> Assignment:
    """The reading of the whole file with the highest total, and how firm each pair is."""
    pairs, total = _solve(scores, columns, fields)
    margins: dict[int, float] = {}
    for column, name in pairs.items():
        _other, without = _solve(scores, columns, fields, forbidden=(column, name))
        margins[column] = max(0.0, total - without)
    return Assignment(pairs, total, margins)


__all__ = ["OUT", "Assignment", "assign"]
