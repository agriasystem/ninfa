"""Numerical integrity: DECISION values versus DISPLAYED values (Gate 5 final review). Pure.

A threshold is compared with the full-precision value the calculation produced; the two-decimal
value that is shown is derived AFTER the decision and never decides anything:

    CALCULATION VALUE -> THRESHOLD COMPARISON -> STATUS -> DISPLAY QUANTIZATION

The old two-decimal boundaries (-19.99 / -20.00, 9.99 / 10.00, ...) live in the pickup and
occupancy test modules and keep passing; here are the cases that only exist beyond two decimals.
"""

import dataclasses
import re
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from app.modules.intelligence.revenue import occupancy as occupancy_module
from app.modules.intelligence.revenue import pickup as pickup_module
from app.modules.intelligence.revenue.fingerprint import calculation_fingerprint
from app.modules.intelligence.revenue.impact import ReferenceAdr
from app.modules.intelligence.revenue.occupancy import (
    classify_occupancy,
    evaluate_occupancy,
    gap_condition,
    shortfall_condition,
)
from app.modules.intelligence.revenue.pickup import (
    classify_pickup,
    evaluate_pickup,
    percent_condition,
    rooms_condition,
)
from app.modules.intelligence.revenue.precision import (
    CALCULATION_CONTEXT,
    canonical_text,
    display_text,
    for_display,
    percent_of,
)
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    OccupancyFacts,
    OccupancyThresholds,
    PickupFacts,
    ReasonCode,
    ReferenceAdrSource,
    RevenueDecisionEvaluation,
)
from tests.revenue_support import (
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    pickup_selection,
    point,
    remaining_selection,
    target_context,
)

D = Decimal
S = EvaluationStatus
R = ReasonCode
ADR = ReferenceAdr(D("100.00"), ReferenceAdrSource.CURRENT_ON_BOOKS_ADR)
NO_SHORTFALL_RULE = OccupancyThresholds(min_room_shortfall=D("1000000"))  # isolates the gap rule


# --- the helpers -----------------------------------------------------------------------------


def test_a_quotient_keeps_every_digit_it_is_not_rounded_to_two_decimals() -> None:
    assert percent_of(D("-3999"), D("20000")) == D("-19.995")
    assert percent_of(D("1"), D("3")) == D("33.333333333333333333333333333333333333333333333333")
    assert len(percent_of(D("-1"), D("7")).as_tuple().digits) == 50  # a repeating decimal


def test_a_quotient_does_not_depend_on_the_process_wide_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 4
        assert percent_of(D("-3999"), D("20000")) == D("-19.995")


def test_the_display_value_rounds_half_up_away_from_zero() -> None:
    assert for_display(D("-19.995")) == D("-20.00")
    assert for_display(D("-20.005")) == D("-20.01")
    assert for_display(D("9.995")) == D("10.00")
    assert for_display(D("10.004")) == D("10.00")
    assert for_display(D("3.125")) == D("3.13")
    assert display_text(D("10")) == "10.00"
    assert display_text(None) is None


def test_the_canonical_text_is_deterministic_and_never_drops_a_digit() -> None:
    assert (
        canonical_text(D("10.00")) == canonical_text(D("10")) == canonical_text(D("1E+1")) == "10"
    )
    assert canonical_text(D("-0.00")) == canonical_text(D("0")) == "0"
    assert canonical_text(D("100")) == canonical_text(D("1E+2")) == "100"
    assert canonical_text(D("-19.995")) == "-19.995"
    assert canonical_text(D("-19.995")) != canonical_text(D("-20.00"))
    assert canonical_text(D("0.10")) == "0.1"
    assert canonical_text(None) is None
    long = D("-19.99500000000000000000000000000000000000001")
    assert canonical_text(long) == "-19.99500000000000000000000000000000000000001"


# --- REV_PICKUP_LOW: the percentage ----------------------------------------------------------


