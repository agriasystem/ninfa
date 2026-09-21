"""COST_CPOR_ANOMALY: the rule, the thresholds, the confidence gate and the five statuses
(Gate 7 groups I, J, K, L, M and the pure part of N and Q). Real builders, no database.
"""

import dataclasses
import hashlib
import json
from decimal import Decimal
from typing import Any

import pytest

from app.modules.intelligence.costs.detector import evaluate_cpor_anomaly
from app.modules.intelligence.costs.fingerprint import evaluation_fingerprint
from app.modules.intelligence.costs.precision import canonical_text
from app.modules.intelligence.costs.selection import select_comparables
from app.modules.intelligence.costs.types import (
    COST_EXPECTED_METHOD,
    COST_METRIC_VERSION,
    COST_RULES_VERSION,
    COST_THRESHOLDS,
    CostDecisionEvaluation,
    CostDecisionType,
    EvaluationStatus,
    ReasonCode,
)
from app.modules.intelligence.revenue.types import EvaluationStatus as RevenueStatus
from app.modules.invoices.cost_categories import CostCategory
from tests.cost_support import (
    AUGUST,
    COMPARABLE_MONTHS,
    EUR,
    LAUNDRY,
    OTHER,
    USD,
    UTILITIES,
    Ledger,
    cpor_history,
)

D = Decimal
AUG = AUGUST
FLAT = ["10"] * 8  # eight observed months at a CPOR of exactly 10 (IQR 0, upper fence 10)
UNEVEN = [D(v) for v in (8, 9, 10, 11, 12)]  # median 10, P25 9, P75 11, IQR 2, fence 14
TRIGGERED, CLEAR, SUPPRESSED = (
    EvaluationStatus.TRIGGERED,
    EvaluationStatus.CLEAR,
    EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE,
)
INSUFFICIENT, NOT_APPLICABLE = EvaluationStatus.INSUFFICIENT_DATA, EvaluationStatus.NOT_APPLICABLE
# a 31-day month with exactly 500 occupied room nights (4 days of 17 rooms, 27 days of 16)
ROOMS_500 = [17] * 4 + [16] * 27


def world(
    values: list[str],
    *,
    net: str,
    rooms: int | list[int] = 10,
    target_confidence: str = "80",
    target_reconstructed: bool = False,
    **history: Any,
) -> Ledger:
    months = COMPARABLE_MONTHS[: len(values)]
    ledger = cpor_history(dict(zip(months, values, strict=True)), **history)
    ledger.cost(AUG, LAUNDRY, net, confidence=target_confidence)
    ledger.rooms(AUG, rooms, reconstructed=range(1, 32) if target_reconstructed else ())
    return ledger


def run(
    ledger: Ledger, category: CostCategory = LAUNDRY, currency: str = EUR
) -> CostDecisionEvaluation:
    target = ledger.metric(AUG, category, currency)
    return evaluate_cpor_anomaly(
        target, lambda: select_comparables(AUG, ledger.metric_of(category, currency))
    )


def never() -> Any:
    raise AssertionError("the comparables must not be selected for this target")


# --- I. expected CPOR and the deltas ------------------------------------------------------------


def test_the_expected_cpor_is_the_median_of_the_comparables() -> None:
    evaluation = run(world([str(v) for v in UNEVEN], net="3100"))

    assert evaluation.expected_cpor_exact == D(10) and evaluation.sample_count == 5
    assert (evaluation.p25_exact, evaluation.p75_exact, evaluation.iqr_exact) == (D(9), D(11), D(2))
    assert evaluation.upper_fence_exact == D(14)


def test_a_normal_positive_expected_cpor_is_evaluated() -> None:
    assert run(world(FLAT, net="3100")).status == CLEAR


def test_an_expected_cpor_of_zero_is_not_applicable() -> None:
    ledger = Ledger()
    for period in COMPARABLE_MONTHS[:5]:
        ledger.cost(period, LAUNDRY, "0", absolute="500")  # +500 invoice, -500 credit note
        ledger.rooms(period, 10)
    ledger.cost(AUG, LAUNDRY, "3720")
    ledger.rooms(AUG, 10)

    evaluation = run(ledger)

    assert evaluation.status == NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.EXPECTED_CPOR_NON_POSITIVE,)
    assert evaluation.expected_cpor_exact == D(0)
    assert evaluation.delta_percent_exact is None and evaluation.cost_gap_proxy_exact is None
    assert evaluation.confidence_score == D(0)  # no confidence was assessed


