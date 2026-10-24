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


class OtaOutcome(StrEnum):
    """What the OTA check concluded (the persisted decision, or NINFA's own live evaluation)."""

    DECISION = "DECISION"
    CLEAR = "CLEAR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SUPPRESSED = "SUPPRESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CHANGED_AFTER_ANALYSIS = "CHANGED_AFTER_ANALYSIS"


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
    """

    start_date: date
    end_date: date
    nights_requested: int
    nights_with_data: int
    nights_with_capacity: int
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


@dataclass(frozen=True, slots=True)
class OccupancyOverview:
    state: Availability
    reason: UnavailableReason | None
    today: PeriodMetrics | None
    days_7: PeriodMetrics | None
    days_30: PeriodMetrics | None
    selected: PeriodMetrics | None
    nights: tuple[NightRow, ...]


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
    total_room_nights: int
    channels: tuple[ChannelWeight, ...]


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


# --- labor ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaborCategoryRow:
    category: str
    planned_hours: Decimal
    days_complete: int
    days_incomplete: int
    planned_cost: Decimal | None


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
    "PERIOD_DAYS_LONG",
    "PERIOD_DAYS_SHORT",
    "Availability",
    "ChannelGroupName",
    "ChannelMix",
    "ChannelWeight",
    "CostCategoryRow",
    "CostDecisionFacts",
    "CostOverview",
    "CporStatus",
    "DataOverview",
    "DecisionRef",
    "DistributionOverview",
    "DomainFreshness",
    "DomainState",
    "FreshnessReason",
    "LaborCategoryRow",
    "LaborDecisionFacts",
    "LaborOverview",
    "NightRow",
    "NightStatus",
    "OccupancyOverview",
    "OtaOutcome",
    "OverviewFreshness",
    "PeriodMetrics",
    "UnavailableReason",
]
