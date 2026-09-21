"""Comparable selection and the whole pure calculation (no database).

Target used throughout: Saturday 2026-08-15 seen 14 days before (snapshot day 2026-08-01). Its
eligible comparables are the earlier Saturdays inside the +-42 day season (`eligible_stay_dates`).
"""

import itertools
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.intelligence.expected.calculator import (
    CALCULATION_VERSION,
    METHOD,
    ExpectedComputation,
    ExpectedStatus,
    comparable_fingerprint,
    compute_expected,
)
from app.modules.intelligence.expected.confidence import ConfidenceBand
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.selection import (
    MAX_SAMPLE,
    MIN_SAMPLE,
    Candidate,
    Exclusion,
    HistoricalTarget,
    calendar_exclusion,
    select_comparables,
)
from app.modules.snapshots.models import SnapshotOrigin

OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
TARGET_STAY = date(2026, 8, 15)  # a Saturday
LEAD = 14
TARGET = HistoricalTarget(TARGET_STAY, LEAD)
ELIGIBLE = eligible_stay_dates(TARGET_STAY)  # newest first
_ids = itertools.count(1)


def cand(
    stay: date,
    *,
    rooms: int = 10,
    origin: SnapshotOrigin = OBSERVED,
    uncertain: int = 0,
    lead: int = LEAD,
) -> Candidate:
    return Candidate(
        snapshot_id=uuid.UUID(int=next(_ids)),
        snapshot_local_date=stay - timedelta(days=lead),
        stay_date=stay,
        origin=origin,
        rooms_on_books=rooms,
        uncertain_rooms=uncertain,
    )


def many(stays: list[date], **kwargs: object) -> list[Candidate]:
    return [cand(stay, **kwargs) for stay in stays]  # type: ignore[arg-type]


def used_stays(computation: ExpectedComputation) -> list[date]:
    return [item.candidate.stay_date for item in computation.selection.comparables]


# --- A. lead time -----------------------------------------------------------------------------


def test_lead_time_is_stay_date_minus_snapshot_day() -> None:
    target = HistoricalTarget(date(2026, 10, 15), 14)

    assert target.snapshot_local_date == date(2026, 10, 1)
    assert cand(date(2025, 10, 17)).lead_time_days == 14
    assert cand(date(2025, 10, 17)).snapshot_local_date == date(2025, 10, 3)  # the spec's example


def test_lead_time_zero_is_valid() -> None:
    target = HistoricalTarget(TARGET_STAY, 0)
    candidates = many(ELIGIBLE[:6], lead=0)

    assert target.snapshot_local_date == TARGET_STAY
    assert compute_expected(target, candidates).status == ExpectedStatus.READY


def test_a_negative_lead_time_is_refused() -> None:
    with pytest.raises(ValueError):
        HistoricalTarget(TARGET_STAY, -1)


@pytest.mark.parametrize("lead", [0, 1, 13, 15, 30])
def test_a_comparable_with_a_different_lead_time_is_excluded(lead: int) -> None:
    computation = compute_expected(TARGET, many(ELIGIBLE[:8], lead=lead))

    assert computation.status == ExpectedStatus.INSUFFICIENT_DATA
    assert computation.selection.sample_size == 0
    # leads 0..13 land on a snapshot day that is not before the target's: the leakage rule fires
    # first; leads above 14 fail the lead-time rule itself. Either way nothing enters the sample.
    assert sum(computation.selection.diagnostics.values()) == 8


def test_only_the_lead_time_rule_rejects_an_older_snapshot_of_a_valid_stay_date() -> None:
    candidate = cand(ELIGIBLE[0], lead=15)  # snapshot a day earlier than required

    assert calendar_exclusion(TARGET, candidate) == Exclusion.LEAD_TIME_MISMATCH


def test_there_is_no_interpolation_between_lead_times() -> None:
    """Snapshots at 13 and 15 days must not stand in for the missing one at 14."""
    around = [cand(stay, lead=lead) for stay in ELIGIBLE[:6] for lead in (13, 15)]

    computation = compute_expected(TARGET, around)

    assert computation.status == ExpectedStatus.INSUFFICIENT_DATA
    assert computation.selection.sample_size == 0 and computation.statistics is None


