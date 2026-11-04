"""What counts of a labor source's plan: the one rule, pure, for everyone who reads it.

Every file a source imports stays, as its own immutable snapshot. Nothing is overwritten or deleted:
what counts is decided here, on reading, from the snapshots known at a date.

    A file speaks for the work dates it names and for the categories it names, together.
    Where it speaks, the newest file wins; where it does not, what was there stays.

The unit is (work date, category), the unit every figure of labor is computed on. It is not a person
(the model holds none) nor a role label (free text a second export may write differently). So:

    week A, then week B                    no date in common: they live side by side
    week A, then week A corrected          the same cells: the correction replaces them, no sum
    Mon-Sun, then Thu-Wed                  Thu-Sun from the second, Mon-Wed from the first
    Reception's file, then Housekeeping's  no category in common: both stay, on the same days
    a correction that drops Spa on Sunday  Spa is named, Sunday is named: Sunday has no Spa any more

What it cannot see: a file that drops a category altogether, on every day it covers, says nothing
about that category. The older rows stay until a file names it again: a stale figure, never a sum.

"Newest" is (snapshot_local_date, revision), the order the files came in. A row whose snapshot is
not in `categories_of` is judged by the categories of the rows given.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.labor.roles import LaborCategory


class PlanRow(Protocol):
    """What the rule looks at: which file, which work date, which category."""

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


def current_rows[Row: PlanRow](
    rows: Sequence[Row],
    categories_of: Mapping[UUID, Collection[LaborCategory]] | None = None,
) -> dict[date, tuple[UUID, list[Row]]]:
    """For each work date: the newest file that names it, and the rows that count on it.

    A work date with no row in any file has no key: nothing is known of it, which is not zero.
    """
    named: dict[UUID, set[LaborCategory]] = defaultdict(set)
    order_of: dict[UUID, tuple[date, int, str]] = {}
    by_day: dict[date, dict[UUID, list[Row]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        named[row.labor_snapshot_id].add(row.labor_category)
        order_of[row.labor_snapshot_id] = (
            row.snapshot_local_date,
            row.revision,
            str(row.labor_snapshot_id),
        )
        by_day[row.work_date][row.labor_snapshot_id].append(row)

    plan: dict[date, tuple[UUID, list[Row]]] = {}
    for work_date, files in by_day.items():
        newest_first = sorted(files, key=lambda snapshot: order_of[snapshot], reverse=True)
        decided: set[LaborCategory] = set()
        counted: list[Row] = []
        for snapshot in newest_first:
            spoken = (
                categories_of[snapshot]
                if categories_of is not None and snapshot in categories_of
                else named[snapshot]
            )
            counted.extend(row for row in files[snapshot] if row.labor_category not in decided)
            decided |= set(spoken)
        plan[work_date] = (newest_first[0], counted)
    return plan


__all__ = ["PlanRow", "current_rows"]
