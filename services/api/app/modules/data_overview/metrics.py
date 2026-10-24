"""The calculations of the Dati overview that need no database (pure, deterministic, tested alone).

Every definition here is one NINFA already approved; none is new:

* the on-books metrics of a night / a window come from the stored OBSERVED `BookingSnapshot` rows
  (Booking snapshots V1) and use the SAME aggregation as Mia's semantic layer (`HomeDataService`):
  occupancy = sum(rooms on books) / sum(rooms available) over the nights with a known capacity,
  room-nights and revenue over every stored night, ADR = revenue / room-nights;
* a night's status and an area's state are read from the persisted run (its decisions, its
  coverage, its own counts) with the Home's own rules - never from a threshold of this module.

No clock is read: every date arrives explicitly.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.modules.data_overview.types import (
    DecisionRef,
    DomainState,
    NightRow,
    NightStatus,
    PeriodMetrics,
)
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import AnalysisCoverage, AnalysisDomain, DomainCoverageStatus
from app.modules.decisions.models import DecisionRun
from app.modules.snapshots.models import BookingSnapshot

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)


def to_cents(value: Decimal) -> Decimal:
    """Two decimals, half up - the rounding every stored occupancy / ADR already uses."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def window_of(as_of: date, days: int) -> tuple[date, date]:
    """`days` stay nights counted FROM the analysis day, both ends included."""
    return as_of, as_of + timedelta(days=days - 1)


def percent_of(part: int, whole: int) -> Decimal | None:
    """`part / whole * 100` to two decimals, or `None` when there is no whole (never a fake 0 %)."""
    if whole <= 0:
        return None
    return to_cents(Decimal(part) * _HUNDRED / Decimal(whole))


def period_metrics(
    rows: Sequence[BookingSnapshot],
    start: date,
    end: date,
    *,
    rooms_7d_ago: Mapping[date, int] | None = None,
) -> PeriodMetrics:
    """The on-books metrics of the nights `start..end` (both included).

    `rooms_7d_ago` maps a stay date to its `rooms_on_books` in the OBSERVED snapshot taken 7 days
    before the analysis day. The comparison exists only when EVERY night of the window has a row
    today AND in that older snapshot: a partial comparison would compare different nights.
    """
    in_window = [row for row in rows if start <= row.stay_date <= end]
    nights_requested = (end - start).days + 1
    with_capacity = [
        row for row in in_window if row.rooms_available is not None and row.rooms_available > 0
    ]
    if not in_window:
        return PeriodMetrics(
            start_date=start,
            end_date=end,
            nights_requested=nights_requested,
            nights_with_data=0,
            nights_with_capacity=0,
            room_nights=None,
            rooms_on_books_with_capacity=None,
            rooms_available=None,
            occupancy_pct=None,
            room_revenue=None,
            adr=None,
            room_nights_7d_ago=None,
            room_nights_delta_7d=None,
        )

    room_nights = sum(row.rooms_on_books for row in in_window)
    available = sum(row.rooms_available or 0 for row in with_capacity)
    on_books_with_capacity = sum(row.rooms_on_books for row in with_capacity)
    revenue = sum((row.allocated_room_revenue_on_books for row in in_window), Decimal(0))

    previous_total: int | None = None
    delta: int | None = None
    if rooms_7d_ago is not None and len(in_window) == nights_requested:
        wanted = [row.stay_date for row in in_window]
        if all(day in rooms_7d_ago for day in wanted):
            previous_total = sum(rooms_7d_ago[day] for day in wanted)
            delta = room_nights - previous_total

    return PeriodMetrics(
        start_date=start,
        end_date=end,
        nights_requested=nights_requested,
        nights_with_data=len(in_window),
        nights_with_capacity=len(with_capacity),
        room_nights=room_nights,
        rooms_on_books_with_capacity=on_books_with_capacity if with_capacity else None,
        rooms_available=available if with_capacity else None,
        occupancy_pct=percent_of(on_books_with_capacity, available),
        room_revenue=to_cents(revenue),
        adr=to_cents(revenue / Decimal(room_nights)) if room_nights > 0 else None,
        room_nights_7d_ago=previous_total,
        room_nights_delta_7d=delta,
    )


def night_status(
    *,
    has_decision: bool,
    has_data: bool,
    run_exists: bool,
    revenue_state: DomainState,
    run_inconclusive: bool,
) -> NightStatus:
    """A night's status, from the run alone (see `NightStatus`). A decision always wins; a night
    without booking data, or in a run that never analysed revenue, is never "regular"."""
    if has_decision:
        return NightStatus.ATTENTION
    if not run_exists or not has_data:
        return NightStatus.NOT_EVALUATED
    if revenue_state in (DomainState.NOT_ANALYZED, DomainState.UNKNOWN):
        return NightStatus.NOT_EVALUATED
    if revenue_state is DomainState.PARTIAL or run_inconclusive:
        return NightStatus.PARTIAL
    return NightStatus.REGULAR