def test_a_snapshot_at_the_exact_lead_time_is_used_even_next_to_wrong_ones() -> None:
    candidates = many(ELIGIBLE[:6]) + many(ELIGIBLE[:6], lead=13) + many(ELIGIBLE[:6], lead=15)

    computation = compute_expected(TARGET, candidates)

    assert computation.selection.sample_size == 6
    assert used_stays(computation) == ELIGIBLE[:6]


# --- B. temporal leakage ----------------------------------------------------------------------


def test_a_comparable_stay_date_in_the_future_is_excluded() -> None:
    future = cand(TARGET_STAY + timedelta(days=7))  # the next Saturday
    same_day = cand(TARGET_STAY)

    assert calendar_exclusion(TARGET, future) == Exclusion.STAY_DATE_NOT_BEFORE_TARGET
    assert calendar_exclusion(TARGET, same_day) == Exclusion.STAY_DATE_NOT_BEFORE_TARGET


def test_a_comparable_snapshot_taken_after_the_target_snapshot_is_excluded() -> None:
    """A past stay date observed on 5 August (lead 3) was not known on 1 August."""
    late_snapshot = Candidate(
        snapshot_id=uuid.UUID(int=next(_ids)),
        snapshot_local_date=date(2026, 8, 5),
        stay_date=date(2026, 8, 8),
        origin=OBSERVED,
        rooms_on_books=99,
        uncertain_rooms=0,
    )

    assert calendar_exclusion(TARGET, late_snapshot) == Exclusion.SNAPSHOT_NOT_BEFORE_TARGET


def test_future_data_never_improves_a_baseline() -> None:
    honest = many(ELIGIBLE[:5])
    leaky = honest + many([TARGET_STAY + timedelta(days=7 * k) for k in range(1, 8)], rooms=200)

    assert compute_expected(TARGET, leaky).statistics == compute_expected(TARGET, honest).statistics
    assert (
        compute_expected(TARGET, leaky).selection.diagnostics[Exclusion.STAY_DATE_NOT_BEFORE_TARGET]
        == 7
    )


def test_history_older_than_730_days_is_excluded_and_the_limit_is_handled_deterministically() -> (
    None
):
    inside = cand(TARGET_STAY - timedelta(days=728))  # 104 weeks: a Saturday, inside the horizon
    beyond = cand(TARGET_STAY - timedelta(days=735))  # 105 weeks: a Saturday, too old
    limit = cand(TARGET_STAY - timedelta(days=730))  # exactly the limit: inside the horizon...
    too_old = cand(TARGET_STAY - timedelta(days=731))

    assert calendar_exclusion(TARGET, inside) is None
    assert calendar_exclusion(TARGET, beyond) == Exclusion.OUTSIDE_HORIZON
    assert calendar_exclusion(TARGET, limit) == Exclusion.WEEKDAY_MISMATCH  # ...but a Thursday
    assert calendar_exclusion(TARGET, too_old) == Exclusion.OUTSIDE_HORIZON


# --- C. weekday and season --------------------------------------------------------------------


def test_the_same_weekday_is_included_and_a_different_one_is_excluded() -> None:
    saturday, friday, sunday = date(2026, 8, 8), date(2026, 8, 7), date(2026, 8, 9)

    assert calendar_exclusion(TARGET, cand(saturday)) is None
    assert calendar_exclusion(TARGET, cand(friday)) == Exclusion.WEEKDAY_MISMATCH
    assert calendar_exclusion(TARGET, cand(sunday)) == Exclusion.WEEKDAY_MISMATCH


def test_a_wrong_weekday_is_never_admitted_silently_to_reach_the_minimum() -> None:
    saturdays = many(ELIGIBLE[:4])
    fridays = many([d - timedelta(days=1) for d in ELIGIBLE[:10]], rooms=99)

    computation = compute_expected(TARGET, saturdays + fridays)

    assert computation.status == ExpectedStatus.INSUFFICIENT_DATA  # 4 usable, not 14
    assert computation.selection.diagnostics[Exclusion.WEEKDAY_MISMATCH] == 10


