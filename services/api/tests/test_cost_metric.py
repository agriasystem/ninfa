"""The cost period metric: aggregation, classification quality, the lead-time-0 denominator and the
CPOR itself (Gate 7 groups B, C, D and E, pure: real builders, no database).
"""

from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext
from fractions import Fraction

import pytest

from app.modules.intelligence.costs.occupancy import (
    build_denominator,
    index_lead_zero,
    lead_zero_keys,
)
from app.modules.intelligence.costs.types import (
    CostPeriodMetric,
    MetricStatus,
    ReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory
from app.modules.snapshots.repository import SnapshotHistoryRow
from tests.cost_support import (
    EUR,
    LAUNDRY,
    OBSERVED,
    OTHER,
    RECONSTRUCTED,
    USD,
    UTILITIES,
    Ledger,
    day_rows,
    denominator,
    month,
)

D = Decimal
AUG = month(2026, 8)


def ready_ledger(net: str = "3100", rooms: int = 10, **options: object) -> Ledger:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, net)
    ledger.rooms(AUG, rooms, **options)
    return ledger


# --- B. the cost side -----------------------------------------------------------------------------


def test_the_net_cost_of_the_category_is_the_signed_sum_of_its_lines() -> None:
    ledger = ready_ledger("1234.56")
    metric = ledger.metric(AUG)
    assert metric.net_cost == D("1234.56") and metric.absolute_category_cost == D("1234.56")


def test_a_credit_note_makes_the_net_smaller_but_not_the_absolute_exposure() -> None:
    ledger = Ledger()
    # +1000 invoice and -400 credit note: net 600, absolute 1400
    ledger.cost(AUG, LAUNDRY, "600", absolute="1400", credit_lines=1, credit_cost="-400")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert (metric.net_cost, metric.absolute_category_cost) == (D(600), D(1400))
    assert (metric.credit_note_line_count, metric.credit_note_cost) == (1, D(-400))


def test_only_the_asked_category_enters_the_category_cost() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300")
    ledger.cost(AUG, UTILITIES, "500")
    ledger.cost(AUG, OTHER, "50")
    ledger.rooms(AUG)

    assert ledger.metric(AUG, LAUNDRY).net_cost == D(300)
    assert ledger.metric(AUG, UTILITIES).net_cost == D(500)
    assert ledger.metric(AUG, LAUNDRY).total_absolute_cost == D(850)  # every category, one currency


def test_other_never_enters_the_cost_of_an_operating_category() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "700")
    ledger.cost(AUG, OTHER, "300")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG, LAUNDRY)

    assert metric.net_cost == D(700)  # not 1000
    assert metric.classified_absolute_cost == D(700) and metric.total_absolute_cost == D(1000)


def test_the_currency_is_exact_and_currencies_are_never_added() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300", currency=EUR)
    ledger.cost(AUG, LAUNDRY, "999", currency=USD)
    ledger.rooms(AUG)

    assert ledger.metric(AUG, LAUNDRY, EUR).net_cost == D(300)
    assert ledger.metric(AUG, LAUNDRY, USD).net_cost == D(999)
    assert ledger.metric(AUG, LAUNDRY, EUR).total_absolute_cost == D(300)  # USD is another world


def test_the_month_is_the_month_of_the_invoice_date_only() -> None:
    ledger = Ledger()
    ledger.cost(month(2026, 7), LAUNDRY, "100")
    ledger.cost(AUG, LAUNDRY, "200")
    ledger.cost(month(2026, 9), LAUNDRY, "400")
    for period in (month(2026, 7), AUG, month(2026, 9)):
        ledger.rooms(period)

    assert [ledger.metric(m).net_cost for m in (month(2026, 7), AUG, month(2026, 9))] == [
        D(100),
        D(200),
        D(400),
    ]


def test_no_line_at_all_is_not_a_zero_cost() -> None:
    ledger = Ledger()
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.NO_COST_DATA
    assert metric.net_cost is None and metric.cpor_exact is None  # not 0
    assert metric.reason_codes == (ReasonCode.COST_CURRENCY_NOT_PRESENT,)


def test_a_currency_with_lines_but_no_line_of_the_category_says_so() -> None:
    ledger = Ledger()
    ledger.cost(AUG, UTILITIES, "500")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG, LAUNDRY)

    assert metric.status == MetricStatus.NO_COST_DATA
    assert metric.reason_codes == (ReasonCode.COST_CATEGORY_NOT_PRESENT,)
    assert metric.total_absolute_cost == D(500) and metric.net_cost is None


