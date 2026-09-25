"""Shared helpers for the Gate 11 (Decision Persistence, Lifecycle and Memory) tests.

Two families, exactly like every other gate's own support module:

* PURE builders of minimal-but-valid source evaluations, `PriorityCandidate`s and
  `PriorityRankingResult`s (plain frozen dataclasses, literal values, no database) - used by the
  FOCUSED unit tests of identity, fingerprint, lifecycle, serialization, atomicity and
  concurrency, exactly the way `revenue_support.py`'s own `target_context()`/`make_pair()` build
  `TargetContext`/`HistoricalPair` literally.
* `sync_run(...)`: a small convenience that builds the matching `PriorityRankingResult` for a list
  of evaluations (TRIGGERED ones get a candidate, in strict input order for ranks) and calls
  `DecisionService.sync()` - so a lifecycle test can write one line per "day" instead of repeating
  the ranking boilerplate.

The GOLDEN scenario (`decision_golden_support.py`) is entirely separate and NEVER uses these
builders: it drives the real detector services and `PriorityService` end to end, exactly as the
Gate 11 prompt requires.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.core.tenant import TenantContext
from app.modules.decisions.service import DecisionService
from app.modules.decisions.types import DecisionSyncResult
from app.modules.intelligence.costs.types import (
    COST_RULES_VERSION,
    COST_THRESHOLDS,
    CostDecisionEvaluation,
    CostDecisionType,
    CostPeriodMetric,
    MetricStatus,
)
from app.modules.intelligence.distribution.types import (
    OTA_DEPENDENCY_RULES_VERSION,
    OTA_THRESHOLDS,
    OtaDecisionType,
    OtaDependencyEvaluation,
)
from app.modules.intelligence.labor.types import (
    LABOR_RULES_VERSION,
    LABOR_THRESHOLDS,
    LaborDecisionEvaluation,
    LaborDecisionType,
)
from app.modules.intelligence.priority.actionability import (
    actionability_policy_name,
    actionability_score,
)
from app.modules.intelligence.priority.fingerprint import candidate_fingerprint
from app.modules.intelligence.priority.precision import for_display
from app.modules.intelligence.priority.scoring import priority_score_display, priority_score_exact
from app.modules.intelligence.priority.types import (
    PRIORITY_RULES_VERSION,
    PriorityCandidate,
    PriorityContext,
    PriorityDecisionType,
    PriorityRankingResult,
    RankedPriorityCandidate,
)
from app.modules.intelligence.revenue.types import (
    RULES_VERSION as REVENUE_RULES_VERSION,
)
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    OccupancyFacts,
    PickupFacts,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)
from app.modules.invoices.cost_categories import CostCategory
from app.modules.labor.roles import LaborCategory

TRIGGERED = EvaluationStatus.TRIGGERED
CLEAR = EvaluationStatus.CLEAR
INSUFFICIENT = EvaluationStatus.INSUFFICIENT_DATA
NOT_APPLICABLE = EvaluationStatus.NOT_APPLICABLE
SUPPRESSED = EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE

Evaluation = (
    RevenueDecisionEvaluation
    | OtaDependencyEvaluation
    | CostDecisionEvaluation
    | LaborDecisionEvaluation
)


def fp(seed: str) -> str:
    """A syntactically valid 64-char lowercase hex fingerprint, distinct per `seed`."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()


# --- REV_PICKUP_LOW / REV_OCCUPANCY_RISK ----------------------------------------------------------