def test_a_negative_expected_cpor_is_not_applicable() -> None:
    ledger = Ledger()
    for period in COMPARABLE_MONTHS[:6]:
        ledger.cost(period, LAUNDRY, "-620", absolute="620", credit_lines=1, credit_cost="-620")
        ledger.rooms(period, 10)
    ledger.cost(AUG, LAUNDRY, "3720")
    ledger.rooms(AUG, 10)

    evaluation = run(ledger)

    assert evaluation.status == NOT_APPLICABLE and evaluation.expected_cpor_exact == D(-2)
    assert evaluation.reason_codes == (ReasonCode.EXPECTED_CPOR_NON_POSITIVE,)


def test_the_deltas_and_the_expected_cost_at_the_target_volume_are_exact() -> None:
    evaluation = run(world(FLAT, net="3720"))  # CPOR 12 over 310 room nights

    assert evaluation.target_metric.cpor_exact == D(12)
    assert evaluation.delta_cpor_exact == D(2)
    assert evaluation.delta_percent_exact == D(20)
    assert evaluation.expected_cost_for_target_volume_exact == D(3100)  # 10 * 310
    assert evaluation.cost_gap_proxy_exact == D(620)
    assert evaluation.delta_percent_display == D("20.00")


def test_the_delta_percent_is_relative_to_the_expected_cpor() -> None:
    evaluation = run(world(["4"] * 8, net="1488"))  # CPOR 4.8 against 4: +20 %
    assert evaluation.delta_percent_exact == D(20)


# --- J. the cost gap proxy ------------------------------------------------------------------------


def test_a_target_above_the_expected_cost_has_a_positive_gap() -> None:
    assert run(world(FLAT, net="4000")).cost_gap_proxy_exact == D(900)  # 4000 - 3100


def test_a_target_below_the_expected_cost_has_a_gap_floored_at_zero() -> None:
    evaluation = run(world(FLAT, net="3000"))
    assert evaluation.cost_gap_proxy_exact == D(0)  # never negative
    assert evaluation.delta_cpor_exact is not None and evaluation.delta_cpor_exact < 0


def test_the_gap_proxy_is_exact_and_its_display_is_half_up() -> None:
    evaluation = run(world(FLAT, net="3720.005"))

    assert evaluation.cost_gap_proxy_exact == D("620.005")  # exact, three decimals
    assert evaluation.cost_gap_proxy_display == D("620.01")  # presentation only


def test_the_gap_proxy_is_never_called_a_loss_a_saving_or_an_impact() -> None:
    evaluation = run(world(FLAT, net="3720"))
    forbidden = ("loss", "saving", "impact", "recover", "priority", "recommend", "profit")
    names = [f.name for f in dataclasses.fields(evaluation)]
    names += [key for key in evaluation.payload()]
    assert not [n for n in names if any(word in n.lower() for word in forbidden)]
    assert "gross" in (CostDecisionEvaluation.__doc__ or "").lower()


# --- K. the trigger: three thresholds, AND, exact boundaries ------------------------------------


def test_a_relative_delta_just_below_20_percent_does_not_reach_the_threshold() -> None:
    evaluation = run(world(FLAT, net="3719.99"))

    assert evaluation.delta_percent_exact is not None and evaluation.delta_percent_exact < 20
    assert evaluation.delta_percent_display == D("20.00")  # displays 20, is not 20
    assert evaluation.relative_condition is False and evaluation.status == CLEAR
    assert evaluation.gap_condition and evaluation.upper_fence_condition  # only this one fails


def test_a_relative_delta_of_exactly_20_percent_reaches_the_threshold() -> None:
    evaluation = run(world(FLAT, net="3720"))
    assert evaluation.relative_condition is True and evaluation.status == TRIGGERED


def test_a_relative_delta_above_20_percent_reaches_the_threshold() -> None:
    evaluation = run(world(FLAT, net="3800"))
    assert evaluation.relative_condition is True and evaluation.status == TRIGGERED


def test_a_gap_just_below_100_does_not_reach_the_threshold() -> None:
    evaluation = run(world(["0.1"] * 8, net="149.99", rooms=ROOMS_500))

    assert evaluation.cost_gap_proxy_exact == D("99.99") and evaluation.gap_condition is False
    assert evaluation.cost_gap_proxy_display == D("99.99")
    assert evaluation.relative_condition and evaluation.upper_fence_condition
    assert evaluation.status == CLEAR


