"""Maps the framework-free `DataOverview` into its response DTOs. Pure mapping: no calculation."""

from decimal import Decimal

from app.api.v1.data.schemas import (
    AnalysisResponse,
    ChannelMixResponse,
    ChannelWeightResponse,
    CostCategoryResponse,
    CostDecisionResponse,
    CostsResponse,
    DataOverviewResponse,
    DecisionRefResponse,
    DistributionResponse,
    DomainFreshnessResponse,
    DomainStateResponse,
    FreshnessResponse,
    LaborCategoryResponse,
    LaborDecisionResponse,
    LaborResponse,
    NightRowResponse,
    OccupancyResponse,
    PeriodMetricsResponse,
)
from app.api.v1.decisions.serializers import coverage_response_of, last_successful_analysis_of
from app.modules.data_overview.types import (
    DATA_OVERVIEW_VERSION,
    CostOverview,
    DataOverview,
    DecisionRef,
    DistributionOverview,
    DomainFreshness,
    LaborOverview,
    NightRow,
    OccupancyOverview,
    PeriodMetrics,
)
from app.modules.decisions.coverage import AnalysisDomain


def _text(value: Decimal | None) -> str | None:
    """A Decimal as plain fixed-point text ("62.50"), never scientific notation, never a float."""
    return None if value is None else format(value, "f")


def _decision_ref(ref: DecisionRef) -> DecisionRefResponse:
    return DecisionRefResponse(
        decision_id=ref.decision_id,
        decision_type=ref.decision_type,
        domain=ref.domain.value,
        target_date=ref.target_date,
        category=ref.category,
    )


def _period(period: PeriodMetrics | None) -> PeriodMetricsResponse | None:
    if period is None:
        return None
    return PeriodMetricsResponse(
        start_date=period.start_date,
        end_date=period.end_date,
        nights_requested=period.nights_requested,
        nights_with_data=period.nights_with_data,
        nights_with_capacity=period.nights_with_capacity,
        room_nights=period.room_nights,
        rooms_on_books_with_capacity=period.rooms_on_books_with_capacity,
        rooms_available=period.rooms_available,
        occupancy_pct=_text(period.occupancy_pct),
        room_revenue=_text(period.room_revenue),
        adr=_text(period.adr),
        room_nights_7d_ago=period.room_nights_7d_ago,
        room_nights_delta_7d=period.room_nights_delta_7d,
    )


def _night(night: NightRow) -> NightRowResponse:
    return NightRowResponse(
        stay_date=night.stay_date,
        has_data=night.has_data,
        bookings=night.bookings,
        rooms_on_books=night.rooms_on_books,
        rooms_available=night.rooms_available,
        occupancy_pct=_text(night.occupancy_pct),
        room_revenue=_text(night.room_revenue),
        adr=_text(night.adr),
        rooms_on_books_7d_ago=night.rooms_on_books_7d_ago,
        rooms_delta_7d=night.rooms_delta_7d,
        status=night.status.value,
        decision_id=night.decision_id,
    )


def _occupancy(occupancy: OccupancyOverview) -> OccupancyResponse:
    return OccupancyResponse(
        state=occupancy.state.value,
        reason=None if occupancy.reason is None else occupancy.reason.value,
        today=_period(occupancy.today),
        days_7=_period(occupancy.days_7),
        days_30=_period(occupancy.days_30),
        selected=_period(occupancy.selected),
        nights=[_night(night) for night in occupancy.nights],
    )


def _distribution(distribution: DistributionOverview) -> DistributionResponse:
    mix = distribution.channel_mix
    return DistributionResponse(
        state=distribution.state.value,
        reason=None if distribution.reason is None else distribution.reason.value,
        window_start=distribution.window_start,
        window_end=distribution.window_end,
        outcome=None if distribution.outcome is None else distribution.outcome.value,
        ota_share_pct=_text(distribution.ota_share_pct),
        direct_share_pct=_text(distribution.direct_share_pct),
        reference_ota_share_pct=_text(distribution.reference_ota_share_pct),
        classification_coverage_pct=_text(distribution.classification_coverage_pct),
        insufficient_reasons=list(distribution.insufficient_reasons),
        decision_id=distribution.decision_id,
        channel_mix=(
            None
            if mix is None
            else ChannelMixResponse(
                total_room_nights=mix.total_room_nights,
                channels=[
                    ChannelWeightResponse(
                        name=channel.name,
                        group=channel.group.value,
                        room_nights=channel.room_nights,
                        share_pct=_text(channel.share_pct) or "0.00",
                    )
                    for channel in mix.channels
                ],
            )
        ),
    )


