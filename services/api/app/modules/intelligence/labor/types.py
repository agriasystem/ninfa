"""The vocabulary of LABOR_OVERSTAFFING V1: statuses, reasons, thresholds, facts, evaluation.

Everything here is immutable and typed. Thresholds are versioned policy of `LABOR_RULES_VERSION`
(never database rows). There is no persisted Decision: an evaluation is the OUTPUT of a pure
calculation over immutable inputs (canonical labor entries and booking snapshots).

Naming convention (the Gate 5/7 one): a field `x_exact` is the full-precision value the rules
compare and hash; `x_display` is the same number quantized to two decimals (HALF_UP) for
presentation. A display value never decides anything and never enters a fingerprint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.intelligence.labor.precision import canonical_text, display_text, for_display

# The SAME five statuses as the revenue/cost detectors: one definition, re-exported on purpose.
from app.modules.intelligence.revenue.types import EvaluationStatus as EvaluationStatus
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.models import SnapshotOrigin

LABOR_RULES_VERSION = "labor-overstaffing-v1"
LABOR_EXPECTED_VERSION = "labor-expected-v1"

# The three trigger thresholds, versioned with the rules.
LABOR_RELATIVE_THRESHOLD = Decimal(20)  # percent above the expected hours
LABOR_EXCESS_HOURS_THRESHOLD = Decimal(4)  # absolute hours above the expected hours
LABOR_IQR_MULTIPLIER = Decimal("1.5")  # upper fence = P75 + 1.5 * IQR

MIN_CLASSIFICATION_COVERAGE = Decimal(70)  # percent of planned minutes that are not OTHER
MIN_CONFIDENCE = Decimal(55)
MIN_COMPARABLES = 5
MAX_COMPARABLES = 24
LOOKBACK_DAYS = 730
SEASONAL_WINDOW_DAYS = 42
SAMPLE_SATURATION = 12  # 12 comparable days earn the full sample score
DEMAND_TOLERANCE_MIN_ROOMS = Decimal(3)
DEMAND_TOLERANCE_PERCENT = Decimal("0.20")


class LaborDecisionType(StrEnum):
    LABOR_OVERSTAFFING = "LABOR_OVERSTAFFING"


class ReasonCode(StrEnum):
    TRIGGER_LABOR_OVERSTAFFING = "TRIGGER_LABOR_OVERSTAFFING"
    CLEAR_WITHIN_EXPECTED_RANGE = "CLEAR_WITHIN_EXPECTED_RANGE"
    LABOR_CATEGORY_OTHER_NOT_ACTIONABLE = "LABOR_CATEGORY_OTHER_NOT_ACTIONABLE"
    LABOR_CATEGORY_NOT_SCHEDULED = "LABOR_CATEGORY_NOT_SCHEDULED"
    LABOR_PLAN_MISSING = "LABOR_PLAN_MISSING"
    LABOR_PLAN_INCOMPLETE = "LABOR_PLAN_INCOMPLETE"
    LABOR_CLASSIFICATION_COVERAGE_LOW = "LABOR_CLASSIFICATION_COVERAGE_LOW"
    LABOR_DEMAND_FORECAST_INSUFFICIENT = "LABOR_DEMAND_FORECAST_INSUFFICIENT"
    LABOR_COMPARABLE_SAMPLE_INSUFFICIENT = "LABOR_COMPARABLE_SAMPLE_INSUFFICIENT"
    EXPECTED_LABOR_HOURS_NON_POSITIVE = "EXPECTED_LABOR_HOURS_NON_POSITIVE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    # Request level: raised as LaborDecisionError, never carried by an evaluation. Kept here so
    # every stable reason has ONE name.
    BOOKING_DATA_SOURCE_INVALID = "BOOKING_DATA_SOURCE_INVALID"
    LABOR_DATA_SOURCE_INVALID = "LABOR_DATA_SOURCE_INVALID"


class LaborBasis(StrEnum):
    """Which field a comparable day's hours were read from (never a mix of the two)."""

    ACTUAL = "ACTUAL_LABOR"
    PLANNED_FALLBACK = "PLANNED_FALLBACK"


