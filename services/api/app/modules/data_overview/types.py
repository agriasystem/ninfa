"""The typed vocabulary of the Dati overview (Dati UI V1): plain, immutable, framework-free values.

Dati answers "what is actually happening in my numbers?". Everything here is a deterministic
projection of data NINFA already stores or already calculates - on-books snapshots, the persisted
decision run, the OTA evaluation, the canonical invoice lines, the canonical labor entries. Nothing
is estimated, nothing comes from a model, and a figure that cannot be calculated safely is `None`
(never `0`) with a stated reason.

Naming: a `*_pct` value is a percentage already rounded half-up to two decimals; money is a
`Decimal` in the property's own currency (NINFA never converts currencies); a count is an `int`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.modules.decision_memory.types import FeedState, LastSuccessfulAnalysis
from app.modules.decisions.coverage import AnalysisCoverage, AnalysisDomain

DATA_OVERVIEW_VERSION = "data-overview-v1"

# The two periods the page offers. They are windows of FUTURE stay nights counted from the analysis
# day (the stored snapshots of that day describe the nights from it forward), never a look-back.
PERIOD_DAYS_SHORT = 7
PERIOD_DAYS_LONG = 30
ALLOWED_PERIOD_DAYS: tuple[int, ...] = (PERIOD_DAYS_SHORT, PERIOD_DAYS_LONG)

# How far back the "vs 7 days ago" comparison looks (the stored snapshot of that day).
COMPARISON_LOOKBACK_DAYS = 7


class NightStatus(StrEnum):
    """What NINFA can honestly say about ONE stay night, derived only from its own decisions and
    from the run's coverage - never from a threshold of this module.

    ATTENTION       a decision of today's feed targets this night
    PARTIAL         revenue was analysed but the run had checks it could not conclude
    REGULAR         revenue was analysed, no decision targets this night and no check was left
                    inconclusive (the same rule as the Home's "everything under control")
    NOT_EVALUATED   no analysis, revenue not analysed, or no booking data for the night
    """

    ATTENTION = "ATTENTION"
    PARTIAL = "PARTIAL"
    REGULAR = "REGULAR"
    NOT_EVALUATED = "NOT_EVALUATED"


class DomainState(StrEnum):
    """The analysis status of one of the four areas, in the Home's own vocabulary."""

    ANALYZED = "ANALYZED"
    PARTIAL = "PARTIAL"
    NOT_ANALYZED = "NOT_ANALYZED"
    UNKNOWN = "UNKNOWN"


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class UnavailableReason(StrEnum):
    """Why a block has no figures - stable codes, rendered as plain Italian by the frontend."""

    NO_ANALYSIS = "NO_ANALYSIS"  # no decision run exists for the day
    NO_BOOKING_SOURCE = "NO_BOOKING_SOURCE"  # the run recorded no booking source
    NO_BOOKING_DATA = "NO_BOOKING_DATA"  # the source has no stored night in the window
    COVERAGE_UNKNOWN = "COVERAGE_UNKNOWN"  # the run recorded no coverage
    NOT_ANALYZED = "NOT_ANALYZED"  # the area was not analysed by this run
    EVALUATION_FAILED = "EVALUATION_FAILED"  # a live read failed: shown as not available
    NO_DATA = "NO_DATA"  # the domain has no data for the period (never a zero)
    NO_OCCUPANCY = "NO_OCCUPANCY"  # a metric needs bookings the run does not provide
    NO_SOURCE = "NO_SOURCE"  # the property has no active data source of the domain
    SEVERAL_SOURCES = "SEVERAL_SOURCES"  # more than one: NINFA does not pick one silently


class CapacityState(StrEnum):
    """Whether the occupancy of a period can be calculated. It needs the number of rooms the
    property has on each night, which only the room inventory says: a capacity is never inferred
    from the bookings (rooms booked, room numbers, the busiest night are not an inventory).

    KNOWN              every night with bookings has its capacity in the analysis day's observation
    PARTIAL            only some do: the occupancy rests on those nights alone (and says so)
    MISSING            none does, and the property has no room inventory for these nights
    AWAITING_ANALYSIS  none does, but a room inventory now exists for some of these nights: it was
                       set after the observation, which copies the capacity when it is taken, and
                       the next analysis takes it in
    """

    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    AWAITING_ANALYSIS = "AWAITING_ANALYSIS"


class OtaOutcome(StrEnum):
    """What the OTA check concluded (the persisted decision, or NINFA's own live evaluation)."""

    DECISION = "DECISION"
    CLEAR = "CLEAR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SUPPRESSED = "SUPPRESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CHANGED_AFTER_ANALYSIS = "CHANGED_AFTER_ANALYSIS"


class OtaInsufficiency(StrEnum):
    """Why the OTA check gave no verdict, for the person reading it: two different things to do.

    DATA_QUALITY  the current data cannot be read (dates or statuses that contradict each other, too
                  many channels unclassified, too few bookings): something can be looked at
    HISTORY       the current data are fine: only the past periods to compare them with are missing,
                  and they come by themselves, one analysis at a time
    """

    DATA_QUALITY = "DATA_QUALITY"
    HISTORY = "HISTORY"


class ChannelGroupName(StrEnum):
    OTA = "OTA"
    DIRECT = "DIRECT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class FreshnessReason(StrEnum):
    NO_SOURCE = "NO_SOURCE"
    SEVERAL_SOURCES = "SEVERAL_SOURCES"
    NO_IMPORT = "NO_IMPORT"


class CporStatus(StrEnum):
    """Why a category has no cost per occupied room (the metric statuses of Cost CPOR V1, plus the
    one this module adds when the run recorded no booking source to take the denominator from)."""

    READY = "READY"
    NO_OCCUPANCY_SOURCE = "NO_OCCUPANCY_SOURCE"
    INCOMPLETE = "INCOMPLETE"
    ZERO_OCCUPANCY = "ZERO_OCCUPANCY"
    LOW_CLASSIFICATION_COVERAGE = "LOW_CLASSIFICATION_COVERAGE"
    NO_COST_DATA = "NO_COST_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # the unclassified bucket: no cost per room is defined for it


# --- decisions (only what the page needs to mark a night or link a row) ---------------------------


@dataclass(frozen=True, slots=True)
class DecisionRef:
    """A decision of today's feed, reduced to what Dati displays: its id (to link to the detail),
    its type, the area it belongs to and, for the types that have one, its target date and
    category."""

    decision_id: UUID
    decision_type: str
    domain: AnalysisDomain
    target_date: date | None
    category: str | None


# --- occupancy / bookings -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodMetrics:
    """The on-books metrics of a window of stay nights, from the stored OBSERVED snapshots of the
    analysis day.

    Occupancy is `sum(rooms on books) / sum(rooms available)` over the nights WITH a known capacity
    only - a night with an unknown capacity never enters it (it is counted in
    `nights_with_capacity`). Room-nights, revenue and ADR cover every night that has a stored
    snapshot. A window with no stored night has `nights_with_data == 0` and every figure `None`.

    `capacity` says whether the occupancy can be calculated at all (`None` with no night of
    bookings: there is nothing to put over a capacity). Without an inventory only the occupancy and
    the rooms available are missing: room-nights, revenue and ADR stay.
    """

    start_date: date
    end_date: date
    nights_requested: int
    nights_with_data: int
    nights_with_capacity: int
    capacity: CapacityState | None
    room_nights: int | None
    rooms_on_books_with_capacity: int | None
    rooms_available: int | None
    occupancy_pct: Decimal | None
    room_revenue: Decimal | None
    adr: Decimal | None
    room_nights_7d_ago: int | None
    room_nights_delta_7d: int | None


@dataclass(frozen=True, slots=True)
class NightRow:
    """One stay night. `has_data` is False when no snapshot is stored for it: every figure is then
    `None` - a missing night is never a night with zero rooms."""

    stay_date: date
    has_data: bool
    bookings: int | None
    rooms_on_books: int | None
    rooms_available: int | None
    occupancy_pct: Decimal | None
    room_revenue: Decimal | None
    adr: Decimal | None
    rooms_on_books_7d_ago: int | None
    rooms_delta_7d: int | None
    status: NightStatus
    decision_id: UUID | None
    # More rooms on the books than the inventory says exist. The figures above stay as stored:
    # an occupancy over 100 % is shown, never cut.
    over_capacity: bool = False


@dataclass(frozen=True, slots=True)
class InventoryConsistency:
    """Whether the bookings and the room inventory tell the same story, over the 30 nights the
    analysis day observed (the same nights whatever period the page shows).

    `over_capacity_nights` are the nights with more rooms on the books than the inventory has. It
    is a question about the data, not a verdict: the inventory may be too low, the hotel may really
    be overbooked, or a booking may be wrong, and NINFA cannot tell which. It is never a decision,
    and nothing is clamped or corrected."""

    over_capacity_nights: int
    first_night: date | None


NO_INVENTORY_INCONSISTENCY = InventoryConsistency(over_capacity_nights=0, first_night=None)


@dataclass(frozen=True, slots=True)
class OccupancyOverview:
    state: Availability
    reason: UnavailableReason | None
    today: PeriodMetrics | None
    days_7: PeriodMetrics | None
    days_30: PeriodMetrics | None
    selected: PeriodMetrics | None
    nights: tuple[NightRow, ...]
    inventory_consistency: InventoryConsistency = NO_INVENTORY_INCONSISTENCY


# --- distribution ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelWeight:
    """A channel's share of ALL the certain room-nights of the window - NOT the OTA share (a
    different denominator: the module never mixes the two)."""

    name: str
    group: ChannelGroupName
    room_nights: int
    share_pct: Decimal


@dataclass(frozen=True, slots=True)
class ChannelMix:
    """The channel weights of the 30-night window and what they are a share of.

    `total_room_nights` is the denominator of every weight: the room-nights certain at the end of
    the analysis day (Gate 3's rule, the OTA check's own population). `classified_room_nights` are
    the OTA and direct ones among them, `unclassified_room_nights` those on a channel NINFA cannot
    classify (the rest are on an identified other channel). `on_books_room_nights` is the analysis
    day's own observation of the same nights - the room-nights the page shows everywhere else -
    `None` unless it holds every night; `matches_on_books` says whether the weights are a share of
    exactly those (`None` when that observation is not whole). When it is False the weights are
    indicative: the bookings' own dates disagree with the observation (`BookingDateConflicts`)."""

    total_room_nights: int
    classified_room_nights: int
    unclassified_room_nights: int
    on_books_room_nights: int | None
    matches_on_books: bool | None
    channels: tuple[ChannelWeight, ...]


@dataclass(frozen=True, slots=True)
class BookingDateConflicts:
    """Bookings of the 30-night window whose own dates contradict the analysis day: the only ways
    the analysis day's observation (statuses as they are) and Gate 3's certainty rule at the end of
    that day can disagree about a booking. Each is a fact of the imported data that NINFA neither
    corrects nor guesses around - while any exists, the channel mix cannot be reconciled with the
    bookings on the books, and the OTA check is not evaluated.

    booked_after            on the books, with a booking date after the analysis day
    cancelled_after         cancelled, with a cancellation date after the analysis day
    no_show_before_arrival  marked as a no-show for a stay that had not begun on the analysis day
    """

    booked_after: int
    cancelled_after: int
    no_show_before_arrival: int

    @property
    def total(self) -> int:
        return self.booked_after + self.cancelled_after + self.no_show_before_arrival


@dataclass(frozen=True, slots=True)
class DistributionOverview:
    state: Availability
    reason: UnavailableReason | None
    window_start: date | None
    window_end: date | None
    outcome: OtaOutcome | None
    ota_share_pct: Decimal | None
    direct_share_pct: Decimal | None
    reference_ota_share_pct: Decimal | None
    classification_coverage_pct: Decimal | None
    insufficient_reasons: tuple[str, ...]
    decision_id: UUID | None
    channel_mix: ChannelMix | None
    # Read beside the channel mix, from the same bookings; `None` when the area was not read.
    date_conflicts: BookingDateConflicts | None
    # Why there is no verdict: the current data, or only the history they are compared with. With
    # `HISTORY` the current figures stand and these say how many past periods exist and are needed.
    insufficiency: OtaInsufficiency | None = None
    comparable_periods_available: int | None = None
    comparable_periods_required: int | None = None


# --- costs ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostCategoryRow:
    category: str
    net_cost: Decimal
    cpor: Decimal | None
    cpor_status: CporStatus
    decision_id: UUID | None


@dataclass(frozen=True, slots=True)
class CostDecisionFacts:
    decision_id: UUID
    period_start: date
    category: str
    currency: str | None
    actual_cpor: Decimal | None
    expected_cpor: Decimal | None


@dataclass(frozen=True, slots=True)
class CostOccupancyBasis:
    """What the cost per occupied room of the month rests on, day by day, and - when it cannot be
    calculated - exactly which days lack what.

    A month's denominator is the rooms on the books of every one of its days (Cost CPOR V1). Of the
    `total_days`, `known_days` have a usable snapshot (observed or reconstructed from the bookings).
    The others are, each one in ONE of these groups:

    uncertain_days            a snapshot exists but how many rooms were occupied is not known (a
                              booking cancelled or marked no-show without a date)
    days_outside_bookings     the bookings imported say nothing about that night (before the first
                              or after the last night they cover): it is unknown, not zero
    days_without_inventory    the bookings cover it but NINFA does not know how many rooms the
                              property had: a snapshot is only rebuilt once the inventory says so
    days_awaiting_rebuild     the bookings and the inventory are there: the next analysis stores it

    `first_day_without_inventory` is the day an inventory should be valid from to close that gap."""

    total_days: int
    known_days: int
    observed_days: int
    reconstructed_days: int
    uncertain_days: int
    days_outside_bookings: int
    days_without_inventory: int
    days_awaiting_rebuild: int
    first_day_without_inventory: date | None


@dataclass(frozen=True, slots=True)
class CostOverview:
    """The last CONCLUDED calendar month's costs, by invoice date (Cost CPOR V1's own attribution).

    The month in progress is never shown: invoices arrive after the fact, so a partial month is not
    a cost of the month (the same reason the cost detector only evaluates concluded months)."""

    state: Availability
    reason: UnavailableReason | None
    month_start: date
    month_end: date
    previous_month_start: date
    currency: str
    total_net_cost: Decimal | None
    previous_total_net_cost: Decimal | None
    delta_pct: Decimal | None
    other_currencies_present: bool
    classification_coverage_pct: Decimal | None
    categories: tuple[CostCategoryRow, ...]
    decision: CostDecisionFacts | None
    # `None` with no booking source to take the denominator from, or no cost in the month.
    occupancy_basis: CostOccupancyBasis | None = None


# --- labor ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaborCategoryRow:
    category: str
    planned_hours: Decimal
    days_complete: int
    days_incomplete: int
    planned_cost: Decimal | None
    # `planned_cost / planned_hours`; None when either is unknown or there are no hours.
    average_hourly_cost: Decimal | None = None
    # The share of the property's planned labor cost: None when that total is not known.
    cost_share_pct: Decimal | None = None
    # `planned_cost / the property's reference revenue * 100`. Deliberately no "revenue per hour" of
    # a role: the hotel's revenue is not produced by one department.
    revenue_incidence_pct: Decimal | None = None


class LaborRevenueGap(StrEnum):
    """Why the labor figures have no revenue beside them. A figure that cannot be compared on the
    SAME days is absent, never computed against another period."""

    NO_LABOR = "NO_LABOR"  # no day with planned hours to compare
    NO_ANALYSIS = "NO_ANALYSIS"  # no observation of the bookings for this day yet
    PERIOD_NOT_COVERED = "PERIOD_NOT_COVERED"  # a day with hours has no revenue stored
    LABOR_INCOMPLETE = "LABOR_INCOMPLETE"  # part of the plan has no hours: the ratio would flatter
    NO_REVENUE = "NO_REVENUE"  # nothing on the books for those days (a real zero: no ratio)


@dataclass(frozen=True, slots=True)
class LaborEconomics:
    """The planned labor of the window as a whole, and how it compares with the revenue of the same
    days. Every division is made here, on exact values, once: the page only formats.

    `reference_revenue` is the ON-BOOKS room revenue of exactly `period_days` (the stored OBSERVED
    snapshots of the analysis day): what is booked so far, never a forecast. `revenue_gap` says why
    it is `None`. The two ratios need it AND, for the incidence, a known cost."""

    planned_hours: Decimal | None
    planned_cost: Decimal | None
    average_hourly_cost: Decimal | None
    period_start: date | None
    period_end: date | None
    period_days: int
    reference_revenue: Decimal | None
    revenue_gap: LaborRevenueGap | None
    cost_to_revenue_pct: Decimal | None
    revenue_per_hour: Decimal | None


@dataclass(frozen=True, slots=True)
class LaborDecisionFacts:
    decision_id: UUID
    work_date: date
    category: str
    scheduled_hours: Decimal | None
    expected_hours: Decimal | None
    excess_hours: Decimal | None


@dataclass(frozen=True, slots=True)
class LaborOverview:
    """Planned hours of the next 7 days by category, from the canonical labor entries of the
    property's ONE active labor source (several or none: nothing is chosen, nothing is shown)."""

    state: Availability
    reason: UnavailableReason | None
    window_start: date
    window_end: date
    currency: str
    days_with_data: int
    categories: tuple[LaborCategoryRow, ...]
    decision: LaborDecisionFacts | None
    economics: LaborEconomics

    @property
    def window_days(self) -> int:
        """How many days the window has: what `economics.period_days` (the days the plan has hours
        for, and so the days every ratio is calculated on) is read against."""
        return (self.window_end - self.window_start).days + 1


# --- freshness / coverage -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainFreshness:
    """A FACT about one domain's data: when the latest successful import of its data source
    finished. Never a CURRENT/STALE judgement, and never a single timestamp pretending to cover
    several domains."""

    known: bool
    finished_at: datetime | None
    reason: FreshnessReason | None


@dataclass(frozen=True, slots=True)
class OverviewFreshness:
    bookings: DomainFreshness
    costs: DomainFreshness
    labor: DomainFreshness


@dataclass(frozen=True, slots=True)
class DataOverview:
    property_id: UUID
    as_of_local_date: date
    period_days: int
    currency: str
    feed_state: FeedState
    coverage: AnalysisCoverage | None
    domain_states: dict[AnalysisDomain, DomainState]
    last_successful_analysis: LastSuccessfulAnalysis | None
    freshness: OverviewFreshness
    occupancy: OccupancyOverview
    distribution: DistributionOverview
    costs: CostOverview
    labor: LaborOverview
    decisions: tuple[DecisionRef, ...]


__all__ = [
    "ALLOWED_PERIOD_DAYS",
    "COMPARISON_LOOKBACK_DAYS",
    "DATA_OVERVIEW_VERSION",
    "NO_INVENTORY_INCONSISTENCY",
    "PERIOD_DAYS_LONG",
    "PERIOD_DAYS_SHORT",
    "Availability",
    "BookingDateConflicts",
    "CapacityState",
    "ChannelGroupName",
    "ChannelMix",
    "ChannelWeight",
    "CostCategoryRow",
    "CostDecisionFacts",
    "CostOccupancyBasis",
    "CostOverview",
    "CporStatus",
    "DataOverview",
    "DecisionRef",
    "DistributionOverview",
    "DomainFreshness",
    "DomainState",
    "FreshnessReason",
    "InventoryConsistency",
    "LaborCategoryRow",
    "LaborDecisionFacts",
    "LaborEconomics",
    "LaborOverview",
    "LaborRevenueGap",
    "NightRow",
    "NightStatus",
    "OccupancyOverview",
    "OtaOutcome",
    "OverviewFreshness",
    "PeriodMetrics",
    "UnavailableReason",
]