def test_a_gap_of_exactly_100_reaches_the_threshold() -> None:
    evaluation = run(world(["0.1"] * 8, net="150", rooms=ROOMS_500))

    assert evaluation.cost_gap_proxy_exact == D(100) and evaluation.gap_condition is True
    assert evaluation.status == TRIGGERED


def test_a_gap_that_only_displays_as_100_does_not_reach_the_threshold() -> None:
    evaluation = run(world(["0.1"] * 8, net="149.995", rooms=ROOMS_500))

    assert evaluation.cost_gap_proxy_display == D("100.00")  # 99.995 shown as 100.00 ...
    assert evaluation.gap_condition is False  # ... but decided on the exact value
    assert evaluation.status == CLEAR


def test_a_cpor_just_below_the_upper_fence_does_not_trigger() -> None:
    evaluation = run(world([str(v) for v in UNEVEN], net="4336.9"))  # 13.99 against a fence of 14

    assert evaluation.target_metric.cpor_exact == D("13.99")
    assert evaluation.upper_fence_condition is False and evaluation.status == CLEAR
    assert evaluation.relative_condition and evaluation.gap_condition


def test_a_cpor_equal_to_the_upper_fence_reaches_it() -> None:
    evaluation = run(world([str(v) for v in UNEVEN], net="4340"))  # exactly 14

    assert evaluation.target_metric.cpor_exact == evaluation.upper_fence_exact == D(14)
    assert evaluation.upper_fence_condition is True and evaluation.status == TRIGGERED


def test_a_cpor_above_expected_but_not_above_the_fence_is_clear_even_with_a_high_delta() -> None:
    values = ["4", "8", "12", "16", "20", "24", "28"]  # median 16, P75 22, IQR 12, fence 40
    evaluation = run(world(values, net=str(24 * 310)))

    assert evaluation.delta_percent_exact == D(50)  # +50 % ...
    assert evaluation.relative_condition is True and evaluation.upper_fence_condition is False
    assert evaluation.status == CLEAR  # ... but inside the historical volatility


@pytest.mark.parametrize(
    ("values", "net", "rooms", "failing"),
    [
        (FLAT, "3719.99", 10, "relative_condition"),
        (["0.1"] * 8, "149.99", ROOMS_500, "gap_condition"),
        ([str(v) for v in UNEVEN], "4336.9", 10, "upper_fence_condition"),
        (FLAT, "3000", 10, "above_expected_condition"),
    ],
)
def test_all_the_conditions_must_hold_and_one_missing_condition_means_clear(
    values: list[str], net: str, rooms: int | list[int], failing: str
) -> None:
    evaluation = run(world(values, net=net, rooms=rooms))

    assert getattr(evaluation, failing) is False
    assert evaluation.status == CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)


def test_when_every_condition_holds_the_rule_triggers() -> None:
    evaluation = run(world(FLAT, net="4000"))

    assert [
        evaluation.above_expected_condition,
        evaluation.relative_condition,
        evaluation.upper_fence_condition,
        evaluation.gap_condition,
    ] == [True, True, True, True]
    assert evaluation.status == TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_CPOR_ANOMALY,)


def test_the_thresholds_are_the_versioned_policy() -> None:
    thresholds = COST_THRESHOLDS
    assert (thresholds.relative_percent, thresholds.absolute_gap) == (D(20), D(100))
    assert thresholds.iqr_multiplier == D("1.5") and thresholds.min_confidence == D(55)
    assert thresholds.min_classification_coverage == D(70)
    assert (thresholds.min_comparables, thresholds.max_comparables) == (5, 12)
    assert (thresholds.lookback_months, thresholds.season_window_months) == (36, 2)
    assert run(world(FLAT, net="4000")).thresholds == thresholds


def test_the_versions_are_stated_on_every_evaluation() -> None:
    evaluation = run(world(FLAT, net="4000"))
    assert evaluation.rules_version == COST_RULES_VERSION == "cost-cpor-anomaly-v1"
    assert evaluation.metric_version == COST_METRIC_VERSION == "cost-period-metric-v1"
    assert evaluation.expected_method == COST_EXPECTED_METHOD == "cost-cpor-expected-v1"
    assert evaluation.decision_type == CostDecisionType.COST_CPOR_ANOMALY