def revenue_evaluation(
    *,
    workspace_id: UUID,
    property_id: UUID,
    data_source_id: UUID,
    stay_date: date,
    snapshot_local_date: date,
    decision_type: RevenueDecisionType = RevenueDecisionType.REV_PICKUP_LOW,
    status: EvaluationStatus = TRIGGERED,
    confidence_score: Decimal = Decimal("80.00"),
    fingerprint: str | None = None,
    target_snapshot_id: UUID | None = None,
    reason_codes: tuple[Any, ...] = (),
) -> RevenueDecisionEvaluation:
    target_snapshot_id = target_snapshot_id or uuid4()
    triggered = status == TRIGGERED
    if decision_type == RevenueDecisionType.REV_PICKUP_LOW:
        facts: PickupFacts | OccupancyFacts = PickupFacts(
            current_rooms_on_books=20,
            rooms_available=40,
            missing_rooms=Decimal(3) if triggered else None,
            delta_percent_exact=Decimal("-25.00") if triggered else None,
            percent_condition=True if triggered else None,
            rooms_condition=True if triggered else None,
        )
    else:
        facts = OccupancyFacts(
            current_rooms_on_books=20,
            rooms_available=40,
            room_shortfall=Decimal(4) if triggered else None,
            occupancy_gap_pp_exact=Decimal("12.00") if triggered else None,
            gap_condition=True if triggered else None,
            shortfall_condition=False if triggered else None,
        )
    return RevenueDecisionEvaluation(
        decision_type=decision_type,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        data_source_id=data_source_id,
        target_snapshot_id=target_snapshot_id,
        target_baseline_id=uuid4(),
        snapshot_local_date=snapshot_local_date,
        stay_date=stay_date,
        lead_time_days=(stay_date - snapshot_local_date).days,
        confidence_score=confidence_score,
        rules_version=REVENUE_RULES_VERSION,
        calculation_fingerprint=fingerprint or fp(f"revenue:{decision_type}:{stay_date}:{uuid4()}"),
        reason_codes=reason_codes,
        facts=facts,
        evidence_snapshot_ids=(target_snapshot_id,),
        revenue_gap_proxy=Decimal("500.00") if triggered else None,
        reference_adr=Decimal("100.00"),
        reference_adr_source=ReferenceAdrSource.CURRENT_ON_BOOKS_ADR,
    )


# --- REV_OTA_DEPENDENCY ---------------------------------------------------------------------------


def ota_evaluation(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    as_of_local_date: date,
    window_start: date | None = None,
    window_end: date | None = None,
    status: EvaluationStatus = TRIGGERED,
    structural: bool = True,
    rising: bool = False,
    ota_share: Decimal = Decimal("75.00"),
    confidence_score: Decimal = Decimal("80.00"),
    fingerprint: str | None = None,
    reason_codes: tuple[Any, ...] = (),
) -> OtaDependencyEvaluation:
    triggered = status == TRIGGERED
    window_start = window_start or as_of_local_date
    window_end = window_end or (as_of_local_date + timedelta(days=29))
    return OtaDependencyEvaluation(
        decision_type=OtaDecisionType.REV_OTA_DEPENDENCY,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        as_of_local_date=as_of_local_date,
        window_start=window_start,
        window_end=window_end,
        window_days=30,
        ota_room_nights=24,
        direct_room_nights=10,
        other_room_nights=0,
        unknown_room_nights=0,
        classified_room_nights=34,
        certain_room_nights=34,
        observed_day_count=30,
        reconstructed_day_count=0,
        classification_coverage_pct_exact=Decimal("100.00"),
        snapshot_provenance_score_exact=Decimal("100.00"),
        ota_share_exact=ota_share if triggered else Decimal("40.00"),
        direct_share_exact=Decimal(100) - (ota_share if triggered else Decimal("40.00")),
        expected_ota_share_exact=Decimal("50.00"),
        p25_exact=Decimal("45.00"),
        p75_exact=Decimal("55.00"),
        iqr_exact=Decimal("10.00"),
        upper_fence_exact=Decimal("70.00"),
        delta_pp_exact=Decimal("25.00") if triggered else Decimal("-10.00"),
        structural_condition=structural if triggered else None,
        rising_condition=rising if triggered else None,
        sample_count=6,
        fully_observed_count=6,
        approximate_count=0,
        candidate_period_count=6,
        rejected_snapshot_incomplete_count=0,
        rejected_snapshot_uncertain_count=0,
        rejected_reconciliation_count=0,
        rejected_low_classification_count=0,
        rejected_low_volume_count=0,
        baseline_confidence=Decimal("90.00"),
        sample_score_exact=Decimal("100.00"),
        provenance_score_exact=Decimal("100.00"),
        classification_score_exact=Decimal("100.00"),
        stability_score_exact=Decimal("90.00"),
        confidence_cap=Decimal("100.00"),
        target_quality=Decimal("100.00"),
        confidence_score=confidence_score,
        ota_room_revenue_on_books_exact=None,
        direct_room_revenue_on_books_exact=None,
        ota_revenue_share_exact=None,
        thresholds=OTA_THRESHOLDS,
        reason_codes=reason_codes,
        comparable_periods=(),
        rules_version=OTA_DEPENDENCY_RULES_VERSION,
        calculation_fingerprint=fingerprint
        or fp(f"ota:{booking_data_source_id}:{as_of_local_date}:{uuid4()}"),
    )


