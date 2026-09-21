"""Historical comparable months of Cost CPOR V1 (Gate 7 groups F and G, pure).

Which months may be compared with a target, and which of them are used: 36 months back, a
seasonal window of +-2 months on the 12-month circle, the same category and currency, only READY
months (complete occupancy, occupied nights > 0, coverage >= 70 %), at least 5 and at most 12,
observed-first.
"""

from collections.abc import Iterable
from decimal import Decimal

import pytest

from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.selection import (
    ComparableSelection,
    candidate_months,
    select_comparables,
)
from app.modules.intelligence.costs.types import MetricStatus
from app.modules.invoices.cost_categories import CostCategory
from tests.cost_support import (
    AUGUST,
    EUR,
    LAUNDRY,
    OTHER,
    USD,
    UTILITIES,
    Ledger,
    cpor_history,
    month,
)

D = Decimal
AUG = AUGUST


def ledger_of(
    observed: Iterable[CalendarMonth] = (),
    reconstructed: Iterable[CalendarMonth] = (),
    *,
    value: str = "10",
    category: CostCategory = LAUNDRY,
    currency: str = EUR,
) -> Ledger:
    ledger = cpor_history({m: value for m in observed}, category=category, currency=currency)
    part = cpor_history(
        {m: value for m in reconstructed},
        category=category,
        currency=currency,
        reconstructed_days=31,
    )
    ledger.costs.extend(part.costs)
    ledger.occupancy.update(part.occupancy)
    return ledger


def select(
    ledger: Ledger,
    target: CalendarMonth = AUG,
    category: CostCategory = LAUNDRY,
    currency: str = EUR,
) -> ComparableSelection:
    return select_comparables(target, ledger.metric_of(category, currency))


def used(selection: ComparableSelection) -> list[CalendarMonth]:
    return [CalendarMonth.of(p.period_start) for p in selection.periods]


# --- the candidates: 36 months back, the seasonal window ------------------------------------------


def test_the_candidates_of_august_are_the_seasonal_months_of_the_last_three_years() -> None:
    assert candidate_months(AUG) == [
        month(2026, 7),
        month(2026, 6),
        month(2025, 10),
        month(2025, 9),
        month(2025, 8),
        month(2025, 7),
        month(2025, 6),
        month(2024, 10),
        month(2024, 9),
        month(2024, 8),
        month(2024, 7),
        month(2024, 6),
        month(2023, 10),
        month(2023, 9),
        month(2023, 8),
    ]


def test_the_target_month_is_never_a_candidate() -> None:
    assert AUG not in candidate_months(AUG)


def test_every_candidate_ends_before_the_target_starts() -> None:
    for target in (month(2026, 1), month(2026, 8), month(2026, 12)):
        assert all(m.end < target.start for m in candidate_months(target))


def test_future_months_are_never_candidates_even_if_they_hold_data() -> None:
    future = [month(2026, 9), month(2026, 10), month(2027, 8)]
    ledger = ledger_of(observed=[*future, month(2026, 7), month(2026, 6)])

    selection = select(ledger)

    assert used(selection) == [month(2026, 7), month(2026, 6)]
    assert not set(future) & set(used(selection))


def test_a_month_exactly_36_months_back_is_included_and_37_is_not() -> None:
    assert month(2023, 8) in candidate_months(AUG)  # 36 months back
    assert month(2023, 7) not in candidate_months(AUG)  # 37 months back (and distance 1)
    ledger = ledger_of(observed=[month(2023, 8), month(2023, 7)])
    assert used(select(ledger)) == [month(2023, 8)]


@pytest.mark.parametrize(
    ("candidate", "included"),
    [
        (month(2026, 8), False),  # the target itself
        (month(2025, 8), True),  # distance 0, a year before
        (month(2026, 7), True),  # distance 1
        (month(2025, 9), True),  # distance 1
        (month(2026, 6), True),  # distance 2
        (month(2025, 10), True),  # distance 2
        (month(2026, 5), False),  # distance 3
        (month(2025, 11), False),  # distance 3
        (month(2026, 1), False),  # distance 5
    ],
)
def test_the_seasonal_window_is_two_months_either_side(
    candidate: CalendarMonth, included: bool
) -> None:
    assert (candidate in candidate_months(AUG)) is included