def test_a_stay_42_days_from_the_season_is_included_and_43_is_excluded() -> None:
    at_42 = cand(date(2026, 7, 4))
    at_43 = cand(date(2025, 9, 27))
    at_49 = cand(date(2026, 6, 27))

    assert calendar_exclusion(TARGET, at_42) is None
    assert calendar_exclusion(TARGET, at_43) == Exclusion.OUTSIDE_SEASONAL_WINDOW
    assert calendar_exclusion(TARGET, at_49) == Exclusion.OUTSIDE_SEASONAL_WINDOW


def test_same_weekday_but_out_of_season_is_excluded() -> None:
    winter = many([date(2026, 1, 10), date(2026, 2, 14), date(2025, 12, 13), date(2026, 3, 14)])

    computation = compute_expected(TARGET, winter)

    assert computation.selection.sample_size == 0
    assert computation.selection.diagnostics[Exclusion.OUTSIDE_SEASONAL_WINDOW] == 4


def test_same_season_but_wrong_weekday_is_excluded() -> None:
    thursdays = many([date(2026, 8, 6), date(2026, 7, 30), date(2026, 7, 23), date(2025, 8, 14)])

    computation = compute_expected(TARGET, thursdays)

    assert computation.selection.sample_size == 0
    assert computation.selection.diagnostics[Exclusion.WEEKDAY_MISMATCH] == 4


def test_a_new_year_target_uses_late_december_and_early_january() -> None:
    target = HistoricalTarget(date(2027, 1, 2), 7)  # a Saturday
    stays = [
        date(2026, 12, 26),
        date(2026, 12, 19),
        date(2026, 12, 12),
        date(2026, 1, 3),
        date(2025, 12, 27),
        date(2025, 11, 22),  # 41 days before 2 Jan: inside
    ]

    computation = compute_expected(target, many(stays, lead=7))

    assert computation.status == ExpectedStatus.READY
    assert used_stays(computation) == stays  # all six, newest first


def test_a_leap_day_target_finds_comparables_in_the_same_season() -> None:
    target = HistoricalTarget(date(2028, 2, 29), 10)  # a Tuesday
    stays = eligible_stay_dates(target.stay_date)

    computation = compute_expected(target, many(stays[:8], lead=10))

    assert computation.status == ExpectedStatus.READY
    assert all(date(2028, 2, 29) - s <= timedelta(days=730) for s in used_stays(computation))


# --- D. provenance: observed first ------------------------------------------------------------


def test_five_observed_comparables_are_used_alone_even_with_plenty_of_reconstructions() -> None:
    observed = many(ELIGIBLE[:5], rooms=10)
    reconstructed = many(ELIGIBLE[5:15], origin=RECONSTRUCTED, rooms=50)

    computation = compute_expected(TARGET, observed + reconstructed)

    assert computation.selection.sample_size == 5
    assert (computation.selection.observed_count, computation.selection.reconstructed_count) == (
        5,
        0,
    )
    assert computation.statistics is not None and computation.statistics.expected == Decimal(
        "10.00"
    )
    assert computation.selection.diagnostics[Exclusion.RECONSTRUCTED_NOT_NEEDED] == 10


def test_a_reconstruction_is_not_added_to_enlarge_a_sufficient_observed_sample() -> None:
    observed = many(ELIGIBLE[:6], rooms=10)
    reconstructed = many(ELIGIBLE[:6], origin=RECONSTRUCTED, rooms=90)  # same dates would clash

    computation = compute_expected(TARGET, observed + reconstructed[3:])

    assert computation.selection.reconstructed_count == 0
    assert {c.candidate.origin for c in computation.selection.comparables} == {OBSERVED}


def test_fewer_than_five_observed_are_completed_with_clean_reconstructions() -> None:
    observed = many(ELIGIBLE[:3], rooms=10)
    reconstructed = many(ELIGIBLE[3:13], origin=RECONSTRUCTED, rooms=20)

    computation = compute_expected(TARGET, observed + reconstructed)

    selection = computation.selection
    assert (selection.observed_count, selection.reconstructed_count) == (3, 10)
    assert selection.sample_size == 13
    assert computation.status == ExpectedStatus.READY
    assert used_stays(computation) == ELIGIBLE[:13]  # newest first, both origins together