# --- COST_CPOR_ANOMALY ----------------------------------------------------------------------------


def _cost_metric(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    period_start: date,
    period_end: date,
    cost_category: CostCategory,
    currency: str,
    triggered: bool,
) -> CostPeriodMetric:
    return CostPeriodMetric(
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        period_start=period_start,
        period_end=period_end,
        cost_category=cost_category,
        currency=currency,
        net_cost=Decimal("600.00") if triggered else Decimal("300.00"),
        absolute_category_cost=Decimal("600.00") if triggered else Decimal("300.00"),
        total_absolute_cost=Decimal("600.00") if triggered else Decimal("300.00"),
        classified_absolute_cost=Decimal("600.00") if triggered else Decimal("300.00"),
        classification_coverage_pct_exact=Decimal("100.00"),
        weighted_classification_confidence_exact=Decimal("90.00"),
        occupied_room_nights=100,
        observed_day_count=30,
        reconstructed_day_count=0,
        missing_day_count=0,
        uncertain_day_count=0,
        occupancy_provenance_score_exact=Decimal("100.00"),
        invoice_count=1,
        line_count=1,
        credit_note_line_count=0,
        credit_note_cost=Decimal("0.00"),
        cpor_exact=Decimal("6.00") if triggered else Decimal("3.00"),
        status=MetricStatus.READY,
        reason_codes=(),
    )


def cost_evaluation(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    target_period_start: date,
    cost_category: CostCategory = CostCategory.LAUNDRY,
    currency: str = "EUR",
    status: EvaluationStatus = TRIGGERED,
    confidence_score: Decimal = Decimal("80.00"),
    fingerprint: str | None = None,
    reason_codes: tuple[Any, ...] = (),
) -> CostDecisionEvaluation:
    triggered = status == TRIGGERED
    period_end = _month_end(target_period_start)
    metric = _cost_metric(
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        period_start=target_period_start,
        period_end=period_end,
        cost_category=cost_category,
        currency=currency,
        triggered=triggered,
    )
    return CostDecisionEvaluation(
        decision_type=CostDecisionType.COST_CPOR_ANOMALY,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        target_period_start=target_period_start,
        target_period_end=period_end,
        cost_category=cost_category,
        currency=currency,
        target_metric=metric,
        expected_cpor_exact=Decimal("3.25"),
        p25_exact=Decimal("3.00"),
        p75_exact=Decimal("3.50"),
        iqr_exact=Decimal("0.50"),
        upper_fence_exact=Decimal("4.25"),
        delta_cpor_exact=(Decimal("6.00") - Decimal("3.25")) if triggered else Decimal("0.00"),
        delta_percent_exact=Decimal("84.62") if triggered else Decimal("0.00"),
        expected_cost_for_target_volume_exact=Decimal("325.00"),
        cost_gap_proxy_exact=Decimal("275.00") if triggered else None,
        above_expected_condition=True if triggered else None,
        relative_condition=True if triggered else None,
        upper_fence_condition=True if triggered else None,
        gap_condition=True if triggered else None,
        sample_count=8,
        observed_period_count=8,
        approximate_period_count=0,
        candidate_month_count=8,
        rejected_no_cost_data_count=0,
        rejected_low_classification_count=0,
        rejected_incomplete_occupancy_count=0,
        rejected_zero_occupancy_count=0,
        baseline_confidence=Decimal("90.00"),
        sample_score_exact=Decimal("100.00"),
        provenance_score_exact=Decimal("100.00"),
        classification_score_exact=Decimal("90.00"),
        stability_score_exact=Decimal("90.00"),
        confidence_cap=Decimal("100.00"),
        target_quality=Decimal("100.00"),
        confidence_score=confidence_score,
        thresholds=COST_THRESHOLDS,
        reason_codes=reason_codes,
        comparable_periods=(),
        rules_version=COST_RULES_VERSION,
        calculation_fingerprint=fingerprint
        or fp(f"cost:{cost_category}:{target_period_start}:{currency}:{uuid4()}"),
    )