def test_a_net_zero_month_is_not_the_absence_of_cost() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "0", absolute="2000", credit_lines=1, credit_cost="-1000", lines=2)
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.READY
    assert metric.net_cost == D(0) and metric.cpor_exact == D(0)  # a valid zero
    assert metric.absolute_category_cost == D(2000)  # there WAS economic activity


def test_every_amount_of_a_metric_is_a_decimal_never_a_float() -> None:
    metric = ready_ledger().metric(AUG)
    for name in (
        "net_cost",
        "absolute_category_cost",
        "total_absolute_cost",
        "classified_absolute_cost",
        "classification_coverage_pct_exact",
        "weighted_classification_confidence_exact",
        "occupancy_provenance_score_exact",
        "cpor_exact",
        "credit_note_cost",
    ):
        value = getattr(metric, name)
        assert isinstance(value, Decimal), name
    assert not any(isinstance(v, float) for v in vars_of(metric).values())


def close(value: Decimal | None, exact: Fraction) -> bool:
    """A 50-digit quotient against the exact fraction, to better than 1e-40."""
    return value is not None and abs(Fraction(value) - exact) < Fraction(1, 10**40)


def vars_of(metric: CostPeriodMetric) -> dict[str, object]:
    return {name: getattr(metric, name) for name in CostPeriodMetric.__dataclass_fields__}


# --- C. classification quality --------------------------------------------------------------------


def test_a_fully_classified_month_has_a_coverage_of_100() -> None:
    metric = ready_ledger().metric(AUG)
    assert metric.classification_coverage_pct_exact == D(100)


def test_other_lowers_the_coverage() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "800")
    ledger.cost(AUG, OTHER, "200")
    ledger.rooms(AUG)

    assert ledger.metric(AUG).classification_coverage_pct_exact == D(80)


def test_the_coverage_uses_absolute_amounts_so_credit_notes_do_not_hide_activity() -> None:
    ledger = Ledger()
    # net 0, but 2000 of absolute exposure classified against 500 of OTHER: 80 %, not 0 / 500
    ledger.cost(AUG, LAUNDRY, "0", absolute="2000")
    ledger.cost(AUG, OTHER, "500")
    ledger.rooms(AUG)

    assert ledger.metric(AUG).classification_coverage_pct_exact == D(80)


def test_a_coverage_just_below_70_makes_the_month_insufficient() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "699.99")
    ledger.cost(AUG, OTHER, "300.01")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert metric.classification_coverage_pct_exact == D("69.999")
    assert metric.status == MetricStatus.LOW_CLASSIFICATION_COVERAGE
    assert metric.reason_codes == (ReasonCode.COST_CLASSIFICATION_COVERAGE_LOW,)
    assert metric.cpor_exact is None


def test_a_coverage_of_exactly_70_is_valid() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "700.00")
    ledger.cost(AUG, OTHER, "300.00")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert metric.classification_coverage_pct_exact == D(70)
    assert metric.status == MetricStatus.READY


def test_a_month_whose_lines_are_all_zero_has_an_undefined_coverage() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "0")  # a line of zero: no absolute exposure at all
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert metric.total_absolute_cost == D(0) and metric.classification_coverage_pct_exact is None
    assert metric.status == MetricStatus.LOW_CLASSIFICATION_COVERAGE
    assert metric.reason_codes == (ReasonCode.COST_CLASSIFICATION_COVERAGE_UNDEFINED,)


def test_the_weighted_classification_confidence_weights_by_absolute_cost() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "100", confidence="80")
    ledger.cost(AUG, UTILITIES, "300", confidence="100")
    ledger.cost(AUG, OTHER, "50")  # UNCLASSIFIED: not part of the confidence
    ledger.rooms(AUG)

    metric = ledger.metric(AUG, LAUNDRY)

    # (100 * 80 + 300 * 100) / (100 + 300): over the classified lines of the currency (all
    # categories)
    assert metric.weighted_classification_confidence_exact == D(95)


def test_the_confidence_is_undefined_when_nothing_is_classified() -> None:
    ledger = Ledger()
    ledger.cost(AUG, OTHER, "100")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG, OTHER)

    assert metric.weighted_classification_confidence_exact is None
    assert metric.classification_coverage_pct_exact == D(0)


def test_the_quality_of_a_currency_ignores_the_other_currency() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "800", currency=EUR)
    ledger.cost(AUG, OTHER, "200", currency=EUR)
    ledger.cost(AUG, OTHER, "9999", currency=USD)
    ledger.rooms(AUG)

    assert ledger.metric(AUG, LAUNDRY, EUR).classification_coverage_pct_exact == D(80)


# --- D. the occupancy denominator ----------------------------------------------------------------