class ReferenceHourlyCostSource(StrEnum):
    TARGET_PLANNED_COST_RATE = "TARGET_PLANNED_COST_RATE"
    HISTORICAL_ACTUAL_MEDIAN_RATE = "HISTORICAL_ACTUAL_MEDIAN_RATE"


# Pair quality (Part D "PAIR PROVENANCE"): (labor basis, occupancy origin) -> a 0-100 score.
_PAIR_QUALITY: dict[tuple[LaborBasis, SnapshotOrigin], Decimal] = {
    (LaborBasis.ACTUAL, SnapshotOrigin.OBSERVED): Decimal(100),
    (LaborBasis.ACTUAL, SnapshotOrigin.RECONSTRUCTED_APPROXIMATE): Decimal(80),
    (LaborBasis.PLANNED_FALLBACK, SnapshotOrigin.OBSERVED): Decimal(80),
    (LaborBasis.PLANNED_FALLBACK, SnapshotOrigin.RECONSTRUCTED_APPROXIMATE): Decimal(60),
}


def pair_quality_score(basis: LaborBasis, occupancy_origin: SnapshotOrigin) -> Decimal:
    return _PAIR_QUALITY[(basis, occupancy_origin)]


def is_fully_observed_pair(basis: LaborBasis, occupancy_origin: SnapshotOrigin) -> bool:
    """FULLY_OBSERVED_COMPARABLE: ACTUAL labor + OBSERVED occupancy."""
    return basis == LaborBasis.ACTUAL and occupancy_origin == SnapshotOrigin.OBSERVED


@dataclass(frozen=True, slots=True)
class LaborThresholds:
    """LABOR_OVERSTAFFING V1: a numeric candidate needs ALL FOUR conditions (AND)."""

    relative_percent: Decimal = LABOR_RELATIVE_THRESHOLD
    excess_hours_threshold: Decimal = LABOR_EXCESS_HOURS_THRESHOLD
    iqr_multiplier: Decimal = LABOR_IQR_MULTIPLIER
    min_confidence: Decimal = MIN_CONFIDENCE
    min_classification_coverage: Decimal = MIN_CLASSIFICATION_COVERAGE
    min_comparables: int = MIN_COMPARABLES
    max_comparables: int = MAX_COMPARABLES
    lookback_days: int = LOOKBACK_DAYS
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS
    demand_tolerance_min_rooms: Decimal = DEMAND_TOLERANCE_MIN_ROOMS
    demand_tolerance_percent: Decimal = DEMAND_TOLERANCE_PERCENT

    def payload(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "relative_percent": text(self.relative_percent),
            "excess_hours_threshold": text(self.excess_hours_threshold),
            "iqr_multiplier": text(self.iqr_multiplier),
            "min_confidence": text(self.min_confidence),
            "min_classification_coverage": text(self.min_classification_coverage),
            "min_comparables": self.min_comparables,
            "max_comparables": self.max_comparables,
            "lookback_days": self.lookback_days,
            "seasonal_window_days": self.seasonal_window_days,
            "demand_tolerance_min_rooms": text(self.demand_tolerance_min_rooms),
            "demand_tolerance_percent": text(self.demand_tolerance_percent),
        }


LABOR_THRESHOLDS = LaborThresholds()


