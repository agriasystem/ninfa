"""Historical comparable 30-day periods of REV_OTA_DEPENDENCY V1 (pure).

For a target as-of T, a historical as-of H is a CANDIDATE only when ALL of these hold (no data
looked at yet):

* H is strictly before T (H is always `T - 7*k`, k >= 1: never the target's own day, never the
  future);
* at most 730 days before T;
* the same weekday as T;
* seasonal distance from T (the Gate 4 algorithm, reused) at most 42 days.

A candidate becomes ELIGIBLE only when: all 30 lead-time-0 snapshots of its own 30-day window
exist, none has `uncertain_rooms > 0`, the independently reconstructed channel mix reconciles
EXACTLY with those snapshots' `rooms_on_books` day by day, its classification coverage is at
least 80%, and its classified room nights are at least 20. Every candidate that is not eligible
is COUNTED by the reason it was rejected, never silently dropped.

Observed-first (the Gate 4/5/7/8 philosophy, applied to periods): with at least 5
FULLY_OBSERVED_PERIOD (all 30 snapshots OBSERVED) periods, ONLY they are used; otherwise every
fully observed period is kept and the newest clean approximate periods complete the sample, up to
24, most recent first. Fewer than 5 total: the sample is insufficient.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.intelligence.distribution.channels import ChannelClassification
from app.modules.intelligence.distribution.metrics import reconstruct_channel_mix
from app.modules.intelligence.distribution.precision import CALCULATION_CONTEXT, percent_of
from app.modules.intelligence.distribution.temporal import StayRecord
from app.modules.intelligence.distribution.types import (
    FORWARD_STAY_WINDOW_DAYS,
    LOOKBACK_DAYS,
    MAX_COMPARABLES,
    MIN_CHANNEL_CLASSIFICATION_COVERAGE,
    MIN_CLASSIFIED_ROOM_NIGHTS,
    MIN_COMPARABLES,
    OBSERVED_DAY_SCORE,
    RECONSTRUCTED_DAY_SCORE,
    SEASONAL_WINDOW_DAYS,
    ComparablePeriodFact,
)
from app.modules.intelligence.expected.seasonality import (
    seasonal_distance_days as seasonal_distance_days,
)
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import SnapshotHistoryRow

_THIRTY = Decimal(FORWARD_STAY_WINDOW_DAYS)


@dataclass(frozen=True, slots=True)
class ComparableSelection:
    periods: tuple[ComparablePeriodFact, ...]  # most recent first, at most max_comparables
    fully_observed_count: int
    approximate_count: int
    candidate_period_count: int
    rejected_snapshot_incomplete_count: int
    rejected_snapshot_uncertain_count: int
    rejected_reconciliation_count: int
    rejected_low_classification_count: int
    rejected_low_volume_count: int

    @property
    def sample_count(self) -> int:
        return len(self.periods)


def candidate_as_of_dates(
    target_as_of_date: date,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS,
) -> list[date]:
    """Historical as-of dates that may be compared with the target, most recent first.

    `back` only ever lands on the target's own weekday when it is a multiple of 7 (no data
    looked at), and the loop bound alone already enforces the horizon (`back <= lookback_days`).
    The season window is `seasonal_distance_days` (Gate 4's own function - the exact distance,
    not the module's own hardcoded-42-day `within_seasonal_window` convenience wrapper, since
    THIS caller's window is itself a parameter, never a constant).
    """
    candidates: list[date] = []
    for back in range(7, lookback_days + 1, 7):
        day = target_as_of_date - timedelta(days=back)
        if seasonal_distance_days(day, target_as_of_date) > seasonal_window_days:
            continue
        candidates.append(day)
    return candidates


def _provenance_score(observed_days: int, reconstructed_days: int) -> Decimal:
    """`(observed_days * 100 + reconstructed_days * 60) / 30` (Part "COMPARABLE PROVENANCE")."""
    weighted = CALCULATION_CONTEXT.add(
        CALCULATION_CONTEXT.multiply(Decimal(observed_days), OBSERVED_DAY_SCORE),
        CALCULATION_CONTEXT.multiply(Decimal(reconstructed_days), RECONSTRUCTED_DAY_SCORE),
    )
    return CALCULATION_CONTEXT.divide(weighted, _THIRTY)


def select_comparable_periods(
    target_as_of_date: date,
    *,
    snapshot_rows_of: Callable[[date], list[SnapshotHistoryRow] | None],
    stays: Sequence[tuple[StayRecord, UUID]],
    classifications: Mapping[UUID, ChannelClassification],
    timezone: ZoneInfo,
    min_comparables: int = MIN_COMPARABLES,
    max_comparables: int = MAX_COMPARABLES,
    lookback_days: int = LOOKBACK_DAYS,
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS,
    forward_window_days: int = FORWARD_STAY_WINDOW_DAYS,
    min_coverage: Decimal = MIN_CHANNEL_CLASSIFICATION_COVERAGE,
    min_volume: int = MIN_CLASSIFIED_ROOM_NIGHTS,
) -> ComparableSelection:
    candidates = candidate_as_of_dates(
        target_as_of_date, lookback_days=lookback_days, seasonal_window_days=seasonal_window_days
    )
    eligible: list[ComparablePeriodFact] = []
    incomplete = uncertain = reconciliation_failed = low_classification = low_volume = 0

    for as_of in candidates:
        window_start = as_of
        window_end = as_of + timedelta(days=forward_window_days - 1)
        rows = snapshot_rows_of(as_of)
        if rows is None or len(rows) != forward_window_days:
            incomplete += 1
            continue
        if any(row.uncertain_rooms > 0 for row in rows):
            uncertain += 1
            continue

        cutoff = end_of_local_day(as_of, timezone)
        mix = reconstruct_channel_mix(
            stays,
            classifications,
            as_of_local_date=as_of,
            cutoff=cutoff,
            window_start=window_start,
            window_end=window_end,
        )
        reconciled = all(mix.rooms_on_books(row.stay_date) == row.rooms_on_books for row in rows)
        if not reconciled:
            reconciliation_failed += 1
            continue

        certain = (
            mix.ota_room_nights
            + mix.direct_room_nights
            + mix.other_room_nights
            + mix.unknown_room_nights
        )
        classified = mix.ota_room_nights + mix.direct_room_nights
        if certain > 0:
            coverage = percent_of(Decimal(classified), Decimal(certain))
            if coverage < min_coverage:
                low_classification += 1
                continue
        else:
            coverage = Decimal(0)
        if classified < min_volume:
            low_volume += 1
            continue

        observed_days = sum(1 for row in rows if row.origin == SnapshotOrigin.OBSERVED)
        reconstructed_days = forward_window_days - observed_days
        eligible.append(
            ComparablePeriodFact(
                as_of_local_date=as_of,
                window_start=window_start,
                window_end=window_end,
                observed_day_count=observed_days,
                reconstructed_day_count=reconstructed_days,
                snapshot_provenance_score_exact=_provenance_score(
                    observed_days, reconstructed_days
                ),
                ota_room_nights=mix.ota_room_nights,
                direct_room_nights=mix.direct_room_nights,
                other_room_nights=mix.other_room_nights,
                unknown_room_nights=mix.unknown_room_nights,
                classification_coverage_pct_exact=coverage,
                ota_share_exact=percent_of(Decimal(mix.ota_room_nights), Decimal(classified)),
            )
        )

    fully_observed = [period for period in eligible if period.is_fully_observed]
    if len(fully_observed) >= min_comparables:
        used = fully_observed[:max_comparables]
    else:
        approximate = [period for period in eligible if not period.is_fully_observed]
        room = max(0, max_comparables - len(fully_observed))
        used = sorted(
            [*fully_observed, *approximate[:room]],
            key=lambda period: period.as_of_local_date,
            reverse=True,
        )
    used_observed = sum(1 for period in used if period.is_fully_observed)
    return ComparableSelection(
        periods=tuple(used),
        fully_observed_count=used_observed,
        approximate_count=len(used) - used_observed,
        candidate_period_count=len(candidates),
        rejected_snapshot_incomplete_count=incomplete,
        rejected_snapshot_uncertain_count=uncertain,
        rejected_reconciliation_count=reconciliation_failed,
        rejected_low_classification_count=low_classification,
        rejected_low_volume_count=low_volume,
    )
