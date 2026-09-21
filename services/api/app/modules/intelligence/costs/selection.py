"""Historical comparable months of Cost CPOR V1 (pure).

For a target month T, a month M is a CANDIDATE comparable only when ALL of these hold:

* M is strictly before T (`M.period_end < T.period_start`: no datum of the target or the future
  can enter the baseline), and at most 36 months before it (a month exactly 36 months back is
  included);
* the circular distance between the months of the year is at most 2 (a July target compares with
  May..September; January and December are 1 apart);
* the same cost category and the same currency (the metric is built for them).

A candidate becomes ELIGIBLE only when its metric is READY (cost lines of the category, a complete
occupancy denominator, occupied room nights > 0, classification coverage >= 70 %). Every candidate
that is not READY is COUNTED by the reason it was rejected, never silently dropped.

Observed-first (the Gate 4 / Gate 5 philosophy): a FULLY_OBSERVED_PERIOD is an eligible month with
no reconstructed day. With at least 5 of them, ONLY they are used; otherwise every fully observed
month is kept and the newest reconstructed (clean) months complete the sample. At most 12 months,
most recent first. With fewer than 5 the sample is insufficient and no baseline is produced.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.intelligence.costs.periods import CalendarMonth, circular_month_distance
from app.modules.intelligence.costs.types import (
    LOOKBACK_MONTHS,
    MAX_COMPARABLES,
    MIN_COMPARABLES,
    SEASON_WINDOW_MONTHS,
    CostPeriodMetric,
    MetricStatus,
)


@dataclass(frozen=True, slots=True)
class ComparableSelection:
    periods: tuple[CostPeriodMetric, ...]  # most recent first, at most MAX_COMPARABLES
    observed_period_count: int  # fully observed months among the used ones
    approximate_period_count: int  # used months with at least one reconstructed day
    candidate_month_count: int
    eligible_month_count: int
    rejected_no_cost_data_count: int
    rejected_low_classification_count: int
    rejected_incomplete_occupancy_count: int
    rejected_zero_occupancy_count: int

    @property
    def sample_count(self) -> int:
        return len(self.periods)

    @property
    def sufficient(self) -> bool:
        return self.sample_count >= MIN_COMPARABLES


def candidate_months(
    target: CalendarMonth,
    *,
    lookback_months: int = LOOKBACK_MONTHS,
    season_window_months: int = SEASON_WINDOW_MONTHS,
) -> list[CalendarMonth]:
    """The months that may be compared with `target`, most recent first (no data looked at)."""
    months: list[CalendarMonth] = []
    for back in range(1, lookback_months + 1):
        month = target.shifted(-back)
        if circular_month_distance(month.month, target.month) > season_window_months:
            continue
        if not month.end < target.start:  # anti-leakage, stated once more: never the target
            raise ValueError("a comparable must end before the target starts")
        months.append(month)
    return months


def select_comparables(
    target: CalendarMonth,
    metric_of: Callable[[CalendarMonth], CostPeriodMetric],
    *,
    min_comparables: int = MIN_COMPARABLES,
    max_comparables: int = MAX_COMPARABLES,
    lookback_months: int = LOOKBACK_MONTHS,
    season_window_months: int = SEASON_WINDOW_MONTHS,
) -> ComparableSelection:
    candidates = candidate_months(
        target, lookback_months=lookback_months, season_window_months=season_window_months
    )
    eligible: list[CostPeriodMetric] = []
    no_cost = low_classification = incomplete = zero_occupancy = 0
    for month in candidates:
        metric = metric_of(month)
        if metric.status == MetricStatus.READY:
            eligible.append(metric)
        elif metric.status == MetricStatus.NO_COST_DATA:
            no_cost += 1
        elif metric.status == MetricStatus.LOW_CLASSIFICATION_COVERAGE:
            low_classification += 1
        elif metric.status == MetricStatus.INCOMPLETE:
            incomplete += 1
        elif metric.status == MetricStatus.ZERO_OCCUPANCY:
            zero_occupancy += 1

    observed = [m for m in eligible if m.is_fully_observed]  # already most recent first
    if len(observed) >= min_comparables:
        used = observed[:max_comparables]
    else:
        # every observed month stays; the newest clean reconstructions complete the sample
        approximate = [m for m in eligible if not m.is_fully_observed]
        room = max(0, max_comparables - len(observed))
        used = sorted([*observed, *approximate[:room]], key=lambda m: m.period_start, reverse=True)
    used_observed = sum(1 for m in used if m.is_fully_observed)
    return ComparableSelection(
        periods=tuple(used),
        observed_period_count=used_observed,
        approximate_period_count=len(used) - used_observed,
        candidate_month_count=len(candidates),
        eligible_month_count=len(eligible),
        rejected_no_cost_data_count=no_cost,
        rejected_low_classification_count=low_classification,
        rejected_incomplete_occupancy_count=incomplete,
        rejected_zero_occupancy_count=zero_occupancy,
    )
