"""What counts of a labor source: the one rule, pure, for everyone who reads it.

Every file a source imports stays, as its own immutable snapshot. Nothing is overwritten or deleted:
what counts is decided here, on reading, from the snapshots known at a date.

Planned and worked hours are two different facts, and neither stands in for the other: this rule is
applied to each on its own (`Basis`). A file of hours worked says nothing about the plan, and a new
plan says nothing about the hours worked.

    A file speaks for the cells it holds: each (work date, category) it has a row for.
    Where it speaks, the newest file wins; where it does not, what was there stays.

The unit is (work date, category), the unit every figure of labor is computed on. It is not a person
(the model holds none) nor a role label (free text a second export may write differently). So:

    week A, then week B                    no date in common: they live side by side
    week A, then week A corrected          the same cells: the correction replaces them, no sum
    Mon-Sun, then Thu-Wed                  Thu-Sun from the second, Mon-Wed from the first
    Reception's file, then Housekeeping's  no category in common: both stay, on the same days
    a file that has no Spa on Sunday       Spa on Sunday stays, even if the file has Spa on Monday
                                           and Reception on Sunday: that cell is not in the file
    a plan, then the hours worked          each stays what it is, on the same days

A day the file names and a category it names elsewhere do not make a cell it holds: the days of a
file times its categories are never read as what it speaks for. Its absence there is no information.

Only a file known to be COMPLETE (`file_scope` FULL) says more: on every day from its first to its
last it speaks for every category, held or not. What it does not hold there is not current any more,
while staying in the history. Whether a file is complete is never guessed from the file: a person
said so. A part (PARTIAL), a list of changes (DELTA) or a file nobody said anything about takes
nothing away. A row of zero hours is not a removal either: it is a plan of zero hours, which the
analysis reads as a department scheduled for nothing, not as one with no plan.

"Newest" is (snapshot_local_date, revision), the order the files came in. A file with no entry in
`files` is judged by the rows given.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.modules.labor.roles import LaborCategory


class Basis(StrEnum):
    PLANNED = "PLANNED"
    ACTUAL = "ACTUAL"


class PlanRow(Protocol):
    """What the rule looks at: which file, which work date, which category, which hours."""

    @property
    def labor_snapshot_id(self) -> UUID: ...
    @property
    def snapshot_local_date(self) -> date: ...
    @property
    def revision(self) -> int: ...
    @property
    def work_date(self) -> date: ...
    @property
    def labor_category(self) -> LaborCategory: ...
    @property
    def planned_minutes(self) -> int | None: ...
    @property
    def actual_minutes(self) -> int | None: ...


@dataclass(frozen=True, slots=True)
class FileCoverage:
    """What one file speaks for, whatever rows are being read: read from the WHOLE file."""

    snapshot_local_date: date
    revision: int
    categories: frozenset[LaborCategory]
    has_planned: bool
    has_actual: bool
    # The days of a file known to be complete; None for any other.
    complete_from: date | None = None
    complete_to: date | None = None

    def _says(self, basis: Basis) -> bool:
        return self.has_planned if basis is Basis.PLANNED else self.has_actual

    def clears(self, basis: Basis, work_date: date) -> bool:
        """With no row of its own in a cell of this day, does this file say the cell is empty?

        Only a complete file does, and only inside its own days. Any other file is silent on every
        cell it does not hold, whatever else it holds on that day or for that category."""
        return (
            self._says(basis)
            and self.complete_from is not None
            and self.complete_to is not None
            and self.complete_from <= work_date <= self.complete_to
        )


def _value(row: PlanRow, basis: Basis) -> int | None:
    return row.planned_minutes if basis is Basis.PLANNED else row.actual_minutes


def current_rows[Row: PlanRow](
    rows: Sequence[Row],
    files: Mapping[UUID, FileCoverage] | None = None,
    *,
    basis: Basis = Basis.PLANNED,
) -> dict[date, tuple[UUID, list[Row]]]:
    """For each work date: the newest file that counts on it, and the rows that count, on one basis.

    A work date where nothing counts has no key: nothing is known of it, which is not zero.
    """
    cells: dict[UUID, dict[tuple[date, LaborCategory], list[Row]]] = defaultdict(
        lambda: defaultdict(list)
    )
    seen: dict[UUID, FileCoverage] = {}
    for row in rows:
        cells[row.labor_snapshot_id][(row.work_date, row.labor_category)].append(row)
        known = seen.get(row.labor_snapshot_id)
        seen[row.labor_snapshot_id] = FileCoverage(
            row.snapshot_local_date,
            row.revision,
            (known.categories if known else frozenset()) | {row.labor_category},
            (known.has_planned if known else False) or row.planned_minutes is not None,
            (known.has_actual if known else False) or row.actual_minutes is not None,
        )
    coverage = {**seen, **(files or {})}

    def order(snapshot: UUID) -> tuple[date, int, str]:
        file = coverage[snapshot]
        return (file.snapshot_local_date, file.revision, str(snapshot))

    newest_first = sorted(coverage, key=order, reverse=True)
    days = {row.work_date for row in rows}
    categories = {category for file in coverage.values() for category in file.categories}

    plan: dict[date, tuple[UUID, list[Row]]] = {}
    for work_date in days:
        counted: list[Row] = []
        newest: UUID | None = None
        for category in categories:
            winner: UUID | None = None
            silent: UUID | None = None
            for snapshot in newest_first:
                in_cell = (
                    cells[snapshot].get((work_date, category), []) if snapshot in cells else []
                )
                if in_cell:
                    # Rows with nothing on this basis say nothing about it: an older file may. If
                    # none does they are what is known of the cell, and the reader sees the gap.
                    if any(_value(row, basis) is not None for row in in_cell):
                        winner = snapshot
                        break
                    silent = silent or snapshot
                    continue
                if coverage[snapshot].clears(basis, work_date):
                    silent = None
                    break
            chosen = winner or silent
            if chosen is not None:
                counted.extend(cells[chosen][(work_date, category)])
                if newest is None or order(chosen) > order(newest):
                    newest = chosen
        if newest is not None:
            plan[work_date] = (newest, counted)
    return plan


__all__ = ["Basis", "FileCoverage", "PlanRow", "current_rows"]
