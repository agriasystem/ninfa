"""REV_OCCUPANCY_RISK (Gate 5, groups I-L): forecast, inventory, gaps, thresholds. Pure."""

import json
from collections.abc import Sequence
from decimal import Decimal

import pytest

from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.revenue.impact import ReferenceAdr
from app.modules.intelligence.revenue.occupancy import (
    classify_occupancy,
    evaluate_occupancy,
    gap_condition,
    shortfall_condition,
)
from app.modules.intelligence.revenue.types import (
    OCCUPANCY_THRESHOLDS,
    EvaluationStatus,
    OccupancyFacts,
    PairSelection,
    ReasonCode,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
    RevenueDecisionType,
)
from tests.revenue_support import make_selection, remaining_selection, target_context

D = Decimal
CONFIDENT = D("90.00")
ADR = ReferenceAdr(D("100.00"), ReferenceAdrSource.CURRENT_ON_BOOKS_ADR)
S = EvaluationStatus
R = ReasonCode


def run(
    *,
    rooms: int = 20,
    available: int | None = 40,
    remaining: Sequence[int] = (4,) * 12,
    finals: Sequence[int] = (30,) * 12,
    baseline_confidence: Decimal = CONFIDENT,
    baseline_status: ExpectedStatus | None = ExpectedStatus.READY,
    selection: PairSelection | None = None,
    reference: ReferenceAdr = ADR,
) -> RevenueDecisionEvaluation:
    """By default: 20 rooms of 40 today, +4 rooms usually to come, usually 30 at the end."""
    return evaluate_occupancy(
        target_context(
            rooms=rooms,
            available=available,
            baseline_confidence=baseline_confidence,
            baseline_status=baseline_status,
        ),
        selection=selection if selection is not None else remaining_selection(remaining, finals),
        reference=reference,
    )


def facts_of(evaluation: RevenueDecisionEvaluation) -> OccupancyFacts:
    assert isinstance(evaluation.facts, OccupancyFacts)
    return evaluation.facts


# --- I: the minimal net-pickup forecast ------------------------------------------------------


def test_the_forecast_is_the_current_rooms_plus_the_expected_remaining_net_pickup() -> None:
    facts = facts_of(run())  # 20 + 4
    assert facts.expected_remaining_net_pickup == D("4.00")
    assert facts.raw_forecast_rooms == D("24.00")
    assert facts.forecast_rooms == D("24.00")


def test_the_expected_remaining_net_pickup_is_the_median_of_the_pairs() -> None:
    facts = facts_of(run(remaining=(1, 2, 3, 4, 5, 6, 7, 8), finals=(30,) * 8))
    assert facts.expected_remaining_net_pickup == D("4.50")
    assert facts.pattern is not None
    assert (facts.pattern.p25, facts.pattern.p75) == (D("2.75"), D("6.25"))


def test_cancellations_lower_the_remaining_net_pickup() -> None:
    # every historical night lost rooms after the anchor: the net pickup is negative
    facts = facts_of(run(rooms=20, remaining=(-3,) * 12, finals=(15,) * 12))
    assert facts.expected_remaining_net_pickup == D("-3.00")
    assert facts.forecast_rooms == D("17.00")  # fewer than today: no separate cancellation model


def test_the_forecast_is_floored_at_zero_and_nothing_else() -> None:
    facts = facts_of(run(rooms=2, remaining=(-9,) * 12, finals=(0,) * 12, available=40))
    assert facts.raw_forecast_rooms == D("-7.00")
    assert facts.forecast_rooms == D("0.00")
    assert facts.forecast_occupancy == D("0.00")


def test_the_forecast_has_no_upper_cap_overbooking_is_preserved() -> None:
    facts = facts_of(run(rooms=35, available=40, remaining=(9,) * 12, finals=(46,) * 12))
    assert facts.forecast_rooms == D("44.00")  # above the 40 rooms of the property
    assert facts.forecast_occupancy == D("110.00")  # not clamped to 100
    assert facts.expected_final_occupancy == D("115.00")


def test_the_expected_final_rooms_come_from_the_same_pairs() -> None:
    facts = facts_of(run(remaining=(2, 4, 6, 8, 10), finals=(10, 20, 40, 30, 50)))
    assert facts.expected_final_rooms == D("30.00")
    assert facts.pattern is not None
    assert [pair.other_rooms_on_books for pair in facts.pattern.pairs] == [10, 20, 40, 30, 50]


def test_both_occupancies_use_the_current_target_inventory() -> None:
    facts = facts_of(run(rooms=20, available=50, remaining=(5,) * 12, finals=(35,) * 12))
    assert facts.forecast_occupancy == D("50.00")  # 25 / 50
    assert facts.expected_final_occupancy == D("70.00")  # 35 / 50


def test_occupancies_are_rounded_half_up_to_two_decimals() -> None:
    facts = facts_of(run(rooms=1, available=3, remaining=(0,) * 12, finals=(2,) * 12))
    assert facts.forecast_occupancy == D("33.33")
    assert facts.expected_final_occupancy == D("66.67")


