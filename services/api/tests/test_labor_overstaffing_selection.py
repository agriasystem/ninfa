"""Pure unit tests of LABOR_OVERSTAFFING's historical comparable-day selection (Gate 8, Part D/E).

No database: `select_comparables` takes plain callables, so every rule (date filtering, demand
similarity, actual-first, observed-first) is tested directly against exact Decimal/date values.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.intelligence.expected.seasonality import seasonal_distance_days
from app.modules.intelligence.labor.aggregation import LaborEntryRow
from app.modules.intelligence.labor.selection import (
    ComparableSelection,
    OccupancyLeadZeroRow,
    candidate_work_dates,
    demand_tolerance,
    select_comparables,
)
from app.modules.intelligence.labor.types import SEASONAL_WINDOW_DAYS, LaborBasis
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.models import SnapshotOrigin

TARGET_WORK_DATE = date(2026, 8, 15)  # a Saturday
TARGET_AS_OF_DATE = date(2026, 8, 14)  # lead_time = 1


def _entry(
    category: LaborCategory,
    *,
    planned: int | None = None,
    actual: int | None = None,
    confidence: str = "80.00",
    snapshot_id: UUID | None = None,
) -> LaborEntryRow:
    return LaborEntryRow(
        labor_snapshot_id=snapshot_id or uuid4(),
        labor_category=category,
        planned_minutes=planned,
        actual_minutes=actual,
        planned_cost=None,
        actual_cost=None,
        currency=None,
        classification_confidence=Decimal(confidence),
    )


# --- candidate_work_dates ----------------------------------------------------------------------


def test_reuses_the_gate_4_seasonal_distance_function_not_a_third_implementation() -> None:
    from app.modules.intelligence.labor import selection as selection_module

    assert selection_module.seasonal_distance_days is seasonal_distance_days


def test_every_candidate_shares_the_targets_weekday() -> None:
    candidates = candidate_work_dates(TARGET_WORK_DATE, TARGET_AS_OF_DATE)
    assert candidates
    assert all(day.weekday() == TARGET_WORK_DATE.weekday() for day in candidates)


def test_no_candidate_is_on_or_after_the_as_of_date_or_the_target_work_date() -> None:
    candidates = candidate_work_dates(TARGET_WORK_DATE, TARGET_AS_OF_DATE)
    assert all(day < TARGET_AS_OF_DATE for day in candidates)
    assert all(day < TARGET_WORK_DATE for day in candidates)


def test_seasonal_window_of_42_days_is_included_43_would_be_excluded() -> None:
    candidates = candidate_work_dates(TARGET_WORK_DATE, TARGET_AS_OF_DATE)
    day_42 = TARGET_WORK_DATE - timedelta(days=42)
    assert seasonal_distance_days(day_42, TARGET_WORK_DATE) == 42
    assert day_42 in candidates
    # 49 days back (7 more weeks) has seasonal distance 49 > 42: excluded.
    day_49 = TARGET_WORK_DATE - timedelta(days=49)
    assert day_49 not in candidates


def test_a_narrower_seasonal_window_excludes_more() -> None:
    wide = candidate_work_dates(TARGET_WORK_DATE, TARGET_AS_OF_DATE, seasonal_window_days=42)
    narrow = candidate_work_dates(TARGET_WORK_DATE, TARGET_AS_OF_DATE, seasonal_window_days=7)
    assert len(narrow) < len(wide)
    assert set(narrow) <= set(wide)


def test_the_730_day_lookback_boundary_is_included_and_737_excluded() -> None:
    # 730 is not itself a multiple of 7; the last reachable multiple of 7 at or under it is 728.
    at_728 = candidate_work_dates(
        TARGET_WORK_DATE, TARGET_AS_OF_DATE, lookback_days=728, seasonal_window_days=730
    )
    at_727 = candidate_work_dates(
        TARGET_WORK_DATE, TARGET_AS_OF_DATE, lookback_days=727, seasonal_window_days=730
    )
    assert (TARGET_WORK_DATE - timedelta(days=728)) in at_728
    assert (TARGET_WORK_DATE - timedelta(days=728)) not in at_727


def test_leap_year_boundary_is_handled_by_the_reused_algorithm() -> None:
    # Reused from Gate 4: itself leap-year safe and already tested there. A smoke check that
    # calling it near a leap day does not raise and gives a sane (small) distance.
    leap_target = date(2028, 3, 1)  # 2028 is a leap year
    candidates = candidate_work_dates(leap_target, date(2028, 2, 28))
    assert all(seasonal_distance_days(day, leap_target) <= 42 for day in candidates)


# --- demand_tolerance ----------------------------------------------------------------------------


def test_demand_tolerance_is_at_least_3_rooms() -> None:
    assert demand_tolerance(Decimal(5)) == Decimal(3)


def test_demand_tolerance_is_20_percent_for_high_demand() -> None:
    assert demand_tolerance(Decimal(30)) == Decimal(6)
    assert demand_tolerance(Decimal(100)) == Decimal(20)


# --- select_comparables: building blocks ---------------------------------------------------------


def _select(
    target_work_date: date,
    target_as_of_date: date,
    target_forecast_rooms: Decimal,
    target_category: LaborCategory,
    *,
    occupancy_of: Callable[[date], OccupancyLeadZeroRow | None],
    labor_of: Callable[[date], tuple[UUID, list[LaborEntryRow]] | None],
    lookback_days: int = 45,
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS,
) -> ComparableSelection:
    """`select_comparables` constrained to ONE seasonal cluster: with the default 730-day
    lookback and 42-day window, dates near the one- and two-year anniversaries of the target
    also qualify (the window is circular, year-independent), which the `_make_world`-based
    tests below do not populate. Fixing `lookback_days` just above the window keeps the
    candidate universe to exactly the single recent cluster these tests build."""
    return select_comparables(
        target_work_date,
        target_as_of_date,
        target_forecast_rooms,
        target_category,
        occupancy_of=occupancy_of,
        labor_of=labor_of,
        lookback_days=lookback_days,
        seasonal_window_days=seasonal_window_days,
    )


_Occupancy = dict[date, OccupancyLeadZeroRow]
_Labor = dict[date, tuple[UUID, list[LaborEntryRow]]]


def _make_world(n: int, *, rooms: int = 30) -> tuple[list[date], _Occupancy, _Labor]:
    days = [TARGET_WORK_DATE - timedelta(weeks=k) for k in range(1, n + 1)]
    occupancy: _Occupancy = {
        day: OccupancyLeadZeroRow(
            uuid4(), rooms_on_books=rooms, uncertain_rooms=0, origin=SnapshotOrigin.OBSERVED
        )
        for day in days
    }
    labor: _Labor = {
        day: (uuid4(), [_entry(LaborCategory.HOUSEKEEPING, actual=24 * 60)]) for day in days
    }
    return days, occupancy, labor


def test_five_fully_observed_days_are_sufficient_and_all_used() -> None:
    days, occupancy, labor = _make_world(5)
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 5
    assert selection.fully_observed_count == 5
    assert selection.approximate_count == 0


def test_missing_occupancy_is_rejected_and_counted() -> None:
    days, occupancy, labor = _make_world(6)
    del occupancy[days[0]]
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 5
    assert selection.rejected_occupancy_incomplete_count == 1


def test_uncertain_occupancy_is_rejected_and_counted() -> None:
    days, occupancy, labor = _make_world(6)
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(), rooms_on_books=30, uncertain_rooms=2, origin=SnapshotOrigin.OBSERVED
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 5
    assert selection.rejected_occupancy_incomplete_count == 1


def test_demand_outside_tolerance_is_rejected() -> None:
    days, occupancy, labor = _make_world(6, rooms=30)
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(), rooms_on_books=50, uncertain_rooms=0, origin=SnapshotOrigin.OBSERVED
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.rejected_demand_mismatch_count == 1


def test_demand_within_tolerance_boundary_is_included() -> None:
    days, occupancy, labor = _make_world(5, rooms=30)
    # tolerance = max(3, 20%*30) = 6; 36 is exactly at the boundary.
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(), rooms_on_books=36, uncertain_rooms=0, origin=SnapshotOrigin.OBSERVED
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 5
    assert selection.rejected_demand_mismatch_count == 0


def test_demand_just_beyond_tolerance_is_excluded() -> None:
    days, occupancy, labor = _make_world(5, rooms=30)
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(), rooms_on_books=37, uncertain_rooms=0, origin=SnapshotOrigin.OBSERVED
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.rejected_demand_mismatch_count == 1


def test_missing_labor_snapshot_is_rejected_and_counted() -> None:
    days, occupancy, labor = _make_world(6)
    del labor[days[0]]
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.rejected_labor_missing_count == 1


def test_full_actual_data_uses_actual_basis() -> None:
    days, occupancy, labor = _make_world(5)
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert all(day.labor_basis is LaborBasis.ACTUAL for day in selection.days)


def test_actual_is_preferred_over_planned_when_both_are_complete() -> None:
    days, occupancy, labor = _make_world(5)
    snap_id = uuid4()
    labor[days[0]] = (
        snap_id,
        [_entry(LaborCategory.HOUSEKEEPING, planned=480, actual=24 * 60, snapshot_id=snap_id)],
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    used = next(day for day in selection.days if day.work_date == days[0])
    assert used.labor_basis is LaborBasis.ACTUAL


def test_partial_actual_falls_back_to_complete_planned() -> None:
    days, occupancy, labor = _make_world(5)
    snap_id = uuid4()
    labor[days[0]] = (
        snap_id,
        [
            _entry(LaborCategory.HOUSEKEEPING, planned=480, actual=None, snapshot_id=snap_id),
            _entry(LaborCategory.HOUSEKEEPING, planned=60, actual=60, snapshot_id=snap_id),
        ],
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    used = next(day for day in selection.days if day.work_date == days[0])
    assert used.labor_basis is LaborBasis.PLANNED_FALLBACK
    assert used.historical_hours_exact == Decimal(9)  # (480+60)/60


def test_partial_actual_and_incomplete_planned_is_rejected() -> None:
    days, occupancy, labor = _make_world(6)
    snap_id = uuid4()
    labor[days[0]] = (
        snap_id,
        [
            _entry(LaborCategory.HOUSEKEEPING, planned=None, actual=60, snapshot_id=snap_id),
            _entry(LaborCategory.HOUSEKEEPING, planned=60, actual=None, snapshot_id=snap_id),
        ],
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.rejected_labor_incomplete_count == 1
    assert days[0] not in {day.work_date for day in selection.days}


def test_low_classification_coverage_on_the_chosen_basis_is_rejected() -> None:
    days, occupancy, labor = _make_world(6)
    snap_id = uuid4()
    # 1 classified minute out of 100: coverage 1% < 70%.
    labor[days[0]] = (
        snap_id,
        [
            _entry(LaborCategory.HOUSEKEEPING, actual=1, snapshot_id=snap_id),
            _entry(LaborCategory.OTHER, actual=99, snapshot_id=snap_id),
        ],
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.rejected_low_classification_count == 1


def test_reconstructed_occupancy_is_used_but_not_fully_observed() -> None:
    days, occupancy, labor = _make_world(5)
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(),
        rooms_on_books=30,
        uncertain_rooms=0,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    used = next(day for day in selection.days if day.work_date == days[0])
    assert used.is_fully_observed is False
    assert used in selection.days  # still entered the sample


def test_with_5_or_more_fully_observed_days_only_they_are_used() -> None:
    days, occupancy, labor = _make_world(7)
    # Add 2 approximate (reconstructed) days beyond the 5 fully-observed ones.
    for day in days[5:]:
        occupancy[day] = OccupancyLeadZeroRow(
            uuid4(),
            rooms_on_books=30,
            uncertain_rooms=0,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 5
    assert selection.approximate_count == 0
    assert selection.fully_observed_count == 5


def test_fewer_than_5_fully_observed_fills_with_approximate() -> None:
    days, occupancy, labor = _make_world(6)
    for day in days[3:]:  # only 3 fully observed, 3 approximate
        occupancy[day] = OccupancyLeadZeroRow(
            uuid4(),
            rooms_on_books=30,
            uncertain_rooms=0,
            origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.fully_observed_count == 3
    assert selection.approximate_count == 3
    assert selection.sample_count == 6


def test_fewer_than_5_total_comparables_is_reported_as_such() -> None:
    days, occupancy, labor = _make_world(3)
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert selection.sample_count == 3  # the caller (detector) decides INSUFFICIENT_DATA


def test_the_sample_never_exceeds_24() -> None:
    days, occupancy, labor = _make_world(30)
    selection = select_comparables(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
        lookback_days=730,
        seasonal_window_days=210,
    )
    assert selection.sample_count <= 24


def test_the_sample_is_ordered_most_recent_first() -> None:
    days, occupancy, labor = _make_world(6)
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    ordered = [day.work_date for day in selection.days]
    assert ordered == sorted(ordered, reverse=True)


def test_no_uncertain_occupancy_pair_ever_enters_the_sample() -> None:
    days, occupancy, labor = _make_world(6)
    occupancy[days[0]] = OccupancyLeadZeroRow(
        uuid4(), rooms_on_books=30, uncertain_rooms=1, origin=SnapshotOrigin.OBSERVED
    )
    selection = _select(
        TARGET_WORK_DATE,
        TARGET_AS_OF_DATE,
        Decimal(30),
        LaborCategory.HOUSEKEEPING,
        occupancy_of=occupancy.get,
        labor_of=labor.get,
    )
    assert days[0] not in {day.work_date for day in selection.days}
