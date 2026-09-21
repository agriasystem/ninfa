"""Reference ADR and revenue gap proxy (Gate 5, groups M and N). Pure, no database."""

import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest

from app.modules.intelligence.revenue.impact import (
    ReferenceAdr,
    median_decimal,
    reference_adr,
    revenue_gap_proxy,
)
from app.modules.intelligence.revenue.occupancy import evaluate_occupancy
from app.modules.intelligence.revenue.pickup import evaluate_pickup
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
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
SOURCE = ReferenceAdrSource

# --- M: the reference ADR --------------------------------------------------------------------


def test_the_current_adr_on_books_comes_first() -> None:
    adr = reference_adr(D("120.50"), [D("90.00"), D("95.00")])
    assert adr == ReferenceAdr(D("120.50"), SOURCE.CURRENT_ON_BOOKS_ADR)


def test_the_historical_comparable_median_is_the_fallback() -> None:
    adr = reference_adr(None, [D("100.00"), D("140.00"), D("110.00")])
    assert adr == ReferenceAdr(D("110.00"), SOURCE.HISTORICAL_COMPARABLE_MEDIAN_ADR)


def test_an_even_number_of_comparable_adrs_is_averaged_in_the_middle() -> None:
    adr = reference_adr(None, [D("100.00"), D("101.00"), D("140.00"), D("90.00")])
    assert adr.value == D("100.50")


def test_the_median_is_rounded_half_up_to_two_decimals() -> None:
    assert median_decimal([D("100.00"), D("100.01")]) == D("100.01")  # 100.005 -> 100.01
    assert median_decimal([D("1.00"), D("2.00"), D("10.00")]) == D("2.00")


def test_a_zero_target_adr_is_not_a_reference() -> None:
    adr = reference_adr(D("0.00"), [D("80.00")])
    assert adr == ReferenceAdr(D("80.00"), SOURCE.HISTORICAL_COMPARABLE_MEDIAN_ADR)


def test_null_and_zero_comparable_adrs_are_ignored() -> None:
    adr = reference_adr(None, [None, D("0.00"), D("90.00"), None, D("110.00")])
    assert adr.value == D("100.00")
    assert adr.source == SOURCE.HISTORICAL_COMPARABLE_MEDIAN_ADR


def test_without_any_usable_adr_the_source_is_unavailable_and_nothing_is_invented() -> None:
    for target, comparables in (
        (None, []),
        (None, [None, None]),
        (D("0.00"), [D("0.00")]),
        (None, [D("0.00"), None]),
    ):
        assert reference_adr(target, comparables) == ReferenceAdr(None, SOURCE.UNAVAILABLE)


def test_the_reference_adr_is_an_exact_decimal() -> None:
    adr = reference_adr(D("99.9"), [])
    assert isinstance(adr.value, Decimal)
    assert adr.value == D("99.90")


# --- N: the revenue gap proxy ----------------------------------------------------------------


def test_the_proxy_is_rooms_at_risk_times_the_adr() -> None:
    assert revenue_gap_proxy(D("2.00"), D("120.00")) == D("240.00")
    assert revenue_gap_proxy(D("0.00"), D("120.00")) == D("0.00")


def test_the_proxy_is_rounded_half_up_to_two_decimals() -> None:
    assert revenue_gap_proxy(D("2.50"), D("123.45")) == D("308.63")  # 308.625
    assert revenue_gap_proxy(D("0.25"), D("10.10")) == D("2.53")  # 2.525


def test_the_proxy_is_null_without_an_adr() -> None:
    assert revenue_gap_proxy(D("5.00"), None) is None


def _pickup(
    *, adr: ReferenceAdr, baseline_confidence: str = "90.00", rooms: int = 20, prior: int = 12
) -> RevenueDecisionEvaluation:
    return evaluate_pickup(
        target_context(rooms=rooms, baseline_confidence=D(baseline_confidence)),
        prior=point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, prior),
        selection=pickup_selection([10] * 12),
        reference=adr,
    )


