"""Historical curve pairing (Gate 5, group B) and its anti-leakage guarantees. Pure, no database."""

import random
from datetime import date, timedelta

from app.modules.intelligence.revenue.pairing import (
    SnapshotKey,
    final_key,
    pickup_pairs,
    pickup_prior_key,
    remaining_pairs,
)
from app.modules.intelligence.revenue.types import (
    MAX_PAIRS,
    MIN_PAIRS,
    PairProvenance,
    SnapshotPoint,
)
from app.modules.snapshots.models import SnapshotOrigin
from tests.revenue_support import (
    OBSERVED,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    endpoints_of,
    point,
)

TARGET_DAY = TARGET_SNAPSHOT_DAY  # 2026-08-01
STAYS = [date(2026, 7, 25) - timedelta(days=7 * i) for i in range(30)]  # newest first


def _pickup_world(
    count: int,
    *,
    anchor: int = 20,
    prior: int = 12,
    prior_origin: SnapshotOrigin = OBSERVED,
    anchor_origin: SnapshotOrigin = OBSERVED,
) -> tuple[list[SnapshotPoint], dict[SnapshotKey, SnapshotPoint]]:
    anchors: list[SnapshotPoint] = []
    points: list[SnapshotPoint] = []
    for stay in STAYS[:count]:
        a = point(stay - timedelta(days=14), stay, anchor, origin=anchor_origin)
        p = point(stay - timedelta(days=21), stay, prior, origin=prior_origin)
        anchors.append(a)
        points.extend([a, p])
    return anchors, endpoints_of(*points)


def _remaining_world(
    count: int, *, anchor: int = 10, final: int = 14, final_origin: SnapshotOrigin = OBSERVED
) -> tuple[list[SnapshotPoint], dict[SnapshotKey, SnapshotPoint]]:
    anchors: list[SnapshotPoint] = []
    points: list[SnapshotPoint] = []
    for stay in STAYS[:count]:
        a = point(stay - timedelta(days=14), stay, anchor)
        f = point(stay, stay, final, origin=final_origin)
        anchors.append(a)
        points.extend([a, f])
    return anchors, endpoints_of(*points)


# --- keys and deltas ------------------------------------------------------------------------


def test_pickup_pair_uses_the_snapshot_exactly_seven_days_earlier_of_the_same_stay_date() -> None:
    anchor = point(date(2026, 7, 11), date(2026, 7, 25), 20)
    assert pickup_prior_key(anchor) == (date(2026, 7, 4), date(2026, 7, 25))
    prior = point(date(2026, 7, 4), date(2026, 7, 25), 12)
    # one day too early / too late, or another stay date, is NOT the prior
    wrong = [
        point(date(2026, 7, 3), date(2026, 7, 25), 5),
        point(date(2026, 7, 5), date(2026, 7, 25), 5),
        point(date(2026, 7, 4), date(2026, 7, 26), 5),
    ]
    result = pickup_pairs(TARGET_DAY, [anchor], endpoints_of(prior, *wrong))
    assert result.pair_count == 1
    assert result.pairs[0].other is prior
    assert result.pairs[0].delta == 8  # historical pickup = anchor - prior


def test_pickup_pair_without_the_exact_prior_is_missing_not_approximated() -> None:
    anchor = point(date(2026, 7, 11), date(2026, 7, 25), 20)
    nearby = point(date(2026, 7, 5), date(2026, 7, 25), 12)  # 6 days before: not accepted
    result = pickup_pairs(TARGET_DAY, [anchor], endpoints_of(anchor, nearby))
    assert result.pair_count == 0
    assert result.missing_endpoint_count == 1


def test_remaining_pair_uses_the_final_snapshot_of_the_same_stay_date() -> None:
    anchor = point(date(2026, 7, 11), date(2026, 7, 25), 10)
    assert final_key(anchor) == (date(2026, 7, 25), date(2026, 7, 25))
    final = point(date(2026, 7, 25), date(2026, 7, 25), 14)
    result = remaining_pairs(TARGET_DAY, [anchor], endpoints_of(final))
    assert result.pairs[0].other is final
    assert result.pairs[0].delta == 4  # remaining net pickup = final - anchor


def test_remaining_net_pickup_can_be_negative_and_zero() -> None:
    a_neg = point(date(2026, 6, 6), date(2026, 6, 20), 12)
    f_neg = point(date(2026, 6, 20), date(2026, 6, 20), 9)  # 3 rooms cancelled after the anchor
    a_zero = point(date(2026, 6, 13), date(2026, 6, 27), 8)
    f_zero = point(date(2026, 6, 27), date(2026, 6, 27), 8)
    result = remaining_pairs(TARGET_DAY, [a_neg, a_zero], endpoints_of(f_neg, f_zero))
    assert [p.delta for p in result.pairs] == [0, -3]  # newest stay date first


# --- provenance ------------------------------------------------------------------------------