def night_rows(
    rows: Sequence[BookingSnapshot],
    start: date,
    end: date,
    *,
    rooms_7d_ago: Mapping[date, int] | None,
    decisions_by_night: Mapping[date, DecisionRef],
    run_exists: bool,
    revenue_state: DomainState,
    run_inconclusive: bool,
) -> tuple[NightRow, ...]:
    """One row per stay night of `start..end`, a missing snapshot included (as "no data")."""
    by_date = {row.stay_date: row for row in rows}
    out: list[NightRow] = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        row = by_date.get(day)
        decision = decisions_by_night.get(day)
        status = night_status(
            has_decision=decision is not None,
            has_data=row is not None,
            run_exists=run_exists,
            revenue_state=revenue_state,
            run_inconclusive=run_inconclusive,
        )
        previous = None if rooms_7d_ago is None else rooms_7d_ago.get(day)
        if row is None:
            out.append(
                NightRow(
                    stay_date=day,
                    has_data=False,
                    bookings=None,
                    rooms_on_books=None,
                    rooms_available=None,
                    occupancy_pct=None,
                    room_revenue=None,
                    adr=None,
                    rooms_on_books_7d_ago=previous,
                    rooms_delta_7d=None,
                    status=status,
                    decision_id=None if decision is None else decision.decision_id,
                )
            )
            continue
        out.append(
            NightRow(
                stay_date=day,
                has_data=True,
                bookings=row.booking_count_on_books,
                rooms_on_books=row.rooms_on_books,
                rooms_available=row.rooms_available,
                occupancy_pct=row.occupancy_on_books,
                room_revenue=row.allocated_room_revenue_on_books,
                adr=row.adr_on_books,
                rooms_on_books_7d_ago=previous,
                rooms_delta_7d=None if previous is None else row.rooms_on_books - previous,
                status=status,
                decision_id=None if decision is None else decision.decision_id,
            )
        )
    return tuple(out)


def run_is_inconclusive(run: DecisionRun | None) -> bool:
    """True when the run had checks it could not conclude (too little data, or a result NINFA was
    not confident enough to show): "no decision" then does not mean "nothing to see"."""
    return run is not None and (run.insufficient_count > 0 or run.suppressed_count > 0)


def domain_states(
    run: DecisionRun | None,
    coverage: AnalysisCoverage | None,
    feed_state: FeedState,
    decision_domains: Iterable[AnalysisDomain],
) -> dict[AnalysisDomain, DomainState]:
    """The four areas' analysis state, with the Home's own rules (`buildDomainSummary`):

    * no run, or a run that recorded no coverage     -> UNKNOWN
    * an area that has a decision                    -> ANALYZED (a decision IS evidence it was)
    * an area the run skipped                        -> NOT_ANALYZED
    * an evaluated area of a data-quality-limited run-> PARTIAL
    * any other evaluated area                       -> ANALYZED
    """
    with_decision = set(decision_domains)
    states: dict[AnalysisDomain, DomainState] = {}
    for domain in AnalysisDomain:
        if run is None or coverage is None:
            states[domain] = DomainState.UNKNOWN
            continue
        if domain in with_decision:
            states[domain] = DomainState.ANALYZED
            continue
        status = next(
            (item.status for item in coverage.domains if item.domain is domain),
            None,
        )
        if status is None:
            states[domain] = DomainState.UNKNOWN
        elif status is DomainCoverageStatus.SKIPPED:
            states[domain] = DomainState.NOT_ANALYZED
        elif feed_state is FeedState.DATA_QUALITY_LIMITED:
            states[domain] = DomainState.PARTIAL
        else:
            states[domain] = DomainState.ANALYZED
    return states


def index_decisions_by_night(decisions: Iterable[DecisionRef]) -> dict[date, DecisionRef]:
    """The revenue decisions that target a stay night, by that night. If two decisions ever target
    the same night, the first in the feed's own order (the higher priority) is the one shown."""
    by_night: dict[date, DecisionRef] = {}
    for decision in decisions:
        if decision.domain is AnalysisDomain.REVENUE and decision.target_date is not None:
            by_night.setdefault(decision.target_date, decision)
    return by_night


def first_decision_id(decisions: Iterable[DecisionRef], decision_type: str) -> UUID | None:
    for decision in decisions:
        if decision.decision_type == decision_type:
            return decision.decision_id
    return None


__all__ = [
    "domain_states",
    "first_decision_id",
    "index_decisions_by_night",
    "night_rows",
    "night_status",
    "percent_of",
    "period_metrics",
    "run_is_inconclusive",
    "to_cents",
    "window_of",
]