# --- J: inventory ----------------------------------------------------------------------------


def test_an_unknown_inventory_is_not_applicable() -> None:
    evaluation = run(available=None)
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.OCCUPANCY_INVENTORY_UNKNOWN,)
    assert facts_of(evaluation).forecast_occupancy is None
    assert evaluation.revenue_gap_proxy is None


def test_a_closed_night_is_not_applicable_and_never_divides_by_zero() -> None:
    evaluation = run(available=0, rooms=0)
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.PROPERTY_CLOSED_FOR_STAY_DATE,)


@pytest.mark.parametrize(("rooms", "available"), [(40, 40), (41, 40), (55, 40)])
def test_a_sold_out_or_overbooked_night_is_not_applicable(rooms: int, available: int) -> None:
    evaluation = run(rooms=rooms, available=available)
    assert evaluation.status == S.NOT_APPLICABLE
    assert evaluation.reason_codes == (R.OCCUPANCY_ALREADY_SOLD_OUT,)


def test_one_room_left_is_still_evaluated() -> None:
    assert run(rooms=39, available=40, remaining=(1,) * 12, finals=(40,) * 12).status != (
        S.NOT_APPLICABLE
    )


def test_inventory_is_checked_before_the_history() -> None:
    no_history = make_selection([])
    for available, reason in (
        (None, R.OCCUPANCY_INVENTORY_UNKNOWN),
        (0, R.PROPERTY_CLOSED_FOR_STAY_DATE),
        (10, R.OCCUPANCY_ALREADY_SOLD_OUT),
    ):
        evaluation = run(available=available, rooms=20, selection=no_history, baseline_status=None)
        assert evaluation.reason_codes == (reason,)


# --- K: gaps ---------------------------------------------------------------------------------


def test_room_shortfall_and_occupancy_gap() -> None:
    facts = facts_of(run())  # forecast 24 (60 %), expected final 30 (75 %)
    assert facts.room_shortfall == D("6.00")
    assert facts.occupancy_gap_pp == D("15.00")


def test_no_shortfall_and_no_gap_when_the_forecast_reaches_the_expected_final() -> None:
    facts = facts_of(run(rooms=28, remaining=(4,) * 12, finals=(30,) * 12))  # forecast 32 > 30
    assert facts.room_shortfall == D("0.00")
    assert facts.occupancy_gap_pp == D("0.00")  # never negative


def test_the_gap_is_in_percentage_points_not_a_relative_percentage() -> None:
    facts = facts_of(run(rooms=20, available=100, remaining=(2,) * 12, finals=(30,) * 12))
    assert facts.occupancy_gap_pp == D("8.00")  # 30 % - 22 %, not (30 - 22) / 22


# --- L: thresholds and boundaries ------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "expected"),
    [("9.99", False), ("10.00", True), ("10.01", True), ("0.00", False)],
)
def test_the_gap_boundary_is_10_points(gap: str, expected: bool) -> None:
    assert gap_condition(D(gap)) is expected


@pytest.mark.parametrize(
    ("shortfall", "expected"),
    [("2.99", False), ("3.00", True), ("3.01", True), ("0.00", False)],
)
def test_the_room_boundary_is_3(shortfall: str, expected: bool) -> None:
    assert shortfall_condition(D(shortfall)) is expected


@pytest.mark.parametrize(
    ("gap", "shortfall", "confidence", "status", "reason"),
    [
        ("9.99", "2.99", "90.00", S.CLEAR, R.CLEAR_WITHIN_EXPECTED_RANGE),
        ("10.00", "2.99", "90.00", S.TRIGGERED, R.TRIGGER_OCCUPANCY_GAP),
        ("9.99", "3.00", "90.00", S.TRIGGERED, R.TRIGGER_ROOM_SHORTFALL),
        ("10.00", "3.00", "90.00", S.TRIGGERED, R.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL),
        ("10.00", "3.00", "54.99", S.SUPPRESSED_LOW_CONFIDENCE, R.LOW_CONFIDENCE),
        ("10.00", "3.00", "55.00", S.TRIGGERED, R.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL),
        ("9.99", "2.99", "10.00", S.CLEAR, R.CLEAR_WITHIN_EXPECTED_RANGE),
    ],
)
def test_the_status_boundaries(
    gap: str, shortfall: str, confidence: str, status: EvaluationStatus, reason: ReasonCode
) -> None:
    assert classify_occupancy(D(gap), D(shortfall), D(confidence)) == (status, (reason,))


