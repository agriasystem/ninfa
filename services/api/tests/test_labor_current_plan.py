"""`labor.current_plan.current_rows`: what counts of a labor source, as a table of cases (pure)."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from app.modules.labor.current_plan import Basis, FileCoverage, current_rows
from app.modules.labor.roles import LaborCategory as C

MON, TUE, WED, THU = (date(2026, 11, day) for day in (2, 3, 4, 5))
TODAY = date(2026, 11, 1)


@dataclass(frozen=True)
class Row:
    labor_snapshot_id: UUID
    snapshot_local_date: date
    revision: int
    work_date: date
    labor_category: C
    hours: int = 8

    @property
    def planned_minutes(self) -> int:
        return self.hours * 60

    @property
    def actual_minutes(self) -> None:
        return None


def file(
    *cells: tuple[date, C] | tuple[date, C, int], on: date = TODAY, revision: int = 1
) -> list[Row]:
    snapshot = uuid4()
    return [Row(snapshot, on, revision, *cell) for cell in cells]


def hours_on(rows: list[Row], day: date) -> Counter[C]:
    totals: Counter[C] = Counter()
    for row in current_rows(rows)[day][1]:
        totals[row.labor_category] += row.hours
    return totals


def test_two_files_with_no_day_in_common_live_side_by_side() -> None:
    first = file((MON, C.FRONT_OFFICE))
    second = file((TUE, C.FRONT_OFFICE), revision=2)

    plan = current_rows([*first, *second])

    assert plan[MON][0] == first[0].labor_snapshot_id
    assert plan[TUE][0] == second[0].labor_snapshot_id
    assert hours_on([*first, *second], MON) == {C.FRONT_OFFICE: 8}


def test_a_second_version_of_a_day_replaces_it_and_never_adds_up() -> None:
    first = file((MON, C.FRONT_OFFICE, 8))
    second = file((MON, C.FRONT_OFFICE, 6), revision=2)

    assert hours_on([*first, *second], MON) == {C.FRONT_OFFICE: 6}


def test_the_newest_file_wins_whatever_order_the_rows_come_in() -> None:
    first = file((MON, C.FRONT_OFFICE, 8))
    second = file((MON, C.FRONT_OFFICE, 6), revision=2)

    assert hours_on([*second, *first], MON) == {C.FRONT_OFFICE: 6}


def test_a_later_day_beats_a_higher_revision_of_an_earlier_day() -> None:
    earlier = file((MON, C.FRONT_OFFICE, 8), revision=9)
    later = file((MON, C.FRONT_OFFICE, 6), on=date(2026, 11, 2))

    assert hours_on([*earlier, *later], MON) == {C.FRONT_OFFICE: 6}


def test_files_that_overlap_share_the_days_by_the_same_rule() -> None:
    first = file((MON, C.FRONT_OFFICE, 8), (TUE, C.FRONT_OFFICE, 8), (WED, C.FRONT_OFFICE, 8))
    second = file(
        (TUE, C.FRONT_OFFICE, 6), (WED, C.FRONT_OFFICE, 6), (THU, C.FRONT_OFFICE, 6), revision=2
    )
    rows = [*first, *second]

    assert hours_on(rows, MON) == {C.FRONT_OFFICE: 8}
    assert hours_on(rows, TUE) == {C.FRONT_OFFICE: 6}
    assert hours_on(rows, WED) == {C.FRONT_OFFICE: 6}
    assert hours_on(rows, THU) == {C.FRONT_OFFICE: 6}


def test_files_of_different_departments_on_the_same_day_are_both_kept() -> None:
    reception = file((MON, C.FRONT_OFFICE, 8))
    housekeeping = file((MON, C.HOUSEKEEPING, 5), revision=2)

    assert hours_on([*reception, *housekeeping], MON) == {C.FRONT_OFFICE: 8, C.HOUSEKEEPING: 5}


def test_the_rows_of_one_cell_in_one_file_add_up_as_they_always_did() -> None:
    both_shifts = file((MON, C.FRONT_OFFICE, 4), (MON, C.FRONT_OFFICE, 3))

    assert hours_on(both_shifts, MON) == {C.FRONT_OFFICE: 7}


def test_a_file_without_a_department_on_one_day_leaves_that_cell_alone() -> None:
    """The file has Spa (on Monday) and has Tuesday (for Reception), but not Spa on Tuesday: that
    cell is not in the file, so the file says nothing about it."""
    first = file((MON, C.SPA_WELLNESS, 8), (TUE, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8))
    second = file((MON, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 6), revision=2)

    assert hours_on([*first, *second], TUE) == {C.FRONT_OFFICE: 6, C.SPA_WELLNESS: 8}


def _diagonal() -> tuple[list[Row], list[Row]]:
    """Reception and Housekeeping on Monday and Tuesday, then a file with only Reception on Monday
    and Housekeeping on Tuesday: both days and both departments are in it, two cells are not."""
    current = file(
        (MON, C.FRONT_OFFICE, 8), (MON, C.HOUSEKEEPING, 5), (TUE, C.FRONT_OFFICE, 8),
        (TUE, C.HOUSEKEEPING, 5),
    )  # fmt: skip
    new = file((MON, C.FRONT_OFFICE, 6), (TUE, C.HOUSEKEEPING, 3), revision=2)
    return current, new


def test_days_times_departments_of_a_part_are_never_what_it_speaks_for() -> None:
    current, new = _diagonal()
    rows = [*current, *new]

    assert hours_on(rows, MON) == {C.FRONT_OFFICE: 6, C.HOUSEKEEPING: 5}
    assert hours_on(rows, TUE) == {C.FRONT_OFFICE: 8, C.HOUSEKEEPING: 3}


def test_the_same_file_said_complete_takes_the_two_missing_cells_away() -> None:
    current, new = _diagonal()
    files = {new[0].labor_snapshot_id: _complete(new, first=MON, last=TUE, revision=2)}

    plan = current_rows([*current, *new], files)

    assert [(row.labor_category, row.hours) for row in plan[MON][1]] == [(C.FRONT_OFFICE, 6)]
    assert [(row.labor_category, row.hours) for row in plan[TUE][1]] == [(C.HOUSEKEEPING, 3)]


def test_a_zero_in_a_part_is_a_plan_of_zero_hours_not_a_removal() -> None:
    """A row of zero hours replaces its cell with a zero: the cell is still there, and counted."""
    current, _ = _diagonal()
    zero = file((MON, C.HOUSEKEEPING, 0), revision=2)

    counted = current_rows([*current, *zero])[MON][1]

    assert sorted((row.labor_category, row.hours) for row in counted) == [
        (C.FRONT_OFFICE, 8),
        (C.HOUSEKEEPING, 0),
    ]


def test_a_day_a_file_does_not_name_is_left_alone_even_for_a_category_it_names() -> None:
    first = file((MON, C.SPA_WELLNESS, 8), (TUE, C.SPA_WELLNESS, 8))
    second = file((MON, C.SPA_WELLNESS, 6), revision=2)

    assert hours_on([*first, *second], TUE) == {C.SPA_WELLNESS: 8}


def test_what_a_part_holds_elsewhere_in_the_file_does_not_reach_the_rows_asked_for() -> None:
    """Asked about Tuesday only, the second file holds Spa on Monday: nothing of Tuesday."""
    first = file((TUE, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8))
    second = file((MON, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 6), revision=2)
    only_tuesday = [row for row in [*first, *second] if row.work_date == TUE]
    named = frozenset({C.SPA_WELLNESS, C.FRONT_OFFICE})
    files = {
        first[0].labor_snapshot_id: FileCoverage(TODAY, 1, named, True, False),
        second[0].labor_snapshot_id: FileCoverage(TODAY, 2, named, True, False),
    }

    counted = current_rows(only_tuesday, files)[TUE][1]

    assert sorted((row.labor_category, row.hours) for row in counted) == [
        (C.FRONT_OFFICE, 6),
        (C.SPA_WELLNESS, 8),
    ]


def _complete(rows: list[Row], *, first: date, last: date, revision: int) -> FileCoverage:
    return FileCoverage(
        TODAY,
        revision,
        frozenset(row.labor_category for row in rows),
        True,
        False,
        complete_from=first,
        complete_to=last,
    )


def test_a_complete_file_speaks_for_every_category_of_its_days_named_or_not() -> None:
    older = file((MON, C.FRONT_OFFICE, 8), (MON, C.HOUSEKEEPING, 5))
    newer = file((MON, C.FRONT_OFFICE, 6), revision=2)
    files = {newer[0].labor_snapshot_id: _complete(newer, first=MON, last=MON, revision=2)}

    counted = current_rows([*older, *newer], files)[MON][1]

    assert [(row.labor_category, row.hours) for row in counted] == [(C.FRONT_OFFICE, 6)]


def test_without_that_word_the_same_file_leaves_the_other_department_alone() -> None:
    older = file((MON, C.FRONT_OFFICE, 8), (MON, C.HOUSEKEEPING, 5))
    newer = file((MON, C.FRONT_OFFICE, 6), revision=2)

    assert hours_on([*older, *newer], MON) == {C.FRONT_OFFICE: 6, C.HOUSEKEEPING: 5}


def test_a_complete_file_clears_a_day_of_its_period_it_has_no_row_for() -> None:
    older = file((MON, C.FRONT_OFFICE, 8), (TUE, C.FRONT_OFFICE, 8), (WED, C.FRONT_OFFICE, 8))
    newer = file((MON, C.FRONT_OFFICE, 6), (WED, C.FRONT_OFFICE, 6), revision=2)
    files = {newer[0].labor_snapshot_id: _complete(newer, first=MON, last=WED, revision=2)}

    plan = current_rows([*older, *newer], files)

    assert TUE not in plan
    assert {MON, WED} <= plan.keys()


def test_a_complete_file_with_no_row_among_those_read_still_speaks() -> None:
    """Reading Tuesday only, the file has no row there, and it is the file that says so."""
    older = file((TUE, C.FRONT_OFFICE, 8))
    newer_id = uuid4()
    files = {
        newer_id: FileCoverage(
            TODAY, 2, frozenset({C.FRONT_OFFICE}), True, False, complete_from=MON, complete_to=WED
        )
    }

    assert current_rows(older, files) == {}


def test_a_complete_file_says_nothing_outside_its_period() -> None:
    older = file((THU, C.FRONT_OFFICE, 8))
    newer = file((MON, C.FRONT_OFFICE, 6), revision=2)
    files = {newer[0].labor_snapshot_id: _complete(newer, first=MON, last=WED, revision=2)}

    assert THU in current_rows([*older, *newer], files)


@dataclass(frozen=True)
class Worked:
    """A row of a file of hours worked: there is no plan in it."""

    labor_snapshot_id: UUID
    snapshot_local_date: date
    revision: int
    work_date: date
    labor_category: C
    hours: int = 8

    @property
    def planned_minutes(self) -> None:
        return None

    @property
    def actual_minutes(self) -> int:
        return self.hours * 60


def test_hours_worked_do_not_take_the_place_of_the_plan() -> None:
    plan_rows = file((MON, C.FRONT_OFFICE, 8))
    worked = [Worked(uuid4(), TODAY, 2, MON, C.FRONT_OFFICE, 3)]
    rows: list[Row | Worked] = [*plan_rows, *worked]

    planned = current_rows(rows, basis=Basis.PLANNED)[MON]
    actual = current_rows(rows, basis=Basis.ACTUAL)[MON]

    assert planned[1] == plan_rows
    assert actual[1] == worked


def test_a_plan_does_not_take_the_place_of_the_hours_worked() -> None:
    worked = [Worked(uuid4(), TODAY, 1, MON, C.FRONT_OFFICE, 3)]
    plan_rows = file((MON, C.FRONT_OFFICE, 8), revision=2)
    rows: list[Row | Worked] = [*worked, *plan_rows]

    assert current_rows(rows, basis=Basis.PLANNED)[MON][1] == plan_rows
    assert current_rows(rows, basis=Basis.ACTUAL)[MON][1] == worked


def test_a_file_of_hours_worked_never_clears_the_plan() -> None:
    plan_rows = file((MON, C.FRONT_OFFICE, 8), (MON, C.HOUSEKEEPING, 5))
    worked = [Worked(uuid4(), TODAY, 2, MON, C.FRONT_OFFICE, 3)]

    rows: list[Row | Worked] = [*plan_rows, *worked]
    planned = current_rows(rows, basis=Basis.PLANNED)[MON][1]

    assert {row.labor_category for row in planned} == {C.FRONT_OFFICE, C.HOUSEKEEPING}


def test_rows_with_nothing_on_a_basis_are_what_is_known_when_nobody_says_more() -> None:
    """So whoever reads the plan sees a gap rather than a day with no staff."""
    worked = [Worked(uuid4(), TODAY, 1, MON, C.FRONT_OFFICE, 3)]

    assert current_rows(worked, basis=Basis.PLANNED)[MON][1] == worked


def test_going_back_to_an_earlier_version_is_simply_the_newest_file() -> None:
    first = file((MON, C.FRONT_OFFICE, 8))
    second = file((MON, C.FRONT_OFFICE, 6), revision=2)
    third = file((MON, C.FRONT_OFFICE, 8), revision=3)

    plan = current_rows([*first, *second, *third])

    assert plan[MON][0] == third[0].labor_snapshot_id
    assert hours_on([*first, *second, *third], MON) == {C.FRONT_OFFICE: 8}


def test_nothing_known_of_a_day_is_no_key_and_not_a_zero() -> None:
    assert current_rows(file((MON, C.FRONT_OFFICE))).keys() == {MON}
    assert current_rows([]) == {}


def test_the_rule_reads_rows_and_nothing_else() -> None:
    rows = file((MON, C.FRONT_OFFICE))

    assert current_rows(rows) == current_rows(rows)
    assert current_rows(tuple(rows)) == current_rows(rows)
