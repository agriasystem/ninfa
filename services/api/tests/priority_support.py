"""Builders of minimal, valid detector evaluations for the Priority Engine (Gate 10) tests.

The Priority Engine is a PURE, in-memory, zero-database service: `PriorityService.rank()` takes
plain evaluation objects, never a repository or a session. These builders construct the real
`RevenueDecisionEvaluation` / `OtaDependencyEvaluation` / `CostDecisionEvaluation` /
`LaborDecisionEvaluation` dataclasses directly (Gate 5/7/8/9's own types, never a substitute), with
sensible TRIGGERED-by-default facts, so a unit test can override only the one or two fields it is
actually exercising. This is deliberately different from a golden-scenario test (`test_priority_
golden.py`), which runs the REAL detector pipeline end to end instead of using these builders.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.intelligence.costs.types import (
    COST_THRESHOLDS,
    CostDecisionEvaluation,
    CostDecisionType,
    CostPeriodMetric,
    CostThresholds,
    MetricStatus,
)
from app.modules.intelligence.costs.types import ReasonCode as CostReasonCode
from app.modules.intelligence.distribution.types import (
    OTA_THRESHOLDS,
    OtaDecisionType,
    OtaDependencyEvaluation,
    OtaThresholds,
)
from app.modules.intelligence.distribution.types import ReasonCode as OtaReasonCode
from app.modules.intelligence.labor.types import (
    LABOR_THRESHOLDS,
    LaborDecisionEvaluation,
    LaborDecisionType,
    LaborThresholds,
    ReferenceHourlyCostSource,
)
from app.modules.intelligence.labor.types import ReasonCode as LaborReasonCode
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    OccupancyFacts,
    OccupancyThresholds,
    PickupFacts,
    PickupThresholds,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)
from app.modules.intelligence.revenue.types import (
    ReasonCode as RevenueReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory

DEFAULT_WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
DEFAULT_PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_WORKSPACE_ID = UUID("99999999-9999-9999-9999-999999999999")
OTHER_PROPERTY_ID = UUID("88888888-8888-8888-8888-888888888888")

TRIGGERED = EvaluationStatus.TRIGGERED
CLEAR = EvaluationStatus.CLEAR
INSUFFICIENT_DATA = EvaluationStatus.INSUFFICIENT_DATA
NOT_APPLICABLE = EvaluationStatus.NOT_APPLICABLE
SUPPRESSED_LOW_CONFIDENCE = EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE


# --- REV_PICKUP_LOW --------------------------------------------------------------------------


def pickup_facts(
    *,
    missing_rooms: Decimal | None = Decimal(3),
    delta_percent_exact: Decimal | None = Decimal("-25.00"),
    percent_condition: bool | None = True,
    rooms_condition: bool | None = True,
    thresholds: PickupThresholds | None = None,
) -> PickupFacts:
    return PickupFacts(
        current_rooms_on_books=40,
        rooms_available=50,
        missing_rooms=missing_rooms,
        delta_percent_exact=delta_percent_exact,
        percent_condition=percent_condition,
        rooms_condition=rooms_condition,
        thresholds=thresholds if thresholds is not None else PickupThresholds(),
    )


def pickup_evaluation(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    status: EvaluationStatus = TRIGGERED,
    snapshot_local_date: date = date(2026, 9, 1),
    stay_date: date = date(2026, 9, 8),
    confidence_score: Decimal = Decimal(80),
    facts: PickupFacts | None = None,
    revenue_gap_proxy: Decimal | None = Decimal("450.00"),
    reason_codes: tuple[RevenueReasonCode, ...] = (RevenueReasonCode.TRIGGER_PICKUP_SHORTFALL,),
    calculation_fingerprint: str = "pickup-fingerprint-1",
    target_snapshot_id: UUID | None = None,
    data_source_id: UUID | None = None,
) -> RevenueDecisionEvaluation:
    return RevenueDecisionEvaluation(
        decision_type=RevenueDecisionType.REV_PICKUP_LOW,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        data_source_id=data_source_id if data_source_id is not None else uuid4(),
        target_snapshot_id=target_snapshot_id if target_snapshot_id is not None else uuid4(),
        target_baseline_id=uuid4(),
        snapshot_local_date=snapshot_local_date,
        stay_date=stay_date,
        lead_time_days=(stay_date - snapshot_local_date).days,
        confidence_score=confidence_score,
        rules_version="revenue-decisions-v1",
        calculation_fingerprint=calculation_fingerprint,
        reason_codes=reason_codes,
        facts=facts if facts is not None else pickup_facts(),
        evidence_snapshot_ids=(),
        revenue_gap_proxy=revenue_gap_proxy,
        reference_adr=Decimal("150.00"),
        reference_adr_source=ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
    )


# --- REV_OCCUPANCY_RISK ----------------------------------------------------------------------


def occupancy_facts(
    *,
    occupancy_gap_pp_exact: Decimal | None = Decimal("15.00"),
    room_shortfall: Decimal | None = Decimal(4),
    gap_condition: bool | None = True,
    shortfall_condition: bool | None = True,
    thresholds: OccupancyThresholds | None = None,
) -> OccupancyFacts:
    return OccupancyFacts(
        current_rooms_on_books=40,
        rooms_available=50,
        occupancy_gap_pp_exact=occupancy_gap_pp_exact,
        room_shortfall=room_shortfall,
        gap_condition=gap_condition,
        shortfall_condition=shortfall_condition,
        thresholds=thresholds if thresholds is not None else OccupancyThresholds(),
    )


def occupancy_evaluation(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    status: EvaluationStatus = TRIGGERED,
    snapshot_local_date: date = date(2026, 9, 1),
    stay_date: date = date(2026, 9, 8),
    confidence_score: Decimal = Decimal(80),
    facts: OccupancyFacts | None = None,
    revenue_gap_proxy: Decimal | None = Decimal("600.00"),
    reason_codes: tuple[RevenueReasonCode, ...] = (RevenueReasonCode.TRIGGER_OCCUPANCY_GAP,),
    calculation_fingerprint: str = "occupancy-fingerprint-1",
    target_snapshot_id: UUID | None = None,
    data_source_id: UUID | None = None,
) -> RevenueDecisionEvaluation:
    return RevenueDecisionEvaluation(
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        data_source_id=data_source_id if data_source_id is not None else uuid4(),
        target_snapshot_id=target_snapshot_id if target_snapshot_id is not None else uuid4(),
        target_baseline_id=uuid4(),
        snapshot_local_date=snapshot_local_date,
        stay_date=stay_date,
        lead_time_days=(stay_date - snapshot_local_date).days,
        confidence_score=confidence_score,
        rules_version="revenue-decisions-v1",
        calculation_fingerprint=calculation_fingerprint,
        reason_codes=reason_codes,
        facts=facts if facts is not None else occupancy_facts(),
        evidence_snapshot_ids=(),
        revenue_gap_proxy=revenue_gap_proxy,
        reference_adr=Decimal("150.00"),
        reference_adr_source=ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
    )


# --- REV_OTA_DEPENDENCY ----------------------------------------------------------------------


def ota_evaluation(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    status: EvaluationStatus = TRIGGERED,
    as_of_local_date: date = date(2026, 9, 1),
    window_start: date | None = None,
    window_end: date | None = None,
    confidence_score: Decimal = Decimal(80),
    ota_share_exact: Decimal | None = Decimal(75),
    delta_pp_exact: Decimal | None = Decimal(5),
    structural_condition: bool | None = True,
    rising_condition: bool | None = False,
    ota_room_revenue_on_books_exact: Decimal | None = Decimal("1200.00"),
    reason_codes: tuple[OtaReasonCode, ...] = (OtaReasonCode.TRIGGER_STRUCTURAL_OTA_DEPENDENCY,),
    calculation_fingerprint: str = "ota-fingerprint-1",
    booking_data_source_id: UUID | None = None,
    thresholds: OtaThresholds = OTA_THRESHOLDS,
) -> OtaDependencyEvaluation:
    resolved_start = window_start if window_start is not None else as_of_local_date
    resolved_end = window_end if window_end is not None else as_of_local_date + timedelta(days=29)
    return OtaDependencyEvaluation(
        decision_type=OtaDecisionType.REV_OTA_DEPENDENCY,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=(
            booking_data_source_id if booking_data_source_id is not None else uuid4()
        ),
        as_of_local_date=as_of_local_date,
        window_start=resolved_start,
        window_end=resolved_end,
        window_days=30,
        ota_room_nights=150,
        direct_room_nights=50,
        other_room_nights=0,
        unknown_room_nights=0,
        classified_room_nights=200,
        certain_room_nights=200,
        observed_day_count=30,
        reconstructed_day_count=0,
        classification_coverage_pct_exact=Decimal(100),
        snapshot_provenance_score_exact=Decimal(100),
        ota_share_exact=ota_share_exact,
        direct_share_exact=(None if ota_share_exact is None else (Decimal(100) - ota_share_exact)),
        expected_ota_share_exact=Decimal(50),
        p25_exact=Decimal(40),
        p75_exact=Decimal(60),
        iqr_exact=Decimal(20),
        upper_fence_exact=Decimal(90),
        delta_pp_exact=delta_pp_exact,
        structural_condition=structural_condition,
        rising_condition=rising_condition,
        sample_count=10,
        fully_observed_count=10,
        approximate_count=0,
        candidate_period_count=10,
        rejected_snapshot_incomplete_count=0,
        rejected_snapshot_uncertain_count=0,
        rejected_reconciliation_count=0,
        rejected_low_classification_count=0,
        rejected_low_volume_count=0,
        baseline_confidence=Decimal(90),
        sample_score_exact=Decimal(100),
        provenance_score_exact=Decimal(100),
        classification_score_exact=Decimal(100),
        stability_score_exact=Decimal(90),
        confidence_cap=Decimal(100),
        target_quality=confidence_score,
        confidence_score=confidence_score,
        ota_room_revenue_on_books_exact=ota_room_revenue_on_books_exact,
        direct_room_revenue_on_books_exact=Decimal("400.00"),
        ota_revenue_share_exact=Decimal(75),
        thresholds=thresholds,
        reason_codes=reason_codes,
        comparable_periods=(),
        calculation_fingerprint=calculation_fingerprint,
    )


# --- COST_CPOR_ANOMALY -----------------------------------------------------------------------


def cost_metric(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    booking_data_source_id: UUID | None = None,
    period_start: date = date(2026, 8, 1),
    period_end: date = date(2026, 8, 31),
    cost_category: CostCategory = CostCategory.LAUNDRY,
    currency: str = "EUR",
    cpor_exact: Decimal | None = Decimal("6.00"),
) -> CostPeriodMetric:
    return CostPeriodMetric(
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=(
            booking_data_source_id if booking_data_source_id is not None else uuid4()
        ),
        period_start=period_start,
        period_end=period_end,
        cost_category=cost_category,
        currency=currency,
        net_cost=Decimal("1200.00"),
        absolute_category_cost=Decimal("1200.00"),
        total_absolute_cost=Decimal("2000.00"),
        classified_absolute_cost=Decimal("1900.00"),
        classification_coverage_pct_exact=Decimal(95),
        weighted_classification_confidence_exact=Decimal(95),
        occupied_room_nights=200,
        observed_day_count=31,
        reconstructed_day_count=0,
        missing_day_count=0,
        uncertain_day_count=0,
        occupancy_provenance_score_exact=Decimal(100),
        invoice_count=5,
        line_count=8,
        credit_note_line_count=0,
        credit_note_cost=Decimal(0),
        cpor_exact=cpor_exact,
        status=MetricStatus.READY,
        reason_codes=(),
        calculation_fingerprint="cost-metric-fingerprint-1",
    )


def cost_evaluation(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    status: EvaluationStatus = TRIGGERED,
    target_period_start: date = date(2026, 8, 1),
    target_period_end: date = date(2026, 8, 31),
    cost_category: CostCategory = CostCategory.LAUNDRY,
    currency: str = "EUR",
    confidence_score: Decimal = Decimal(80),
    delta_percent_exact: Decimal | None = Decimal("40.00"),
    upper_fence_exact: Decimal | None = Decimal("4.00"),
    actual_cpor_exact: Decimal | None = Decimal("6.00"),
    cost_gap_proxy_exact: Decimal | None = Decimal("1100.00"),
    reason_codes: tuple[CostReasonCode, ...] = (CostReasonCode.TRIGGER_CPOR_ANOMALY,),
    calculation_fingerprint: str = "cost-fingerprint-1",
    booking_data_source_id: UUID | None = None,
    all_conditions: bool = True,
    thresholds: CostThresholds = COST_THRESHOLDS,
) -> CostDecisionEvaluation:
    metric = cost_metric(
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        period_start=target_period_start,
        period_end=target_period_end,
        cost_category=cost_category,
        currency=currency,
        cpor_exact=actual_cpor_exact,
    )
    return CostDecisionEvaluation(
        decision_type=CostDecisionType.COST_CPOR_ANOMALY,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=metric.booking_data_source_id,
        target_period_start=target_period_start,
        target_period_end=target_period_end,
        cost_category=cost_category,
        currency=currency,
        target_metric=metric,
        expected_cpor_exact=Decimal("3.25"),
        p25_exact=Decimal("2.75"),
        p75_exact=Decimal("3.75"),
        iqr_exact=Decimal("1.00"),
        upper_fence_exact=upper_fence_exact,
        delta_cpor_exact=Decimal("2.75"),
        delta_percent_exact=delta_percent_exact,
        expected_cost_for_target_volume_exact=Decimal("650.00"),
        cost_gap_proxy_exact=cost_gap_proxy_exact,
        above_expected_condition=all_conditions,
        relative_condition=all_conditions,
        upper_fence_condition=all_conditions,
        gap_condition=all_conditions,
        sample_count=10,
        observed_period_count=10,
        approximate_period_count=0,
        candidate_month_count=10,
        rejected_no_cost_data_count=0,
        rejected_low_classification_count=0,
        rejected_incomplete_occupancy_count=0,
        rejected_zero_occupancy_count=0,
        baseline_confidence=Decimal(90),
        sample_score_exact=Decimal(100),
        provenance_score_exact=Decimal(100),
        classification_score_exact=Decimal(100),
        stability_score_exact=Decimal(90),
        confidence_cap=Decimal(100),
        target_quality=confidence_score,
        confidence_score=confidence_score,
        thresholds=thresholds,
        reason_codes=reason_codes,
        comparable_periods=(),
        calculation_fingerprint=calculation_fingerprint,
    )


# --- LABOR_OVERSTAFFING -----------------------------------------------------------------------


def labor_evaluation(
    *,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    property_id: UUID = DEFAULT_PROPERTY_ID,
    status: EvaluationStatus = TRIGGERED,
    target_as_of_date: date = date(2026, 9, 1),
    target_work_date: date = date(2026, 9, 8),
    labor_category: LaborCategory = LaborCategory.HOUSEKEEPING,
    confidence_score: Decimal = Decimal(80),
    delta_percent_exact: Decimal | None = Decimal("40.00"),
    excess_hours_exact: Decimal | None = Decimal(8),
    labor_cost_gap_proxy_exact: Decimal | None = Decimal("200.00"),
    cost_currency: str | None = "EUR",
    reason_codes: tuple[LaborReasonCode, ...] = (LaborReasonCode.TRIGGER_LABOR_OVERSTAFFING,),
    calculation_fingerprint: str = "labor-fingerprint-1",
    booking_data_source_id: UUID | None = None,
    labor_data_source_id: UUID | None = None,
    target_booking_snapshot_id: UUID | None = None,
    target_labor_snapshot_id: UUID | None = None,
    all_conditions: bool = True,
    thresholds: LaborThresholds = LABOR_THRESHOLDS,
) -> LaborDecisionEvaluation:
    return LaborDecisionEvaluation(
        decision_type=LaborDecisionType.LABOR_OVERSTAFFING,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=(
            booking_data_source_id if booking_data_source_id is not None else uuid4()
        ),
        labor_data_source_id=(
            labor_data_source_id if labor_data_source_id is not None else uuid4()
        ),
        target_booking_snapshot_id=(
            target_booking_snapshot_id if target_booking_snapshot_id is not None else uuid4()
        ),
        target_labor_snapshot_id=(
            target_labor_snapshot_id if target_labor_snapshot_id is not None else uuid4()
        ),
        target_as_of_date=target_as_of_date,
        target_work_date=target_work_date,
        labor_category=labor_category,
        forecast_rooms_exact=Decimal(40),
        demand_confidence=Decimal(95),
        scheduled_hours_exact=Decimal(28),
        classification_coverage_pct_exact=Decimal(95),
        target_category_classification_confidence_exact=Decimal(95),
        target_plan_quality=Decimal(95),
        expected_labor_hours_exact=Decimal(20),
        p25_exact=Decimal(18),
        p75_exact=Decimal(22),
        iqr_exact=Decimal(4),
        upper_fence_hours_exact=Decimal(26),
        excess_hours_exact=excess_hours_exact,
        delta_percent_exact=delta_percent_exact,
        above_expected_condition=all_conditions,
        relative_condition=all_conditions,
        excess_hours_condition=all_conditions,
        upper_fence_condition=all_conditions,
        sample_count=10,
        fully_observed_count=10,
        approximate_count=0,
        candidate_day_count=10,
        rejected_occupancy_incomplete_count=0,
        rejected_demand_mismatch_count=0,
        rejected_labor_missing_count=0,
        rejected_labor_incomplete_count=0,
        rejected_low_classification_count=0,
        baseline_confidence=Decimal(90),
        sample_score_exact=Decimal(100),
        provenance_score_exact=Decimal(100),
        classification_score_exact=Decimal(100),
        stability_score_exact=Decimal(90),
        confidence_cap=Decimal(100),
        confidence_score=confidence_score,
        reference_hourly_cost_exact=Decimal("25.00"),
        reference_hourly_cost_source=ReferenceHourlyCostSource.HISTORICAL_ACTUAL_MEDIAN_RATE,
        cost_currency=cost_currency,
        labor_cost_gap_proxy_exact=labor_cost_gap_proxy_exact,
        thresholds=thresholds,
        reason_codes=reason_codes,
        comparable_days=(),
        calculation_fingerprint=calculation_fingerprint,
    )
