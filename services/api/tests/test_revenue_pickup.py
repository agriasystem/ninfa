"""REV_PICKUP_LOW (Gate 5, groups E-H): actual, expected, thresholds, materiality. Pure."""

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

import pytest

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.revenue.impact import ReferenceAdr
from app.modules.intelligence.revenue.pickup import (
    classify_pickup,
    evaluate_pickup,
    percent_condition,
    rooms_condition,
)
from app.modules.intelligence.revenue.types import (
    PICKUP_THRESHOLDS,
    EvaluationStatus,
    PairSelection,
    PickupFacts,
    ReasonCode,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
    SnapshotPoint,
)
from app.modules.snapshots.models import SnapshotOrigin
from tests.revenue_support import (
    OBSERVED,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    make_selection,
    pickup_selection,
    point,
    target_context,
)

D = Decimal
CONFIDENT = D("90.00")
ADR = ReferenceAdr(D("100.00"), ReferenceAdrSource.CURRENT_ON_BOOKS_ADR)
S = EvaluationStatus
R = ReasonCode


def prior_of(rooms: int, origin: SnapshotOrigin = OBSERVED) -> SnapshotPoint:
    return point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, rooms, origin=origin)


def run(
    *,
    rooms: int = 20,
    prior_rooms: int | None = 12,
    pickups: Sequence[int] = (10,) * 12,
    available: int | None = 40,
    baseline_confidence: Decimal = CONFIDENT,
    baseline_status: ExpectedStatus | None = ExpectedStatus.READY,
    prior_origin: SnapshotOrigin = OBSERVED,
    selection: PairSelection | None = None,
    reference: ReferenceAdr = ADR,
) -> RevenueDecisionEvaluation:
    """Twelve observed pairs of a pickup of 10 (expected 10), actual pickup 8 by default."""
    return evaluate_pickup(
        target_context(
            rooms=rooms,
            available=available,
            baseline_confidence=baseline_confidence,
            baseline_status=baseline_status,
        ),
        prior=None if prior_rooms is None else prior_of(prior_rooms, prior_origin),
        selection=selection if selection is not None else pickup_selection(list(pickups)),
        reference=reference,
    )


def facts_of(evaluation: RevenueDecisionEvaluation) -> PickupFacts:
    assert isinstance(evaluation.facts, PickupFacts)
    return evaluation.facts


# --- E: the actual pickup --------------------------------------------------------------------


def test_actual_pickup_is_current_rooms_minus_the_prior_seven_days_earlier() -> None:
    evaluation = run(rooms=25, prior_rooms=14)
    assert facts_of(evaluation).actual_pickup == 11
    assert facts_of(evaluation).window_days == 7


def test_actual_pickup_can_be_zero_or_negative() -> None:
    assert facts_of(run(rooms=12, prior_rooms=12)).actual_pickup == 0
    negative = run(rooms=10, prior_rooms=12)  # two rooms cancelled during the week
    assert facts_of(negative).actual_pickup == -2
    assert facts_of(negative).missing_rooms == D("12.00")  # expected 10 - (-2)


def test_a_missing_prior_is_insufficient_data() -> None:
    evaluation = run(prior_rooms=None)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PICKUP_PRIOR_OBSERVATION_MISSING,)
    assert facts_of(evaluation).actual_pickup is None
    assert evaluation.revenue_gap_proxy is None


def test_a_reconstructed_prior_is_not_an_observation() -> None:
    evaluation = run(prior_rooms=12, prior_origin=RECONSTRUCTED)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PICKUP_PRIOR_OBSERVATION_MISSING,)
    assert facts_of(evaluation).prior_origin == RECONSTRUCTED
    assert facts_of(evaluation).actual_pickup is None  # never computed from a reconstruction


def test_the_prior_is_part_of_the_evidence() -> None:
    prior = prior_of(12)
    evaluation = evaluate_pickup(
        target_context(),
        prior=prior,
        selection=pickup_selection([10] * 12),
        reference=ADR,
    )
    assert evaluation.evidence_snapshot_ids[0] == evaluation.target_snapshot_id
    assert evaluation.evidence_snapshot_ids[1] == prior.snapshot_id
    assert (
        len(evaluation.evidence_snapshot_ids) == 2 + 2 * 12
    )  # target, prior, both ends of 12 pairs
    assert len(set(evaluation.evidence_snapshot_ids)) == len(evaluation.evidence_snapshot_ids)


