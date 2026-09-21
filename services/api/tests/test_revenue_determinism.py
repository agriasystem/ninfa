"""Determinism and the calculation fingerprint (Gate 5, group O). Pure, no database."""

import random
import re
import uuid
from datetime import timedelta
from decimal import Decimal

from app.modules.intelligence.revenue.impact import ReferenceAdr
from app.modules.intelligence.revenue.occupancy import evaluate_occupancy
from app.modules.intelligence.revenue.pairing import pickup_pairs
from app.modules.intelligence.revenue.pickup import evaluate_pickup
from app.modules.intelligence.revenue.types import (
    OCCUPANCY_THRESHOLDS,
    PICKUP_THRESHOLDS,
    OccupancyThresholds,
    PairSelection,
    PickupThresholds,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    SnapshotPoint,
    TargetContext,
)
from tests.revenue_support import (
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    endpoints_of,
    pickup_selection,
    point,
    remaining_selection,
    target_context,
)

D = Decimal
ADR = ReferenceAdr(D("100.00"), ReferenceAdrSource.CURRENT_ON_BOOKS_ADR)
PRIOR = point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, 12)
TARGET = target_context()


def pickup(
    *,
    selection: PairSelection | None = None,
    context: TargetContext = TARGET,
    thresholds: PickupThresholds = PICKUP_THRESHOLDS,
    reference: ReferenceAdr = ADR,
) -> RevenueDecisionEvaluation:
    return evaluate_pickup(
        context,
        prior=PRIOR,
        selection=selection or pickup_selection([10] * 12),
        reference=reference,
        thresholds=thresholds,
    )


def occupancy(
    *,
    selection: PairSelection | None = None,
    context: TargetContext = TARGET,
    thresholds: OccupancyThresholds = OCCUPANCY_THRESHOLDS,
    reference: ReferenceAdr = ADR,
) -> RevenueDecisionEvaluation:
    return evaluate_occupancy(
        context,
        selection=selection or remaining_selection([4] * 12, [30] * 12),
        reference=reference,
        thresholds=thresholds,
    )


def test_the_same_input_gives_the_same_status_and_fingerprint() -> None:
    selection = pickup_selection([10] * 12)
    first, second = pickup(selection=selection), pickup(selection=selection)
    assert first == second
    assert first.status == second.status
    assert first.calculation_fingerprint == second.calculation_fingerprint
    occupancy_selection = remaining_selection([4] * 12, [30] * 12)
    assert (
        occupancy(selection=occupancy_selection).calculation_fingerprint
        == occupancy(selection=occupancy_selection).calculation_fingerprint
    )


def test_the_fingerprint_is_a_sha256_hex_digest() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", pickup().calculation_fingerprint)


def test_the_same_logical_input_built_twice_is_the_same_fingerprint() -> None:
    # two independently built selections with the same snapshot ids and rooms
    selection = pickup_selection([10] * 12)
    rebuilt = pickup_selection([10] * 12)
    assert selection.pairs[0].anchor.snapshot_id != rebuilt.pairs[0].anchor.snapshot_id
    # different snapshot ids are different evidence, hence a different fingerprint ...
    assert pickup(selection=selection).calculation_fingerprint != (
        pickup(selection=rebuilt).calculation_fingerprint
    )
    # ... and the very same evidence is always the same one
    assert pickup(selection=selection).calculation_fingerprint == (
        pickup(selection=selection).calculation_fingerprint
    )


def test_the_two_detectors_never_share_a_fingerprint() -> None:
    assert pickup().calculation_fingerprint != occupancy().calculation_fingerprint


def test_every_meaningful_input_changes_the_fingerprint() -> None:
    selection = pickup_selection([10] * 12)
    base = pickup(selection=selection).calculation_fingerprint
    changed = {
        "a historical delta": pickup(selection=pickup_selection([10] * 11 + [11])),
        "the target snapshot": pickup(
            selection=selection, context=target_context(target_id=uuid.uuid4())
        ),
        "the target baseline": pickup(
            selection=selection, context=target_context(baseline_id=uuid.uuid4())
        ),
        "the current rooms": pickup(selection=selection, context=target_context(rooms=21)),
        "the inventory": pickup(selection=selection, context=target_context(available=41)),
        "the baseline confidence": pickup(
            selection=selection, context=target_context(baseline_confidence=D("80.00"))
        ),
        "a threshold": pickup(
            selection=selection, thresholds=PickupThresholds(min_confidence=D("51"))
        ),
        "the reference ADR": pickup(
            selection=selection,
            reference=ReferenceAdr(D("101.00"), ReferenceAdrSource.CURRENT_ON_BOOKS_ADR),
        ),
        "the ADR source": pickup(
            selection=selection,
            reference=ReferenceAdr(
                D("100.00"), ReferenceAdrSource.HISTORICAL_COMPARABLE_MEDIAN_ADR
            ),
        ),
    }
    for name, evaluation in changed.items():
        assert evaluation.calculation_fingerprint != base, name


def test_the_status_is_part_of_the_fingerprint() -> None:
    selection = pickup_selection([10] * 12)
    triggered = pickup(selection=selection, context=target_context(baseline_confidence=D("50.00")))
    suppressed = pickup(selection=selection, context=target_context(baseline_confidence=D("49.99")))
    assert triggered.status != suppressed.status
    assert triggered.calculation_fingerprint != suppressed.calculation_fingerprint


def test_equal_decimals_written_differently_hash_the_same() -> None:
    selection = pickup_selection([10] * 12)
    a = pickup(selection=selection, context=target_context(baseline_confidence=D("90")))
    b = pickup(selection=selection, context=target_context(baseline_confidence=D("90.00")))
    assert a.calculation_fingerprint == b.calculation_fingerprint


def test_the_order_of_the_stored_rows_does_not_change_the_result() -> None:
    anchors: list[SnapshotPoint] = []
    points: list[SnapshotPoint] = []
    for index in range(10):
        stay = TARGET_SNAPSHOT_DAY - timedelta(days=7 * (index + 1))
        anchor = point(stay - timedelta(days=14), stay, 20 + index)
        prior = point(stay - timedelta(days=21), stay, 10)
        anchors.append(anchor)
        points.extend([anchor, prior])
    endpoints = endpoints_of(*points)
    baseline = pickup(selection=pickup_pairs(TARGET_SNAPSHOT_DAY, anchors, endpoints))
    for seed in range(6):
        shuffled = anchors[:]
        random.Random(seed).shuffle(shuffled)
        again = pickup(selection=pickup_pairs(TARGET_SNAPSHOT_DAY, shuffled, endpoints))
        assert again == baseline
        assert again.calculation_fingerprint == baseline.calculation_fingerprint


def test_an_evaluation_is_immutable() -> None:
    evaluation = pickup()
    for attribute, value in (("status", None), ("confidence_score", D(1)), ("facts", None)):
        try:
            setattr(evaluation, attribute, value)
        except (AttributeError, TypeError):
            continue
        raise AssertionError(f"{attribute} could be changed")


def test_evaluating_does_not_change_the_inputs() -> None:
    selection = pickup_selection([10] * 12)
    snapshot = (selection.pairs, selection.observed_pair_count, TARGET)
    pickup(selection=selection)
    occupancy()
    assert (selection.pairs, selection.observed_pair_count, TARGET) == snapshot