@dataclass(frozen=True, slots=True)
class ComparableDayFact:
    """One historical work date that entered the baseline, with what a person needs to audit it."""

    work_date: date
    historical_occupied_rooms: int
    occupancy_origin: SnapshotOrigin
    booking_snapshot_id: UUID
    labor_basis: LaborBasis
    labor_snapshot_id: UUID
    historical_hours_exact: Decimal
    classification_coverage_pct_exact: Decimal
    weighted_category_confidence_exact: Decimal | None
    # Only ever set on an ACTUAL-basis day (the input of the historical-actual-rate cost proxy).
    category_cost_exact: Decimal | None = None
    cost_currency: str | None = None

    @property
    def is_fully_observed(self) -> bool:
        return is_fully_observed_pair(self.labor_basis, self.occupancy_origin)

    @property
    def pair_quality(self) -> Decimal:
        return pair_quality_score(self.labor_basis, self.occupancy_origin)

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "work_date": self.work_date.isoformat(),
            "historical_occupied_rooms": self.historical_occupied_rooms,
            "occupancy_origin": self.occupancy_origin.value,
            "booking_snapshot_id": str(self.booking_snapshot_id),
            "labor_basis": self.labor_basis.value,
            "labor_snapshot_id": str(self.labor_snapshot_id),
            "historical_hours": text(self.historical_hours_exact),
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "weighted_category_confidence": text(self.weighted_category_confidence_exact),
            "pair_quality": text(self.pair_quality),
            "category_cost": text(self.category_cost_exact),
            "cost_currency": self.cost_currency,
        }

    def payload(self) -> dict[str, Any]:
        return self._body(display_text)

    def canonical_payload(self) -> dict[str, Any]:
        return self._body(canonical_text)