# --- F: the expected pickup ------------------------------------------------------------------


def test_expected_pickup_is_the_median_with_its_range_and_provenance() -> None:
    evaluation = run(pickups=(2, 4, 6, 8, 10, 12, 14, 16))
    pattern = facts_of(evaluation).pattern
    assert pattern is not None
    assert facts_of(evaluation).expected_pickup == D("9.00")
    assert (pattern.median, pattern.p25, pattern.p75, pattern.iqr) == (
        D("9.00"),
        D("5.50"),
        D("12.50"),
        D("7.00"),
    )
    assert (pattern.pair_count, pattern.observed_pair_count, pattern.approximate_pair_count) == (
        8,
        8,
        0,
    )
    assert pattern.provenance_score == D(100)
    assert len(pattern.pairs) == 8
    assert [pair.delta for pair in pattern.pairs] == [2, 4, 6, 8, 10, 12, 14, 16]


def test_delta_rooms_and_missing_rooms() -> None:
    below = facts_of(run(rooms=20, prior_rooms=12))  # actual 8, expected 10
    assert (below.delta_rooms, below.missing_rooms) == (D("-2.00"), D("2.00"))
    above = facts_of(run(rooms=25, prior_rooms=12))  # actual 13, expected 10
    assert (above.delta_rooms, above.missing_rooms) == (D("3.00"), D("0.00"))  # never negative


def test_delta_percent_is_relative_to_the_expected_pickup() -> None:
    assert facts_of(run(rooms=20, prior_rooms=12)).delta_percent == D("-20.00")  # (8-10)/10
    assert facts_of(run(rooms=20, prior_rooms=18)).delta_percent == D("-80.00")  # (2-10)/10
    assert facts_of(run(rooms=25, prior_rooms=12)).delta_percent == D("30.00")  # (13-10)/10


def test_a_fractional_expectation_is_rounded_half_up_to_two_decimals() -> None:
    evaluation = run(rooms=20, prior_rooms=14, pickups=(7,) * 12)  # actual 6, expected 7
    assert facts_of(evaluation).delta_percent == D("-14.29")  # -1/7 = -14.2857...
    third = run(rooms=20, prior_rooms=11, pickups=(3,) * 12)  # actual 9, expected 3
    assert facts_of(third).delta_percent == D("200.00")


def test_an_expected_pickup_of_zero_is_not_applicable_and_never_divides_by_zero() -> None:
    evaluation = run(pickups=(0,) * 12)
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.PICKUP_EXPECTATION_NON_POSITIVE,)
    assert facts_of(evaluation).delta_percent is None
    assert facts_of(evaluation).expected_pickup == D("0.00")
    assert evaluation.revenue_gap_proxy is None


def test_a_negative_expected_pickup_is_not_applicable() -> None:
    evaluation = run(pickups=(-3,) * 12)  # a night that historically loses rooms in the week
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.PICKUP_EXPECTATION_NON_POSITIVE,)
    assert facts_of(evaluation).delta_percent is None


def test_a_non_positive_expectation_still_reports_the_confidence_it_computed() -> None:
    evaluation = run(pickups=(0,) * 12, baseline_confidence=D("70.00"))
    assert evaluation.confidence_score == D("70.00")


# --- G: thresholds and boundaries ------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta_percent", "expected"),
    [("-19.99", False), ("-20.00", True), ("-20.01", True), ("0.00", False), ("15.00", False)],
)
def test_the_percentage_boundary_is_minus_20(delta_percent: str, expected: bool) -> None:
    assert percent_condition(D(delta_percent)) is expected


@pytest.mark.parametrize(
    ("missing", "expected"),
    [("1.99", False), ("2.00", True), ("2.01", True), ("0.00", False)],
)
def test_the_room_boundary_is_2(missing: str, expected: bool) -> None:
    assert rooms_condition(D(missing)) is expected