def test_pair_provenance_is_observed_only_when_both_endpoints_are_observed() -> None:
    stay = date(2026, 7, 25)
    prior = point(date(2026, 7, 4), stay, 12)
    prior_rec = point(date(2026, 7, 4), stay, 12, origin=RECONSTRUCTED)
    obs_anchor = point(date(2026, 7, 11), stay, 20)
    rec_anchor = point(date(2026, 7, 11), stay, 20, origin=RECONSTRUCTED)
    cases = [
        (obs_anchor, prior, PairProvenance.OBSERVED_PAIR),
        (obs_anchor, prior_rec, PairProvenance.APPROXIMATE_PAIR),
        (rec_anchor, prior, PairProvenance.APPROXIMATE_PAIR),
        (rec_anchor, prior_rec, PairProvenance.APPROXIMATE_PAIR),
    ]
    for anchor, other, expected in cases:
        (pair,) = pickup_pairs(TARGET_DAY, [anchor], endpoints_of(other)).pairs
        assert pair.provenance == expected


# --- uncertainty -----------------------------------------------------------------------------


def test_a_pair_with_an_uncertain_endpoint_is_excluded_and_counted() -> None:
    anchors, endpoints = _pickup_world(6)
    stay = STAYS[0]
    endpoints[(stay - timedelta(days=21), stay)] = point(
        stay - timedelta(days=21), stay, 12, origin=RECONSTRUCTED, uncertain=2
    )
    result = pickup_pairs(TARGET_DAY, anchors, endpoints)
    assert result.pair_count == 5
    assert result.rejected_uncertain_count == 1
    assert stay not in [pair.stay_date for pair in result.pairs]


def test_an_uncertain_anchor_is_excluded_and_counted() -> None:
    anchors, endpoints = _pickup_world(6)
    anchors[2] = point(
        anchors[2].snapshot_local_date, anchors[2].stay_date, 20, origin=RECONSTRUCTED, uncertain=1
    )
    result = pickup_pairs(TARGET_DAY, anchors, endpoints)
    assert result.pair_count == 5
    assert result.rejected_uncertain_count == 1


def test_uncertain_pairs_are_never_used_to_reach_the_minimum() -> None:
    anchors, endpoints = _pickup_world(MIN_PAIRS - 1)  # 4 clean pairs
    for stay in STAYS[MIN_PAIRS - 1 : MIN_PAIRS + 2]:  # 3 more, all uncertain
        a = point(stay - timedelta(days=14), stay, 20)
        anchors.append(a)
        endpoints[(stay - timedelta(days=21), stay)] = point(
            stay - timedelta(days=21), stay, 12, origin=RECONSTRUCTED, uncertain=1
        )
    result = pickup_pairs(TARGET_DAY, anchors, endpoints)
    assert result.pair_count == 4  # below the minimum: the caller says INSUFFICIENT_DATA
    assert result.rejected_uncertain_count == 3


# --- the observed-first policy ---------------------------------------------------------------


def test_five_clean_observed_pairs_mean_observed_only() -> None:
    anchors, endpoints = _pickup_world(5)
    more, more_endpoints = _pickup_world(12, prior_origin=RECONSTRUCTED)
    extra = [a for a in more if a.stay_date not in {x.stay_date for x in anchors}]
    endpoints.update(
        {k: v for k, v in more_endpoints.items() if k not in endpoints}  # approximate ones
    )
    result = pickup_pairs(TARGET_DAY, anchors + extra, endpoints)
    assert result.pair_count == 5
    assert result.observed_pair_count == 5
    assert result.approximate_pair_count == 0  # never enlarged with approximations


def test_fewer_than_five_observed_pairs_are_completed_with_clean_approximate_ones() -> None:
    observed, endpoints = _pickup_world(3)
    approx_anchors, approx_endpoints = _pickup_world(10, prior_origin=RECONSTRUCTED)
    extra = [a for a in approx_anchors if a.stay_date not in {x.stay_date for x in observed}]
    endpoints.update({k: v for k, v in approx_endpoints.items() if k not in endpoints})
    result = pickup_pairs(TARGET_DAY, observed + extra, endpoints)
    assert result.pair_count == 10
    assert result.observed_pair_count == 3
    assert result.approximate_pair_count == 7
    # the observed evidence is kept whatever its age: it never gives way to newer approximations
    assert {p.stay_date for p in result.pairs if p.provenance == PairProvenance.OBSERVED_PAIR} == {
        a.stay_date for a in observed
    }


def test_the_sample_is_capped_at_24_newest_first() -> None:
    anchors, endpoints = _pickup_world(30)
    result = pickup_pairs(TARGET_DAY, anchors, endpoints)
    assert result.pair_count == MAX_PAIRS == 24
    assert [p.stay_date for p in result.pairs] == STAYS[:24]  # the 24 newest, newest first


def test_the_fill_stops_at_24_in_total() -> None:
    observed, endpoints = _pickup_world(3)
    approx, approx_endpoints = _pickup_world(30, prior_origin=RECONSTRUCTED)
    extra = [a for a in approx if a.stay_date not in {x.stay_date for x in observed}]
    endpoints.update({k: v for k, v in approx_endpoints.items() if k not in endpoints})
    result = pickup_pairs(TARGET_DAY, observed + extra, endpoints)
    assert result.pair_count == 24
    assert result.observed_pair_count == 3
    assert result.approximate_pair_count == 21