def _month_end(period_start: date) -> date:
    next_month = period_start.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


# --- LABOR_OVERSTAFFING ---------------------------------------------------------------------------


def labor_evaluation(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    labor_data_source_id: UUID,
    target_work_date: date,
    target_as_of_date: date | None = None,
    labor_category: LaborCategory = LaborCategory.HOUSEKEEPING,
    status: EvaluationStatus = TRIGGERED,
    confidence_score: Decimal = Decimal("80.00"),
    fingerprint: str | None = None,
    reason_codes: tuple[Any, ...] = (),
) -> LaborDecisionEvaluation:
    triggered = status == TRIGGERED
    return LaborDecisionEvaluation(
        decision_type=LaborDecisionType.LABOR_OVERSTAFFING,
        status=status,
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        labor_data_source_id=labor_data_source_id,
        target_booking_snapshot_id=uuid4(),
        target_labor_snapshot_id=uuid4(),
        target_as_of_date=target_as_of_date or target_work_date,
        target_work_date=target_work_date,
        labor_category=labor_category,
        forecast_rooms_exact=Decimal(30),
        demand_confidence=Decimal("100.00"),
        scheduled_hours_exact=Decimal("32.00") if triggered else Decimal("20.00"),
        classification_coverage_pct_exact=Decimal("100.00"),
        target_category_classification_confidence_exact=Decimal("90.00"),
        target_plan_quality=Decimal("100.00"),
        expected_labor_hours_exact=Decimal("24.00"),
        p25_exact=Decimal("22.00"),
        p75_exact=Decimal("26.00"),
        iqr_exact=Decimal("4.00"),
        upper_fence_hours_exact=Decimal("32.00"),
        excess_hours_exact=Decimal("8.00") if triggered else Decimal("0.00"),
        delta_percent_exact=Decimal("33.33") if triggered else Decimal("0.00"),
        above_expected_condition=True if triggered else None,
        relative_condition=True if triggered else None,
        excess_hours_condition=True if triggered else None,
        upper_fence_condition=True if triggered else None,
        sample_count=6,
        fully_observed_count=6,
        approximate_count=0,
        candidate_day_count=6,
        rejected_occupancy_incomplete_count=0,
        rejected_demand_mismatch_count=0,
        rejected_labor_missing_count=0,
        rejected_labor_incomplete_count=0,
        rejected_low_classification_count=0,
        baseline_confidence=Decimal("90.00"),
        sample_score_exact=Decimal("100.00"),
        provenance_score_exact=Decimal("100.00"),
        classification_score_exact=Decimal("90.00"),
        stability_score_exact=Decimal("90.00"),
        confidence_cap=Decimal("100.00"),
        confidence_score=confidence_score,
        reference_hourly_cost_exact=None,
        reference_hourly_cost_source=None,
        cost_currency=None,
        labor_cost_gap_proxy_exact=None,
        thresholds=LABOR_THRESHOLDS,
        reason_codes=reason_codes,
        comparable_days=(),
        rules_version=LABOR_RULES_VERSION,
        calculation_fingerprint=fingerprint
        or fp(f"labor:{labor_category}:{target_work_date}:{uuid4()}"),
    )