def pickup(rooms: int, expected_pickup: int) -> RevenueDecisionEvaluation:
    """`expected_pickup` rooms were picked up by every one of 12 historical stay dates; today the
    night has `rooms` rooms and had none a week ago, with an unknown inventory."""
    context = target_context(rooms=rooms, available=None)
    return evaluate_pickup(
        context,
        prior=point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, 0),
        selection=pickup_selection([expected_pickup] * 12),
        reference=ADR,
    )


def pickup_facts(evaluation: RevenueDecisionEvaluation) -> PickupFacts:
    assert isinstance(evaluation.facts, PickupFacts)
    return evaluation.facts


def test_minus_19_995_is_displayed_as_minus_20_but_does_not_trigger() -> None:
    evaluation = pickup(rooms=16001, expected_pickup=20000)  # (16001 - 20000) / 20000 = -19.995 %
    facts = pickup_facts(evaluation)

    assert facts.delta_percent_exact == D("-19.995")  # the value that decides
    assert facts.delta_percent == D("-20.00")  # the value that is shown
    assert facts.percent_condition is False
    assert (evaluation.status, evaluation.reason_codes) == (
        S.CLEAR,
        (R.CLEAR_WITHIN_EXPECTED_RANGE,),
    )
    assert evaluation.revenue_gap_proxy is None


def test_exactly_minus_20_triggers() -> None:
    evaluation = pickup(rooms=16000, expected_pickup=20000)
    facts = pickup_facts(evaluation)

    assert facts.delta_percent_exact == D("-20")
    assert facts.percent_condition is True
    assert evaluation.status == S.TRIGGERED


def test_minus_20_005_triggers_and_is_displayed_as_minus_20_01() -> None:
    evaluation = pickup(rooms=15999, expected_pickup=20000)
    facts = pickup_facts(evaluation)

    assert facts.delta_percent_exact == D("-20.005")
    assert facts.delta_percent == D("-20.01")
    assert evaluation.status == S.TRIGGERED


def test_minus_20_001_is_displayed_like_the_case_that_does_not_trigger_and_does_trigger() -> None:
    """Two evaluations that display the SAME -20.00 have OPPOSITE outcomes: the decision is not
    taken on the displayed value."""
    below = pickup(rooms=16001, expected_pickup=20000)  # -19.995 %
    above = pickup(rooms=79999, expected_pickup=100000)  # -20.001 %

    assert pickup_facts(below).delta_percent == pickup_facts(above).delta_percent == D("-20.00")
    assert pickup_facts(above).delta_percent_exact == D("-20.001")
    assert (below.status, above.status) == (S.CLEAR, S.TRIGGERED)
    assert below.calculation_fingerprint != above.calculation_fingerprint


def test_a_repeating_quotient_keeps_its_digits_and_displays_rounded() -> None:
    facts = pickup_facts(pickup(rooms=6, expected_pickup=7))  # (6 - 7) / 7 = -14.2857142857... %

    assert facts.delta_percent == D("-14.29")
    assert facts.delta_percent_exact is not None
    assert str(facts.delta_percent_exact).startswith("-14.28571428571428571428571428571428571428")
    assert facts.delta_percent_exact != facts.delta_percent


@pytest.mark.parametrize(
    ("delta_percent", "expected"),
    [
        ("-19.99", False),
        ("-19.995", False),
        ("-19.9999999999", False),
        ("-20", True),
        ("-20.000", True),
        ("-20.0000000001", True),
        ("-20.001", True),
    ],
)
def test_the_percentage_condition_on_decision_values(delta_percent: str, expected: bool) -> None:
    assert percent_condition(D(delta_percent)) is expected


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("1.99", False),
        ("1.995", False),
        ("1.9999999999", False),
        ("2", True),
        ("2.000", True),
        ("2.0000000001", True),
    ],
)
def test_the_room_condition_on_decision_values(missing: str, expected: bool) -> None:
    """Rooms are exact at two decimals in the engine (a median of integers), but the comparison
    itself never rounds: a value beyond two decimals is compared as it is."""
    assert rooms_condition(D(missing)) is expected