@pytest.mark.parametrize(
    ("delta_percent", "missing", "confidence", "status"),
    [
        ("-19.99", "3.00", "90.00", S.CLEAR),  # percentage just short
        ("-20.00", "3.00", "90.00", S.TRIGGERED),  # percentage exactly on the threshold
        ("-30.00", "1.99", "90.00", S.CLEAR),  # rooms just short
        ("-30.00", "2.00", "90.00", S.TRIGGERED),  # rooms exactly on the threshold
        ("-20.00", "2.00", "90.00", S.TRIGGERED),  # both exactly on the threshold
        ("-30.00", "3.00", "49.99", S.SUPPRESSED_LOW_CONFIDENCE),  # confidence just short
        ("-30.00", "3.00", "50.00", S.TRIGGERED),  # confidence exactly on the gate
        ("-19.99", "3.00", "10.00", S.CLEAR),  # low confidence does not turn CLEAR into anything
    ],
)
def test_the_status_boundaries(
    delta_percent: str, missing: str, confidence: str, status: EvaluationStatus
) -> None:
    result, reasons = classify_pickup(D(delta_percent), D(missing), D(confidence))
    assert result == status
    assert len(reasons) == 1


def test_both_conditions_are_needed_to_trigger() -> None:
    # 20 % below but only 1 missing room: expected 5, actual 4
    small = run(rooms=16, prior_rooms=12, pickups=(5,) * 12)
    assert (facts_of(small).delta_percent, facts_of(small).missing_rooms) == (
        D("-20.00"),
        D("1.00"),
    )
    assert small.status == S.CLEAR
    # 3 missing rooms but only 10 % below: expected 30, actual 27
    wide = run(rooms=39, prior_rooms=12, pickups=(30,) * 12, available=60)
    assert (facts_of(wide).delta_percent, facts_of(wide).missing_rooms) == (D("-10.00"), D("3.00"))
    assert wide.status == S.CLEAR


def test_the_thresholds_are_versioned_constants() -> None:
    assert PICKUP_THRESHOLDS.max_delta_percent == D("-20")
    assert PICKUP_THRESHOLDS.min_missing_rooms == D("2")
    assert PICKUP_THRESHOLDS.min_confidence == D("50")
    assert facts_of(run()).thresholds == PICKUP_THRESHOLDS


def test_a_triggered_pickup() -> None:
    evaluation = run(rooms=20, prior_rooms=12)  # actual 8 vs expected 10: exactly -20 %, 2 rooms
    assert evaluation.status == S.TRIGGERED
    assert evaluation.reason_codes == (R.TRIGGER_PICKUP_SHORTFALL,)
    assert evaluation.decision_type == RevenueDecisionType.REV_PICKUP_LOW
    assert facts_of(evaluation).percent_condition is True
    assert facts_of(evaluation).rooms_condition is True


def test_a_clear_pickup() -> None:
    evaluation = run(rooms=25, prior_rooms=12)  # actual 13, expected 10
    assert evaluation.status == S.CLEAR
    assert evaluation.reason_codes == (R.CLEAR_WITHIN_EXPECTED_RANGE,)
    assert evaluation.revenue_gap_proxy is None  # nothing is missing


def test_a_suppressed_pickup_keeps_only_the_low_confidence_reason() -> None:
    evaluation = run(baseline_confidence=D("49.99"))
    assert evaluation.status == S.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.reason_codes == (R.LOW_CONFIDENCE,)
    assert evaluation.confidence_score == D("49.99")
    # the numeric facts are kept for the audit
    assert facts_of(evaluation).missing_rooms == D("2.00")
    assert facts_of(evaluation).percent_condition is True


def test_the_confidence_gate_boundary_through_the_evaluation() -> None:
    assert run(baseline_confidence=D("49.99")).status == S.SUPPRESSED_LOW_CONFIDENCE
    assert run(baseline_confidence=D("50.00")).status == S.TRIGGERED


def test_the_final_confidence_is_the_minimum_of_baseline_and_pattern() -> None:
    high_baseline_low_pattern = run(
        pickups=(10,) * 12,
        selection=pickup_selection([10] * 12, approximate=range(12)),
        baseline_confidence=D("99.00"),
    )
    # 12 approximate pairs: pattern confidence 65 (capped); baseline 99 -> final 65
    assert high_baseline_low_pattern.confidence_score == D("65.00")
    low_baseline_high_pattern = run(baseline_confidence=D("55.00"))
    assert low_baseline_high_pattern.confidence_score == D("55.00")  # pattern is 100


# --- H: materiality --------------------------------------------------------------------------


def test_a_closed_night_is_not_applicable() -> None:
    evaluation = run(available=0, rooms=0, prior_rooms=0)
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.PROPERTY_CLOSED_FOR_STAY_DATE,)