def test_the_denominator_is_the_sum_of_the_lead_time_zero_rooms_of_every_day() -> None:
    result = denominator(AUG, 10)
    assert result.occupied_room_nights == 310 and result.total_days == 31
    assert result.complete and result.observed_day_count == 31


def test_only_snapshots_of_lead_time_zero_are_used() -> None:
    rows = list(day_rows(AUG, 10).values())
    # a snapshot taken a week before the stay night: never used, whatever it says
    rows.append(
        SnapshotHistoryRow(
            snapshot_id=rows[0].snapshot_id,
            snapshot_local_date=date(2026, 7, 29),
            stay_date=date(2026, 8, 5),
            origin=OBSERVED,
            rooms_on_books=99,
            uncertain_rooms=0,
            adr_on_books=None,
        )
    )
    indexed = index_lead_zero(rows)

    assert indexed[date(2026, 8, 5)].rooms_on_books == 10  # the lead-time-0 row, not the 99
    assert build_denominator(AUG, indexed).occupied_room_nights == 310


def test_the_keys_asked_for_are_exactly_lead_time_zero() -> None:
    keys = lead_zero_keys(AUG)
    assert len(keys) == 31 and all(snapshot == stay for snapshot, stay in keys)
    assert keys[0] == (date(2026, 8, 1), date(2026, 8, 1))


def test_a_reconstructed_clean_day_is_admitted() -> None:
    result = denominator(AUG, 10, reconstructed=[1, 2, 3])
    assert result.complete and result.reconstructed_day_count == 3
    assert result.occupied_room_nights == 310


def test_an_uncertain_snapshot_invalidates_the_month() -> None:
    result = denominator(AUG, 10, uncertain=[15])

    assert not result.complete and result.uncertain_day_count == 1
    assert result.occupied_room_nights is None  # uncertain rooms are not subtracted, not estimated
    assert result.occupancy_provenance_score_exact is None


def test_a_missing_day_invalidates_the_month_and_is_not_a_zero() -> None:
    result = denominator(AUG, 10, missing=[31])

    assert not result.complete and result.missing_day_count == 1
    assert result.occupied_room_nights is None  # not 300


def test_a_day_with_zero_rooms_is_valid_when_its_snapshot_exists() -> None:
    result = denominator(AUG, [10] * 14 + [0] + [10] * 16)

    assert result.complete and result.occupied_room_nights == 300


def test_the_sum_of_the_month_is_correct_for_uneven_days() -> None:
    result = denominator(AUG, list(range(1, 32)))  # 1 + 2 + ... + 31
    assert result.occupied_room_nights == 496


def test_observed_and_reconstructed_days_are_counted() -> None:
    result = denominator(AUG, 10, reconstructed=range(1, 11))
    assert (result.observed_day_count, result.reconstructed_day_count) == (21, 10)


def test_provenance_is_100_for_a_fully_observed_month() -> None:
    assert denominator(AUG, 10).occupancy_provenance_score_exact == D(100)


def test_provenance_is_60_for_a_fully_reconstructed_month() -> None:
    assert denominator(AUG, 10, reconstructed=range(1, 32)).occupancy_provenance_score_exact == D(
        60
    )


def test_provenance_of_a_mixed_month_is_the_day_weighted_mean() -> None:
    # 21 observed days * 100 + 10 reconstructed days * 60 = 2700 / 31
    result = denominator(AUG, 10, reconstructed=range(1, 11))
    assert close(result.occupancy_provenance_score_exact, Fraction(2700, 31))
    half = denominator(month(2026, 4), 10, reconstructed=range(1, 16))  # 15 + 15 of 30
    assert half.occupancy_provenance_score_exact == D(80)


def test_a_complete_month_without_a_single_occupied_room_has_no_cpor() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300")
    ledger.rooms(AUG, 0)

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.ZERO_OCCUPANCY and metric.occupied_room_nights == 0
    assert metric.reason_codes == (ReasonCode.ZERO_OCCUPIED_ROOM_NIGHTS,)
    assert metric.cpor_exact is None  # never divided by zero


def test_an_incomplete_month_is_incomplete_whatever_its_cost() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300")
    ledger.rooms(AUG, 10, missing=[3])

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.INCOMPLETE
    assert metric.reason_codes == (ReasonCode.OCCUPANCY_PERIOD_INCOMPLETE,)
    assert (metric.missing_day_count, metric.occupied_room_nights) == (1, None)


def test_a_month_with_no_snapshot_at_all_is_incomplete_not_empty() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "300")  # no occupancy stored

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.INCOMPLETE and metric.missing_day_count == 31


# --- E. the period metric ------------------------------------------------------------------------