def test_the_pickup_status_is_decided_on_unrounded_inputs() -> None:
    almost = classify_pickup(D("-19.995"), D("3"), D("90"))
    exactly = classify_pickup(D("-20"), D("3"), D("90"))
    short_of_rooms = classify_pickup(D("-30"), D("1.995"), D("90"))
    assert almost == (S.CLEAR, (R.CLEAR_WITHIN_EXPECTED_RANGE,))
    assert exactly == (S.TRIGGERED, (R.TRIGGER_PICKUP_SHORTFALL,))
    assert short_of_rooms == (S.CLEAR, (R.CLEAR_WITHIN_EXPECTED_RANGE,))


# --- REV_OCCUPANCY_RISK: the gap and the shortfall -------------------------------------------


def occupancy(
    finals: list[int], *, rooms: int = 1000, available: int = 20000
) -> RevenueDecisionEvaluation:
    """Nothing usually arrives after the anchor (remaining net pickup 0); the nights usually end
    at `finals`. With only the gap rule active (see `NO_SHORTFALL_RULE`) the gap is
    (final - rooms) / available * 100."""
    return evaluate_occupancy(
        target_context(rooms=rooms, available=available),
        selection=remaining_selection([0] * len(finals), finals),
        reference=ADR,
        thresholds=NO_SHORTFALL_RULE,
    )


def occupancy_facts(evaluation: RevenueDecisionEvaluation) -> OccupancyFacts:
    assert isinstance(evaluation.facts, OccupancyFacts)
    return evaluation.facts


def test_a_gap_of_9_995_is_displayed_as_10_but_does_not_trigger() -> None:
    evaluation = occupancy([2999] * 12)  # 1999 rooms short of 20000: 9.995 points
    facts = occupancy_facts(evaluation)

    assert facts.occupancy_gap_pp_exact == D("9.995")
    assert facts.occupancy_gap_pp == D("10.00")
    assert facts.gap_condition is False
    assert (evaluation.status, evaluation.reason_codes) == (
        S.CLEAR,
        (R.CLEAR_WITHIN_EXPECTED_RANGE,),
    )
    assert evaluation.revenue_gap_proxy is None


def test_a_gap_of_exactly_10_triggers() -> None:
    evaluation = occupancy([3000] * 12)  # 2000 rooms short of 20000
    facts = occupancy_facts(evaluation)

    assert facts.occupancy_gap_pp_exact == D("10")
    assert facts.gap_condition is True
    assert evaluation.status == S.TRIGGERED
    assert evaluation.reason_codes == (R.TRIGGER_OCCUPANCY_GAP,)


def test_a_gap_of_10_005_triggers_and_is_displayed_as_10_01() -> None:
    facts = occupancy_facts(occupancy([3001] * 12))

    assert facts.occupancy_gap_pp_exact == D("10.005")
    assert facts.occupancy_gap_pp == D("10.01")
    assert facts.gap_condition is True


def test_a_gap_just_below_10_is_not_rescued_by_rounding() -> None:
    finals = [2999, 3000] * 6  # median 2999.5: 1999.5 rooms short, 9.9975 points
    evaluation = occupancy(finals)
    facts = occupancy_facts(evaluation)

    assert facts.occupancy_gap_pp_exact == D("9.9975")
    assert facts.occupancy_gap_pp == D("10.00")
    assert evaluation.status == S.CLEAR


def test_the_gap_is_one_division_of_an_exact_numerator() -> None:
    """max(0, final occupancy - forecast occupancy) equals shortfall / available * 100, and it is
    computed that way: never a difference of two rounded quotients."""
    facts = occupancy_facts(occupancy([30] * 12, rooms=1, available=30))  # 29 rooms short of 30
    assert facts.forecast_occupancy_exact is not None
    assert facts.expected_final_occupancy_exact is not None
    assert facts.occupancy_gap_pp_exact is not None
    difference = CALCULATION_CONTEXT.subtract(
        facts.expected_final_occupancy_exact, facts.forecast_occupancy_exact
    )
    assert abs(facts.occupancy_gap_pp_exact - difference) < D("1e-40")
    assert facts.occupancy_gap_pp_exact == percent_of(D(29), D(30))


