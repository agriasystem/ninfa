"""The vocabulary of Revenue Decision Detection V1: statuses, reason codes, thresholds, facts.

Everything here is immutable and typed: the two detectors do not share a generic JSON bag, each
has its own facts. Thresholds are versioned policy of `RULES_VERSION` (never database rows).

There is no persisted Decision: an evaluation is the OUTPUT of a pure calculation over immutable
inputs (snapshots, Expected baselines and their comparables). Only a TRIGGERED evaluation will
ever become a visible Decision, in a later gate.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.revenue.precision import canonical_text, display_text
from app.modules.snapshots.models import SnapshotOrigin

RULES_VERSION = "revenue-decisions-v1"
PATTERN_VERSION = "revenue-curve-pattern-v1"
PICKUP_WINDOW_DAYS = 7  # actual and historical pickup are measured over 7 snapshot days
MIN_PAIRS = 5
MAX_PAIRS = 24


class RevenueDecisionType(StrEnum):
    REV_PICKUP_LOW = "REV_PICKUP_LOW"
    REV_OCCUPANCY_RISK = "REV_OCCUPANCY_RISK"


class EvaluationStatus(StrEnum):
    """Five different answers, never interchangeable.

    TRIGGERED                the rule holds and the confidence is sufficient;
    CLEAR                    the data is sufficient and the condition does not pass the thresholds;
    INSUFFICIENT_DATA        there is not enough reliable data to evaluate;
    NOT_APPLICABLE           the rule has no meaning in the current context;
    SUPPRESSED_LOW_CONFIDENCE the numeric condition holds but NINFA is not confident enough to
                             show it.
    """

    TRIGGERED = "TRIGGERED"
    CLEAR = "CLEAR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUPPRESSED_LOW_CONFIDENCE = "SUPPRESSED_LOW_CONFIDENCE"


class ReasonCode(StrEnum):
    TRIGGER_PICKUP_SHORTFALL = "TRIGGER_PICKUP_SHORTFALL"
    TRIGGER_OCCUPANCY_GAP = "TRIGGER_OCCUPANCY_GAP"
    TRIGGER_ROOM_SHORTFALL = "TRIGGER_ROOM_SHORTFALL"
    TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL = "TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL"
    CLEAR_WITHIN_EXPECTED_RANGE = "CLEAR_WITHIN_EXPECTED_RANGE"
    EXPECTED_BASELINE_MISSING = "EXPECTED_BASELINE_MISSING"
    EXPECTED_BASELINE_INSUFFICIENT = "EXPECTED_BASELINE_INSUFFICIENT"
    PAIR_SAMPLE_INSUFFICIENT = "PAIR_SAMPLE_INSUFFICIENT"
    PICKUP_PRIOR_OBSERVATION_MISSING = "PICKUP_PRIOR_OBSERVATION_MISSING"
    PICKUP_EXPECTATION_NON_POSITIVE = "PICKUP_EXPECTATION_NON_POSITIVE"
    PICKUP_NEAR_SOLD_OUT = "PICKUP_NEAR_SOLD_OUT"
    OCCUPANCY_INVENTORY_UNKNOWN = "OCCUPANCY_INVENTORY_UNKNOWN"
    OCCUPANCY_ALREADY_SOLD_OUT = "OCCUPANCY_ALREADY_SOLD_OUT"
    PROPERTY_CLOSED_FOR_STAY_DATE = "PROPERTY_CLOSED_FOR_STAY_DATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class PairProvenance(StrEnum):
    """OBSERVED_PAIR only when BOTH endpoints are OBSERVED; anything else is APPROXIMATE_PAIR."""

    OBSERVED_PAIR = "OBSERVED_PAIR"
    APPROXIMATE_PAIR = "APPROXIMATE_PAIR"


class ReferenceAdrSource(StrEnum):
    CURRENT_ON_BOOKS_ADR = "CURRENT_ON_BOOKS_ADR"
    HISTORICAL_COMPARABLE_MEDIAN_ADR = "HISTORICAL_COMPARABLE_MEDIAN_ADR"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PickupThresholds:
    """REV_PICKUP_LOW V1: a numeric candidate needs BOTH conditions; the gate needs confidence."""

    max_delta_percent: Decimal = Decimal("-20")  # delta_percent <= -20 %
    min_missing_rooms: Decimal = Decimal("2")  # missing_rooms >= 2
    min_confidence: Decimal = Decimal("50")
    max_remaining_capacity: int = 1  # remaining capacity <= 1 (sold out / overbooked) is immaterial


@dataclass(frozen=True, slots=True)
class OccupancyThresholds:
    """REV_OCCUPANCY_RISK V1: EITHER condition is a numeric candidate; the gate needs confidence."""

    min_gap_pp: Decimal = Decimal("10")  # percentage points
    min_room_shortfall: Decimal = Decimal("3")
    min_confidence: Decimal = Decimal("55")


PICKUP_THRESHOLDS = PickupThresholds()
OCCUPANCY_THRESHOLDS = OccupancyThresholds()


@dataclass(frozen=True, slots=True)
class SnapshotPoint:
    """A stored snapshot as the detectors see it (only what they need)."""

    snapshot_id: UUID
    snapshot_local_date: date
    stay_date: date
    origin: SnapshotOrigin
    rooms_on_books: int
    uncertain_rooms: int
    adr_on_books: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TargetContext:
    """The observed target, its capacity and the Gate 4 baseline that defines its context."""

    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    target_snapshot_id: UUID
    snapshot_local_date: date
    stay_date: date
    rooms_on_books: int
    rooms_available: int | None
    adr_on_books: Decimal | None
    baseline_id: UUID | None
    baseline_status: ExpectedStatus | None
    baseline_confidence: Decimal | None

    @property
    def lead_time_days(self) -> int:
        return (self.stay_date - self.snapshot_local_date).days


@dataclass(frozen=True, slots=True)
class HistoricalPair:
    """Two snapshots of the SAME historical stay date: an anchor (a Gate 4 comparable) and the
    other end of the curve (the snapshot 7 days before it, or the final one at lead time 0)."""

    stay_date: date
    anchor: SnapshotPoint
    other: SnapshotPoint
    provenance: PairProvenance
    delta: int  # pickup: anchor - prior; remaining net pickup: final - anchor


@dataclass(frozen=True, slots=True)
class PairSelection:
    pairs: tuple[HistoricalPair, ...]  # newest historical stay date first, at most MAX_PAIRS
    observed_pair_count: int
    approximate_pair_count: int
    rejected_uncertain_count: int  # pairs excluded because an endpoint had uncertain_rooms > 0
    missing_endpoint_count: int  # anchors with no snapshot at the exact other endpoint
    excluded_future_count: int  # endpoints not yet known at the target's snapshot day

    @property
    def pair_count(self) -> int:
        return len(self.pairs)


@dataclass(frozen=True, slots=True)
class PairFact:
    stay_date: date
    provenance: PairProvenance
    anchor_snapshot_id: UUID
    other_snapshot_id: UUID
    anchor_rooms_on_books: int
    other_rooms_on_books: int
    delta: int

    def payload(self) -> dict[str, Any]:
        return {
            "stay_date": self.stay_date.isoformat(),
            "provenance": self.provenance.value,
            "anchor_snapshot_id": str(self.anchor_snapshot_id),
            "other_snapshot_id": str(self.other_snapshot_id),
            "anchor_rooms_on_books": self.anchor_rooms_on_books,
            "other_rooms_on_books": self.other_rooms_on_books,
            "delta": self.delta,
        }


@dataclass(frozen=True, slots=True)
class PatternFacts:
    """The historical curve pattern behind a detector: which pairs, what statistics, how sure.

    The statistics (`median`, `p25`, `p75`, `iqr`) and `pattern_confidence` are exact at two
    decimals by definition. The three component scores are informational and stored quantized to
    two decimals; the confidence itself is computed from their unrounded values.
    """

    pair_count: int
    observed_pair_count: int
    approximate_pair_count: int
    rejected_uncertain_count: int
    missing_endpoint_count: int
    excluded_future_count: int
    median: Decimal | None = None
    p25: Decimal | None = None
    p75: Decimal | None = None
    iqr: Decimal | None = None
    pattern_confidence: Decimal | None = None
    sample_score: Decimal | None = None
    provenance_score: Decimal | None = None
    stability_score: Decimal | None = None
    pairs: tuple[PairFact, ...] = ()

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "observed_pair_count": self.observed_pair_count,
            "approximate_pair_count": self.approximate_pair_count,
            "rejected_uncertain_count": self.rejected_uncertain_count,
            "missing_endpoint_count": self.missing_endpoint_count,
            "excluded_future_count": self.excluded_future_count,
            "median": text(self.median),
            "p25": text(self.p25),
            "p75": text(self.p75),
            "iqr": text(self.iqr),
            "pattern_confidence": text(self.pattern_confidence),
            "sample_score": text(self.sample_score),
            "provenance_score": text(self.provenance_score),
            "stability_score": text(self.stability_score),
            "pairs": [pair.payload() for pair in self.pairs],
        }

    def payload(self) -> dict[str, Any]:
        """The presentation of the pattern (two-decimal figures)."""
        return self._body(display_text)

    def canonical_payload(self) -> dict[str, Any]:
        """The same facts with non-lossy Decimals: what the fingerprint hashes."""
        return self._body(canonical_text)


@dataclass(frozen=True, slots=True)
class PickupFacts:
    """Everything behind a REV_PICKUP_LOW evaluation (what a Decision Detail will show).

    `delta_percent_exact` is the full-precision value the rule compared with its threshold (the
    DECISION value); `delta_percent` is the same number quantized to two decimals for display and
    never decides anything. Rooms (`delta_rooms`, `missing_rooms`, `expected_pickup`) are exact by
    construction: integers and the median of integers.
    """

    current_rooms_on_books: int
    rooms_available: int | None
    remaining_capacity: int | None = None
    prior_snapshot_id: UUID | None = None
    prior_origin: SnapshotOrigin | None = None
    prior_rooms_on_books: int | None = None
    actual_pickup: int | None = None
    expected_pickup: Decimal | None = None
    delta_rooms: Decimal | None = None
    missing_rooms: Decimal | None = None
    delta_percent: Decimal | None = None  # DISPLAY value (two decimals)
    delta_percent_exact: Decimal | None = None  # DECISION value (full precision)
    percent_condition: bool | None = None
    rooms_condition: bool | None = None
    baseline_confidence: Decimal | None = None
    pattern: PatternFacts | None = None
    window_days: int = PICKUP_WINDOW_DAYS
    thresholds: PickupThresholds = PICKUP_THRESHOLDS

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "current_rooms_on_books": self.current_rooms_on_books,
            "rooms_available": self.rooms_available,
            "remaining_capacity": self.remaining_capacity,
            "prior_snapshot_id": None
            if self.prior_snapshot_id is None
            else str(self.prior_snapshot_id),
            "prior_origin": None if self.prior_origin is None else self.prior_origin.value,
            "prior_rooms_on_books": self.prior_rooms_on_books,
            "actual_pickup": self.actual_pickup,
            "expected_pickup": text(self.expected_pickup),
            "delta_rooms": text(self.delta_rooms),
            "missing_rooms": text(self.missing_rooms),
            "delta_percent_exact": canonical_text(self.delta_percent_exact),
            "percent_condition": self.percent_condition,
            "rooms_condition": self.rooms_condition,
            "baseline_confidence": text(self.baseline_confidence),
            "thresholds": {
                "max_delta_percent": text(self.thresholds.max_delta_percent),
                "min_missing_rooms": text(self.thresholds.min_missing_rooms),
                "min_confidence": text(self.thresholds.min_confidence),
                "max_remaining_capacity": self.thresholds.max_remaining_capacity,
            },
        }

    def payload(self) -> dict[str, Any]:
        """The presentation: two-decimal figures, the display percent and the decision value."""
        return self._body(display_text) | {
            "delta_percent": display_text(self.delta_percent),
            "pattern": None if self.pattern is None else self.pattern.payload(),
        }

    def canonical_payload(self) -> dict[str, Any]:
        """Non-lossy Decimals and no display-only figure: what the fingerprint hashes."""
        return self._body(canonical_text) | {
            "pattern": None if self.pattern is None else self.pattern.canonical_payload(),
        }


@dataclass(frozen=True, slots=True)
class OccupancyFacts:
    """Everything behind a REV_OCCUPANCY_RISK evaluation, including the minimal forecast.

    Quotients have two values: `x_exact` is the full-precision figure the rule compared with its
    threshold (the DECISION value) and `x` is the same number quantized to two decimals for
    display, which never decides anything. Rooms (`forecast_rooms`, `expected_final_rooms`,
    `room_shortfall`, ...) are exact by construction: integers and medians of integers.
    """

    current_rooms_on_books: int
    rooms_available: int | None
    expected_remaining_net_pickup: Decimal | None = None
    raw_forecast_rooms: Decimal | None = None
    forecast_rooms: Decimal | None = None
    expected_final_rooms: Decimal | None = None
    forecast_occupancy: Decimal | None = None  # DISPLAY
    forecast_occupancy_exact: Decimal | None = None  # DECISION precision
    expected_final_occupancy: Decimal | None = None  # DISPLAY
    expected_final_occupancy_exact: Decimal | None = None  # DECISION precision
    occupancy_gap_pp: Decimal | None = None  # DISPLAY
    occupancy_gap_pp_exact: Decimal | None = None  # DECISION value
    room_shortfall: Decimal | None = None
    gap_condition: bool | None = None
    shortfall_condition: bool | None = None
    baseline_confidence: Decimal | None = None
    pattern: PatternFacts | None = None
    thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS

    def _body(self, text: Callable[[Decimal | None], str | None]) -> dict[str, Any]:
        return {
            "current_rooms_on_books": self.current_rooms_on_books,
            "rooms_available": self.rooms_available,
            "expected_remaining_net_pickup": text(self.expected_remaining_net_pickup),
            "raw_forecast_rooms": text(self.raw_forecast_rooms),
            "forecast_rooms": text(self.forecast_rooms),
            "expected_final_rooms": text(self.expected_final_rooms),
            "forecast_occupancy_exact": canonical_text(self.forecast_occupancy_exact),
            "expected_final_occupancy_exact": canonical_text(self.expected_final_occupancy_exact),
            "occupancy_gap_pp_exact": canonical_text(self.occupancy_gap_pp_exact),
            "room_shortfall": text(self.room_shortfall),
            "gap_condition": self.gap_condition,
            "shortfall_condition": self.shortfall_condition,
            "baseline_confidence": text(self.baseline_confidence),
            "thresholds": {
                "min_gap_pp": text(self.thresholds.min_gap_pp),
                "min_room_shortfall": text(self.thresholds.min_room_shortfall),
                "min_confidence": text(self.thresholds.min_confidence),
            },
        }

    def payload(self) -> dict[str, Any]:
        """The presentation: two-decimal figures, the display quotients and the decision values."""
        return self._body(display_text) | {
            "forecast_occupancy": display_text(self.forecast_occupancy),
            "expected_final_occupancy": display_text(self.expected_final_occupancy),
            "occupancy_gap_pp": display_text(self.occupancy_gap_pp),
            "pattern": None if self.pattern is None else self.pattern.payload(),
        }

    def canonical_payload(self) -> dict[str, Any]:
        """Non-lossy Decimals and no display-only figure: what the fingerprint hashes."""
        return self._body(canonical_text) | {
            "pattern": None if self.pattern is None else self.pattern.canonical_payload(),
        }


@dataclass(frozen=True, slots=True)
class RevenueDecisionEvaluation:
    """The immutable, auditable outcome of one detector for one observed target.

    `revenue_gap_proxy` is a GROSS EXPOSURE proxy (rooms x a reference ADR), not a prediction of
    lost revenue, and is filled only when the numeric condition holds (TRIGGERED or
    SUPPRESSED_LOW_CONFIDENCE). `reference_adr` is context and is resolved for every evaluation.
    """

    decision_type: RevenueDecisionType
    status: EvaluationStatus
    workspace_id: UUID
    property_id: UUID
    data_source_id: UUID
    target_snapshot_id: UUID
    target_baseline_id: UUID | None
    snapshot_local_date: date
    stay_date: date
    lead_time_days: int
    confidence_score: Decimal  # 0.00 = no confidence was assessed (an early exit), never a real low
    rules_version: str
    calculation_fingerprint: str
    reason_codes: tuple[ReasonCode, ...]
    facts: PickupFacts | OccupancyFacts
    evidence_snapshot_ids: tuple[UUID, ...]
    revenue_gap_proxy: Decimal | None
    reference_adr: Decimal | None
    reference_adr_source: ReferenceAdrSource
    pattern_version: str = PATTERN_VERSION


@dataclass(frozen=True, slots=True)
class RevenueSignals:
    """Both detectors on one target."""

    pickup_low: RevenueDecisionEvaluation
    occupancy_risk: RevenueDecisionEvaluation