def test_reconstructions_fill_the_sample_but_never_displace_observed_comparables() -> None:
    """Two OLD observed comparables survive next to reconstructions that are all more recent."""
    observed = many([ELIGIBLE[22], ELIGIBLE[23]], rooms=10)
    reconstructed = many(ELIGIBLE[:22], origin=RECONSTRUCTED, rooms=20)

    computation = compute_expected(TARGET, observed + reconstructed)

    assert computation.selection.sample_size == 24
    assert (computation.selection.observed_count, computation.selection.reconstructed_count) == (
        2,
        22,
    )


def test_with_too_many_reconstructions_the_observed_ones_are_kept_and_the_oldest_dropped() -> None:
    observed = many([ELIGIBLE[22], ELIGIBLE[23]], rooms=10)
    # 30 clean reconstructions (duplicated stay dates: only possible on hand-built input)
    reconstructed = many(ELIGIBLE[:15], origin=RECONSTRUCTED, rooms=20) + many(
        ELIGIBLE[:15], origin=RECONSTRUCTED, rooms=30
    )

    selection = compute_expected(TARGET, observed + reconstructed).selection

    assert selection.sample_size == MAX_SAMPLE
    assert selection.observed_count == 2 and selection.reconstructed_count == 22
    assert selection.diagnostics[Exclusion.BEYOND_MAX_SAMPLE] == 8


def test_a_reconstruction_with_uncertainty_never_enters_the_numbers() -> None:
    observed = many(ELIGIBLE[:3], rooms=10)
    uncertain = many(ELIGIBLE[3:6], origin=RECONSTRUCTED, rooms=999, uncertain=2)
    clean = many(ELIGIBLE[6:9], origin=RECONSTRUCTED, rooms=20)

    computation = compute_expected(TARGET, observed + uncertain + clean)

    assert computation.selection.rejected_uncertain_count == 3
    assert computation.selection.diagnostics[Exclusion.UNCERTAIN] == 3
    assert computation.selection.reconstructed_count == 3
    assert 999 not in [c.candidate.rooms_on_books for c in computation.selection.comparables]
    assert computation.statistics is not None and computation.statistics.upper < 100


def test_rejected_uncertain_count_only_counts_comparables_that_pass_the_calendar_rules() -> None:
    observed = many(ELIGIBLE[:6], rooms=10)
    uncertain_eligible = many(ELIGIBLE[6:8], origin=RECONSTRUCTED, uncertain=1)
    uncertain_wrong_weekday = many([date(2026, 8, 7)], origin=RECONSTRUCTED, uncertain=1)

    computation = compute_expected(TARGET, observed + uncertain_eligible + uncertain_wrong_weekday)

    assert computation.selection.rejected_uncertain_count == 2  # informative even if not needed
    assert computation.selection.reconstructed_count == 0


def test_only_reconstructed_comparables_can_make_a_baseline_but_never_a_confident_one() -> None:
    reconstructed = many(ELIGIBLE[:14], origin=RECONSTRUCTED, rooms=20)

    computation = compute_expected(TARGET, reconstructed)

    assert computation.status == ExpectedStatus.READY
    assert (computation.selection.observed_count, computation.selection.reconstructed_count) == (
        0,
        14,
    )
    assert computation.confidence is not None
    assert computation.confidence.score == Decimal("65.00")  # 40 + 21 + 25 = 86, capped at 65
    assert computation.confidence.band == ConfidenceBand.MEDIUM


def test_mixed_provenance_is_capped_at_85() -> None:
    observed = many(ELIGIBLE[:4], rooms=20)
    reconstructed = many(ELIGIBLE[4:14], origin=RECONSTRUCTED, rooms=20)

    computation = compute_expected(TARGET, observed + reconstructed)

    assert computation.confidence is not None
    assert computation.confidence.score == Decimal("85.00")  # 40 + 0.35 * 71.4 + 25 = 90 -> 85
    assert computation.confidence.band == ConfidenceBand.HIGH


# --- E. minimum and maximum sample ------------------------------------------------------------