# --- Priority candidates / ranking (literal, never `PriorityService.rank()`'s own math) -----------

_DECISION_TYPE_OF = {
    RevenueDecisionType.REV_PICKUP_LOW: PriorityDecisionType.REV_PICKUP_LOW,
    RevenueDecisionType.REV_OCCUPANCY_RISK: PriorityDecisionType.REV_OCCUPANCY_RISK,
}


def _decision_type_of(evaluation: Evaluation) -> PriorityDecisionType:
    if isinstance(evaluation, RevenueDecisionEvaluation):
        return _DECISION_TYPE_OF[evaluation.decision_type]
    if isinstance(evaluation, OtaDependencyEvaluation):
        return PriorityDecisionType.REV_OTA_DEPENDENCY
    if isinstance(evaluation, CostDecisionEvaluation):
        return PriorityDecisionType.COST_CPOR_ANOMALY
    if isinstance(evaluation, LaborDecisionEvaluation):
        return PriorityDecisionType.LABOR_OVERSTAFFING
    raise TypeError(type(evaluation))


def _target_key_of(evaluation: Evaluation) -> str:
    from app.modules.decisions.identity import raw_target_key

    return raw_target_key(evaluation)


def candidate_for(
    evaluation: Evaluation,
    *,
    impact: Decimal = Decimal("80.00"),
    urgency: Decimal = Decimal("80.00"),
) -> PriorityCandidate:
    """A minimal, internally-consistent `PriorityCandidate` for ONE TRIGGERED evaluation."""
    decision_type = _decision_type_of(evaluation)
    actionability = actionability_score(decision_type)
    exact = priority_score_exact(
        impact_score=impact,
        urgency_score=urgency,
        confidence_score=evaluation.confidence_score,
        actionability_score=actionability,
    )
    fingerprint = candidate_fingerprint(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        priority_as_of_date=_as_of_of(evaluation),
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=_target_key_of(evaluation),
        impact_score_exact=impact,
        urgency_score=urgency,
        confidence_score=evaluation.confidence_score,
        actionability_score=actionability,
        priority_score_exact=exact,
        impact_basis={},
        urgency_basis={},
        source_reason_codes=(),
        priority_version=PRIORITY_RULES_VERSION,
    )
    return PriorityCandidate(
        decision_type=decision_type,
        workspace_id=evaluation.workspace_id,
        property_id=evaluation.property_id,
        priority_as_of_date=_as_of_of(evaluation),
        source_evaluation_fingerprint=evaluation.calculation_fingerprint,
        source_target_key=_target_key_of(evaluation),
        impact_score_exact=impact,
        impact_score_display=for_display(impact),
        urgency_score=urgency,
        confidence_score=evaluation.confidence_score,
        actionability_score=actionability,
        priority_score_exact=exact,
        priority_score_display=priority_score_display(exact),
        impact_basis={},
        urgency_basis={},
        actionability_policy=actionability_policy_name(),
        economic_proxy_exact=None,
        economic_proxy_currency=None,
        economic_proxy_label=None,
        source_reason_codes=(),
        calculation_fingerprint=fingerprint,
    )