def test_december_and_january_are_one_month_apart() -> None:
    january = candidate_months(month(2027, 1))
    assert month(2026, 12) in january  # distance 1
    assert month(2026, 11) in january  # distance 2
    assert month(2026, 10) not in january  # distance 3
    assert month(2026, 2) in january  # February is 1 after January
    assert month(2026, 1) in candidate_months(month(2026, 12))  # January is 1 after December


def test_the_same_category_only() -> None:
    ledger = ledger_of(observed=candidate_months(AUG)[:6], category=UTILITIES)

    assert used(select(ledger, category=LAUNDRY)) == []  # nothing is laundry
    assert select(ledger, category=LAUNDRY).rejected_no_cost_data_count == 15
    assert len(used(select(ledger, category=UTILITIES))) == 6


def test_the_same_currency_only() -> None:
    ledger = ledger_of(observed=candidate_months(AUG)[:6], currency=USD)

    assert used(select(ledger, currency=EUR)) == []
    assert len(used(select(ledger, currency=USD))) == 6


# --- eligibility and the counts of what was rejected ----------------------------------------------


def test_a_month_with_incomplete_occupancy_is_excluded_and_counted() -> None:
    months = candidate_months(AUG)[:6]
    ledger = ledger_of(observed=months[1:])
    ledger.rooms(months[0], 10, missing=[9])  # the newest month lacks one day
    ledger.cost(months[0], LAUNDRY, "3100")

    selection = select(ledger)

    assert months[0] not in used(selection) and len(selection.periods) == 5
    assert selection.rejected_incomplete_occupancy_count == 1


def test_a_month_with_an_uncertain_snapshot_never_enters() -> None:
    months = candidate_months(AUG)[:7]
    ledger = ledger_of(observed=months[1:])
    ledger.rooms(months[0], 10, uncertain=[4])
    ledger.cost(months[0], LAUNDRY, "3100")

    selection = select(ledger)

    assert months[0] not in used(selection)
    assert selection.rejected_incomplete_occupancy_count == 1


def test_a_month_with_low_classification_coverage_is_excluded_and_counted() -> None:
    months = candidate_months(AUG)[:6]
    ledger = ledger_of(observed=months[1:])
    ledger.cost(months[0], LAUNDRY, "600")
    ledger.cost(months[0], OTHER, "400")  # coverage 60 %
    ledger.rooms(months[0], 10)

    selection = select(ledger)

    assert months[0] not in used(selection)
    assert selection.rejected_low_classification_count == 1


def test_a_month_with_zero_occupied_room_nights_is_excluded_and_counted() -> None:
    months = candidate_months(AUG)[:6]
    ledger = ledger_of(observed=months[1:])
    ledger.cost(months[0], LAUNDRY, "500")
    ledger.rooms(months[0], 0)

    selection = select(ledger)

    assert months[0] not in used(selection) and selection.rejected_zero_occupancy_count == 1


def test_a_month_without_cost_data_is_excluded_and_counted_not_treated_as_zero() -> None:
    months = candidate_months(AUG)[:6]
    ledger = ledger_of(observed=months[1:])
    ledger.rooms(months[0], 10)  # occupancy is there, the invoices are not

    selection = select(ledger)

    assert months[0] not in used(selection) and len(selection.periods) == 5
    assert selection.rejected_no_cost_data_count >= 1


def test_the_rejection_counts_add_up_to_the_candidates() -> None:
    months = candidate_months(AUG)
    ledger = ledger_of(observed=months[2:8])
    selection = select(ledger)
    rejected = (
        selection.rejected_no_cost_data_count
        + selection.rejected_low_classification_count
        + selection.rejected_incomplete_occupancy_count
        + selection.rejected_zero_occupancy_count
    )
    assert selection.candidate_month_count == 15
    assert selection.eligible_month_count + rejected == 15


# --- order, maximum and minimum ------------------------------------------------------------------


def test_the_used_months_are_ordered_from_the_most_recent_to_the_oldest() -> None:
    months = candidate_months(AUG)
    ledger = ledger_of(observed=reversed(months[:8]))  # inserted oldest first

    selection = select(ledger)

    assert used(selection) == sorted(used(selection), reverse=True) == months[:8]


