"""Parts J/K/L: historical comparable selection, quality gates, observed-first sampling.

Pure: `select_comparable_periods` and `candidate_as_of_dates` take plain data, never a database.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.modules.bookings.models import BookingStatus
from app.modules.intelligence.distribution.selection import (
    ComparableSelection,
    candidate_as_of_dates,
    select_comparable_periods,
)
from app.modules.intelligence.distribution.temporal import StayRecord
from app.modules.intelligence.distribution.types import (
    ChannelClassification,
    ChannelClassificationMethod,
    ChannelGroup,
)
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import SnapshotHistoryRow

TZ = ZoneInfo("Europe/Rome")
TARGET = date(2026, 9, 5)  # a Saturday
LONG_AGO = datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))

OTA_ID = uuid4()
DIRECT_ID = uuid4()
_RULE = ChannelClassificationMethod.DETERMINISTIC_RULE
CLASSIFICATIONS = {
    OTA_ID: ChannelClassification(OTA_ID, ChannelGroup.OTA, _RULE, Decimal(95), "ota"),
    DIRECT_ID: ChannelClassification(DIRECT_ID, ChannelGroup.DIRECT, _RULE, Decimal(95), "direct"),
}


# --- J: candidate as-of dates (pure calendar arithmetic) ----------------------------------------


def test_candidates_are_only_historical_never_the_target_or_the_future() -> None:
    candidates = candidate_as_of_dates(TARGET)
    assert all(candidate < TARGET for candidate in candidates)


def test_horizon_boundary_is_included_at_the_last_whole_week_within_730_days() -> None:
    """Candidates only ever land on multiples of 7 days back: 728 (=7*104) is the last one at
    or under the 730-day horizon. A wide season window isolates the horizon check itself."""
    within = TARGET - timedelta(days=728)
    candidates = candidate_as_of_dates(TARGET, seasonal_window_days=183)
    assert within in candidates
    assert all((TARGET - candidate).days <= 730 for candidate in candidates)


def test_horizon_boundary_excludes_the_next_whole_week_beyond_730_days() -> None:
    """735 (=7*105) is the next multiple of 7 back, one week past the 730-day horizon."""
    beyond = TARGET - timedelta(days=735)
    candidates = candidate_as_of_dates(TARGET, seasonal_window_days=183)
    assert beyond not in candidates


def test_every_candidate_shares_the_targets_weekday() -> None:
    for candidate in candidate_as_of_dates(TARGET):
        assert candidate.weekday() == TARGET.weekday()


def test_seasonal_window_of_exactly_42_days_is_included_43_is_excluded() -> None:
    """The literal day-distance boundary, on the pure calendar function itself."""
    from app.modules.intelligence.expected.seasonality import within_seasonal_window

    at_42 = TARGET - timedelta(days=42)
    at_43 = TARGET - timedelta(days=43)
    assert within_seasonal_window(at_42, TARGET) is True
    assert within_seasonal_window(at_43, TARGET) is False


def test_the_weekly_stepped_candidate_list_respects_the_same_42_day_window() -> None:
    # 42 days back is week 6 (7*6=42): within the window boundary (<=42).
    week6 = TARGET - timedelta(weeks=6)
    assert week6 in candidate_as_of_dates(TARGET)
    # week 7 (49 days back) exceeds the 42-day season window: excluded.
    week7 = TARGET - timedelta(weeks=7)
    assert week7 not in candidate_as_of_dates(TARGET)


def test_a_narrower_seasonal_window_excludes_more() -> None:
    default = candidate_as_of_dates(TARGET, lookback_days=45)
    narrow = candidate_as_of_dates(TARGET, lookback_days=45, seasonal_window_days=7)
    assert len(narrow) < len(default)
    assert set(narrow) <= set(default)


def test_reuses_gate_4s_own_seasonal_distance_helper() -> None:
    from app.modules.intelligence.distribution.selection import (
        seasonal_distance_days as reexported,
    )
    from app.modules.intelligence.expected.seasonality import seasonal_distance_days

    assert reexported is seasonal_distance_days


def test_leap_year_boundary_is_handled_by_the_reused_algorithm() -> None:
    """29 February as the target: the reused helper (already tested in Gate 4/8) must not
    crash and must still only admit same-weekday, in-season candidates."""
    leap_target = date(2028, 2, 29)  # 2028 is a leap year
    candidates = candidate_as_of_dates(leap_target)
    assert all(c.weekday() == leap_target.weekday() for c in candidates)


def test_december_january_boundary_is_handled_correctly() -> None:
    target = date(2026, 1, 3)  # a Saturday, close to the year boundary
    candidates = candidate_as_of_dates(target)
    # December dates of the PREVIOUS year, within the circular 42-day season window, must be
    # reachable as candidates even though the calendar month differs.
    assert any(c.month == 12 for c in candidates)


# --- pure selection fixtures ----------------------------------------------------------------------


def _period_rows(
    as_of: date, rooms: int, *, origin: SnapshotOrigin = SnapshotOrigin.OBSERVED, uncertain: int = 0
) -> list[SnapshotHistoryRow]:
    return [
        SnapshotHistoryRow(
            snapshot_id=uuid4(),
            snapshot_local_date=as_of,
            stay_date=as_of + timedelta(days=i),
            origin=origin,
            rooms_on_books=rooms,
            uncertain_rooms=uncertain,
            adr_on_books=None,
        )
        for i in range(30)
    ]


def _spanning_stay(
    channel_id: UUID, first_night: date, last_night: date, rooms: int
) -> tuple[StayRecord, UUID]:
    nights = (last_night - first_night).days + 1
    return (
        StayRecord(
            status=BookingStatus.CONFIRMED,
            booked_at=LONG_AGO,
            cancelled_at=None,
            check_in=first_night,
            check_out=last_night + timedelta(days=1),
            rooms=rooms,
            room_revenue=Decimal(rooms * nights * 100),
        ),
        channel_id,
    )


_World = tuple[list[date], dict[date, list[SnapshotHistoryRow]], list[tuple[StayRecord, UUID]]]


def _world(
    n: int,
    *,
    rooms_ota: int = 20,
    rooms_direct: int = 10,
    origin: SnapshotOrigin = SnapshotOrigin.OBSERVED,
) -> _World:
    """`n` clean, reconciling historical candidates (weeks 1..n back), same OTA/DIRECT mix.

    Consecutive weekly 30-night windows overlap by design: ONE pair of bookings spans the WHOLE
    combined range (exactly like `DistributionWorld.uniform_bookings` for the DB-backed tests),
    never one separate booking per week - that would double-count the overlap.
    """
    weeks = [TARGET - timedelta(weeks=k) for k in range(1, n + 1)]
    first_night = min(weeks)
    last_night = max(weeks) + timedelta(days=29)
    stays = [
        _spanning_stay(OTA_ID, first_night, last_night, rooms_ota),
        _spanning_stay(DIRECT_ID, first_night, last_night, rooms_direct),
    ]
    rows_by_as_of = {
        as_of: _period_rows(as_of, rooms_ota + rooms_direct, origin=origin) for as_of in weeks
    }
    return weeks, rows_by_as_of, stays


def _select(
    rows_by_as_of: dict[date, list[SnapshotHistoryRow]],
    stays: list[tuple[StayRecord, UUID]],
    **overrides: Any,
) -> ComparableSelection:
    # A narrow default lookback keeps these fixtures free of the (real, production-correct)
    # 1-/2-year seasonal-anniversary candidates the full 730-day horizon would also admit: this
    # module's OWN tests build a handful of weeks, not two years of history.
    overrides.setdefault("lookback_days", 45)
    return select_comparable_periods(
        TARGET,
        snapshot_rows_of=rows_by_as_of.get,
        stays=stays,
        classifications=CLASSIFICATIONS,
        timezone=TZ,
        **overrides,
    )


# --- K: historical quality gates -----------------------------------------------------------------


def test_incomplete_snapshot_window_is_excluded_and_counted() -> None:
    weeks, rows, stays = _world(6)
    rows[weeks[0]] = rows[weeks[0]][:29]  # one snapshot short
    selection = _select(rows, stays)
    assert selection.rejected_snapshot_incomplete_count == 1
    assert weeks[0] not in {p.as_of_local_date for p in selection.periods}


def test_uncertain_snapshot_is_excluded_and_counted() -> None:
    weeks, rows, stays = _world(6)
    rows[weeks[0]] = _period_rows(weeks[0], 30, uncertain=5)
    selection = _select(rows, stays)
    assert selection.rejected_snapshot_uncertain_count == 1
    assert weeks[0] not in {p.as_of_local_date for p in selection.periods}


def test_reconciliation_failure_is_excluded_and_counted() -> None:
    weeks, rows, stays = _world(6)
    rows[weeks[0]] = _period_rows(weeks[0], 999)  # never matches the real 30-room mix
    selection = _select(rows, stays)
    assert selection.rejected_reconciliation_count == 1
    assert weeks[0] not in {p.as_of_local_date for p in selection.periods}


def _only_in(
    as_of: date, rooms: int, channel_id: UUID, *, booked_after: date
) -> tuple[StayRecord, UUID]:
    """A booking that affects ONLY `as_of`'s own window's totals, never any other candidate's:
    booked just after `booked_after`'s own cutoff (the next-most-recent candidate), so it is
    excluded from every earlier historical period by Gate 3's own temporal rule regardless of
    calendar overlap - never by carving out a non-overlapping date range."""
    booked_at = end_of_local_day(booked_after, TZ) + timedelta(hours=1)
    return (
        StayRecord(
            status=BookingStatus.CONFIRMED,
            booked_at=booked_at,
            cancelled_at=None,
            check_in=as_of,
            check_out=as_of + timedelta(days=30),
            rooms=rooms,
            room_revenue=Decimal(rooms * 30 * 100),
        ),
        channel_id,
    )


def test_low_classification_coverage_is_excluded_and_counted() -> None:
    weeks, rows, stays = _world(6)
    unknown_id = uuid4()
    bad_week, next_older_week = weeks[0], weeks[1]
    stays.append(_only_in(bad_week, 100, unknown_id, booked_after=next_older_week))
    rows[bad_week] = _period_rows(bad_week, 30 + 100)
    selection = _select(rows, stays)
    assert selection.rejected_low_classification_count == 1
    assert bad_week not in {p.as_of_local_date for p in selection.periods}
    assert selection.sample_count == 5  # the other 5 weeks are unaffected


def test_low_volume_is_excluded_and_counted() -> None:
    """Each week gets only a single-night, 2-room booking (never a 30-night spanning one, whose
    per-night rooms multiply by 30 and could never stay under the volume floor): even with the
    heaviest realistic cross-week overlap this design allows, no period's total nears 20."""
    weeks = [TARGET - timedelta(weeks=k) for k in range(1, 7)]
    stays = []
    rows: dict[date, list[SnapshotHistoryRow]] = {}
    for as_of in weeks:
        stays.append(_spanning_stay(OTA_ID, as_of, as_of, 1))
        stays.append(_spanning_stay(DIRECT_ID, as_of, as_of, 1))
    for as_of in weeks:
        window = [as_of + timedelta(days=i) for i in range(30)]
        touching = {w for w in weeks if w in window}
        rows[as_of] = [
            SnapshotHistoryRow(
                snapshot_id=uuid4(),
                snapshot_local_date=as_of,
                stay_date=day,
                origin=SnapshotOrigin.OBSERVED,
                rooms_on_books=2 if day in touching else 0,
                uncertain_rooms=0,
                adr_on_books=None,
            )
            for day in window
        ]
    selection = _select(rows, stays)
    assert selection.rejected_low_volume_count == len(weeks)
    assert selection.sample_count == 0