def test_either_condition_is_enough_to_trigger() -> None:
    # gap only: 8 of 20 rooms forecast (40 %), 10 expected (50 %): 10 points but only 2 rooms
    gap_only = run(rooms=6, available=20, remaining=(2,) * 12, finals=(10,) * 12)
    assert (facts_of(gap_only).occupancy_gap_pp, facts_of(gap_only).room_shortfall) == (
        D("10.00"),
        D("2.00"),
    )
    assert gap_only.status == S.TRIGGERED
    assert gap_only.reason_codes == (R.TRIGGER_OCCUPANCY_GAP,)
    # shortfall only: 3 rooms of 100 is 3 points
    rooms_only = run(rooms=30, available=100, remaining=(2,) * 12, finals=(35,) * 12)
    assert (facts_of(rooms_only).occupancy_gap_pp, facts_of(rooms_only).room_shortfall) == (
        D("3.00"),
        D("3.00"),
    )
    assert rooms_only.status == S.TRIGGERED
    assert rooms_only.reason_codes == (R.TRIGGER_ROOM_SHORTFALL,)


def test_a_triggered_occupancy_risk_with_both_conditions() -> None:
    evaluation = run()
    assert evaluation.status == S.TRIGGERED
    assert evaluation.reason_codes == (R.TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL,)
    assert evaluation.decision_type == RevenueDecisionType.REV_OCCUPANCY_RISK
    assert facts_of(evaluation).gap_condition is True
    assert facts_of(evaluation).shortfall_condition is True


def test_a_clear_occupancy_risk() -> None:
    evaluation = run(rooms=28, remaining=(4,) * 12, finals=(32,) * 12)
    assert evaluation.status == S.CLEAR
    assert evaluation.reason_codes == (R.CLEAR_WITHIN_EXPECTED_RANGE,)
    assert evaluation.revenue_gap_proxy is None


def test_a_suppressed_occupancy_risk_keeps_only_the_low_confidence_reason() -> None:
    evaluation = run(baseline_confidence=D("54.99"))
    assert evaluation.status == S.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.reason_codes == (R.LOW_CONFIDENCE,)
    assert facts_of(evaluation).room_shortfall == D("6.00")  # kept for the audit


def test_the_confidence_gate_boundary_through_the_evaluation() -> None:
    assert run(baseline_confidence=D("54.99")).status == S.SUPPRESSED_LOW_CONFIDENCE
    assert run(baseline_confidence=D("55.00")).status == S.TRIGGERED


def test_the_final_confidence_is_the_minimum_of_baseline_and_pattern() -> None:
    selection = remaining_selection([4] * 12, [30] * 12, approximate=range(12))
    capped = run(selection=selection, baseline_confidence=D("99.00"))
    assert capped.confidence_score == D("65.00")  # 12 approximate pairs: pattern capped at 65
    assert run(baseline_confidence=D("60.00")).confidence_score == D("60.00")


def test_the_thresholds_are_versioned_constants() -> None:
    assert OCCUPANCY_THRESHOLDS.min_gap_pp == D("10")
    assert OCCUPANCY_THRESHOLDS.min_room_shortfall == D("3")
    assert OCCUPANCY_THRESHOLDS.min_confidence == D("55")
    assert facts_of(run()).thresholds == OCCUPANCY_THRESHOLDS


# --- data sufficiency ------------------------------------------------------------------------


def test_an_insufficient_baseline_is_insufficient_data() -> None:
    evaluation = run(baseline_status=ExpectedStatus.INSUFFICIENT_DATA, baseline_confidence=D(0))
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.EXPECTED_BASELINE_INSUFFICIENT,)


def test_a_missing_baseline_is_insufficient_data() -> None:
    evaluation = run(baseline_status=None)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.EXPECTED_BASELINE_MISSING,)


def test_fewer_than_five_pairs_is_insufficient_data() -> None:
    evaluation = run(remaining=(4,) * 4, finals=(30,) * 4)
    assert evaluation.status == S.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (R.PAIR_SAMPLE_INSUFFICIENT,)
    assert facts_of(evaluation).forecast_rooms is None
    assert facts_of(evaluation).pattern is not None


def test_exactly_five_pairs_is_enough() -> None:
    assert run(remaining=(4,) * 5, finals=(30,) * 5).status == S.TRIGGERED


# --- explainability --------------------------------------------------------------------------


def test_a_triggered_evaluation_exposes_every_number_behind_it() -> None:
    evaluation = run()
    facts = facts_of(evaluation)
    assert facts.current_rooms_on_books == 20
    assert facts.rooms_available == 40
    assert facts.expected_remaining_net_pickup is not None
    assert facts.forecast_rooms is not None
    assert facts.expected_final_rooms is not None
    assert facts.forecast_occupancy is not None
    assert facts.expected_final_occupancy is not None
    assert facts.occupancy_gap_pp is not None
    assert facts.room_shortfall is not None
    assert facts.baseline_confidence == CONFIDENT
    assert facts.pattern is not None and facts.pattern.pair_count == 12
    assert evaluation.confidence_score == CONFIDENT
    assert evaluation.revenue_gap_proxy == D("600.00")  # 6 rooms x 100.00


def test_the_facts_are_plain_numbers_and_codes_never_prose() -> None:
    payload = facts_of(run()).payload()
    text = json.dumps(payload)
    assert json.loads(text) == payload  # serialisable as it is: no Decimal, no object
    assert "recommend" not in text.lower()
    assert "should" not in text.lower()
