"""`labor.current_plan.current_rows`: what counts of a labor source, as a table of cases (pure)."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from app.modules.labor.current_plan import current_rows
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


def test_a_correction_that_drops_a_department_on_one_day_empties_that_cell() -> None:
    """The file names Spa (on Monday) and names Tuesday (for Reception): Tuesday has no Spa."""
    first = file((MON, C.SPA_WELLNESS, 8), (TUE, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8))
    second = file((MON, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8), revision=2)

    assert hours_on([*first, *second], TUE) == {C.FRONT_OFFICE: 8}


def test_a_day_a_file_does_not_name_is_left_alone_even_for_a_category_it_names() -> None:
    first = file((MON, C.SPA_WELLNESS, 8), (TUE, C.SPA_WELLNESS, 8))
    second = file((MON, C.SPA_WELLNESS, 6), revision=2)

    assert hours_on([*first, *second], TUE) == {C.SPA_WELLNESS: 8}


def test_what_a_file_names_is_read_from_the_whole_file_not_from_the_rows_asked_for() -> None:
    """Asked about Tuesday only, the second file still speaks for Spa, which it names on Monday."""
    first = file((TUE, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8))
    second = file((MON, C.SPA_WELLNESS, 8), (TUE, C.FRONT_OFFICE, 8), revision=2)
    only_tuesday = [row for row in [*first, *second] if row.work_date == TUE]
    categories_of = {
        first[0].labor_snapshot_id: {C.SPA_WELLNESS, C.FRONT_OFFICE},
        second[0].labor_snapshot_id: {C.SPA_WELLNESS, C.FRONT_OFFICE},
    }

    counted = current_rows(only_tuesday, categories_of)[TUE][1]

    assert [(row.labor_category, row.hours) for row in counted] == [(C.FRONT_OFFICE, 8)]


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