def test_pairs_are_ordered_newest_first_whatever_the_input_order() -> None:
    anchors, endpoints = _pickup_world(12)
    expected = pickup_pairs(TARGET_DAY, anchors, endpoints)
    for seed in range(5):
        shuffled = anchors[:]
        random.Random(seed).shuffle(shuffled)
        again = pickup_pairs(TARGET_DAY, shuffled, endpoints)
        assert [p.stay_date for p in again.pairs] == [p.stay_date for p in expected.pairs]
        assert [p.delta for p in again.pairs] == [p.delta for p in expected.pairs]
    assert [p.stay_date for p in expected.pairs] == sorted(
        (p.stay_date for p in expected.pairs), reverse=True
    )


def test_a_duplicated_anchor_counts_once() -> None:
    anchors, endpoints = _pickup_world(6)
    result = pickup_pairs(TARGET_DAY, anchors + anchors[:3], endpoints)
    assert result.pair_count == 6


def test_no_anchors_no_pairs() -> None:
    result = pickup_pairs(TARGET_DAY, [], {})
    assert result.pair_count == 0
    assert (result.observed_pair_count, result.approximate_pair_count) == (0, 0)


# --- no temporal leakage ---------------------------------------------------------------------


def test_a_final_snapshot_not_yet_known_at_the_target_day_is_excluded_and_counted() -> None:
    # target snapshot day 2026-08-01: finals of 07-25 (known), 08-01 (same day) and 08-08 (future)
    anchors, points = [], []
    for stay in (date(2026, 7, 25), date(2026, 8, 1), date(2026, 8, 8)):
        a = point(stay - timedelta(days=14), stay, 10)
        anchors.append(a)
        points.append(point(stay, stay, 15))
    result = remaining_pairs(TARGET_DAY, anchors, endpoints_of(*points))
    assert [p.stay_date for p in result.pairs] == [date(2026, 7, 25)]
    assert result.excluded_future_count == 2  # the same day is treated as not yet known


def test_the_final_of_the_day_before_the_target_is_the_last_one_allowed() -> None:
    stay = TARGET_DAY - timedelta(days=1)
    anchor = point(stay - timedelta(days=14), stay, 10)
    final = point(stay, stay, 12)
    result = remaining_pairs(TARGET_DAY, [anchor], endpoints_of(final))
    assert result.pair_count == 1
    assert result.excluded_future_count == 0


def test_an_anchor_taken_on_or_after_the_target_day_is_excluded() -> None:
    stay = date(2026, 8, 22)
    on_the_day = point(TARGET_DAY, stay, 10)
    later = point(TARGET_DAY + timedelta(days=3), stay + timedelta(days=3), 10)
    priors = [
        point(TARGET_DAY - timedelta(days=7), stay, 4),
        point(TARGET_DAY - timedelta(days=4), stay + timedelta(days=3), 4),
    ]
    result = pickup_pairs(TARGET_DAY, [on_the_day, later], endpoints_of(*priors))
    assert result.pair_count == 0
    assert result.excluded_future_count == 2


def test_future_information_never_changes_the_selected_pairs() -> None:
    anchors, endpoints = _remaining_world(8)
    before = remaining_pairs(TARGET_DAY, anchors, endpoints)
    # a later stay date whose final would move the statistics, and a wildly different snapshot
    future_stay = date(2026, 8, 8)
    future_anchor = point(future_stay - timedelta(days=14), future_stay, 1)
    future_final = point(future_stay, future_stay, 99)
    after = remaining_pairs(
        TARGET_DAY,
        [*anchors, future_anchor],
        {**endpoints, **endpoints_of(future_final)},
    )
    assert [(p.stay_date, p.delta) for p in after.pairs] == [
        (p.stay_date, p.delta) for p in before.pairs
    ]
    assert after.excluded_future_count == before.excluded_future_count + 1


def test_a_pair_never_mixes_stay_dates() -> None:
    anchor = point(date(2026, 7, 11), date(2026, 7, 25), 10)
    other_night = point(date(2026, 7, 25), date(2026, 7, 26), 99)  # key would match by day only
    # a mapping that (wrongly) returns another stay date's snapshot is refused
    result = remaining_pairs(TARGET_DAY, [anchor], {final_key(anchor): other_night})
    assert result.pair_count == 0
    assert result.missing_endpoint_count == 1


def test_an_endpoint_of_another_stay_date_is_never_used_as_a_neighbour() -> None:
    stay = date(2026, 7, 25)
    anchor = point(stay - timedelta(days=14), stay, 10)
    neighbours = [
        point(stay - timedelta(days=1), stay, 30),  # the day before the final, same stay date
        point(stay, stay + timedelta(days=7), 30),  # the same weekday next week
    ]
    result = remaining_pairs(TARGET_DAY, [anchor], endpoints_of(*neighbours))
    assert result.pair_count == 0
    assert result.missing_endpoint_count == 1
