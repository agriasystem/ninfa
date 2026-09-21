"""The whole Expected calculation for one target (pure functions, no database, no HTTP).

    HistoricalTarget + candidates -> selection -> statistics -> confidence -> ExpectedComputation

Nothing here knows about alerts, decisions, forecasts or pickup, and nothing reads a clock.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.modules.intelligence.expected.confidence import Confidence, ConfidenceBand, confidence
from app.modules.intelligence.expected.selection import (
    MIN_SAMPLE,
    Candidate,
    HistoricalTarget,
    Selection,
    select_comparables,
)
from app.modules.intelligence.expected.statistics import Statistics, summarize

# Identify the RULES (selection, statistics, confidence), not the application release. Changing
# any rule means a new calculation_version, never an edit of stored baselines.
METHOD = "MEDIAN_SAME_DOW_SEASONAL_WINDOW"
CALCULATION_VERSION = "booking-expected-v1"
_FINGERPRINT_FORMAT = 1


class ExpectedStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class ExpectedComputation:
    """Everything derived from the comparables of one target."""

    status: ExpectedStatus
    selection: Selection
    statistics: Statistics | None  # None <=> INSUFFICIENT_DATA
    confidence: Confidence | None  # None <=> INSUFFICIENT_DATA

    @property
    def confidence_score(self) -> Decimal:
        return Decimal("0.00") if self.confidence is None else self.confidence.score

    @property
    def confidence_band(self) -> ConfidenceBand | None:
        return None if self.confidence is None else self.confidence.band


def compute_expected(
    target: HistoricalTarget, candidates: Iterable[Candidate]
) -> ExpectedComputation:
    """Expected rooms on books for a stay date seen `lead_time_days` before it.

    With fewer than 5 usable comparables the result is INSUFFICIENT_DATA and NO number is
    produced, even though a median of 4 values is mathematically computable: a figure without a
    reliable sample is not an Expected.
    """
    selection = select_comparables(target, candidates)
    if selection.sample_size < MIN_SAMPLE:
        return ExpectedComputation(ExpectedStatus.INSUFFICIENT_DATA, selection, None, None)
    statistics = summarize([c.candidate.rooms_on_books for c in selection.comparables])
    baseline_confidence = confidence(
        selection.observed_count,
        selection.reconstructed_count,
        statistics.iqr,
        statistics.expected,
    )
    return ExpectedComputation(ExpectedStatus.READY, selection, statistics, baseline_confidence)


def comparable_fingerprint(
    *,
    data_source_id: UUID,
    target_snapshot_id: UUID,
    target: HistoricalTarget,
    computation: ExpectedComputation,
) -> str:
    """SHA-256 of the canonical JSON of the logical input of a baseline.

    It depends on the target context, the method and version, the ordered comparables (snapshot
    id, rooms, origin, rank) and the provenance counts. It does NOT depend on row ids, creation
    time or any runtime metadata: the same logical input gives the same fingerprint.
    """
    selection = computation.selection
    payload = {
        "v": _FINGERPRINT_FORMAT,
        "method": METHOD,
        "calculation_version": CALCULATION_VERSION,
        "data_source_id": str(data_source_id),
        "target_snapshot_id": str(target_snapshot_id),
        "target_snapshot_local_date": target.snapshot_local_date.isoformat(),
        "target_stay_date": target.stay_date.isoformat(),
        "lead_time_days": target.lead_time_days,
        "observed": selection.observed_count,
        "reconstructed": selection.reconstructed_count,
        "rejected_uncertain": selection.rejected_uncertain_count,
        "comparables": [
            {
                "rank": item.recency_rank,
                "snapshot_id": str(item.candidate.snapshot_id),
                "rooms_on_books": item.candidate.rooms_on_books,
                "origin": item.candidate.origin.value,
            }
            for item in selection.comparables
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()