def test_at_most_twelve_months_are_used_the_most_recent_ones() -> None:
    months = candidate_months(AUG)
    ledger = ledger_of(observed=months)  # all 15 have data

    selection = select(ledger)

    assert len(selection.periods) == 12 and used(selection) == months[:12]
    assert selection.eligible_month_count == 15


def test_fewer_than_five_months_is_an_insufficient_sample() -> None:
    selection = select(ledger_of(observed=candidate_months(AUG)[:4]))
    assert selection.sample_count == 4 and not selection.sufficient


def test_five_months_are_enough_for_a_baseline() -> None:
    selection = select(ledger_of(observed=candidate_months(AUG)[:5]))
    assert selection.sample_count == 5 and selection.sufficient


# --- G. observed first ----------------------------------------------------------------------------


def test_with_five_observed_months_only_the_observed_ones_are_used() -> None:
    months = candidate_months(AUG)
    observed, approximate = months[2:7], [months[0], months[1], months[9], months[10]]
    ledger = ledger_of(observed=observed, reconstructed=approximate)

    selection = select(ledger)

    assert sorted(used(selection)) == sorted(observed)
    assert selection.observed_period_count == 5 and selection.approximate_period_count == 0
    assert selection.eligible_month_count == 9  # the reconstructed ones were eligible, unused


def test_with_fewer_than_five_observed_the_newest_reconstructed_months_complete_the_sample() -> (
    None
):
    months = candidate_months(AUG)
    observed = [months[4], months[6]]
    approximate = [months[0], months[1], months[2], months[3], months[5]]
    ledger = ledger_of(observed=observed, reconstructed=approximate)

    selection = select(ledger)

    assert len(selection.periods) == 7 and selection.sufficient
    assert (selection.observed_period_count, selection.approximate_period_count) == (2, 5)
    assert set(observed) <= set(used(selection))  # every observed month stays


def test_the_sample_is_completed_up_to_twelve_and_keeps_every_observed_month() -> None:
    months = candidate_months(AUG)
    observed = months[13:15]  # the two OLDEST candidates, observed
    approximate = months[:13]  # thirteen newer reconstructed ones
    ledger = ledger_of(observed=observed, reconstructed=approximate)

    selection = select(ledger)

    assert len(selection.periods) == 12
    assert set(observed) <= set(used(selection))  # not displaced by newer reconstructions
    assert selection.observed_period_count == 2 and selection.approximate_period_count == 10
    assert used(selection) == sorted(used(selection), reverse=True)


def test_an_all_reconstructed_sample_is_allowed_when_it_is_large_enough() -> None:
    ledger = ledger_of(reconstructed=candidate_months(AUG)[:6])

    selection = select(ledger)

    assert selection.sufficient
    assert (selection.observed_period_count, selection.approximate_period_count) == (0, 6)


def test_a_reconstructed_month_with_uncertain_rooms_is_never_used() -> None:
    months = candidate_months(AUG)
    ledger = ledger_of(reconstructed=months[1:6])
    ledger.rooms(months[0], 10, reconstructed=range(1, 32), uncertain=[7])
    ledger.cost(months[0], LAUNDRY, "3100")

    selection = select(ledger)

    assert months[0] not in used(selection)
    assert all(p.status == MetricStatus.READY for p in selection.periods)


def test_a_partly_reconstructed_month_counts_as_approximate() -> None:
    months = candidate_months(AUG)[:5]
    ledger = ledger_of(observed=months[1:])  # four fully observed months
    ledger.cost(months[0], LAUNDRY, "3100")
    ledger.rooms(months[0], 10, reconstructed=[1])  # ONE reconstructed day is enough

    selection = select(ledger)

    assert selection.approximate_period_count == 1 and selection.observed_period_count == 4
    assert months[0] in used(selection)  # fewer than five observed months: it completes the sample


def test_a_partly_reconstructed_month_is_left_out_when_five_observed_months_exist() -> None:
    months = candidate_months(AUG)[:6]
    ledger = ledger_of(observed=months[1:])  # five fully observed months
    ledger.cost(months[0], LAUNDRY, "3100")
    ledger.rooms(months[0], 10, reconstructed=[1])

    selection = select(ledger)

    assert selection.approximate_period_count == 0 and selection.observed_period_count == 5
    assert months[0] not in used(selection)