def test_rejected_counters_are_exact_not_approximate() -> None:
    weeks, rows, stays = _world(8)
    rows[weeks[0]] = rows[weeks[0]][:29]
    rows[weeks[1]] = _period_rows(weeks[1], 30, uncertain=1)
    rows[weeks[2]] = _period_rows(weeks[2], 12345)
    selection = _select(rows, stays)
    assert selection.rejected_snapshot_incomplete_count == 1
    assert selection.rejected_snapshot_uncertain_count == 1
    assert selection.rejected_reconciliation_count == 1
    assert selection.rejected_low_classification_count == 0
    assert selection.rejected_low_volume_count == 0
    # _world(8) still only ever offers 6 CANDIDATES (weeks 7-8 back exceed the 42-day season
    # window regardless of their data): 3 rejected above leaves 3 of those 6 eligible.
    assert selection.candidate_period_count == 6
    assert selection.sample_count == 3


# --- L: observed-first sampling ------------------------------------------------------------------


def test_5_or_more_fully_observed_uses_only_fully_observed() -> None:
    weeks, rows, stays = _world(6)
    selection = _select(rows, stays)
    assert selection.sample_count == 6
    assert selection.fully_observed_count == 6
    assert selection.approximate_count == 0


def test_fewer_than_5_fully_observed_fills_with_approximate() -> None:
    weeks, rows, stays = _world(6, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    # Make only 3 of the 6 fully observed (ACTUAL... here: OBSERVED occupancy).
    for as_of in weeks[:3]:
        rows[as_of] = _period_rows(as_of, 30, origin=SnapshotOrigin.OBSERVED)
    selection = _select(rows, stays)
    assert selection.fully_observed_count == 3
    assert selection.approximate_count == 3
    assert selection.sample_count == 6


def test_sample_never_exceeds_24() -> None:
    weeks, rows, stays = _world(30)
    selection = _select(rows, stays)
    assert selection.sample_count <= 24


def test_fewer_than_5_total_is_insufficient() -> None:
    weeks, rows, stays = _world(3)
    selection = _select(rows, stays)
    assert selection.sample_count == 3


def test_the_sample_is_ordered_most_recent_first() -> None:
    weeks, rows, stays = _world(6, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    for as_of in weeks[:3]:
        rows[as_of] = _period_rows(as_of, 30, origin=SnapshotOrigin.OBSERVED)
    selection = _select(rows, stays)
    dates = [period.as_of_local_date for period in selection.periods]
    assert dates == sorted(dates, reverse=True)


def test_all_approximate_is_allowed_when_the_sample_is_5_or_more() -> None:
    weeks, rows, stays = _world(6, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    selection = _select(rows, stays)
    assert selection.sample_count == 6
    assert selection.fully_observed_count == 0
    assert selection.approximate_count == 6


def test_provenance_of_each_used_period_is_correct() -> None:
    weeks, rows, stays = _world(5, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    selection = _select(rows, stays)
    for period in selection.periods:
        assert period.observed_day_count == 0
        assert period.reconstructed_day_count == 30
        assert period.snapshot_provenance_score_exact == 60