def test_it_is_the_only_decision_type_and_the_statuses_are_the_revenue_ones() -> None:
    assert [t.value for t in CostDecisionType] == ["COST_CPOR_ANOMALY"]
    assert EvaluationStatus is RevenueStatus
    assert [s.value for s in EvaluationStatus] == [
        "TRIGGERED",
        "CLEAR",
        "INSUFFICIENT_DATA",
        "NOT_APPLICABLE",
        "SUPPRESSED_LOW_CONFIDENCE",
    ]


# --- L. confidence --------------------------------------------------------------------------------


def test_the_baseline_confidence_of_a_clean_history_is_96() -> None:
    evaluation = run(world(FLAT, net="4000"))

    assert evaluation.baseline_confidence == D("96.00")  # 35 + 25 + 0.2 * 80 + 20
    assert evaluation.sample_score_exact == D(100)
    assert evaluation.provenance_score_exact == D(100)
    assert evaluation.classification_score_exact == D(80)
    assert evaluation.stability_score_exact == D(100)
    assert evaluation.confidence_cap is None


def test_a_small_sample_lowers_the_sample_score() -> None:
    evaluation = run(world(["10"] * 5, net="4000"))
    assert evaluation.sample_score_exact == D("62.5")
    assert evaluation.baseline_confidence == D("82.88")  # 21.875 + 25 + 16 + 20 = 82.875, half up


def test_a_volatile_history_lowers_the_stability_score() -> None:
    evaluation = run(world(["1", "1", "10", "20", "30"], net="30000"))

    assert evaluation.expected_cpor_exact == D(10) and evaluation.iqr_exact == D(19)
    assert evaluation.stability_score_exact == D(5)  # 100 - 50 * 19 / 10


def test_the_stability_score_is_floored_at_zero() -> None:
    evaluation = run(world(["1", "1", "10", "30", "40"], net="30000"))

    assert evaluation.iqr_exact == D(29)  # 30 - 1
    assert evaluation.stability_score_exact == D(0)  # 100 - 50 * 29 / 10 < 0


def test_a_history_with_no_fully_observed_month_is_capped_at_65_even_if_mostly_observed() -> None:
    evaluation = run(world(FLAT[:8], net="4000", reconstructed_days=5))

    # eight months, each with 5 of 31 days reconstructed: fewer than five FULLY observed exist
    assert evaluation.observed_period_count == 0 and evaluation.approximate_period_count == 8
    assert evaluation.confidence_cap == D(65)  # no fully observed month at all


def test_a_mixed_history_with_a_reconstructed_month_is_capped_at_85() -> None:
    ledger = world(["10"] * 4, net="4000")
    part = cpor_history(
        dict(zip(COMPARABLE_MONTHS[4:8], ["10"] * 4, strict=True)), reconstructed_days=5
    )
    ledger.costs.extend(part.costs)
    ledger.occupancy.update(part.occupancy)

    evaluation = run(ledger)

    assert (evaluation.observed_period_count, evaluation.approximate_period_count) == (4, 4)
    assert evaluation.confidence_cap == D(85) and evaluation.baseline_confidence == D("85.00")
    assert evaluation.confidence_score == D("85.00")  # min(85, target quality 90)


def test_an_all_reconstructed_history_is_capped_at_65() -> None:
    evaluation = run(world(FLAT, net="4000", reconstructed_days=31))

    assert evaluation.observed_period_count == 0 and evaluation.confidence_cap == D(65)
    assert evaluation.baseline_confidence == D("65.00")  # the formula alone gives 86.00
    assert evaluation.provenance_score_exact == D(60)
    assert evaluation.status == TRIGGERED  # 65 >= 55: capped, not silenced


def test_the_target_quality_is_half_provenance_and_half_classification() -> None:
    observed = run(world(FLAT, net="4000"))
    reconstructed = run(world(FLAT, net="4000", target_reconstructed=True))

    assert observed.target_quality == D("90.00")  # 0.5 * 100 + 0.5 * 80
    assert reconstructed.target_quality == D("70.00")  # 0.5 * 60 + 0.5 * 80


def test_the_final_confidence_is_the_minimum_of_baseline_and_target_quality() -> None:
    weak_target = run(world(FLAT, net="4000", target_reconstructed=True))
    weak_history = run(world(FLAT, net="4000", reconstructed_days=31))

    assert weak_target.baseline_confidence == D("96.00") and weak_target.target_quality == D(
        "70.00"
    )
    assert weak_target.confidence_score == D("70.00")  # the target is the weakest input
    assert weak_history.confidence_score == D("65.00")  # the history is


