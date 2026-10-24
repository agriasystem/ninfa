"""Dati overview API V1 response DTOs (see docs/architecture/data-ui-v1.md).

Every Decimal is a canonical STRING with two decimals (never a float): JavaScript's `Number` must
not carry a business figure, and the frontend only ever formats these for display. A figure that
cannot be calculated safely is `null` with a stated `reason` - never `0`. Nothing here is a model's
output.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.api.v1.decisions.schemas import AnalysisCoverageResponse, LastSuccessfulAnalysisResponse

# --- decisions ---------------------------------------------------------------------------------


class DecisionRefResponse(BaseModel):
    decision_id: UUID
    decision_type: str
    domain: str
    target_date: date | None
    category: str | None


# --- occupancy / bookings ----------------------------------------------------------------------


class PeriodMetricsResponse(BaseModel):
    start_date: date
    end_date: date
    nights_requested: int
    nights_with_data: int
    nights_with_capacity: int
    room_nights: int | None
    rooms_on_books_with_capacity: int | None
    rooms_available: int | None
    occupancy_pct: str | None
    room_revenue: str | None
    adr: str | None
    room_nights_7d_ago: int | None
    room_nights_delta_7d: int | None


class NightRowResponse(BaseModel):
    stay_date: date
    has_data: bool
    bookings: int | None
    rooms_on_books: int | None
    rooms_available: int | None
    occupancy_pct: str | None
    room_revenue: str | None
    adr: str | None
    rooms_on_books_7d_ago: int | None
    rooms_delta_7d: int | None
    status: str
    decision_id: UUID | None


class OccupancyResponse(BaseModel):
    state: str
    reason: str | None
    today: PeriodMetricsResponse | None
    days_7: PeriodMetricsResponse | None
    days_30: PeriodMetricsResponse | None
    selected: PeriodMetricsResponse | None
    nights: list[NightRowResponse]


# --- distribution ------------------------------------------------------------------------------


class ChannelWeightResponse(BaseModel):
    name: str
    group: str
    room_nights: int
    share_pct: str


class ChannelMixResponse(BaseModel):
    total_room_nights: int
    channels: list[ChannelWeightResponse]


class DistributionResponse(BaseModel):
    state: str
    reason: str | None
    window_start: date | None
    window_end: date | None
    outcome: str | None
    ota_share_pct: str | None
    direct_share_pct: str | None
    reference_ota_share_pct: str | None
    classification_coverage_pct: str | None
    insufficient_reasons: list[str]
    decision_id: UUID | None
    channel_mix: ChannelMixResponse | None


# --- costs -------------------------------------------------------------------------------------


class CostCategoryResponse(BaseModel):
    category: str
    net_cost: str
    cpor: str | None
    cpor_status: str
    decision_id: UUID | None


class CostDecisionResponse(BaseModel):
    decision_id: UUID
    period_start: date
    category: str
    currency: str | None
    actual_cpor: str | None
    expected_cpor: str | None


class CostsResponse(BaseModel):
    state: str
    reason: str | None
    month_start: date
    month_end: date
    previous_month_start: date
    currency: str
    total_net_cost: str | None
    previous_total_net_cost: str | None
    delta_pct: str | None
    other_currencies_present: bool
    classification_coverage_pct: str | None
    categories: list[CostCategoryResponse]
    decision: CostDecisionResponse | None


# --- labor -------------------------------------------------------------------------------------


class LaborCategoryResponse(BaseModel):
    category: str
    planned_hours: str
    days_complete: int
    days_incomplete: int
    planned_cost: str | None


class LaborDecisionResponse(BaseModel):
    decision_id: UUID
    work_date: date
    category: str
    scheduled_hours: str | None
    expected_hours: str | None
    excess_hours: str | None


class LaborResponse(BaseModel):
    state: str
    reason: str | None
    window_start: date
    window_end: date
    currency: str
    days_with_data: int
    categories: list[LaborCategoryResponse]
    decision: LaborDecisionResponse | None


# --- freshness / analysis ----------------------------------------------------------------------


class DomainFreshnessResponse(BaseModel):
    """`KNOWN` only states when the latest successful import of the domain's source finished - a
    fact, never "current" or "stale"."""

    status: str
    last_successful_import_finished_at: datetime | None
    reason: str | None


class FreshnessResponse(BaseModel):
    bookings: DomainFreshnessResponse
    costs: DomainFreshnessResponse
    labor: DomainFreshnessResponse


class DomainStateResponse(BaseModel):
    domain: str
    state: str


class AnalysisResponse(BaseModel):
    feed_state: str
    coverage: AnalysisCoverageResponse
    domain_states: list[DomainStateResponse]
    last_successful_analysis: LastSuccessfulAnalysisResponse | None


class DataOverviewResponse(BaseModel):
    """GET /api/v1/properties/{property_id}/data/overview?as_of=YYYY-MM-DD&period=7|30."""

    property_id: UUID
    as_of_local_date: date
    period_days: int
    currency: str
    analysis: AnalysisResponse
    freshness: FreshnessResponse
    occupancy: OccupancyResponse
    distribution: DistributionResponse
    costs: CostsResponse
    labor: LaborResponse
    decisions: list[DecisionRefResponse]
    overview_version: str
