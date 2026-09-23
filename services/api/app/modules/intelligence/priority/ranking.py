"""Deduplication, conflict detection, deterministic sort and unique rank assignment.

Two `AdaptedSignal`s of the SAME decision type and the SAME logical `source_target_key`:

* identical `source_evaluation_fingerprint` -> the SAME evaluation, seen twice in one input
  (deduplicated to one candidate, counted in `duplicate_input_count`, never producing two ranked
  rows for one real signal);
* different fingerprint -> two DIFFERENT results claimed for the one logical target in the same
  run, and NEITHER is chosen arbitrarily (`PRIORITY_CONFLICTING_SOURCE_EVALUATION`).

Two different decision types describing the same calendar date (REV_PICKUP_LOW and
REV_OCCUPANCY_RISK on the same stay date) are two DISTINCT signals and are never merged: grouping
is always by `(decision_type, source_target_key)`, never by `source_target_key` alone.

The final sort is 8 keys deep, so that any two candidates - even two with an identical priority
score, in Decimal, at full precision - always land in one deterministic order, on any machine, on
any run, whatever order their inputs arrived in.
"""

from collections import defaultdict
from decimal import Decimal

from app.modules.intelligence.priority.adapters import AdaptedSignal
from app.modules.intelligence.priority.errors import PriorityError, PriorityErrorCode
from app.modules.intelligence.priority.types import (
    DECISION_TYPE_TIE_ORDER_INDEX,
    PriorityCandidate,
    RankedPriorityCandidate,
)

_SortKey = tuple[Decimal, Decimal, Decimal, Decimal, Decimal, int, str, str]


def deduplicate_and_check_conflicts(
    signals: list[AdaptedSignal],
) -> tuple[list[AdaptedSignal], int]:
    """Collapse exact duplicates, reject conflicts. Returns `(kept_signals, duplicate_count)`."""
    groups: dict[tuple[str, str], list[AdaptedSignal]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for signal in signals:
        key = (signal.decision_type.value, signal.source_target_key)
        if key not in groups:
            order.append(key)
        groups[key].append(signal)

    kept: list[AdaptedSignal] = []
    duplicate_count = 0
    for key in order:
        group = groups[key]
        fingerprints = {signal.source_evaluation_fingerprint for signal in group}
        if len(fingerprints) > 1:
            raise PriorityError(
                PriorityErrorCode.PRIORITY_CONFLICTING_SOURCE_EVALUATION,
                f"{key[0]} target {key[1]!r} has {len(fingerprints)} different fingerprints "
                "in the same ranking run",
            )
        kept.append(group[0])
        duplicate_count += len(group) - 1
    return kept, duplicate_count


def _sort_key(candidate: PriorityCandidate) -> _SortKey:
    return (
        -candidate.priority_score_exact,
        -candidate.impact_score_exact,
        -candidate.urgency_score,
        -candidate.confidence_score,
        -candidate.actionability_score,
        DECISION_TYPE_TIE_ORDER_INDEX[candidate.decision_type],
        candidate.source_target_key,
        candidate.source_evaluation_fingerprint,
    )


def rank_candidates(candidates: list[PriorityCandidate]) -> tuple[RankedPriorityCandidate, ...]:
    """Sort deterministically (the 8-key tie-break) and assign UNIQUE ranks `1..n`.

    Never dense/shared ranking: even two candidates equal in every one of the 8 keys are
    impossible in practice (key 8, the source fingerprint, is unique per candidate after
    deduplication), but the enumeration below assigns a distinct rank regardless. Input order is
    irrelevant: the same set of candidates always produces the same ordered output.
    """
    ordered = sorted(candidates, key=_sort_key)
    return tuple(
        RankedPriorityCandidate(rank=index + 1, candidate=candidate)
        for index, candidate in enumerate(ordered)
    )
