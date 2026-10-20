"""Dati overview: the pure calculations (no database).

Every definition tested here is one NINFA already approved (Booking snapshots V1, the Home's own
status rules): the tests pin that Dati applies them exactly, and never invents a figure - an unknown
capacity is not a zero, a night without a snapshot is not a night with no rooms.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.data_overview import metrics
from app.modules.data_overview.service import DOMAIN_OF_DECISION_TYPE
from app.modules.data_overview.types import DecisionRef, DomainState, NightStatus
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.models import DecisionRun
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin

D = Decimal
START = date(2026, 8, 1)


def snap(
    day: date,
    rooms: int,
    available: int | None,
    *,
    revenue: str | None = None,
    bookings: int | None = None,
) -> BookingSnapshot:
    """A transient (never stored) snapshot row with the columns the calculations read."""
    revenue_value = D(revenue) if revenue is not None else D("100.00") * rooms
    return BookingSnapshot(
        stay_date=day,
        origin=SnapshotOrigin.OBSERVED,
        booking_count_on_books=bookings if bookings is not None else (0 if rooms == 0 else 1),
        rooms_on_books=rooms,
        allocated_room_revenue_on_books=revenue_value,
        rooms_available=available,
        occupancy_on_books=(
            None if not available else (D(rooms) * 100 / D(available)).quantize(D("0.01"))
        ),
        adr_on_books=None if rooms == 0 else (revenue_value / rooms).quantize(D("0.01")),
    )


def days(count: int) -> list[date]:
    return [START + timedelta(days=offset) for offset in range(count)]


# --- occupancy ------------------------------------------------------------------------------------


def test_occupancy_is_summed_over_nights_with_a_known_capacity_only() -> None:
    rows = [
        snap(START, 10, 40),
        snap(START + timedelta(1), 20, None),
        snap(START + timedelta(2), 5, 0),
    ]

    result = metrics.period_metrics(rows, START, START + timedelta(2))

    # 10 of 40 rooms on the one night whose capacity is known: 25.00 %. The unknown-capacity night
    # and the zero-capacity (closed) night enter neither the numerator nor the denominator.
    assert result.occupancy_pct == D("25.00")
    assert result.rooms_on_books_with_capacity == 10
    assert result.rooms_available == 40
    assert result.nights_with_capacity == 1
    assert result.nights_with_data == 3


def test_room_nights_count_every_stored_night_even_without_a_capacity() -> None:
    rows = [snap(START, 10, 40), snap(START + timedelta(1), 20, None)]

    result = metrics.period_metrics(rows, START, START + timedelta(1))

    assert result.room_nights == 30  # camere-notte: a different quantity from the occupancy base
    assert result.rooms_on_books_with_capacity == 10


def test_no_known_capacity_means_no_occupancy_never_zero() -> None:
    rows = [snap(day, 12, None) for day in days(3)]

    result = metrics.period_metrics(rows, START, START + timedelta(2))

    assert result.occupancy_pct is None
    assert result.rooms_available is None
    assert result.rooms_on_books_with_capacity is None
    assert result.nights_with_capacity == 0
    assert result.room_nights == 36  # the bookings are still real


def test_a_window_with_no_stored_night_has_no_figure_at_all() -> None:
    result = metrics.period_metrics([], START, START + timedelta(6))

    assert result.nights_with_data == 0
    assert result.nights_requested == 7
    for value in (
        result.room_nights,
        result.occupancy_pct,
        result.room_revenue,
        result.adr,
        result.rooms_available,
    ):
        assert value is None  # missing is never zero


def test_nights_outside_the_window_are_ignored() -> None:
    rows = [snap(day, 10, 40) for day in days(10)]

    result = metrics.period_metrics(rows, START, START + timedelta(2))

    assert result.nights_with_data == 3
    assert result.room_nights == 30


@pytest.mark.parametrize(
    ("rooms", "available", "expected"),
    [(1, 3, "33.33"), (2, 3, "66.67"), (1, 32, "3.13"), (1, 16, "6.25"), (45, 40, "112.50")],
)
def test_occupancy_is_rounded_half_up_and_never_clamped(
    rooms: int, available: int, expected: str
) -> None:
    result = metrics.period_metrics([snap(START, rooms, available)], START, START)

    assert result.occupancy_pct == D(expected)  # 45 on 40 is 112.50: overbooking is information


# --- revenue / ADR --------------------------------------------------------------------------------


def test_revenue_is_the_on_books_room_revenue_and_adr_divides_by_room_nights() -> None:
    rows = [
        snap(START, 10, 40, revenue="1000.00"),
        snap(START + timedelta(1), 20, 40, revenue="2500.00"),
    ]

    result = metrics.period_metrics(rows, START, START + timedelta(1))

    assert result.room_revenue == D("3500.00")
    assert result.adr == D("116.67")  # 3500 / 30 room-nights, half up


def test_adr_is_not_available_without_room_nights_while_revenue_is_a_real_zero() -> None:
    rows = [snap(START, 0, 40, revenue="0.00")]

    result = metrics.period_metrics(rows, START, START)

    assert result.room_revenue == D("0.00")
    assert result.adr is None  # never a fake 0.00 ADR
    assert result.occupancy_pct == D("0.00")  # an empty night with a known capacity IS 0 %


def test_a_multi_night_booking_is_one_booking_per_night_not_a_period_booking_count() -> None:
    # One 3-night booking appears as 1 booking on each of its nights. Summing it across the window
    # would count it three times: Dati therefore never sums `bookings`, it exposes room-nights.
    rows = [snap(day, 1, 40, bookings=1) for day in days(3)]

    result = metrics.period_metrics(rows, START, START + timedelta(2))

    assert result.room_nights == 3
    assert not hasattr(result, "bookings")


# --- the 7-days-ago comparison --------------------------------------------------------------------


def test_the_seven_day_comparison_needs_every_night_in_both_snapshots() -> None:
    rows = [snap(day, 10, 40) for day in days(3)]
    older = {day: 7 for day in days(3)}

    result = metrics.period_metrics(rows, START, START + timedelta(2), rooms_7d_ago=older)

    assert result.room_nights_7d_ago == 21
    assert result.room_nights_delta_7d == 9


def test_the_comparison_is_absent_when_the_older_snapshot_misses_a_night() -> None:
    rows = [snap(day, 10, 40) for day in days(3)]
    older = {days(3)[0]: 7, days(3)[1]: 7}  # the third night was not in the older snapshot

    result = metrics.period_metrics(rows, START, START + timedelta(2), rooms_7d_ago=older)

    assert result.room_nights_7d_ago is None
    assert result.room_nights_delta_7d is None  # never a partial comparison of different nights


def test_the_comparison_is_absent_when_today_misses_a_night() -> None:
    rows = [snap(days(3)[0], 10, 40), snap(days(3)[2], 10, 40)]

    result = metrics.period_metrics(
        rows, START, START + timedelta(2), rooms_7d_ago={day: 5 for day in days(3)}
    )

    assert result.room_nights_delta_7d is None


def test_without_an_older_snapshot_there_is_no_comparison() -> None:
    result = metrics.period_metrics([snap(START, 10, 40)], START, START, rooms_7d_ago=None)

    assert result.room_nights_7d_ago is None
    assert result.room_nights_delta_7d is None


def test_a_negative_delta_is_kept_as_it_is() -> None:
    result = metrics.period_metrics([snap(START, 4, 40)], START, START, rooms_7d_ago={START: 9})

    assert result.room_nights_delta_7d == -5


# --- windows / percentages ------------------------------------------------------------------------


def test_a_window_counts_nights_from_the_analysis_day_both_ends_included() -> None:
    assert metrics.window_of(START, 1) == (START, START)
    assert metrics.window_of(START, 7) == (START, date(2026, 8, 7))
    assert metrics.window_of(START, 30) == (START, date(2026, 8, 30))


def test_a_percentage_of_nothing_is_not_available() -> None:
    assert metrics.percent_of(0, 0) is None
    assert metrics.percent_of(5, 0) is None
    assert metrics.percent_of(0, 10) == D("0.00")


# --- night status ---------------------------------------------------------------------------------


def _status(**overrides: object) -> NightStatus:
    arguments: dict[str, object] = {
        "has_decision": False,
        "has_data": True,
        "run_exists": True,
        "revenue_state": DomainState.ANALYZED,
        "run_inconclusive": False,
    }
    arguments.update(overrides)
    return metrics.night_status(**arguments)  # type: ignore[arg-type]


def test_a_decision_always_makes_a_night_attention() -> None:
    assert _status(has_decision=True) is NightStatus.ATTENTION
    assert (
        _status(has_decision=True, revenue_state=DomainState.NOT_ANALYZED) is NightStatus.ATTENTION
    )
    assert _status(has_decision=True, run_inconclusive=True) is NightStatus.ATTENTION


def test_a_clean_analysed_night_without_a_decision_is_regular() -> None:
    assert _status() is NightStatus.REGULAR


def test_an_inconclusive_run_never_lets_a_night_read_regular() -> None:
    assert _status(run_inconclusive=True) is NightStatus.PARTIAL
    assert _status(revenue_state=DomainState.PARTIAL) is NightStatus.PARTIAL


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_exists": False},
        {"has_data": False},
        {"revenue_state": DomainState.NOT_ANALYZED},
        {"revenue_state": DomainState.UNKNOWN},
    ],
)
def test_a_night_nobody_evaluated_is_not_evaluated(overrides: dict[str, object]) -> None:
    assert _status(**overrides) is NightStatus.NOT_EVALUATED


def test_run_inconclusive_reads_the_runs_own_counts() -> None:
    assert metrics.run_is_inconclusive(None) is False
    assert (
        metrics.run_is_inconclusive(DecisionRun(insufficient_count=0, suppressed_count=0)) is False
    )
    assert (
        metrics.run_is_inconclusive(DecisionRun(insufficient_count=1, suppressed_count=0)) is True
    )
    assert (
        metrics.run_is_inconclusive(DecisionRun(insufficient_count=0, suppressed_count=2)) is True
    )


# --- night rows -----------------------------------------------------------------------------------


def test_a_missing_snapshot_is_a_night_without_data_never_a_night_with_zero_rooms() -> None:
    rows = [snap(START, 10, 40), snap(START + timedelta(2), 12, 40)]

    result = metrics.night_rows(
        rows,
        START,
        START + timedelta(2),
        rooms_7d_ago=None,
        decisions_by_night={},
        run_exists=True,
        revenue_state=DomainState.ANALYZED,
        run_inconclusive=False,
    )

    assert [night.has_data for night in result] == [True, False, True]
    gap = result[1]
    assert gap.rooms_on_books is None
    assert gap.occupancy_pct is None
    assert gap.status is NightStatus.NOT_EVALUATED


def test_a_night_links_to_its_decision() -> None:
    decision = DecisionRef(uuid4(), "REV_PICKUP_LOW", AnalysisDomain.REVENUE, START, None)

    result = metrics.night_rows(
        [snap(START, 10, 40)],
        START,
        START,
        rooms_7d_ago=None,
        decisions_by_night={START: decision},
        run_exists=True,
        revenue_state=DomainState.ANALYZED,
        run_inconclusive=False,
    )

    assert result[0].status is NightStatus.ATTENTION
    assert result[0].decision_id == decision.decision_id


def test_a_night_keeps_its_stored_occupancy_and_adr() -> None:
    result = metrics.night_rows(
        [snap(START, 10, 40, revenue="1250.00")],
        START,
        START,
        rooms_7d_ago={START: 6},
        decisions_by_night={},
        run_exists=True,
        revenue_state=DomainState.ANALYZED,
        run_inconclusive=False,
    )

    [night] = result
    assert night.occupancy_pct == D("25.00")
    assert night.adr == D("125.00")
    assert night.rooms_on_books_7d_ago == 6
    assert (
        night.rooms_delta_7d == 4
    )  # 10 rooms now, 6 a week ago: calculated here, never by the page


def test_a_nights_change_needs_both_the_older_and_the_current_snapshot() -> None:
    rows = [snap(START, 10, 40), snap(START + timedelta(1), 10, 40)]

    result = metrics.night_rows(
        rows,
        START,
        START + timedelta(2),
        rooms_7d_ago={
            START: 7,
            START + timedelta(2): 3,
        },  # no older row for the 2nd, no row today for the 3rd
        decisions_by_night={},
        run_exists=True,
        revenue_state=DomainState.ANALYZED,
        run_inconclusive=False,
    )

    assert [night.rooms_delta_7d for night in result] == [3, None, None]  # never a made-up delta


def test_only_revenue_decisions_are_indexed_by_night_and_the_first_one_wins() -> None:
    first = DecisionRef(uuid4(), "REV_PICKUP_LOW", AnalysisDomain.REVENUE, START, None)
    second = DecisionRef(uuid4(), "REV_OCCUPANCY_RISK", AnalysisDomain.REVENUE, START, None)
    labor = DecisionRef(uuid4(), "LABOR_OVERSTAFFING", AnalysisDomain.LABOR, START, "HOUSEKEEPING")
    cost = DecisionRef(uuid4(), "COST_CPOR_ANOMALY", AnalysisDomain.COSTS, START, "FOOD")
    ota = DecisionRef(uuid4(), "REV_OTA_DEPENDENCY", AnalysisDomain.DISTRIBUTION, None, None)

    indexed = metrics.index_decisions_by_night([first, second, labor, cost, ota])

    assert indexed == {START: first}


# --- domain states --------------------------------------------------------------------------------


def _coverage(**statuses: DomainCoverageStatus) -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=tuple(
            DomainCoverage(
                domain,
                statuses[domain.name],
                DomainSkipReason.NOT_REQUESTED
                if statuses[domain.name] is DomainCoverageStatus.SKIPPED
                else None,
            )
            for domain in AnalysisDomain
        )
    )


EVALUATED = DomainCoverageStatus.EVALUATED
SKIPPED = DomainCoverageStatus.SKIPPED


def test_without_a_run_or_without_coverage_every_area_is_unknown() -> None:
    all_unknown = {domain: DomainState.UNKNOWN for domain in AnalysisDomain}

    assert metrics.domain_states(None, None, FeedState.NOT_PROCESSED, []) == all_unknown
    # a run that recorded no coverage (it predates Gate 22): never inferred as full or partial
    assert (
        metrics.domain_states(DecisionRun(), None, FeedState.NO_ACTION_REQUIRED, []) == all_unknown
    )


def test_a_skipped_area_is_not_analysed_and_an_evaluated_one_is_analysed() -> None:
    coverage = _coverage(REVENUE=EVALUATED, DISTRIBUTION=EVALUATED, COSTS=SKIPPED, LABOR=SKIPPED)

    states = metrics.domain_states(DecisionRun(), coverage, FeedState.NO_ACTION_REQUIRED, [])

    assert states[AnalysisDomain.REVENUE] is DomainState.ANALYZED
    assert states[AnalysisDomain.DISTRIBUTION] is DomainState.ANALYZED
    assert states[AnalysisDomain.COSTS] is DomainState.NOT_ANALYZED
    assert states[AnalysisDomain.LABOR] is DomainState.NOT_ANALYZED


def test_a_data_quality_limited_run_never_reads_clear_for_an_evaluated_area() -> None:
    coverage = _coverage(REVENUE=EVALUATED, DISTRIBUTION=EVALUATED, COSTS=SKIPPED, LABOR=SKIPPED)

    states = metrics.domain_states(DecisionRun(), coverage, FeedState.DATA_QUALITY_LIMITED, [])

    assert states[AnalysisDomain.REVENUE] is DomainState.PARTIAL
    assert states[AnalysisDomain.DISTRIBUTION] is DomainState.PARTIAL
    assert states[AnalysisDomain.COSTS] is DomainState.NOT_ANALYZED  # skipped stays skipped


def test_an_area_with_a_decision_is_analysed_whatever_the_run_says() -> None:
    coverage = _coverage(REVENUE=EVALUATED, DISTRIBUTION=EVALUATED, COSTS=SKIPPED, LABOR=SKIPPED)

    states = metrics.domain_states(
        DecisionRun(), coverage, FeedState.DATA_QUALITY_LIMITED, [AnalysisDomain.REVENUE]
    )

    assert states[AnalysisDomain.REVENUE] is DomainState.ANALYZED  # a decision IS the evidence


# --- vocabulary guard -----------------------------------------------------------------------------


def test_every_decision_type_has_exactly_one_area() -> None:
    assert set(DOMAIN_OF_DECISION_TYPE) == set(PriorityDecisionType)
    assert DOMAIN_OF_DECISION_TYPE[PriorityDecisionType.REV_PICKUP_LOW] is AnalysisDomain.REVENUE
    assert (
        DOMAIN_OF_DECISION_TYPE[PriorityDecisionType.REV_OCCUPANCY_RISK] is AnalysisDomain.REVENUE
    )
    assert (
        DOMAIN_OF_DECISION_TYPE[PriorityDecisionType.REV_OTA_DEPENDENCY]
        is AnalysisDomain.DISTRIBUTION
    )
    assert DOMAIN_OF_DECISION_TYPE[PriorityDecisionType.COST_CPOR_ANOMALY] is AnalysisDomain.COSTS
    assert DOMAIN_OF_DECISION_TYPE[PriorityDecisionType.LABOR_OVERSTAFFING] is AnalysisDomain.LABOR
