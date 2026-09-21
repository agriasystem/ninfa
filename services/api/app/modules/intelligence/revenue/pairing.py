"""Historical curve pairs (pure functions, no database).

The ANCHORS are the comparables the Expected Engine already selected and stored (same weekday,
same lead time, seasonal window, horizon, ...): Gate 5 never repeats that discovery. Each anchor
is a snapshot of a historical stay date D_h taken `L` days before it. A curve PAIR adds ONE more
snapshot of the SAME stay date D_h:

    pickup pair      the snapshot exactly 7 days earlier            delta = anchor - prior
    remaining pair   the final snapshot (snapshot day = D_h)        delta = final - anchor

so a pair measures how the curve of one real stay date moved, never a mix of different nights.

An endpoint is looked up by its exact (snapshot day, stay date) key: no interpolation, no nearest
neighbour, no other stay date, no other data source. A pair is used only when

* both endpoints exist;
* both endpoints were already known at the target's snapshot day (strictly before it): no
  temporal leakage, whatever the lead time;
* neither endpoint has uncertain rooms (an uncertain pair is excluded and COUNTED, never used to
  reach the minimum).

Provenance: OBSERVED_PAIR when both endpoints are OBSERVED, otherwise APPROXIMATE_PAIR. Policy V1
(the same as Gate 4, applied to pairs): at least 5 clean observed pairs -> observed pairs only;
fewer -> all of them, completed with clean approximate pairs, newest first, up to 24. The result
is ordered newest historical stay date first.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from uuid import UUID

from app.modules.intelligence.revenue.types import (
    MAX_PAIRS,
    MIN_PAIRS,
    PICKUP_WINDOW_DAYS,
    HistoricalPair,
    PairProvenance,
    PairSelection,
    SnapshotPoint,
)
from app.modules.snapshots.models import SnapshotOrigin

SnapshotKey = tuple[date, date]  # (snapshot_local_date, stay_date)


def prior_key(snapshot_local_date: date, stay_date: date) -> SnapshotKey:
    """Where the prior of a snapshot lives: the same stay date, 7 snapshot days earlier."""
    return (snapshot_local_date - timedelta(days=PICKUP_WINDOW_DAYS), stay_date)


def pickup_prior_key(anchor: SnapshotPoint) -> SnapshotKey:
    """Where the anchor's own prior snapshot lives: 7 snapshot days earlier, same stay date."""
    return prior_key(anchor.snapshot_local_date, anchor.stay_date)


def final_key(anchor: SnapshotPoint) -> SnapshotKey:
    """Where the anchor's final snapshot lives: taken on the stay date itself (lead time 0)."""
    return (anchor.stay_date, anchor.stay_date)


def _provenance(anchor: SnapshotPoint, other: SnapshotPoint) -> PairProvenance:
    both_observed = (
        anchor.origin == SnapshotOrigin.OBSERVED and other.origin == SnapshotOrigin.OBSERVED
    )
    return PairProvenance.OBSERVED_PAIR if both_observed else PairProvenance.APPROXIMATE_PAIR


def _newest_first(pairs: Iterable[HistoricalPair]) -> list[HistoricalPair]:
    # A data source has one snapshot per (snapshot day, stay date): the stay date makes the order
    # total for stored data; the anchor id only makes it total for hand-built inputs.
    return sorted(pairs, key=lambda p: (p.stay_date, str(p.anchor.snapshot_id)), reverse=True)


def _select(
    target_snapshot_local_date: date,
    anchors: Iterable[SnapshotPoint],
    endpoints: Mapping[SnapshotKey, SnapshotPoint],
    key_of: Callable[[SnapshotPoint], SnapshotKey],
    delta_of: Callable[[SnapshotPoint, SnapshotPoint], int],
) -> PairSelection:
    observed: list[HistoricalPair] = []
    approximate: list[HistoricalPair] = []
    rejected_uncertain = missing = future = 0
    seen: set[UUID] = set()
    for anchor in anchors:
        if anchor.snapshot_id in seen:
            continue
        seen.add(anchor.snapshot_id)
        other = endpoints.get(key_of(anchor))
        if other is None:
            missing += 1
            continue
        # Same stay date by construction of the key; guard against a hand-built mapping anyway.
        if other.stay_date != anchor.stay_date:
            missing += 1
            continue
        known_at_target = (
            anchor.snapshot_local_date < target_snapshot_local_date
            and other.snapshot_local_date < target_snapshot_local_date
        )
        if not known_at_target:
            future += 1
            continue
        if anchor.uncertain_rooms > 0 or other.uncertain_rooms > 0:
            rejected_uncertain += 1
            continue
        pair = HistoricalPair(
            stay_date=anchor.stay_date,
            anchor=anchor,
            other=other,
            provenance=_provenance(anchor, other),
            delta=delta_of(anchor, other),
        )
        (observed if pair.provenance == PairProvenance.OBSERVED_PAIR else approximate).append(pair)

    observed = _newest_first(observed)
    approximate = _newest_first(approximate)
    if len(observed) >= MIN_PAIRS:
        chosen = observed[:MAX_PAIRS]
    else:
        chosen = observed + approximate[: MAX_PAIRS - len(observed)]
    chosen = _newest_first(chosen)
    observed_count = sum(p.provenance == PairProvenance.OBSERVED_PAIR for p in chosen)
    return PairSelection(
        pairs=tuple(chosen),
        observed_pair_count=observed_count,
        approximate_pair_count=len(chosen) - observed_count,
        rejected_uncertain_count=rejected_uncertain,
        missing_endpoint_count=missing,
        excluded_future_count=future,
    )


def pickup_pairs(
    target_snapshot_local_date: date,
    anchors: Sequence[SnapshotPoint],
    endpoints: Mapping[SnapshotKey, SnapshotPoint],
) -> PairSelection:
    """Pairs (prior 7 days earlier -> anchor); `delta` is the historical pickup."""
    return _select(
        target_snapshot_local_date,
        anchors,
        endpoints,
        pickup_prior_key,
        lambda anchor, prior: anchor.rooms_on_books - prior.rooms_on_books,
    )


def remaining_pairs(
    target_snapshot_local_date: date,
    anchors: Sequence[SnapshotPoint],
    endpoints: Mapping[SnapshotKey, SnapshotPoint],
) -> PairSelection:
    """Pairs (anchor -> final at lead time 0); `delta` is the remaining NET pickup.

    It is negative when the stay date lost rooms after the anchor: cancellations are already
    inside the net movement of the curve, there is no separate cancellation model.
    """
    return _select(
        target_snapshot_local_date,
        anchors,
        endpoints,
        final_key,
        lambda anchor, final: final.rooms_on_books - anchor.rooms_on_books,
    )