def test_occupancies_keep_their_digits_and_display_rounded() -> None:
    facts = occupancy_facts(
        evaluate_occupancy(
            target_context(rooms=1, available=3),
            selection=remaining_selection([0] * 12, [2] * 12),
            reference=ADR,
        )
    )
    assert (facts.forecast_occupancy, facts.expected_final_occupancy) == (D("33.33"), D("66.67"))
    assert facts.forecast_occupancy_exact == percent_of(D(1), D(3))
    assert facts.expected_final_occupancy_exact == percent_of(D(2), D(3))
    assert facts.forecast_occupancy_exact != facts.forecast_occupancy


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        ("9.99", False),
        ("9.995", False),
        ("9.9999999999", False),
        ("10", True),
        ("10.0000000001", True),
    ],
)
def test_the_gap_condition_on_decision_values(gap: str, expected: bool) -> None:
    assert gap_condition(D(gap)) is expected


@pytest.mark.parametrize(
    ("shortfall", "expected"),
    [
        ("2.99", False),
        ("2.995", False),
        ("2.9999999999", False),
        ("3", True),
        ("3.0000000001", True),
    ],
)
def test_the_shortfall_condition_on_decision_values(shortfall: str, expected: bool) -> None:
    assert shortfall_condition(D(shortfall)) is expected


def test_the_occupancy_status_is_decided_on_unrounded_inputs() -> None:
    assert classify_occupancy(D("9.995"), D("0"), D("90")) == (
        S.CLEAR,
        (R.CLEAR_WITHIN_EXPECTED_RANGE,),
    )
    assert classify_occupancy(D("0"), D("2.995"), D("90")) == (
        S.CLEAR,
        (R.CLEAR_WITHIN_EXPECTED_RANGE,),
    )
    assert classify_occupancy(D("10"), D("0"), D("90")) == (S.TRIGGERED, (R.TRIGGER_OCCUPANCY_GAP,))
    assert classify_occupancy(D("0"), D("3"), D("90")) == (S.TRIGGERED, (R.TRIGGER_ROOM_SHORTFALL,))


# --- the decision never reads the displayed value --------------------------------------------