def test_a_confidence_of_54_99_with_a_numeric_trigger_is_suppressed() -> None:
    evaluation = run(world(FLAT, net="4000", target_confidence="9.98"))

    assert evaluation.target_quality == D("54.99") and evaluation.confidence_score == D("54.99")
    assert evaluation.status == SUPPRESSED
    assert evaluation.reason_codes == (ReasonCode.LOW_CONFIDENCE,)
    assert evaluation.cost_gap_proxy_exact == D(900)  # the anomaly is kept for the audit


def test_a_confidence_of_exactly_55_with_a_numeric_trigger_is_triggered() -> None:
    evaluation = run(world(FLAT, net="4000", target_confidence="10"))

    assert evaluation.target_quality == D("55.00") and evaluation.status == TRIGGERED


def test_low_confidence_without_a_numeric_trigger_is_clear_not_suppressed() -> None:
    evaluation = run(world(FLAT, net="3100", target_confidence="9.98"))

    assert evaluation.confidence_score == D("54.99")
    assert evaluation.status == CLEAR and evaluation.reason_codes == (
        ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,
    )


# --- M. status and reasons ------------------------------------------------------------------------


def test_an_incomplete_target_occupancy_is_insufficient_data() -> None:
    ledger = world(FLAT, net="4000")
    ledger.rooms(AUG, 10, missing=[12])

    evaluation = run(ledger)

    assert evaluation.status == INSUFFICIENT
    assert evaluation.reason_codes == (ReasonCode.OCCUPANCY_PERIOD_INCOMPLETE,)
    assert evaluation.target_metric.missing_day_count == 1


def test_an_uncertain_target_snapshot_is_insufficient_data() -> None:
    ledger = world(FLAT, net="4000")
    ledger.rooms(AUG, 10, uncertain=[3])

    evaluation = run(ledger)

    assert evaluation.status == INSUFFICIENT
    assert evaluation.reason_codes == (ReasonCode.OCCUPANCY_PERIOD_INCOMPLETE,)


def test_low_classification_coverage_is_insufficient_data() -> None:
    ledger = world(FLAT, net="4000")
    ledger.cost(AUG, OTHER, "2000")  # 4000 classified against 2000 OTHER: 66.7 %

    evaluation = run(ledger)

    assert evaluation.status == INSUFFICIENT
    assert evaluation.reason_codes == (ReasonCode.COST_CLASSIFICATION_COVERAGE_LOW,)


def test_a_small_comparable_sample_is_insufficient_data() -> None:
    evaluation = run(world(["10"] * 4, net="4000"))

    assert evaluation.status == INSUFFICIENT
    assert evaluation.reason_codes == (ReasonCode.COMPARABLE_SAMPLE_INSUFFICIENT,)
    assert evaluation.sample_count == 4 and evaluation.expected_cpor_exact is None


def test_a_month_with_no_occupied_room_night_is_not_applicable() -> None:
    evaluation = run(world(FLAT, net="4000", rooms=0))

    assert evaluation.status == NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.ZERO_OCCUPIED_ROOM_NIGHTS,)


def test_the_other_category_is_not_applicable_even_when_it_has_data() -> None:
    ledger = world(FLAT, net="4000")
    ledger.cost(AUG, OTHER, "50")

    evaluation = run(ledger, category=OTHER)

    assert evaluation.status == NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.COST_CATEGORY_OTHER_NOT_ACTIONABLE,)


def test_the_other_category_is_refused_before_anything_else_is_looked_at() -> None:
    ledger = Ledger()  # no cost, no occupancy: the OTHER answer does not need them
    target = ledger.metric(AUG, OTHER)

    evaluation = evaluate_cpor_anomaly(target, never)

    assert evaluation.reason_codes == (ReasonCode.COST_CATEGORY_OTHER_NOT_ACTIONABLE,)


def test_no_cost_line_of_the_currency_is_not_applicable_not_a_zero_cost() -> None:
    ledger = Ledger()
    ledger.rooms(AUG, 10)

    evaluation = evaluate_cpor_anomaly(ledger.metric(AUG), never)

    assert evaluation.status == NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.COST_CURRENCY_NOT_PRESENT,)
    assert evaluation.target_metric.net_cost is None


