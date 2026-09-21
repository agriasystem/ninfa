"""A curve pattern: the pairs behind a detector, their statistics and their confidence.

The pure glue shared by both detectors. It reads no database and no clock: it takes an already
selected `PairSelection`.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.intelligence.expected.statistics import Statistics
from app.modules.intelligence.revenue.confidence import PatternConfidence, pattern_confidence
from app.modules.intelligence.revenue.precision import for_display
from app.modules.intelligence.revenue.statistics import delta_statistics
from app.modules.intelligence.revenue.types import (
    MIN_PAIRS,
    HistoricalPair,
    PairFact,
    PairSelection,
    PatternFacts,
)


@dataclass(frozen=True, slots=True)
class CurvePattern:
    statistics: Statistics
    confidence: PatternConfidence
    facts: PatternFacts


def pair_facts(pairs: tuple[HistoricalPair, ...]) -> tuple[PairFact, ...]:
    return tuple(
        PairFact(
            stay_date=pair.stay_date,
            provenance=pair.provenance,
            anchor_snapshot_id=pair.anchor.snapshot_id,
            other_snapshot_id=pair.other.snapshot_id,
            anchor_rooms_on_books=pair.anchor.rooms_on_books,
            other_rooms_on_books=pair.other.rooms_on_books,
            delta=pair.delta,
        )
        for pair in pairs
    )


def empty_selection() -> PairSelection:
    """No pairs at all (there was nothing to pair: no baseline, no comparables)."""
    return PairSelection(
        pairs=(),
        observed_pair_count=0,
        approximate_pair_count=0,
        rejected_uncertain_count=0,
        missing_endpoint_count=0,
        excluded_future_count=0,
    )


def diagnostic_facts(selection: PairSelection) -> PatternFacts:
    """The counts of a selection that is too small to describe: no statistics, no confidence."""
    return PatternFacts(
        pair_count=selection.pair_count,
        observed_pair_count=selection.observed_pair_count,
        approximate_pair_count=selection.approximate_pair_count,
        rejected_uncertain_count=selection.rejected_uncertain_count,
        missing_endpoint_count=selection.missing_endpoint_count,
        excluded_future_count=selection.excluded_future_count,
    )


def analyse(selection: PairSelection) -> CurvePattern:
    """Statistics and confidence of a selection that has at least `MIN_PAIRS` pairs."""
    if selection.pair_count < MIN_PAIRS:
        raise ValueError(f"a curve pattern needs at least {MIN_PAIRS} pairs")
    statistics = delta_statistics(selection.pairs)
    confidence = pattern_confidence(
        selection.observed_pair_count,
        selection.approximate_pair_count,
        statistics.iqr,
        statistics.expected,
    )
    facts = PatternFacts(
        pair_count=selection.pair_count,
        observed_pair_count=selection.observed_pair_count,
        approximate_pair_count=selection.approximate_pair_count,
        rejected_uncertain_count=selection.rejected_uncertain_count,
        missing_endpoint_count=selection.missing_endpoint_count,
        excluded_future_count=selection.excluded_future_count,
        median=statistics.expected,
        p25=statistics.lower,
        p75=statistics.upper,
        iqr=statistics.iqr,
        pattern_confidence=confidence.score,
        sample_score=for_display(confidence.sample_score),
        provenance_score=for_display(confidence.provenance_score),
        stability_score=for_display(confidence.stability_score),
        pairs=pair_facts(selection.pairs),
    )
    return CurvePattern(statistics, confidence, facts)


def evidence_snapshot_ids(
    target_snapshot_id: UUID,
    *,
    prior_snapshot_id: UUID | None = None,
    pairs: tuple[HistoricalPair, ...] = (),
) -> tuple[UUID, ...]:
    """Every stored snapshot an evaluation rests on, in a fixed order, without repeats:
    the target, its own prior (pickup), then the two endpoints of each pair, newest pair first."""
    ordered: list[UUID] = [target_snapshot_id]
    if prior_snapshot_id is not None:
        ordered.append(prior_snapshot_id)
    for pair in pairs:
        ordered.extend((pair.anchor.snapshot_id, pair.other.snapshot_id))
    seen: set[UUID] = set()
    unique: list[UUID] = []
    for snapshot_id in ordered:
        if snapshot_id not in seen:
            seen.add(snapshot_id)
            unique.append(snapshot_id)
    return tuple(unique)
