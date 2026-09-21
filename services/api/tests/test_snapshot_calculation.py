"""The arithmetic of a snapshot: stay nights, revenue allocation, ADR, occupancy, fingerprint.

Pure functions: no database. Money is exact (integer cents), there is no float anywhere.
"""

import ast
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

import app.modules.snapshots as snapshots_package
from app.modules.bookings.models import BookingStatus
from app.modules.snapshots.aggregate import aggregate_observed
from app.modules.snapshots.calculation import (
    CALCULATION_VERSION,
    OBSERVED_STATUSES,
    DayTotals,
    SnapshotContent,
    StayRecord,
    adr,
    build_content,
    from_cents,
    night_revenue_cents,
    occupancy,
    stay_nights,
    to_cents,
)
from app.modules.snapshots.models import SnapshotOrigin

DATA_SOURCE = UUID("00000000-0000-4000-8000-000000000001")
BOOKED = datetime(2026, 1, 1, 10, tzinfo=UTC)


def stay(
    check_in: date,
    check_out: date,
    *,
    rooms: int = 1,
    revenue: str = "300.00",
    status: BookingStatus = BookingStatus.CONFIRMED,
) -> StayRecord:
    return StayRecord(status, BOOKED, None, check_in, check_out, rooms, Decimal(revenue))


# --- B. stay-night semantics -------------------------------------------------------------------


def test_the_check_out_date_is_not_a_stay_night() -> None:
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 13))], date(2026, 3, 9), date(2026, 3, 14)
    )

    assert {day.day: t.rooms for day, t in totals.items()} == {
        9: 0,
        10: 1,
        11: 1,
        12: 1,
        13: 0,
        14: 0,
    }


def test_a_multi_night_stay_contributes_to_every_night() -> None:
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 15))], date(2026, 3, 10), date(2026, 3, 14)
    )

    assert [t.booking_count for t in totals.values()] == [1, 1, 1, 1, 1]


def test_a_booking_with_three_rooms_adds_three_rooms_per_night_but_counts_once() -> None:
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 12), rooms=3)], date(2026, 3, 10), date(2026, 3, 11)
    )

    assert [(t.booking_count, t.rooms) for t in totals.values()] == [(1, 3), (1, 3)]


def test_a_range_starting_inside_a_stay_still_uses_the_whole_stays_allocation() -> None:
    """Range 12..13 of a stay 10..14: nights 2 and 3 of 4 get their own share of 100.01."""
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 14), revenue="100.01")],
        date(2026, 3, 12),
        date(2026, 3, 13),
    )

    # 10001 cents over 4 nights: 2500 each + 1 cent to the first night only.
    assert [t.revenue_cents for t in totals.values()] == [2500, 2500]


def test_a_stay_outside_the_range_contributes_nothing_but_every_night_has_an_entry() -> None:
    totals = aggregate_observed(
        [stay(date(2026, 4, 1), date(2026, 4, 3))], date(2026, 3, 10), date(2026, 3, 12)
    )

    assert len(totals) == 3
    assert all(t == DayTotals() for t in totals.values())


def test_stay_nights_needs_a_positive_length() -> None:
    assert stay_nights(date(2026, 3, 10), date(2026, 3, 11)) == 1
    with pytest.raises(ValueError):
        stay_nights(date(2026, 3, 10), date(2026, 3, 10))


# --- C. observed status policy -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "counted"),
    [
        (BookingStatus.CONFIRMED, True),
        (BookingStatus.CHECKED_IN, True),
        (BookingStatus.CHECKED_OUT, True),
        (BookingStatus.CANCELLED, False),
        (BookingStatus.NO_SHOW, False),
    ],
)
def test_the_observed_status_policy_is_explicit(status: BookingStatus, counted: bool) -> None:
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 11), status=status)],
        date(2026, 3, 10),
        date(2026, 3, 10),
    )

    assert (totals[date(2026, 3, 10)].rooms == 1) is counted
    assert (status in OBSERVED_STATUSES) is counted


def test_every_status_is_classified() -> None:
    assert {
        BookingStatus.CONFIRMED,
        BookingStatus.CHECKED_IN,
        BookingStatus.CHECKED_OUT,
    } == OBSERVED_STATUSES
    assert set(BookingStatus) - OBSERVED_STATUSES == {
        BookingStatus.CANCELLED,
        BookingStatus.NO_SHOW,
    }