def _costs(costs: CostOverview) -> CostsResponse:
    decision = costs.decision
    return CostsResponse(
        state=costs.state.value,
        reason=None if costs.reason is None else costs.reason.value,
        month_start=costs.month_start,
        month_end=costs.month_end,
        previous_month_start=costs.previous_month_start,
        currency=costs.currency,
        total_net_cost=_text(costs.total_net_cost),
        previous_total_net_cost=_text(costs.previous_total_net_cost),
        delta_pct=_text(costs.delta_pct),
        other_currencies_present=costs.other_currencies_present,
        classification_coverage_pct=_text(costs.classification_coverage_pct),
        categories=[
            CostCategoryResponse(
                category=row.category,
                net_cost=_text(row.net_cost) or "0.00",
                cpor=_text(row.cpor),
                cpor_status=row.cpor_status.value,
                decision_id=row.decision_id,
            )
            for row in costs.categories
        ],
        decision=(
            None
            if decision is None
            else CostDecisionResponse(
                decision_id=decision.decision_id,
                period_start=decision.period_start,
                category=decision.category,
                currency=decision.currency,
                actual_cpor=_text(decision.actual_cpor),
                expected_cpor=_text(decision.expected_cpor),
            )
        ),
    )


def _labor(labor: LaborOverview) -> LaborResponse:
    decision = labor.decision
    return LaborResponse(
        state=labor.state.value,
        reason=None if labor.reason is None else labor.reason.value,
        window_start=labor.window_start,
        window_end=labor.window_end,
        currency=labor.currency,
        days_with_data=labor.days_with_data,
        categories=[
            LaborCategoryResponse(
                category=row.category,
                planned_hours=_text(row.planned_hours) or "0.00",
                days_complete=row.days_complete,
                days_incomplete=row.days_incomplete,
                planned_cost=_text(row.planned_cost),
            )
            for row in labor.categories
        ],
        decision=(
            None
            if decision is None
            else LaborDecisionResponse(
                decision_id=decision.decision_id,
                work_date=decision.work_date,
                category=decision.category,
                scheduled_hours=_text(decision.scheduled_hours),
                expected_hours=_text(decision.expected_hours),
                excess_hours=_text(decision.excess_hours),
            )
        ),
    )


def _freshness(freshness: DomainFreshness) -> DomainFreshnessResponse:
    return DomainFreshnessResponse(
        status="KNOWN" if freshness.known else "UNKNOWN",
        last_successful_import_finished_at=freshness.finished_at,
        reason=None if freshness.reason is None else freshness.reason.value,
    )


def data_overview_response_of(overview: DataOverview) -> DataOverviewResponse:
    coverage_json = None if overview.coverage is None else overview.coverage.to_json()
    return DataOverviewResponse(
        property_id=overview.property_id,
        as_of_local_date=overview.as_of_local_date,
        period_days=overview.period_days,
        currency=overview.currency,
        analysis=AnalysisResponse(
            feed_state=overview.feed_state.value,
            coverage=coverage_response_of(coverage_json),
            domain_states=[
                DomainStateResponse(domain=domain.value, state=overview.domain_states[domain].value)
                for domain in AnalysisDomain
            ],
            last_successful_analysis=last_successful_analysis_of(overview.last_successful_analysis),
        ),
        freshness=FreshnessResponse(
            bookings=_freshness(overview.freshness.bookings),
            costs=_freshness(overview.freshness.costs),
            labor=_freshness(overview.freshness.labor),
        ),
        occupancy=_occupancy(overview.occupancy),
        distribution=_distribution(overview.distribution),
        costs=_costs(overview.costs),
        labor=_labor(overview.labor),
        decisions=[_decision_ref(ref) for ref in overview.decisions],
        overview_version=DATA_OVERVIEW_VERSION,
    )


__all__ = ["data_overview_response_of"]