def _as_of_of(evaluation: Evaluation) -> date:
    if isinstance(evaluation, RevenueDecisionEvaluation):
        return evaluation.snapshot_local_date
    if isinstance(evaluation, OtaDependencyEvaluation):
        return evaluation.as_of_local_date
    if isinstance(evaluation, LaborDecisionEvaluation):
        return evaluation.target_as_of_date
    if isinstance(evaluation, CostDecisionEvaluation):
        return evaluation.target_period_end
    raise TypeError(type(evaluation))


def ranking_result_for(
    context: PriorityContext, evaluations: Sequence[Evaluation]
) -> PriorityRankingResult:
    """A `PriorityRankingResult` whose exclusion counts and candidates match `evaluations`
    exactly: rank 1..n in INPUT order (no tie-break math - these are focused unit tests, not
    ranking tests), a TRIGGERED duplicate (same `calculation_fingerprint`) collapsed to one
    candidate exactly like `PriorityService`'s own dedup, and a REAL, deterministic
    `calculation_fingerprint` (via Gate 10's own `ranking_fingerprint`, never a random value - a
    random fingerprint here would make every "same input" idempotency test flaky by construction).
    """
    from app.modules.intelligence.priority.fingerprint import ranking_fingerprint

    counts = dict.fromkeys([EvaluationStatus.CLEAR, INSUFFICIENT, NOT_APPLICABLE, SUPPRESSED], 0)
    ranked: list[RankedPriorityCandidate] = []
    seen_fingerprints: set[str] = set()
    duplicate_input_count = 0
    for evaluation in evaluations:
        if evaluation.status == TRIGGERED:
            fingerprint = evaluation.calculation_fingerprint
            if fingerprint in seen_fingerprints:
                duplicate_input_count += 1
                continue
            seen_fingerprints.add(fingerprint)
            ranked.append(RankedPriorityCandidate(len(ranked) + 1, candidate_for(evaluation)))
        else:
            counts[evaluation.status] += 1
    result_fingerprint = ranking_fingerprint(
        workspace_id=context.workspace_id,
        property_id=context.property_id,
        as_of_local_date=context.as_of_local_date,
        ranked_candidates=tuple(ranked),
        excluded_clear_count=counts[EvaluationStatus.CLEAR],
        excluded_insufficient_count=counts[INSUFFICIENT],
        excluded_not_applicable_count=counts[NOT_APPLICABLE],
        excluded_suppressed_count=counts[SUPPRESSED],
        duplicate_input_count=duplicate_input_count,
        priority_version=PRIORITY_RULES_VERSION,
    )
    return PriorityRankingResult(
        workspace_id=context.workspace_id,
        property_id=context.property_id,
        as_of_local_date=context.as_of_local_date,
        candidate_count=len(ranked),
        excluded_clear_count=counts[EvaluationStatus.CLEAR],
        excluded_insufficient_count=counts[INSUFFICIENT],
        excluded_not_applicable_count=counts[NOT_APPLICABLE],
        excluded_suppressed_count=counts[SUPPRESSED],
        duplicate_input_count=duplicate_input_count,
        ranked_candidates=tuple(ranked),
        calculation_fingerprint=result_fingerprint,
    )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    result: DecisionSyncResult
    ranking: PriorityRankingResult


def sync_run(
    session: Any,
    tenant: TenantContext,
    context: PriorityContext,
    evaluations: Sequence[Evaluation],
) -> RunOutcome:
    """Build the matching ranking and call `DecisionService.sync()`: one line per "day" for the
    focused lifecycle tests."""
    ranking = ranking_result_for(context, evaluations)
    result = DecisionService(session, tenant).sync(context, ranking, evaluations)
    return RunOutcome(result, ranking)


__all__ = [
    "CLEAR",
    "INSUFFICIENT",
    "NOT_APPLICABLE",
    "SUPPRESSED",
    "TRIGGERED",
    "Evaluation",
    "RunOutcome",
    "candidate_for",
    "cost_evaluation",
    "fp",
    "labor_evaluation",
    "ota_evaluation",
    "ranking_result_for",
    "revenue_evaluation",
    "sync_run",
]