def test_the_status_does_not_change_when_the_display_rounding_is_sabotaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the display value leaked into a decision, replacing it would change a status."""
    cases = [pickup(16001, 20000), pickup(16000, 20000), pickup(79999, 100000), pickup(6, 7)]
    gap_cases = [occupancy([2999] * 12), occupancy([3000] * 12), occupancy([3001] * 12)]
    before = [(e.status, e.reason_codes) for e in cases + gap_cases]

    def sabotage(value: Decimal) -> Decimal:
        return D("-999999")

    monkeypatch.setattr(pickup_module, "for_display", sabotage)
    monkeypatch.setattr(occupancy_module, "for_display", sabotage)
    sabotaged = [
        pickup(16001, 20000),
        pickup(16000, 20000),
        pickup(79999, 100000),
        pickup(6, 7),
        occupancy([2999] * 12),
        occupancy([3000] * 12),
        occupancy([3001] * 12),
    ]

    assert [(e.status, e.reason_codes) for e in sabotaged] == before
    assert pickup_facts(sabotaged[0]).delta_percent == D("-999999")  # only the display changed
    assert pickup_facts(sabotaged[0]).delta_percent_exact == D("-19.995")


# --- the fingerprint keeps the decision precision --------------------------------------------


def fingerprint_of(
    evaluation: RevenueDecisionEvaluation, facts: PickupFacts | OccupancyFacts
) -> str:
    context = target_context()
    return calculation_fingerprint(
        decision_type=evaluation.decision_type,
        status=evaluation.status,
        target=context,
        confidence_score=evaluation.confidence_score,
        reason_codes=evaluation.reason_codes,
        facts=facts,
        evidence_snapshot_ids=evaluation.evidence_snapshot_ids,
        reference=ADR,
        revenue_gap_proxy=evaluation.revenue_gap_proxy,
    )


def test_two_percentages_that_display_alike_have_different_fingerprints() -> None:
    evaluation = pickup(16001, 20000)
    facts = pickup_facts(evaluation)
    just_above = dataclasses.replace(facts, delta_percent_exact=D("-19.995"))
    just_below = dataclasses.replace(facts, delta_percent_exact=D("-20.001"))
    assert just_above.delta_percent == just_below.delta_percent  # the same display value
    assert just_above.canonical_payload() != just_below.canonical_payload()
    assert fingerprint_of(evaluation, just_above) != fingerprint_of(evaluation, just_below)


def test_two_gaps_that_display_alike_have_different_fingerprints() -> None:
    evaluation = occupancy([2999] * 12)
    facts = occupancy_facts(evaluation)
    just_below = dataclasses.replace(facts, occupancy_gap_pp_exact=D("9.995"))
    just_above = dataclasses.replace(facts, occupancy_gap_pp_exact=D("10.004"))
    assert just_below.occupancy_gap_pp == just_above.occupancy_gap_pp  # the same display value
    assert fingerprint_of(evaluation, just_below) != fingerprint_of(evaluation, just_above)


def test_the_same_number_written_differently_has_the_same_fingerprint() -> None:
    evaluation = pickup(16000, 20000)
    facts = pickup_facts(evaluation)
    a = dataclasses.replace(facts, delta_percent_exact=D("-20"))
    b = dataclasses.replace(facts, delta_percent_exact=D("-20.000000"))
    c = dataclasses.replace(facts, delta_percent_exact=D("-2E+1"))
    assert (
        fingerprint_of(evaluation, a)
        == fingerprint_of(evaluation, b)
        == fingerprint_of(evaluation, c)
    )


def test_the_display_only_figures_are_not_part_of_the_fingerprint() -> None:
    evaluation = pickup(16001, 20000)
    facts = pickup_facts(evaluation)
    tampered = dataclasses.replace(facts, delta_percent=D("-99.99"))  # display only
    assert fingerprint_of(evaluation, facts) == fingerprint_of(evaluation, tampered)
    occupancy_evaluation = occupancy([2999] * 12)
    occupancy_facts_ = occupancy_facts(occupancy_evaluation)
    changed = dataclasses.replace(
        occupancy_facts_,
        forecast_occupancy=D("1"),
        expected_final_occupancy=D("2"),
        occupancy_gap_pp=D("3"),
    )
    assert fingerprint_of(occupancy_evaluation, occupancy_facts_) == fingerprint_of(
        occupancy_evaluation, changed
    )


def test_the_canonical_payload_holds_exact_values_and_the_presentation_holds_both() -> None:
    facts = pickup_facts(pickup(16001, 20000))
    assert facts.canonical_payload()["delta_percent_exact"] == "-19.995"
    assert "delta_percent" not in facts.canonical_payload()
    assert facts.payload()["delta_percent"] == "-20.00"
    assert facts.payload()["delta_percent_exact"] == "-19.995"


def test_the_fingerprint_is_stable_for_the_same_logical_input() -> None:
    selection = pickup_selection([20000] * 12)
    context = target_context(rooms=16001, available=None)
    prior = point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, 0)
    first = evaluate_pickup(context, prior=prior, selection=selection, reference=ADR)
    second = evaluate_pickup(context, prior=prior, selection=selection, reference=ADR)
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert re.fullmatch(r"[0-9a-f]{64}", first.calculation_fingerprint)


def test_no_versions_were_bumped_by_this_correction() -> None:
    evaluation = pickup(16000, 20000)
    assert evaluation.rules_version == "revenue-decisions-v1"
    assert evaluation.pattern_version == "revenue-curve-pattern-v1"
