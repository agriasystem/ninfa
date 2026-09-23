"""Historical staffing comparable days of LABOR_OVERSTAFFING V1 (pure).

For a target work date T (as-of date S = the target booking snapshot's own snapshot_local_date), a
day H is a CANDIDATE comparable only when ALL of these hold (no data looked at yet):

* H is strictly before S AND strictly before T (anti-leakage: never the target's own day, never
  the future, whatever the lead time);
* at most 730 days before T;
* the same weekday as T;
* seasonal distance from T (the Gate 4 algorithm, reused) at most 42 days.

A candidate becomes ELIGIBLE only when: a clean lead-time-0 booking snapshot exists for H
(`uncertain_rooms > 0` rejects it), its occupied rooms are within tolerance of the target's
forecast rooms, a labor snapshot covers H, the target category's ACTUAL-FIRST basis is complete
on H, and the day's classification coverage (same basis) is at least 70%. Every candidate that is
not eligible is COUNTED by the reason it was rejected, never silently dropped.

Observed-first (the Gate 4/5/7 philosophy, applied to days): with at least 5
FULLY_OBSERVED_COMPARABLE (ACTUAL labor + OBSERVED occupancy) days, ONLY they are used; otherwise
every fully observed day is kept and the newest clean approximate days complete the sample, up to
24, most recent first. Fewer than 5 total: the sample is insufficient.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from app.modules.intelligence.expected.seasonality import (
    seasonal_distance_days as seasonal_distance_days,
)
from app.modules.intelligence.labor.aggregation import LaborEntryRow, build_historical_day
from app.modules.intelligence.labor.types import (
    DEMAND_TOLERANCE_MIN_ROOMS,
    DEMAND_TOLERANCE_PERCENT,
    LOOKBACK_DAYS,
    MAX_COMPARABLES,
    MIN_COMPARABLES,
    SEASONAL_WINDOW_DAYS,
    ComparableDayFact,
)
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.models import SnapshotOrigin

_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class OccupancyLeadZeroRow:
    """The lead-time-0 booking snapshot of ONE historical stay night."""

    booking_snapshot_id: UUID
    rooms_on_books: int
    uncertain_rooms: int
    origin: SnapshotOrigin


@dataclass(frozen=True, slots=True)
class ComparableSelection:
    days: tuple[ComparableDayFact, ...]  # most recent first, at most max_comparables
    fully_observed_count: int
    approximate_count: int
    candidate_day_count: int
    rejected_occupancy_incomplete_count: int
    rejected_demand_mismatch_count: int
    rejected_labor_missing_count: int
    rejected_labor_incomplete_count: int
    rejected_low_classification_count: int

    @property
    def sample_count(self) -> int:
        return len(self.days)


def candidate_work_dates(
    target_work_date: date,
    target_as_of_date: date,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS,
) -> list[date]:
    """The work dates that may be compared with the target, most recent first (no data looked
    at). `back` only ever lands on the target's own weekday when it is a multiple of 7."""
    candidates: list[date] = []
    for back in range(7, lookback_days + 1, 7):
        day = target_work_date - timedelta(days=back)
        if not (day < target_as_of_date and day < target_work_date):
            continue  # anti-leakage, stated once more: never the target's own day or the future
        if seasonal_distance_days(day, target_work_date) > seasonal_window_days:
            continue
        candidates.append(day)
    return candidates


def demand_tolerance(target_forecast_rooms: Decimal) -> Decimal:
    """`max(3, 20% * max(target forecast rooms, 1))`, exact Decimal."""
    return max(
        DEMAND_TOLERANCE_MIN_ROOMS,
        DEMAND_TOLERANCE_PERCENT * max(target_forecast_rooms, _ONE),
    )


def select_comparables(
    target_work_date: date,
    target_as_of_date: date,
    target_forecast_rooms: Decimal,
    target_category: LaborCategory,
    *,
    occupancy_of: Callable[[date], OccupancyLeadZeroRow | None],
    labor_of: Callable[[date], tuple[UUID, list[LaborEntryRow]] | None],
    min_comparables: int = MIN_COMPARABLES,
    max_comparables: int = MAX_COMPARABLES,
    lookback_days: int = LOOKBACK_DAYS,
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS,
) -> ComparableSelection:
    candidates = candidate_work_dates(
        target_work_date,
        target_as_of_date,
        lookback_days=lookback_days,
        seasonal_window_days=seasonal_window_days,
    )
    tolerance = demand_tolerance(target_forecast_rooms)
    eligible: list[ComparableDayFact] = []
    occupancy_incomplete = 0
    demand_mismatch = labor_missing = labor_incomplete = low_classification = 0

    for day in candidates:
        occupancy = occupancy_of(day)
        if occupancy is None or occupancy.uncertain_rooms > 0:
            occupancy_incomplete += 1
            continue
        delta = abs(Decimal(occupancy.rooms_on_books) - target_forecast_rooms)
        if delta > tolerance:
            demand_mismatch += 1
            continue
        labor = labor_of(day)
        if labor is None:
            labor_missing += 1
            continue
        labor_snapshot_id, day_rows = labor
        historical = build_historical_day(day_rows, target_category)
        if historical is None:
            # Either the ACTUAL-FIRST basis was incomplete, or the day's classification
            # coverage on that basis is undefined (nothing to classify): both mean the day's
            # labor data cannot support this comparison.
            labor_incomplete += 1
            continue
        coverage = historical.quality.coverage_pct_exact
        assert coverage is not None  # build_historical_day never returns an undefined coverage
        if coverage < 70:
            low_classification += 1
            continue
        eligible.append(
            ComparableDayFact(
                work_date=day,
                historical_occupied_rooms=occupancy.rooms_on_books,
                occupancy_origin=occupancy.origin,
                booking_snapshot_id=occupancy.booking_snapshot_id,
                labor_basis=historical.basis,
                labor_snapshot_id=labor_snapshot_id,
                historical_hours_exact=historical.category_hours_exact,
                classification_coverage_pct_exact=coverage,
                weighted_category_confidence_exact=historical.quality.weighted_confidence_exact,
                category_cost_exact=historical.category_cost_exact,
                cost_currency=historical.cost_currency,
            )
        )

    fully_observed = [day for day in eligible if day.is_fully_observed]
    if len(fully_observed) >= min_comparables:
        used = fully_observed[:max_comparables]
    else:
        approximate = [day for day in eligible if not day.is_fully_observed]
        room = max(0, max_comparables - len(fully_observed))
        used = sorted(
            [*fully_observed, *approximate[:room]], key=lambda d: d.work_date, reverse=True
        )
    used_observed = sum(1 for day in used if day.is_fully_observed)
    return ComparableSelection(
        days=tuple(used),
        fully_observed_count=used_observed,
        approximate_count=len(used) - used_observed,
        candidate_day_count=len(candidates),
        rejected_occupancy_incomplete_count=occupancy_incomplete,
        rejected_demand_mismatch_count=demand_mismatch,
        rejected_labor_missing_count=labor_missing,
        rejected_labor_incomplete_count=labor_incomplete,
        rejected_low_classification_count=low_classification,
    )