def test_no_cost_line_of_the_category_is_not_applicable() -> None:
    ledger = Ledger()
    ledger.cost(AUG, UTILITIES, "300")
    ledger.rooms(AUG, 10)

    evaluation = evaluate_cpor_anomaly(ledger.metric(AUG, LAUNDRY), never)

    assert evaluation.status == NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.COST_CATEGORY_NOT_PRESENT,)


def test_an_unusable_target_never_pays_for_a_baseline() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300")
    ledger.rooms(AUG, 10, missing=[1])
    evaluate_cpor_anomaly(ledger.metric(AUG), never)  # would raise if it selected


def test_a_normal_period_is_clear() -> None:
    evaluation = run(world(FLAT, net="3100"))
    assert evaluation.status == CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)


def test_an_anomaly_with_low_confidence_is_suppressed_and_with_enough_confidence_triggered() -> (
    None
):
    assert run(world(FLAT, net="4000", target_confidence="9.98")).status == SUPPRESSED
    assert run(world(FLAT, net="4000")).status == TRIGGERED


def test_a_target_with_a_negative_net_cost_is_clear_not_not_applicable() -> None:
    evaluation = run(world(FLAT, net="-620"))

    assert evaluation.target_metric.cpor_exact == D(-2)
    assert evaluation.status == CLEAR  # credit notes make a month cheaper, never an anomaly
    assert evaluation.cost_gap_proxy_exact == D(0)


def test_a_target_with_a_zero_net_cost_is_clear() -> None:
    ledger = world(FLAT, net="0")
    ledger.cost(AUG, LAUNDRY, "0", absolute="400")  # +400 invoice and -400 credit note

    evaluation = run(ledger)

    assert evaluation.target_metric.cpor_exact == D(0) and evaluation.status == CLEAR


def test_the_target_currency_only_uses_history_of_the_same_currency() -> None:
    ledger = world(FLAT, net="4000")  # EUR history and EUR target
    ledger.cost(AUG, LAUNDRY, "9000", currency=USD)

    eur, usd = run(ledger, currency=EUR), run(ledger, currency=USD)

    assert eur.status == TRIGGERED and eur.target_metric.net_cost == D(4000)
    assert usd.status == INSUFFICIENT and usd.sample_count == 0  # no USD history: nothing converted


def test_a_currency_never_borrows_the_history_of_another_one() -> None:
    ledger = world(FLAT, net="4000", currency=USD)  # USD history
    ledger.cost(AUG, LAUNDRY, "4000", currency=EUR)  # EUR target, no EUR history

    assert run(ledger, currency=EUR).status == INSUFFICIENT
    assert run(ledger, currency=EUR).sample_count == 0


# --- explainability -------------------------------------------------------------------------------


def test_a_triggered_evaluation_carries_every_fact_needed_to_explain_it() -> None:
    ledger = world(FLAT, net="4000")
    ledger.cost(AUG, LAUNDRY, "4000", invoices=4, lines=9, credit_lines=2, credit_cost="-300")

    evaluation = run(ledger)
    facts = evaluation.payload()
    metric = facts["target_metric"]

    assert evaluation.status == TRIGGERED
    assert (facts["cost_category"], facts["currency"]) == ("LAUNDRY", "EUR")
    assert (facts["target_period_start"], facts["target_period_end"]) == (
        "2026-08-01",
        "2026-08-31",
    )
    assert (metric["invoice_count"], metric["line_count"]) == (4, 9)
    assert metric["net_cost"] == "4000.00" and metric["credit_note_cost"] == "-300.00"
    assert metric["occupied_room_nights"] == 310
    assert (metric["observed_day_count"], metric["reconstructed_day_count"]) == (31, 0)
    assert metric["classification_coverage_pct"] == "100.00" and metric["cpor"] == "12.90"
    assert facts["expected_cpor"] == "10.00" and (facts["p25"], facts["p75"]) == ("10.00", "10.00")
    assert (facts["iqr"], facts["upper_fence"]) == ("0.00", "10.00")
    assert facts["delta_cpor"] == "2.90" and facts["delta_percent"] == "29.03"
    assert facts["expected_cost_for_target_volume"] == "3100.00"
    assert facts["cost_gap_proxy"] == "900.00"
    assert (facts["baseline_confidence"], facts["target_quality"]) == ("96.00", "90.00")
    assert facts["confidence_score"] == "90.00"
    assert {"sample_score", "provenance_score", "classification_score", "stability_score"} <= set(
        facts
    )
    assert facts["thresholds"]["relative_percent"] == "20.00"
    assert facts["reason_codes"] == ["TRIGGER_CPOR_ANOMALY"]
    assert len(facts["comparable_periods"]) == 8
    first = facts["comparable_periods"][0]
    assert first["period_start"] == "2026-07-01" and first["cpor"] == "10.00"
    assert facts["calculation_fingerprint"] == evaluation.calculation_fingerprint