def test_the_cpor_is_the_net_cost_over_the_occupied_room_nights() -> None:
    metric = ready_ledger("3100", 10).metric(AUG)
    assert metric.cpor_exact == D(10) and metric.occupied_room_nights == 310


def test_a_non_terminating_cpor_keeps_fifty_digits_and_displays_two_decimals() -> None:
    metric = ready_ledger("100", 10).metric(AUG)  # 100 / 310 = 0.3225806451612903...
    assert close(metric.cpor_exact, Fraction(100, 310))
    assert len(str(metric.cpor_exact)) > 40
    assert metric.cpor_display == D("0.32")


def test_the_display_of_the_cpor_is_half_up() -> None:
    assert ready_ledger("3110.155", 10).metric(AUG).cpor_display == D("10.03")  # 10.0327...
    assert ready_ledger("3105", 10).metric(AUG).cpor_display == D("10.02")  # 10.016129...


def test_the_display_value_never_decides_anything() -> None:
    metric = ready_ledger("3100.0001", 10).metric(AUG)  # 10.000000322...
    assert metric.cpor_display == D("10.00")  # displayed as 10 ...
    assert metric.cpor_exact is not None and metric.cpor_exact > D(10)  # ... and it is above it


def test_a_negative_net_cost_gives_a_valid_negative_cpor() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "-620", absolute="620", credit_lines=1, credit_cost="-620")
    ledger.rooms(AUG, 10)

    metric = ledger.metric(AUG)

    assert metric.status == MetricStatus.READY and metric.cpor_exact == D(-2)


def test_a_zero_net_cost_gives_a_valid_zero_cpor() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "0", absolute="100")
    ledger.rooms(AUG, 10)
    assert ledger.metric(AUG).cpor_exact == D(0)


def test_the_metric_reports_its_counts() -> None:
    ledger = Ledger()
    ledger.cost(AUG, LAUNDRY, "500", invoices=3, lines=7, credit_lines=2, credit_cost="-150")
    ledger.rooms(AUG)

    metric = ledger.metric(AUG)

    assert (metric.invoice_count, metric.line_count, metric.credit_note_line_count) == (3, 7, 2)


def test_the_metric_carries_its_dimensions_versions_and_policies() -> None:
    metric = ready_ledger().metric(AUG)
    assert (metric.period_start, metric.period_end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert (metric.cost_category, metric.currency) == (LAUNDRY, EUR)
    assert metric.calculation_version == "cost-period-metric-v1"
    payload = metric.payload()
    assert payload["cost_attribution"] == "INVOICE_DATE_ATTRIBUTION"
    assert payload["occupancy_proxy"] == "LEAD_TIME_0_ROOMS_ON_BOOKS_PROXY"


def test_the_metric_fingerprint_is_deterministic() -> None:
    first, second = ready_ledger().metric(AUG), ready_ledger().metric(AUG)
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert len(first.calculation_fingerprint) == 64
    assert ready_ledger("3101").metric(AUG).calculation_fingerprint != first.calculation_fingerprint


def test_the_fingerprint_does_not_depend_on_the_order_the_costs_arrive() -> None:
    forward, backward = Ledger(), Ledger()
    for ledger, order in (
        (forward, (LAUNDRY, UTILITIES, OTHER)),
        (backward, (OTHER, UTILITIES, LAUNDRY)),
    ):
        for category in order:
            ledger.cost(AUG, category, "100")
        ledger.rooms(AUG)
    assert (
        forward.metric(AUG).calculation_fingerprint == backward.metric(AUG).calculation_fingerprint
    )


def test_a_global_decimal_context_does_not_change_a_metric() -> None:
    ledger = ready_ledger("1234.56", 7)
    reference = ledger.metric(AUG)
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        changed = ledger.metric(AUG)
    assert changed == reference
    assert changed.calculation_fingerprint == reference.calculation_fingerprint


@pytest.mark.parametrize("category", [c for c in CostCategory if c != OTHER])
def test_every_operating_category_can_be_measured(category: CostCategory) -> None:
    ledger = Ledger()
    ledger.cost(AUG, category, "620")
    ledger.rooms(AUG, 10)
    assert ledger.metric(AUG, category).cpor_exact == D(2)


def test_reconstructed_days_of_the_denominator_are_reported_on_the_metric() -> None:
    metric = ready_ledger(reconstructed=range(1, 6)).metric(AUG)
    assert (metric.observed_day_count, metric.reconstructed_day_count) == (26, 5)
    assert not metric.is_fully_observed
    assert close(metric.occupancy_provenance_score_exact, Fraction(26 * 100 + 5 * 60, 31))
    assert RECONSTRUCTED.value == "RECONSTRUCTED_APPROXIMATE"