def test_a_closed_night_wins_over_near_sold_out() -> None:
    # 0 available and 0 rooms is "remaining capacity 0" too: closed is checked first
    evaluation = run(available=0, rooms=0)
    assert evaluation.reason_codes == (R.PROPERTY_CLOSED_FOR_STAY_DATE,)
    assert facts_of(evaluation).remaining_capacity == 0


@pytest.mark.parametrize(
    ("available", "rooms", "sold_out"),
    [
        (30, 28, False),  # 2 rooms left: evaluable
        (30, 29, True),  # 1 room left
        (30, 30, True),  # sold out
        (30, 33, True),  # overbooked
    ],
)
def test_near_sold_out_is_at_most_one_room_left(available: int, rooms: int, sold_out: bool) -> None:
    evaluation = run(rooms=rooms, available=available)
    if sold_out:
        assert evaluation.status == S.NOT_APPLICABLE
        assert evaluation.reason_codes == (R.PICKUP_NEAR_SOLD_OUT,)
        assert facts_of(evaluation).remaining_capacity == available - rooms
    else:
        assert evaluation.status != S.NOT_APPLICABLE


def test_near_sold_out_is_evaluated_before_data_sufficiency() -> None:
    # nothing to sell: "not applicable" is the honest answer even without prior or history
    evaluation = run(available=21, rooms=20, prior_rooms=None, selection=make_selection([]))
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.PICKUP_NEAR_SOLD_OUT,)


def test_an_unknown_inventory_does_not_stop_the_pickup() -> None:
    evaluation = run(available=None)
    assert evaluation.status == S.TRIGGERED
    assert facts_of(evaluation).remaining_capacity is None
    assert facts_of(evaluation).rooms_available is None


# --- data sufficiency ------------------------------------------------------------------------


def test_an_insufficient_baseline_is_insufficient_data() -> None:
    evaluation = run(baseline_status=ExpectedStatus.INSUFFICIENT_DATA, baseline_confidence=D(0))
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.EXPECTED_BASELINE_INSUFFICIENT,)
    assert evaluation.confidence_score == D("0.00")


def test_a_missing_baseline_is_insufficient_data() -> None:
    evaluation = run(baseline_status=None)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.EXPECTED_BASELINE_MISSING,)
    assert evaluation.target_baseline_id is None


def test_fewer_than_five_pairs_is_insufficient_data() -> None:
    evaluation = run(pickups=(10,) * 4)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PAIR_SAMPLE_INSUFFICIENT,)
    pattern = facts_of(evaluation).pattern
    assert pattern is not None
    assert pattern.pair_count == 4
    assert pattern.median is None  # no number without a reliable sample
    assert facts_of(evaluation).expected_pickup is None


def test_exactly_five_pairs_is_enough() -> None:
    assert run(pickups=(10,) * 5).status == S.TRIGGERED


def test_the_diagnostics_of_a_short_selection_are_reported() -> None:
    selection = make_selection(
        pickup_selection([10] * 3).pairs,
        rejected_uncertain_count=2,
        missing_endpoint_count=4,
        excluded_future_count=1,
    )
    pattern = facts_of(run(selection=selection)).pattern
    assert pattern is not None
    assert (
        pattern.rejected_uncertain_count,
        pattern.missing_endpoint_count,
        pattern.excluded_future_count,
    ) == (2, 4, 1)


def test_an_evaluation_carries_its_target_baseline_and_versions() -> None:
    context = target_context()
    evaluation = evaluate_pickup(
        context, prior=prior_of(12), selection=pickup_selection([10] * 12), reference=ADR
    )
    assert evaluation.workspace_id == context.workspace_id
    assert evaluation.property_id == context.property_id
    assert evaluation.data_source_id == context.data_source_id
    assert evaluation.target_snapshot_id == context.target_snapshot_id
    assert evaluation.target_baseline_id == context.baseline_id
    assert evaluation.snapshot_local_date == TARGET_SNAPSHOT_DAY
    assert evaluation.stay_date == TARGET_STAY
    assert evaluation.lead_time_days == 14
    assert evaluation.rules_version == "revenue-decisions-v1"
    assert evaluation.pattern_version == "revenue-curve-pattern-v1"
    assert len(evaluation.calculation_fingerprint) == 64


def test_a_ready_baseline_without_a_confidence_is_a_corrupt_input() -> None:
    context = target_context(baseline_confidence=None)
    with pytest.raises(ValueError):
        evaluate_pickup(
            context, prior=prior_of(12), selection=pickup_selection([10] * 12), reference=ADR
        )
