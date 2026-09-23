"""The vocabulary of REV_OTA_DEPENDENCY V1: statuses, reasons, thresholds, facts, evaluation.

Everything here is immutable and typed. Thresholds are versioned policy of
`OTA_DEPENDENCY_RULES_VERSION` (never database rows). There is no persisted Decision: an
evaluation is the OUTPUT of a pure calculation over immutable inputs (canonical bookings, booking
channels and booking snapshots).

REV_OTA_DEPENDENCY measures CONCENTRATION of the distribution mix, never channel PERFORMANCE:
it never says whether a channel converts well, is profitable, or should be closed.

Naming convention (the Gate 5/7/8 one): a field `x_exact` is the full-precision value the rules
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

from app.modules.intelligence.distribution.precision import (
    canonical_text,
    display_text,
    for_display,
)

# The SAME five statuses as the revenue/cost/labor detectors: one definition, re-exported.
from app.modules.intelligence.revenue.types import EvaluationStatus as EvaluationStatus

OTA_DEPENDENCY_RULES_VERSION = "ota-dependency-v1"
CHANNEL_MIX_METRIC_VERSION = "ota-channel-mix-v1"
OTA_SHARE_EXPECTED_VERSION = "ota-share-expected-v1"

# --- policy V1, versioned with the rules --------------------------------------------------------

FORWARD_STAY_WINDOW_DAYS = 30

MIN_CHANNEL_CLASSIFICATION_COVERAGE = Decimal(80)  # percent
MIN_CLASSIFIED_ROOM_NIGHTS = 20

OTA_STRUCTURAL_SHARE_THRESHOLD = Decimal(70)  # percent
OTA_RISING_MIN_SHARE = Decimal(55)  # percent
OTA_RISING_GAP_PP = Decimal(15)  # percentage points
IQR_MULTIPLIER = Decimal("1.5")

MIN_CONFIDENCE = Decimal(55)
MIN_COMPARABLES = 5
MAX_COMPARABLES = 24
LOOKBACK_DAYS = 730
SEASONAL_WINDOW_DAYS = 42
SAMPLE_SATURATION = 12

# Period provenance (Part "COMPARABLE PROVENANCE"/"TARGET PROVENANCE"): a whole snapshot day of
# the 30-day window is either OBSERVED or a clean RECONSTRUCTED_APPROXIMATE (an uncertain day
# already made the whole window unusable, long before a score is computed).
OBSERVED_DAY_SCORE = Decimal(100)
RECONSTRUCTED_DAY_SCORE = Decimal(60)


class ChannelGroup(StrEnum):
    """The ONLY four groups REV_OTA_DEPENDENCY reasons about (never the richer ChannelType)."""

    OTA = "OTA"
    DIRECT = "DIRECT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ChannelClassificationMethod(StrEnum):
    CANONICAL_SOURCE = "CANONICAL_SOURCE"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    UNCLASSIFIED = "UNCLASSIFIED"


CONFIDENCE_CANONICAL_SOURCE = Decimal(100)
CONFIDENCE_DETERMINISTIC_RULE = Decimal(95)
CONFIDENCE_UNCLASSIFIED = Decimal(0)


@dataclass(frozen=True, slots=True)
class ChannelClassification:
    """A `BookingChannel`, classified into one of the four groups. Provenance quality, NOT a
    probability: 100/95/0 say where the answer came from, not how likely it is to be right."""

    channel_id: UUID
    group: ChannelGroup
    method: ChannelClassificationMethod
    confidence: Decimal
    normalized_label: str


class OtaDecisionType(StrEnum):
    REV_OTA_DEPENDENCY = "REV_OTA_DEPENDENCY"


class ReasonCode(StrEnum):
    TRIGGER_STRUCTURAL_OTA_DEPENDENCY = "TRIGGER_STRUCTURAL_OTA_DEPENDENCY"
    TRIGGER_RISING_OTA_DEPENDENCY = "TRIGGER_RISING_OTA_DEPENDENCY"
    TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY = "TRIGGER_STRUCTURAL_AND_RISING_OTA_DEPENDENCY"
    CLEAR_WITHIN_EXPECTED_RANGE = "CLEAR_WITHIN_EXPECTED_RANGE"
    OTA_NO_ON_BOOKS_DEMAND = "OTA_NO_ON_BOOKS_DEMAND"
    OTA_BOOKING_VOLUME_LOW = "OTA_BOOKING_VOLUME_LOW"
    OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW = "OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW"
    OTA_SNAPSHOT_WINDOW_INCOMPLETE = "OTA_SNAPSHOT_WINDOW_INCOMPLETE"
    OTA_SNAPSHOT_WINDOW_UNCERTAIN = "OTA_SNAPSHOT_WINDOW_UNCERTAIN"
    OTA_CHANNEL_MIX_RECONCILIATION_FAILED = "OTA_CHANNEL_MIX_RECONCILIATION_FAILED"
    OTA_COMPARABLE_SAMPLE_INSUFFICIENT = "OTA_COMPARABLE_SAMPLE_INSUFFICIENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    # Request level: raised as OtaDependencyError, never carried by an evaluation. Kept here so
    # every stable reason has ONE name.
    BOOKING_DATA_SOURCE_INVALID = "BOOKING_DATA_SOURCE_INVALID"


@dataclass(frozen=True, slots=True)
class OtaThresholds:
    """REV_OTA_DEPENDENCY V1: structural OR rising, each its own exact-Decimal rule."""

    forward_window_days: int = FORWARD_STAY_WINDOW_DAYS
    min_classification_coverage: Decimal = MIN_CHANNEL_CLASSIFICATION_COVERAGE
    min_classified_room_nights: int = MIN_CLASSIFIED_ROOM_NIGHTS
    structural_share_threshold: Decimal = OTA_STRUCTURAL_SHARE_THRESHOLD
    rising_min_share: Decimal = OTA_RISING_MIN_SHARE
    rising_gap_pp: Decimal = OTA_RISING_GAP_PP
    iqr_multiplier: Decimal = IQR_MULTIPLIER
    min_confidence: Decimal = MIN_CONFIDENCE
    min_comparables: int = MIN_COMPARABLES
    max_comparables: int = MAX_COMPARABLES
    lookback_days: int = LOOKBACK_DAYS
    seasonal_window_days: int = SEASONAL_WINDOW_DAYS

    def payload(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "forward_window_days": self.forward_window_days,
            "min_classification_coverage": text(self.min_classification_coverage),
            "min_classified_room_nights": self.min_classified_room_nights,
            "structural_share_threshold": text(self.structural_share_threshold),
            "rising_min_share": text(self.rising_min_share),
            "rising_gap_pp": text(self.rising_gap_pp),
            "iqr_multiplier": text(self.iqr_multiplier),
            "min_confidence": text(self.min_confidence),
            "min_comparables": self.min_comparables,
            "max_comparables": self.max_comparables,
            "lookback_days": self.lookback_days,
            "seasonal_window_days": self.seasonal_window_days,
        }


OTA_THRESHOLDS = OtaThresholds()


@dataclass(frozen=True, slots=True)
class ChannelMixTotals:
    """The room-night (and optional revenue) channel mix of ONE 30-day window, at ONE as-of."""

    ota_room_nights: int
    direct_room_nights: int
    other_room_nights: int
    unknown_room_nights: int
    observed_day_count: int
    reconstructed_day_count: int
    reconciled: bool
    ota_room_revenue_exact: Decimal | None = None
    direct_room_revenue_exact: Decimal | None = None

    @property
    def certain_room_nights(self) -> int:
        return (
            self.ota_room_nights
            + self.direct_room_nights
            + self.other_room_nights
            + self.unknown_room_nights
        )

    @property
    def classified_room_nights(self) -> int:
        return self.ota_room_nights + self.direct_room_nights

    @property
    def is_fully_observed(self) -> bool:
        return self.reconstructed_day_count == 0


@dataclass(frozen=True, slots=True)
class ComparablePeriodFact:
    """One historical 30-day period that entered the baseline, with what a person needs to
    audit it."""

    as_of_local_date: date
    window_start: date
    window_end: date
    observed_day_count: int
    reconstructed_day_count: int
    snapshot_provenance_score_exact: Decimal
    ota_room_nights: int
    direct_room_nights: int
    other_room_nights: int
    unknown_room_nights: int
    classification_coverage_pct_exact: Decimal
    ota_share_exact: Decimal

    @property
    def certain_room_nights(self) -> int:
        return (
            self.ota_room_nights
            + self.direct_room_nights
            + self.other_room_nights
            + self.unknown_room_nights
        )

    @property
    def classified_room_nights(self) -> int:
        return self.ota_room_nights + self.direct_room_nights

    @property
    def is_fully_observed(self) -> bool:
        return self.reconstructed_day_count == 0

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "as_of_local_date": self.as_of_local_date.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "observed_day_count": self.observed_day_count,
            "reconstructed_day_count": self.reconstructed_day_count,
            "snapshot_provenance_score": text(self.snapshot_provenance_score_exact),
            "ota_room_nights": self.ota_room_nights,
            "direct_room_nights": self.direct_room_nights,
            "other_room_nights": self.other_room_nights,
            "unknown_room_nights": self.unknown_room_nights,
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "ota_share": text(self.ota_share_exact),
        }

    def payload(self) -> dict[str, Any]:
        return self._body(display_text)

    def canonical_payload(self) -> dict[str, Any]:
        return self._body(canonical_text)


@dataclass(frozen=True, slots=True)
class OtaDependencyEvaluation:
    """The immutable, auditable outcome of REV_OTA_DEPENDENCY for one target.

    `ota_room_revenue_on_books_exact`/`direct_room_revenue_on_books_exact`/`ota_revenue_share_exact`
    are an OPTIONAL, read-only EXPOSURE figure (never a commission cost, a saving or a loss): they
    never enter the trigger. `confidence_score` is 0.00 when no confidence was assessed (an early
    exit), never a real low. Every `*_exact` figure is the value the rules compared and the
    fingerprint hashed.
    """

    decision_type: OtaDecisionType
    status: EvaluationStatus

    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID

    as_of_local_date: date
    window_start: date
    window_end: date
    window_days: int

    ota_room_nights: int | None
    direct_room_nights: int | None
    other_room_nights: int | None
    unknown_room_nights: int | None
    classified_room_nights: int | None
    certain_room_nights: int | None

    observed_day_count: int
    reconstructed_day_count: int
    classification_coverage_pct_exact: Decimal | None
    snapshot_provenance_score_exact: Decimal | None

    ota_share_exact: Decimal | None
    direct_share_exact: Decimal | None

    expected_ota_share_exact: Decimal | None
    p25_exact: Decimal | None
    p75_exact: Decimal | None
    iqr_exact: Decimal | None
    upper_fence_exact: Decimal | None

    delta_pp_exact: Decimal | None

    structural_condition: bool | None
    rising_condition: bool | None

    sample_count: int
    fully_observed_count: int
    approximate_count: int
    candidate_period_count: int
    rejected_snapshot_incomplete_count: int
    rejected_snapshot_uncertain_count: int
    rejected_reconciliation_count: int
    rejected_low_classification_count: int
    rejected_low_volume_count: int

    baseline_confidence: Decimal | None
    sample_score_exact: Decimal | None
    provenance_score_exact: Decimal | None
    classification_score_exact: Decimal | None
    stability_score_exact: Decimal | None
    confidence_cap: Decimal | None
    target_quality: Decimal | None
    confidence_score: Decimal

    ota_room_revenue_on_books_exact: Decimal | None
    direct_room_revenue_on_books_exact: Decimal | None
    ota_revenue_share_exact: Decimal | None

    thresholds: OtaThresholds
    reason_codes: tuple[ReasonCode, ...]
    comparable_periods: tuple[ComparablePeriodFact, ...]

    rules_version: str = OTA_DEPENDENCY_RULES_VERSION
    metric_version: str = CHANNEL_MIX_METRIC_VERSION
    expected_method: str = OTA_SHARE_EXPECTED_VERSION
    calculation_fingerprint: str = ""

    def _display(self, value: Decimal | None) -> Decimal | None:
        return None if value is None else for_display(value)

    @property
    def ota_share_display(self) -> Decimal | None:
        return self._display(self.ota_share_exact)

    @property
    def direct_share_display(self) -> Decimal | None:
        return self._display(self.direct_share_exact)

    @property
    def delta_pp_display(self) -> Decimal | None:
        return self._display(self.delta_pp_exact)

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "status": self.status.value,
            "workspace_id": str(self.workspace_id),
            "property_id": str(self.property_id),
            "booking_data_source_id": str(self.booking_data_source_id),
            "as_of_local_date": self.as_of_local_date.isoformat(),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "window_days": self.window_days,
            "ota_room_nights": self.ota_room_nights,
            "direct_room_nights": self.direct_room_nights,
            "other_room_nights": self.other_room_nights,
            "unknown_room_nights": self.unknown_room_nights,
            "classified_room_nights": self.classified_room_nights,
            "certain_room_nights": self.certain_room_nights,
            "observed_day_count": self.observed_day_count,
            "reconstructed_day_count": self.reconstructed_day_count,
            "classification_coverage_pct": text(self.classification_coverage_pct_exact),
            "snapshot_provenance_score": text(self.snapshot_provenance_score_exact),
            "ota_share": text(self.ota_share_exact),
            "direct_share": text(self.direct_share_exact),
            "expected_ota_share": text(self.expected_ota_share_exact),
            "p25": text(self.p25_exact),
            "p75": text(self.p75_exact),
            "iqr": text(self.iqr_exact),
            "upper_fence": text(self.upper_fence_exact),
            "delta_pp": text(self.delta_pp_exact),
            "structural_condition": self.structural_condition,
            "rising_condition": self.rising_condition,
            "sample_count": self.sample_count,
            "fully_observed_count": self.fully_observed_count,
            "approximate_count": self.approximate_count,
            "candidate_period_count": self.candidate_period_count,
            "rejected_snapshot_incomplete_count": self.rejected_snapshot_incomplete_count,
            "rejected_snapshot_uncertain_count": self.rejected_snapshot_uncertain_count,
            "rejected_reconciliation_count": self.rejected_reconciliation_count,
            "rejected_low_classification_count": self.rejected_low_classification_count,
            "rejected_low_volume_count": self.rejected_low_volume_count,
            "baseline_confidence": text(self.baseline_confidence),
            "sample_score": text(self.sample_score_exact),
            "provenance_score": text(self.provenance_score_exact),
            "classification_score": text(self.classification_score_exact),
            "stability_score": text(self.stability_score_exact),
            "confidence_cap": text(self.confidence_cap),
            "target_quality": text(self.target_quality),
            "confidence_score": text(self.confidence_score),
            "ota_room_revenue_on_books": text(self.ota_room_revenue_on_books_exact),
            "direct_room_revenue_on_books": text(self.direct_room_revenue_on_books_exact),
            "ota_revenue_share": text(self.ota_revenue_share_exact),
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