# --- D. revenue allocation ---------------------------------------------------------------------


def nights_of(total: str, nights: int) -> list[Decimal]:
    cents = to_cents(Decimal(total))
    return [from_cents(night_revenue_cents(cents, nights, index)) for index in range(nights)]


def test_300_over_3_nights_is_100_each() -> None:
    assert nights_of("300.00", 3) == [Decimal("100.00")] * 3


def test_100_over_3_nights_gives_the_remainder_to_the_earliest_night() -> None:
    allocated = nights_of("100.00", 3)

    assert allocated == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert sum(allocated) == Decimal("100.00")


def test_100_over_6_nights_sums_exactly() -> None:
    allocated = nights_of("100.00", 6)

    assert allocated == [Decimal("16.67")] * 4 + [Decimal("16.66")] * 2
    assert sum(allocated) == Decimal("100.00")


def test_one_cent_over_several_nights_is_preserved_exactly() -> None:
    allocated = nights_of("0.01", 4)

    assert allocated == [Decimal("0.01"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")]
    assert sum(allocated) == Decimal("0.01")


def test_zero_revenue_allocates_zero() -> None:
    assert nights_of("0.00", 5) == [Decimal("0.00")] * 5


def test_allocations_always_sum_exactly_and_never_differ_by_more_than_one_cent() -> None:
    for total in (0, 1, 2, 7, 99, 100, 101, 12_345, 999_999_999_999):
        for nights in range(1, 40):
            parts = [night_revenue_cents(total, nights, index) for index in range(nights)]
            assert sum(parts) == total, (total, nights)
            assert max(parts) - min(parts) <= 1, (total, nights)
            assert parts == sorted(parts, reverse=True), (total, nights)  # earliest nights first


def test_the_full_stay_revenue_is_never_added_to_every_night() -> None:
    totals = aggregate_observed(
        [stay(date(2026, 3, 10), date(2026, 3, 13), revenue="300.00")],
        date(2026, 3, 10),
        date(2026, 3, 12),
    )

    assert sum(t.revenue_cents for t in totals.values()) == 30_000  # not 90_000


def test_sub_cent_amounts_are_refused_not_rounded() -> None:
    with pytest.raises(ValueError):
        to_cents(Decimal("10.005"))
    assert to_cents(Decimal("10.50")) == 1050 and to_cents(Decimal("10.5")) == 1050


def test_money_is_decimal_and_no_float_is_used_in_the_snapshot_code() -> None:
    assert isinstance(from_cents(1234), Decimal) and str(from_cents(1234)) == "12.34"
    package_dir = Path(snapshots_package.__file__).parent
    for source in package_dir.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        floats = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "float"]
        literals = [
            n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)
        ]
        assert floats == [] and literals == [], source.name


def test_adr_of_multi_room_bookings_divides_by_rooms_not_by_bookings() -> None:
    # one booking of 2 rooms (200 for the night) + one of 1 room (100): 300 / 3 rooms = 100.00
    totals = aggregate_observed(
        [
            stay(date(2026, 3, 10), date(2026, 3, 11), rooms=2, revenue="200.00"),
            stay(date(2026, 3, 10), date(2026, 3, 11), rooms=1, revenue="100.00"),
        ],
        date(2026, 3, 10),
        date(2026, 3, 10),
    )
    day = totals[date(2026, 3, 10)]

    assert (day.booking_count, day.rooms, day.revenue_cents) == (2, 3, 30_000)
    assert adr(day.revenue_cents, day.rooms) == Decimal("100.00")


# --- E. occupancy and ADR ----------------------------------------------------------------------


def test_occupancy_is_rooms_on_books_over_rooms_available_in_percent() -> None:
    assert occupancy(20, 40) == Decimal("50.00")


def test_occupancy_over_100_is_not_clamped() -> None:
    assert occupancy(45, 40) == Decimal("112.50")


def test_occupancy_is_none_without_inventory_and_with_zero_inventory() -> None:
    assert occupancy(5, None) is None
    assert occupancy(5, 0) is None  # no division by zero, no invented 0 or 100
    assert occupancy(0, 0) is None


def test_occupancy_is_zero_when_capacity_exists_and_nothing_is_booked() -> None:
    assert occupancy(0, 40) == Decimal("0.00")