def test_four_valid_comparables_are_insufficient_even_if_the_statistics_could_be_computed() -> None:
    four = many(ELIGIBLE[:4], rooms=12)

    computation = compute_expected(TARGET, four)

    assert computation.selection.sample_size == 4
    assert computation.status == ExpectedStatus.INSUFFICIENT_DATA
    assert computation.statistics is None and computation.confidence is None
    assert computation.confidence_score == Decimal("0.00") and computation.confidence_band is None


def test_five_valid_comparables_are_ready() -> None:
    computation = compute_expected(TARGET, many(ELIGIBLE[:MIN_SAMPLE], rooms=12))

    assert computation.status == ExpectedStatus.READY
    assert computation.statistics is not None and computation.statistics.expected == Decimal(
        "12.00"
    )


def test_zero_room_comparables_count_in_the_sample() -> None:
    rooms = [0, 0, 1, 2, 3]
    candidates = [cand(stay, rooms=value) for stay, value in zip(ELIGIBLE, rooms, strict=False)]

    computation = compute_expected(TARGET, candidates)

    assert computation.status == ExpectedStatus.READY
    assert computation.statistics is not None
    assert computation.statistics.expected == Decimal("1.00")
    assert computation.selection.sample_size == 5


def test_no_comparable_at_all_is_insufficient() -> None:
    computation = compute_expected(TARGET, [])

    assert computation.status == ExpectedStatus.INSUFFICIENT_DATA
    assert computation.selection.sample_size == 0


def test_the_v1_calendar_never_offers_more_than_24_stay_dates() -> None:
    """Two seasonal windows of about 12 same-weekday dates: 24 is the structural maximum, so the
    sample cap is an explicit guarantee that only hand-built input can ever exercise."""
    counts = {
        len(eligible_stay_dates(date(2026, 1, 1) + timedelta(days=offset))) for offset in range(800)
    }

    assert max(counts) == MAX_SAMPLE == 24


def duplicated_pool() -> list[Candidate]:
    """40 calendar-valid observed candidates: the 24 eligible dates, 16 of them twice."""
    return many(ELIGIBLE) + many(ELIGIBLE[:16])


def test_the_sample_is_capped_at_24() -> None:
    selection = select_comparables(TARGET, duplicated_pool())

    assert selection.sample_size == 24
    assert selection.diagnostics[Exclusion.BEYOND_MAX_SAMPLE] == 16
    assert [item.recency_rank for item in selection.comparables] == list(range(1, 25))


def test_with_more_than_24_the_24_most_recent_stay_dates_are_used() -> None:
    pool = duplicated_pool()
    selection = select_comparables(TARGET, pool)

    used = [item.candidate.stay_date for item in selection.comparables]
    assert used == sorted(used, reverse=True)
    # the 12 most recent dates exist twice (24 candidates): the 12 older dates are cut off
    assert set(used) == set(ELIGIBLE[:12])
    assert min(used) > max(ELIGIBLE[12:])


def test_the_cap_is_deterministic_whatever_the_input_order() -> None:
    pool = duplicated_pool()

    def ids(candidates: list[Candidate]) -> list[uuid.UUID]:
        return [c.candidate.snapshot_id for c in select_comparables(TARGET, candidates).comparables]

    reference = ids(pool)

    assert ids(list(reversed(pool))) == reference
    assert ids(pool[10:] + pool[:10]) == reference


# --- G. expected output -----------------------------------------------------------------------


def test_expected_lower_upper_are_the_median_and_the_quartiles_of_the_sample() -> None:
    rooms = [10, 12, 14, 16, 18, 20]
    candidates = [cand(stay, rooms=value) for stay, value in zip(ELIGIBLE, rooms, strict=False)]

    computation = compute_expected(TARGET, candidates)

    stats = computation.statistics
    assert stats is not None
    assert stats.expected == Decimal("15.00")  # median of 10..20 step 2
    assert stats.lower == Decimal("12.50") and stats.upper == Decimal("17.50")
    assert stats.iqr == Decimal("5.00")


def test_a_fractional_expected_is_kept() -> None:
    rooms = [10, 11, 10, 11, 10, 11]
    computation = compute_expected(
        TARGET, [cand(stay, rooms=value) for stay, value in zip(ELIGIBLE, rooms, strict=False)]
    )

    assert computation.statistics is not None
    assert computation.statistics.expected == Decimal("10.50")