# --- Q. determinism and the fingerprint -----------------------------------------------------------


def test_the_same_input_gives_the_same_evaluation_and_the_same_fingerprint() -> None:
    first, second = run(world(FLAT, net="4000")), run(world(FLAT, net="4000"))

    assert first == second
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert len(first.calculation_fingerprint) == 64


def test_a_changed_input_changes_the_fingerprint() -> None:
    base = run(world(FLAT, net="4000")).calculation_fingerprint
    assert run(world(FLAT, net="4001")).calculation_fingerprint != base
    assert run(world(["10"] * 7 + ["11"], net="4000")).calculation_fingerprint != base
    assert run(world(FLAT, net="4000", target_confidence="79")).calculation_fingerprint != base


def test_the_order_in_which_the_rows_arrive_does_not_change_the_result() -> None:
    forward = world(FLAT, net="4000")
    backward = world(FLAT, net="4000")
    backward.costs.reverse()

    assert run(forward).calculation_fingerprint == run(backward).calculation_fingerprint
    assert run(forward) == run(backward)


def test_equal_decimals_written_differently_share_a_fingerprint() -> None:
    assert (
        run(world(FLAT, net="4000")).calculation_fingerprint
        == run(world(FLAT, net="4000.00")).calculation_fingerprint
        == run(world(FLAT, net="4E+3")).calculation_fingerprint
    )


def test_two_values_on_opposite_sides_of_a_threshold_never_share_a_fingerprint() -> None:
    below = run(world(FLAT, net="3719.99")).calculation_fingerprint
    exact = run(world(FLAT, net="3720")).calculation_fingerprint
    assert below != exact  # both display 20.00, only one reaches it


def test_the_fingerprint_hashes_the_canonical_payload_and_nothing_displayed() -> None:
    evaluation = run(world(FLAT, net="3719.99"))
    canonical = evaluation.canonical_payload()

    assert canonical["delta_percent"] == canonical_text(evaluation.delta_percent_exact)
    assert canonical["delta_percent"] != "20"  # the exact 19.9996..., never the displayed 20.00
    assert evaluation.payload()["delta_percent"] == "20.00"
    encoded = json.dumps(
        {"v": 1, "kind": "cost-cpor-anomaly", **canonical},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert hashlib.sha256(encoded.encode("ascii")).hexdigest() == evaluation.calculation_fingerprint
    assert evaluation_fingerprint(evaluation) == evaluation.calculation_fingerprint


def test_the_fingerprint_does_not_include_itself_or_a_timestamp() -> None:
    evaluation = run(world(FLAT, net="4000"))
    payload = evaluation.canonical_payload()
    assert "calculation_fingerprint" not in payload
    blob = json.dumps(payload)
    assert "created_at" not in blob and "timestamp" not in blob and "T00:00" not in blob
    assert evaluation_fingerprint(dataclasses.replace(evaluation, calculation_fingerprint="x")) == (
        evaluation.calculation_fingerprint
    )


def test_every_status_has_a_distinct_stable_name() -> None:
    assert len({s.value for s in EvaluationStatus}) == 5
    codes = [c.value for c in ReasonCode]
    assert len(codes) == len(set(codes))
    for required in (
        "TRIGGER_CPOR_ANOMALY",
        "CLEAR_WITHIN_EXPECTED_RANGE",
        "COST_CATEGORY_OTHER_NOT_ACTIONABLE",
        "COST_CLASSIFICATION_COVERAGE_LOW",
        "OCCUPANCY_PERIOD_INCOMPLETE",
        "ZERO_OCCUPIED_ROOM_NIGHTS",
        "EXPECTED_CPOR_NON_POSITIVE",
        "COMPARABLE_SAMPLE_INSUFFICIENT",
        "LOW_CONFIDENCE",
        "BOOKING_DATA_SOURCE_INVALID",
        "COST_CURRENCY_NOT_PRESENT",
    ):
        assert required in codes