@dataclass(frozen=True, slots=True)
class LaborDecisionEvaluation:
    """The immutable, auditable outcome of LABOR_OVERSTAFFING for one target.

    `labor_cost_gap_proxy_exact` is a GROSS LABOR COST GAP PROXY (excess hours times a reference
    hourly rate): NOT a saving, NOT a loss, NOT a guaranteed avoidable cost. It never enters the
    trigger. `confidence_score` is 0.00 when no confidence was assessed (an early exit), never a
    real low. Every `*_exact` figure is the value the rules compared and the fingerprint hashed.
    """

    decision_type: LaborDecisionType
    status: EvaluationStatus

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    labor_data_source_id: UUID

    target_booking_snapshot_id: UUID
    target_labor_snapshot_id: UUID | None
    target_as_of_date: date
    target_work_date: date
    labor_category: LaborCategory

    forecast_rooms_exact: Decimal | None
    demand_confidence: Decimal | None

    scheduled_hours_exact: Decimal | None
    classification_coverage_pct_exact: Decimal | None
    target_category_classification_confidence_exact: Decimal | None
    target_plan_quality: Decimal | None

    expected_labor_hours_exact: Decimal | None
    p25_exact: Decimal | None
    p75_exact: Decimal | None
    iqr_exact: Decimal | None
    upper_fence_hours_exact: Decimal | None

    excess_hours_exact: Decimal | None
    delta_percent_exact: Decimal | None

    above_expected_condition: bool | None
    relative_condition: bool | None
    excess_hours_condition: bool | None
    upper_fence_condition: bool | None

    sample_count: int
    fully_observed_count: int
    approximate_count: int
    candidate_day_count: int
    rejected_occupancy_incomplete_count: int
    rejected_demand_mismatch_count: int
    rejected_labor_missing_count: int
    rejected_labor_incomplete_count: int
    rejected_low_classification_count: int

    baseline_confidence: Decimal | None
    sample_score_exact: Decimal | None
    provenance_score_exact: Decimal | None
    classification_score_exact: Decimal | None
    stability_score_exact: Decimal | None
    confidence_cap: Decimal | None
    confidence_score: Decimal

    reference_hourly_cost_exact: Decimal | None
    reference_hourly_cost_source: ReferenceHourlyCostSource | None
    cost_currency: str | None
    labor_cost_gap_proxy_exact: Decimal | None

    thresholds: LaborThresholds
    reason_codes: tuple[ReasonCode, ...]
    comparable_days: tuple[ComparableDayFact, ...]

    rules_version: str = LABOR_RULES_VERSION
    expected_method: str = LABOR_EXPECTED_VERSION
    calculation_fingerprint: str = ""

    def _display(self, value: Decimal | None) -> Decimal | None:
        return None if value is None else for_display(value)

    @property
    def scheduled_hours_display(self) -> Decimal | None:
        return self._display(self.scheduled_hours_exact)

    @property
    def expected_labor_hours_display(self) -> Decimal | None:
        return self._display(self.expected_labor_hours_exact)

    @property
    def delta_percent_display(self) -> Decimal | None:
        return self._display(self.delta_percent_exact)

    @property
    def forecast_rooms_display(self) -> Decimal | None:
        return self._display(self.forecast_rooms_exact)

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "status": self.status.value,
            "workspace_id": str(self.workspace_id),
            "property_id": str(self.property_id),
            "booking_data_source_id": str(self.booking_data_source_id),
            "labor_data_source_id": str(self.labor_data_source_id),
            "target_booking_snapshot_id": str(self.target_booking_snapshot_id),
            "target_labor_snapshot_id": (
                None
                if self.target_labor_snapshot_id is None
                else str(self.target_labor_snapshot_id)
            ),
            "target_as_of_date": self.target_as_of_date.isoformat(),
            "target_work_date": self.target_work_date.isoformat(),
            "labor_category": self.labor_category.value,
            "forecast_rooms": text(self.forecast_rooms_exact),
            "demand_confidence": text(self.demand_confidence),
            "scheduled_hours": text(self.scheduled_hours_exact),
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "target_category_classification_confidence": text(
                self.target_category_classification_confidence_exact
            ),
            "target_plan_quality": text(self.target_plan_quality),
            "expected_labor_hours": text(self.expected_labor_hours_exact),
            "p25": text(self.p25_exact),
            "p75": text(self.p75_exact),
            "iqr": text(self.iqr_exact),
            "upper_fence_hours": text(self.upper_fence_hours_exact),
            "excess_hours": text(self.excess_hours_exact),
            "delta_percent": text(self.delta_percent_exact),
            "above_expected_condition": self.above_expected_condition,
            "relative_condition": self.relative_condition,
            "excess_hours_condition": self.excess_hours_condition,
            "upper_fence_condition": self.upper_fence_condition,
            "sample_count": self.sample_count,
            "fully_observed_count": self.fully_observed_count,
            "approximate_count": self.approximate_count,
            "candidate_day_count": self.candidate_day_count,
            "rejected_occupancy_incomplete_count": self.rejected_occupancy_incomplete_count,
            "rejected_demand_mismatch_count": self.rejected_demand_mismatch_count,
            "rejected_labor_missing_count": self.rejected_labor_missing_count,
            "rejected_labor_incomplete_count": self.rejected_labor_incomplete_count,
            "rejected_low_classification_count": self.rejected_low_classification_count,
            "baseline_confidence": text(self.baseline_confidence),
            "sample_score": text(self.sample_score_exact),
            "provenance_score": text(self.provenance_score_exact),
            "classification_score": text(self.classification_score_exact),
            "stability_score": text(self.stability_score_exact),
            "confidence_cap": text(self.confidence_cap),
            "confidence_score": text(self.confidence_score),
            "reference_hourly_cost": text(self.reference_hourly_cost_exact),
            "reference_hourly_cost_source": (
                None
                if self.reference_hourly_cost_source is None
                else self.reference_hourly_cost_source.value
            ),
            "cost_currency": self.cost_currency,
            "labor_cost_gap_proxy": text(self.labor_cost_gap_proxy_exact),
            "thresholds": self.thresholds.payload(text),
            "reason_codes": [code.value for code in self.reason_codes],
            "comparable_days": [
                day.payload() if text is display_text else day.canonical_payload()
                for day in self.comparable_days
            ],
            "rules_version": self.rules_version,
            "expected_method": self.expected_method,
        }

    def payload(self) -> dict[str, Any]:
        """The presentation: every fact a person needs to audit the evaluation, two decimals.

        This is data, not language: there is no generated text.
        """
        return self._body(display_text) | {"calculation_fingerprint": self.calculation_fingerprint}

    def canonical_payload(self) -> dict[str, Any]:
        """Non-lossy Decimals and no display-only figure: what the fingerprint hashes."""
        return self._body(canonical_text)
