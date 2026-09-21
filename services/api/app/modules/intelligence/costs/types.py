"""The vocabulary of Cost CPOR Anomaly Detection V1: statuses, reasons, thresholds, metric, facts.

Everything here is immutable and typed. Thresholds are versioned policy of `COST_RULES_VERSION`
(never database rows). There is no persisted Decision: an evaluation is the OUTPUT of a pure
calculation over immutable inputs (canonical invoice lines and lead-time-0 booking snapshots).

Naming convention (the Gate 5 one): a field `x_exact` is the full-precision value the rules
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

from app.modules.intelligence.costs.precision import canonical_text, display_text, for_display

# The SAME five statuses as the revenue detectors: one definition, re-exported on purpose.
from app.modules.intelligence.revenue.types import EvaluationStatus as EvaluationStatus
from app.modules.invoices.cost_categories import CostCategory

COST_RULES_VERSION = "cost-cpor-anomaly-v1"
COST_METRIC_VERSION = "cost-period-metric-v1"
COST_EXPECTED_METHOD = "cost-cpor-expected-v1"

# Explicit V1 policies (documented, never inferred).
COST_ATTRIBUTION_POLICY = "INVOICE_DATE_ATTRIBUTION"
OCCUPANCY_PROXY_POLICY = "LEAD_TIME_0_ROOMS_ON_BOOKS_PROXY"

# The three trigger thresholds, versioned with the rules.
CPOR_RELATIVE_THRESHOLD = Decimal(20)  # percent above the expected CPOR
CPOR_ABSOLUTE_GAP_THRESHOLD = Decimal(100)  # currency units of gross cost gap
CPOR_IQR_MULTIPLIER = Decimal("1.5")  # upper fence = P75 + 1.5 * IQR

MIN_CLASSIFICATION_COVERAGE = Decimal(70)  # percent of the absolute cost that is not OTHER
MIN_CONFIDENCE = Decimal(55)
MIN_COMPARABLES = 5
MAX_COMPARABLES = 12
LOOKBACK_MONTHS = 36
SEASON_WINDOW_MONTHS = 2  # circular distance on the 12-month circle
SAMPLE_SATURATION = 8  # 8 comparables earn the full sample score


class CostDecisionType(StrEnum):
    COST_CPOR_ANOMALY = "COST_CPOR_ANOMALY"


class MetricStatus(StrEnum):
    """What a period metric is fit for. Only READY has a CPOR."""

    READY = "READY"
    # No invoice line of the category (or of the currency) exists in the month: NOT a zero cost.
    NO_COST_DATA = "NO_COST_DATA"
    # A lead-time-0 snapshot is missing or uncertain for at least one day of the month.
    INCOMPLETE = "INCOMPLETE"
    # The month is complete but has no occupied room night: CPOR is undefined, never divided.
    ZERO_OCCUPANCY = "ZERO_OCCUPANCY"
    # Too much of the month's cost is OTHER (or the coverage is undefined) to trust a category.
    LOW_CLASSIFICATION_COVERAGE = "LOW_CLASSIFICATION_COVERAGE"


class ReasonCode(StrEnum):
    TRIGGER_CPOR_ANOMALY = "TRIGGER_CPOR_ANOMALY"
    CLEAR_WITHIN_EXPECTED_RANGE = "CLEAR_WITHIN_EXPECTED_RANGE"
    COST_CATEGORY_OTHER_NOT_ACTIONABLE = "COST_CATEGORY_OTHER_NOT_ACTIONABLE"
    COST_CLASSIFICATION_COVERAGE_LOW = "COST_CLASSIFICATION_COVERAGE_LOW"
    COST_CLASSIFICATION_COVERAGE_UNDEFINED = "COST_CLASSIFICATION_COVERAGE_UNDEFINED"
    OCCUPANCY_PERIOD_INCOMPLETE = "OCCUPANCY_PERIOD_INCOMPLETE"
    ZERO_OCCUPIED_ROOM_NIGHTS = "ZERO_OCCUPIED_ROOM_NIGHTS"
    EXPECTED_CPOR_NON_POSITIVE = "EXPECTED_CPOR_NON_POSITIVE"
    COMPARABLE_SAMPLE_INSUFFICIENT = "COMPARABLE_SAMPLE_INSUFFICIENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    # Request level: raised as CostDecisionError, never carried by an evaluation (an invalid data
    # source cannot produce one). Kept here so every stable reason has ONE name.
    BOOKING_DATA_SOURCE_INVALID = "BOOKING_DATA_SOURCE_INVALID"
    # Nothing was invoiced in this currency in the month (NOT a zero cost) ...
    COST_CURRENCY_NOT_PRESENT = "COST_CURRENCY_NOT_PRESENT"
    # ... or in this currency but not in this category.
    COST_CATEGORY_NOT_PRESENT = "COST_CATEGORY_NOT_PRESENT"


@dataclass(frozen=True, slots=True)
class CostThresholds:
    """COST_CPOR_ANOMALY V1: a numeric candidate needs ALL of the three conditions (AND)."""

    relative_percent: Decimal = CPOR_RELATIVE_THRESHOLD
    absolute_gap: Decimal = CPOR_ABSOLUTE_GAP_THRESHOLD
    iqr_multiplier: Decimal = CPOR_IQR_MULTIPLIER
    min_confidence: Decimal = MIN_CONFIDENCE
    min_classification_coverage: Decimal = MIN_CLASSIFICATION_COVERAGE
    min_comparables: int = MIN_COMPARABLES
    max_comparables: int = MAX_COMPARABLES
    lookback_months: int = LOOKBACK_MONTHS
    season_window_months: int = SEASON_WINDOW_MONTHS

    def payload(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "relative_percent": text(self.relative_percent),
            "absolute_gap": text(self.absolute_gap),
            "iqr_multiplier": text(self.iqr_multiplier),
            "min_confidence": text(self.min_confidence),
            "min_classification_coverage": text(self.min_classification_coverage),
            "min_comparables": self.min_comparables,
            "max_comparables": self.max_comparables,
            "lookback_months": self.lookback_months,
            "season_window_months": self.season_window_months,
        }


COST_THRESHOLDS = CostThresholds()


@dataclass(frozen=True, slots=True)
class MonthlyCostAggregate:
    """The canonical invoice lines of ONE (month, currency, category), summed by the database.

    A month is the month of `Invoice.invoice_date` (INVOICE_DATE_ATTRIBUTION). Amounts are the
    signed Gate 6 `line_total`: a credit note is already negative and is never re-signed here.
    """

    month: date  # the first day of the month
    currency: str
    cost_category: CostCategory
    net_cost: Decimal  # SUM(line_total)
    absolute_cost: Decimal  # SUM(abs(line_total))
    confidence_weighted_cost: Decimal  # SUM(abs(line_total) * classification_confidence)
    invoice_count: int  # distinct canonical invoices with a line here
    line_count: int
    credit_note_line_count: int
    credit_note_cost: Decimal  # SUM(line_total) of the credit-note lines (<= 0)


@dataclass(frozen=True, slots=True)
class OccupancyDenominator:
    """The occupied-room-night PROXY of one month: lead-time-0 `rooms_on_books`, day by day.

    `occupied_room_nights` and the provenance score exist only when EVERY day of the month has a
    usable snapshot (present, and with no uncertain room). A missing day is never zero rooms.
    """

    total_days: int
    observed_day_count: int
    reconstructed_day_count: int
    missing_day_count: int
    uncertain_day_count: int
    occupied_room_nights: int | None
    occupancy_provenance_score_exact: Decimal | None

    @property
    def complete(self) -> bool:
        return self.missing_day_count == 0 and self.uncertain_day_count == 0


@dataclass(frozen=True, slots=True)
class CostPeriodMetric:
    """The cost per occupied room of ONE category and currency in ONE calendar month.

    NOT a database model and never persisted. `cpor_exact` exists only for a READY metric.
    `net_cost` is signed (credit notes reduce it and it can be zero or negative: a valid figure);
    `absolute_category_cost` uses `abs` and says whether there was any economic activity at all.
    The cost fields are `None` when there is NO invoice line (no cost is not a zero cost).
    """

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    period_start: date
    period_end: date
    cost_category: CostCategory
    currency: str

    net_cost: Decimal | None
    absolute_category_cost: Decimal | None
    total_absolute_cost: Decimal | None  # every category of the currency, OTHER included
    classified_absolute_cost: Decimal | None  # every category but OTHER

    classification_coverage_pct_exact: Decimal | None
    weighted_classification_confidence_exact: Decimal | None

    occupied_room_nights: int | None
    observed_day_count: int
    reconstructed_day_count: int
    missing_day_count: int
    uncertain_day_count: int
    occupancy_provenance_score_exact: Decimal | None

    invoice_count: int
    line_count: int
    credit_note_line_count: int
    credit_note_cost: Decimal | None

    cpor_exact: Decimal | None
    status: MetricStatus
    reason_codes: tuple[ReasonCode, ...]
    calculation_version: str = COST_METRIC_VERSION
    calculation_fingerprint: str = ""

    @property
    def cpor_display(self) -> Decimal | None:
        return None if self.cpor_exact is None else for_display(self.cpor_exact)

    @property
    def classification_coverage_pct_display(self) -> Decimal | None:
        value = self.classification_coverage_pct_exact
        return None if value is None else for_display(value)

    @property
    def weighted_classification_confidence_display(self) -> Decimal | None:
        value = self.weighted_classification_confidence_exact
        return None if value is None else for_display(value)

    @property
    def occupancy_provenance_score_display(self) -> Decimal | None:
        value = self.occupancy_provenance_score_exact
        return None if value is None else for_display(value)

    @property
    def is_fully_observed(self) -> bool:
        """FULLY_OBSERVED_PERIOD: no day of the month rests on a reconstruction."""
        return self.reconstructed_day_count == 0

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "property_id": str(self.property_id),
            "booking_data_source_id": str(self.booking_data_source_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "cost_category": self.cost_category.value,
            "currency": self.currency,
            "cost_attribution": COST_ATTRIBUTION_POLICY,
            "occupancy_proxy": OCCUPANCY_PROXY_POLICY,
            "net_cost": text(self.net_cost),
            "absolute_category_cost": text(self.absolute_category_cost),
            "total_absolute_cost": text(self.total_absolute_cost),
            "classified_absolute_cost": text(self.classified_absolute_cost),
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "weighted_classification_confidence": text(
                self.weighted_classification_confidence_exact
            ),
            "occupied_room_nights": self.occupied_room_nights,
            "observed_day_count": self.observed_day_count,
            "reconstructed_day_count": self.reconstructed_day_count,
            "missing_day_count": self.missing_day_count,
            "uncertain_day_count": self.uncertain_day_count,
            "occupancy_provenance_score": text(self.occupancy_provenance_score_exact),
            "invoice_count": self.invoice_count,
            "line_count": self.line_count,
            "credit_note_line_count": self.credit_note_line_count,
            "credit_note_cost": text(self.credit_note_cost),
            "cpor": text(self.cpor_exact),
            "status": self.status.value,
            "reason_codes": [code.value for code in self.reason_codes],
            "calculation_version": self.calculation_version,
        }

    def payload(self) -> dict[str, Any]:
        """The presentation of the metric (two-decimal figures)."""
        return self._body(display_text)

    def canonical_payload(self) -> dict[str, Any]:
        """Non-lossy Decimals and no display-only figure: what the fingerprint hashes."""
        return self._body(canonical_text)


@dataclass(frozen=True, slots=True)
class ComparablePeriodFact:
    """One historical month that entered the baseline, with what a person needs to audit it."""

    period_start: date
    period_end: date
    cpor_exact: Decimal
    net_cost: Decimal
    absolute_category_cost: Decimal
    occupied_room_nights: int
    observed_day_count: int
    reconstructed_day_count: int
    occupancy_provenance_score_exact: Decimal
    classification_coverage_pct_exact: Decimal
    weighted_classification_confidence_exact: Decimal | None
    invoice_count: int
    line_count: int

    @property
    def is_fully_observed(self) -> bool:
        return self.reconstructed_day_count == 0

    @classmethod
    def of(cls, metric: CostPeriodMetric) -> "ComparablePeriodFact":
        assert metric.cpor_exact is not None and metric.net_cost is not None
        assert metric.absolute_category_cost is not None
        assert metric.occupied_room_nights is not None
        assert metric.occupancy_provenance_score_exact is not None
        assert metric.classification_coverage_pct_exact is not None
        return cls(
            period_start=metric.period_start,
            period_end=metric.period_end,
            cpor_exact=metric.cpor_exact,
            net_cost=metric.net_cost,
            absolute_category_cost=metric.absolute_category_cost,
            occupied_room_nights=metric.occupied_room_nights,
            observed_day_count=metric.observed_day_count,
            reconstructed_day_count=metric.reconstructed_day_count,
            occupancy_provenance_score_exact=metric.occupancy_provenance_score_exact,
            classification_coverage_pct_exact=metric.classification_coverage_pct_exact,
            weighted_classification_confidence_exact=(
                metric.weighted_classification_confidence_exact
            ),
            invoice_count=metric.invoice_count,
            line_count=metric.line_count,
        )

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "cpor": text(self.cpor_exact),
            "net_cost": text(self.net_cost),
            "absolute_category_cost": text(self.absolute_category_cost),
            "occupied_room_nights": self.occupied_room_nights,
            "observed_day_count": self.observed_day_count,
            "reconstructed_day_count": self.reconstructed_day_count,
            "occupancy_provenance_score": text(self.occupancy_provenance_score_exact),
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "weighted_classification_confidence": text(
                self.weighted_classification_confidence_exact
            ),
            "invoice_count": self.invoice_count,
            "line_count": self.line_count,
        }

    def payload(self) -> dict[str, Any]:
        return self._body(display_text)

    def canonical_payload(self) -> dict[str, Any]:
        return self._body(canonical_text)


@dataclass(frozen=True, slots=True)
class CostDecisionEvaluation:
    """The immutable, auditable outcome of COST_CPOR_ANOMALY for one target.

    `cost_gap_proxy_exact` is a GROSS COST GAP PROXY (the target cost above what the historical
    CPOR would have cost at the target's own volume): NOT a loss, NOT a guaranteed saving, NOT a
    recoverable cost and NOT an economic impact. It is filled whenever the baseline exists.

    `confidence_score` is 0.00 when no confidence was assessed (an early exit), never a real low.
    Every `*_exact` figure is the value the rules compared and the fingerprint hashed.
    """

    decision_type: CostDecisionType
    status: EvaluationStatus

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    target_period_start: date
    target_period_end: date
    cost_category: CostCategory
    currency: str

    target_metric: CostPeriodMetric

    expected_cpor_exact: Decimal | None
    p25_exact: Decimal | None
    p75_exact: Decimal | None
    iqr_exact: Decimal | None
    upper_fence_exact: Decimal | None

    delta_cpor_exact: Decimal | None
    delta_percent_exact: Decimal | None
    expected_cost_for_target_volume_exact: Decimal | None
    cost_gap_proxy_exact: Decimal | None

    above_expected_condition: bool | None
    relative_condition: bool | None
    upper_fence_condition: bool | None
    gap_condition: bool | None

    sample_count: int
    observed_period_count: int
    approximate_period_count: int
    candidate_month_count: int
    rejected_no_cost_data_count: int
    rejected_low_classification_count: int
    rejected_incomplete_occupancy_count: int
    rejected_zero_occupancy_count: int

    baseline_confidence: Decimal | None
    sample_score_exact: Decimal | None
    provenance_score_exact: Decimal | None
    classification_score_exact: Decimal | None
    stability_score_exact: Decimal | None
    confidence_cap: Decimal | None
    target_quality: Decimal | None
    confidence_score: Decimal

    thresholds: CostThresholds
    reason_codes: tuple[ReasonCode, ...]
    comparable_periods: tuple[ComparablePeriodFact, ...]

    rules_version: str = COST_RULES_VERSION
    metric_version: str = COST_METRIC_VERSION
    expected_method: str = COST_EXPECTED_METHOD
    calculation_fingerprint: str = ""

    def _display(self, value: Decimal | None) -> Decimal | None:
        return None if value is None else for_display(value)

    @property
    def expected_cpor_display(self) -> Decimal | None:
        return self._display(self.expected_cpor_exact)

    @property
    def p25_display(self) -> Decimal | None:
        return self._display(self.p25_exact)

    @property
    def p75_display(self) -> Decimal | None:
        return self._display(self.p75_exact)

    @property
    def iqr_display(self) -> Decimal | None:
        return self._display(self.iqr_exact)

    @property
    def upper_fence_display(self) -> Decimal | None:
        return self._display(self.upper_fence_exact)

    @property
    def delta_cpor_display(self) -> Decimal | None:
        return self._display(self.delta_cpor_exact)

    @property
    def delta_percent_display(self) -> Decimal | None:
        return self._display(self.delta_percent_exact)

    @property
    def expected_cost_for_target_volume_display(self) -> Decimal | None:
        return self._display(self.expected_cost_for_target_volume_exact)

    @property
    def cost_gap_proxy_display(self) -> Decimal | None:
        return self._display(self.cost_gap_proxy_exact)

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "status": self.status.value,
            "workspace_id": str(self.workspace_id),
            "property_id": str(self.property_id),
            "booking_data_source_id": str(self.booking_data_source_id),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "cost_category": self.cost_category.value,
            "currency": self.currency,
            "target_metric": (
                self.target_metric.payload()
                if text is display_text
                else self.target_metric.canonical_payload()
            ),
            "expected_cpor": text(self.expected_cpor_exact),
            "p25": text(self.p25_exact),
            "p75": text(self.p75_exact),
            "iqr": text(self.iqr_exact),
            "upper_fence": text(self.upper_fence_exact),
            "delta_cpor": text(self.delta_cpor_exact),
            "delta_percent": text(self.delta_percent_exact),
            "expected_cost_for_target_volume": text(self.expected_cost_for_target_volume_exact),
            "cost_gap_proxy": text(self.cost_gap_proxy_exact),
            "above_expected_condition": self.above_expected_condition,
            "relative_condition": self.relative_condition,
            "upper_fence_condition": self.upper_fence_condition,
            "gap_condition": self.gap_condition,
            "sample_count": self.sample_count,
            "observed_period_count": self.observed_period_count,
            "approximate_period_count": self.approximate_period_count,
            "candidate_month_count": self.candidate_month_count,
            "rejected_no_cost_data_count": self.rejected_no_cost_data_count,
            "rejected_low_classification_count": self.rejected_low_classification_count,
            "rejected_incomplete_occupancy_count": self.rejected_incomplete_occupancy_count,
            "rejected_zero_occupancy_count": self.rejected_zero_occupancy_count,
            "baseline_confidence": text(self.baseline_confidence),
            "sample_score": text(self.sample_score_exact),
            "provenance_score": text(self.provenance_score_exact),
            "classification_score": text(self.classification_score_exact),
            "stability_score": text(self.stability_score_exact),
            "confidence_cap": text(self.confidence_cap),
            "target_quality": text(self.target_quality),
            "confidence_score": text(self.confidence_score),
            "thresholds": self.thresholds.payload(text),
            "reason_codes": [code.value for code in self.reason_codes],
            "comparable_periods": [
                period.payload() if text is display_text else period.canonical_payload()
                for period in self.comparable_periods
            ],
            "rules_version": self.rules_version,
            "metric_version": self.metric_version,
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