def _occupancy(
    *, adr: ReferenceAdr, baseline_confidence: str = "90.00"
) -> RevenueDecisionEvaluation:
    return evaluate_occupancy(
        target_context(baseline_confidence=D(baseline_confidence)),
        selection=remaining_selection([4] * 12, [30] * 12),
        reference=adr,
    )


CURRENT = ReferenceAdr(D("123.45"), SOURCE.CURRENT_ON_BOOKS_ADR)
HISTORICAL = ReferenceAdr(D("88.00"), SOURCE.HISTORICAL_COMPARABLE_MEDIAN_ADR)
NONE = ReferenceAdr(None, SOURCE.UNAVAILABLE)


def test_the_pickup_proxy_prices_the_missing_rooms() -> None:
    evaluation = _pickup(adr=CURRENT)  # 2 missing rooms
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.revenue_gap_proxy == D("246.90")
    assert evaluation.reference_adr == D("123.45")
    assert evaluation.reference_adr_source == SOURCE.CURRENT_ON_BOOKS_ADR


def test_the_occupancy_proxy_prices_the_room_shortfall() -> None:
    evaluation = _occupancy(adr=HISTORICAL)  # 6 rooms short
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.revenue_gap_proxy == D("528.00")
    assert evaluation.reference_adr_source == SOURCE.HISTORICAL_COMPARABLE_MEDIAN_ADR


def test_without_an_adr_the_decision_still_triggers_but_has_no_proxy() -> None:
    for evaluation in (_pickup(adr=NONE), _occupancy(adr=NONE)):
        assert evaluation.status == EvaluationStatus.TRIGGERED
        assert evaluation.revenue_gap_proxy is None
        assert evaluation.reference_adr is None
        assert evaluation.reference_adr_source == SOURCE.UNAVAILABLE


def test_the_proxy_exists_only_when_the_numeric_condition_holds() -> None:
    clear = _pickup(adr=CURRENT, rooms=25)  # ahead of the expected pickup
    assert clear.status == EvaluationStatus.CLEAR
    assert clear.revenue_gap_proxy is None
    assert clear.reference_adr == D("123.45")  # the ADR is context, the proxy is a conclusion


def test_a_suppressed_evaluation_keeps_the_proxy_for_the_audit_and_the_same_value() -> None:
    triggered = _pickup(adr=CURRENT, baseline_confidence="90.00")
    suppressed = _pickup(adr=CURRENT, baseline_confidence="49.99")
    assert suppressed.status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE
    assert suppressed.revenue_gap_proxy == triggered.revenue_gap_proxy


def test_the_proxy_is_never_named_after_a_loss() -> None:
    names = {field.name for field in dataclasses.fields(RevenueDecisionEvaluation)}
    assert "revenue_gap_proxy" in names
    for forbidden in ("economic_impact", "revenue_loss", "lost_revenue", "loss_probability"):
        assert forbidden not in names


@pytest.mark.parametrize(
    "status", [EvaluationStatus.NOT_APPLICABLE, EvaluationStatus.INSUFFICIENT_DATA]
)
def test_no_proxy_when_the_rule_cannot_decide(status: EvaluationStatus) -> None:
    if status == EvaluationStatus.NOT_APPLICABLE:
        evaluation = evaluate_pickup(
            target_context(rooms=39, available=40),  # one room left
            prior=point(TARGET_SNAPSHOT_DAY - timedelta(days=7), TARGET_STAY, 12),
            selection=pickup_selection([10] * 12),
            reference=CURRENT,
        )
    else:
        evaluation = evaluate_pickup(
            target_context(),
            prior=None,
            selection=pickup_selection([10] * 12),
            reference=CURRENT,
        )
    assert evaluation.status == status
    assert evaluation.revenue_gap_proxy is None