def test_occupancy_rounds_half_up_to_two_decimals() -> None:
    assert occupancy(1, 3) == Decimal("33.33")
    assert occupancy(2, 3) == Decimal("66.67")
    assert occupancy(1, 8) == Decimal("12.50")
    assert occupancy(1, 16) == Decimal("6.25")
    assert occupancy(1, 32) == Decimal("3.13")  # 3.125 -> half up


def test_adr_is_none_never_zero_without_rooms_on_books() -> None:
    assert adr(0, 0) is None
    assert adr(12_345, 0) is None


def test_adr_rounds_half_up_to_two_decimals() -> None:
    assert adr(10_000, 3) == Decimal("33.33")
    assert adr(20_000, 3) == Decimal("66.67")
    assert adr(1, 2) == Decimal("0.01")  # 0.005 -> half up
    assert adr(0, 4) == Decimal("0.00")  # rooms are booked for free: ADR is 0.00, not missing


# --- J. fingerprint and versioning -------------------------------------------------------------


BASE = SnapshotContent(
    origin=SnapshotOrigin.OBSERVED,
    snapshot_local_date=date(2026, 3, 1),
    stay_date=date(2026, 3, 10),
    data_source_id=DATA_SOURCE,
    booking_count_on_books=2,
    rooms_on_books=3,
    allocated_room_revenue_on_books=Decimal("300.00"),
    rooms_available=10,
    occupancy_on_books=Decimal("30.00"),
    adr_on_books=Decimal("100.00"),
    uncertain_booking_count=0,
    uncertain_rooms=0,
)


def content(**overrides: Any) -> SnapshotContent:
    return replace(BASE, **overrides)


def test_identical_content_has_the_same_fingerprint_and_it_is_a_sha256() -> None:
    first, second = content().fingerprint(), content().fingerprint()

    assert first == second
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")


def test_two_decimal_spellings_of_one_value_are_the_same_content() -> None:
    assert content(adr_on_books=Decimal("100")).fingerprint() == content().fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"origin": SnapshotOrigin.RECONSTRUCTED_APPROXIMATE},
        {"snapshot_local_date": date(2026, 3, 2)},
        {"stay_date": date(2026, 3, 11)},
        {"data_source_id": UUID("00000000-0000-4000-8000-000000000002")},
        {"booking_count_on_books": 3},
        {"rooms_on_books": 4},
        {"allocated_room_revenue_on_books": Decimal("300.01")},
        {"rooms_available": 11},
        {"rooms_available": None},
        {"occupancy_on_books": Decimal("30.01")},
        {"adr_on_books": Decimal("100.01")},
        {"adr_on_books": None},
        {"uncertain_booking_count": 1, "uncertain_rooms": 1},
        {"uncertain_rooms": 2, "uncertain_booking_count": 1},
        {"calculation_version": "booking-snapshot-v2"},
    ],
)
def test_every_field_of_the_content_changes_the_fingerprint(change: dict[str, Any]) -> None:
    assert content(**change).fingerprint() != content().fingerprint()


def test_null_inventory_and_zero_inventory_are_different_content() -> None:
    a = content(rooms_available=None, occupancy_on_books=None)
    b = content(rooms_available=0, occupancy_on_books=None)

    assert a.fingerprint() != b.fingerprint()


def test_calculation_version_is_the_rules_version_not_the_application_version() -> None:
    assert CALCULATION_VERSION == "booking-snapshot-v1"
    assert content().calculation_version == CALCULATION_VERSION


def test_build_content_copies_inventory_and_derives_the_metrics() -> None:
    totals = DayTotals(booking_count=2, rooms=3, revenue_cents=30_000)

    built = build_content(
        origin=SnapshotOrigin.OBSERVED,
        snapshot_local_date=date(2026, 3, 1),
        stay_date=date(2026, 3, 10),
        data_source_id=DATA_SOURCE,
        totals=totals,
        rooms_available=10,
    )

    assert built == content()
    assert built.fingerprint() == content().fingerprint()


def test_runtime_metadata_is_not_part_of_the_content() -> None:
    """as_of_at, created_at and the row id are deliberately not fields of SnapshotContent."""
    fields = set(SnapshotContent.__dataclass_fields__)

    assert not {"as_of_at", "created_at", "id"} & fields