def test_a_ready_result_carries_statistics_and_confidence_and_an_insufficient_one_none() -> None:
    ready = compute_expected(TARGET, many(ELIGIBLE[:6]))
    insufficient = compute_expected(TARGET, many(ELIGIBLE[:2]))

    assert ready.statistics is not None and ready.confidence is not None
    assert (insufficient.statistics, insufficient.confidence) == (None, None)


def test_expected_is_not_a_forecast_it_has_no_final_or_remaining_or_pickup_fields() -> None:
    fields = set(ExpectedComputation.__dataclass_fields__)

    assert fields == {"status", "selection", "statistics", "confidence"}
    stats = compute_expected(TARGET, many(ELIGIBLE[:6])).statistics
    assert stats is not None
    assert set(type(stats).__dataclass_fields__) == {"expected", "lower", "upper", "iqr"}


# --- I. fingerprint ---------------------------------------------------------------------------


def fingerprint(candidates: list[Candidate], target_snapshot: uuid.UUID | None = None) -> str:
    return comparable_fingerprint(
        data_source_id=uuid.UUID(int=7),
        target_snapshot_id=target_snapshot or uuid.UUID(int=9),
        target=TARGET,
        computation=compute_expected(TARGET, candidates),
    )


def test_the_fingerprint_is_deterministic_and_a_sha256() -> None:
    candidates = many(ELIGIBLE[:6])

    first, second = fingerprint(candidates), fingerprint(list(reversed(candidates)))

    assert first == second  # the input order is irrelevant: the selection orders it
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")


def test_the_fingerprint_changes_with_any_comparable_value_origin_or_target() -> None:
    base = many(ELIGIBLE[:6], rooms=10)
    changed_value = [*base[:5], cand(ELIGIBLE[5], rooms=11)]
    changed_origin = [*base[:5], cand(ELIGIBLE[5], rooms=10, origin=RECONSTRUCTED)]

    fingerprints = {
        fingerprint(base),
        fingerprint(changed_value),
        fingerprint(changed_origin),
        fingerprint(base, target_snapshot=uuid.UUID(int=10)),
    }

    assert len(fingerprints) == 4


def test_the_fingerprint_depends_on_the_comparable_set_not_on_ignored_candidates() -> None:
    base = many(ELIGIBLE[:6], rooms=10)
    noise = many([date(2026, 8, 7)], rooms=99)  # a Friday: excluded, must not matter

    assert fingerprint(base) == fingerprint(base + noise)


def test_the_fingerprint_sees_the_rejected_uncertain_count() -> None:
    base = many(ELIGIBLE[:6], rooms=10)
    uncertain = many(ELIGIBLE[6:7], origin=RECONSTRUCTED, uncertain=2)

    assert fingerprint(base) != fingerprint(base + uncertain)


def test_method_and_version_are_the_documented_stable_names() -> None:
    assert METHOD == "MEDIAN_SAME_DOW_SEASONAL_WINDOW"
    assert CALCULATION_VERSION == "booking-expected-v1"
    assert ExpectedStatus.READY.value == "READY"
    assert ExpectedStatus.INSUFFICIENT_DATA.value == "INSUFFICIENT_DATA"


def test_the_target_is_a_stay_date_and_a_lead_time_not_a_decision() -> None:
    assert set(HistoricalTarget.__dataclass_fields__) == {"stay_date", "lead_time_days"}


def test_a_stay_exactly_42_real_days_before_across_february_is_comparable() -> None:
    """27 February -> 10 April 2026 is 42 real days: inside the window, as a calendar would say."""
    target = HistoricalTarget(date(2026, 4, 10), LEAD)  # a Friday
    stay = date(2026, 2, 27)  # also a Friday
    assert (target.stay_date - stay).days == 42 and stay.weekday() == target.stay_date.weekday()

    assert calendar_exclusion(target, cand(stay)) is None
    assert calendar_exclusion(target, cand(stay - timedelta(days=7))) == (
        Exclusion.OUTSIDE_SEASONAL_WINDOW  # 49 real days
    )
