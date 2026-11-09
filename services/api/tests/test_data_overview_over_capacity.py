"""Dati overview: more rooms on the books than the inventory has.

An occupancy over 100 % is a real figure of two things NINFA stores - the bookings and the room
inventory - that disagree. It may mean the inventory is too low, the hotel really is overbooked, or
a booking is wrong; NINFA cannot tell which, so it never hides the figure (no clamp) and never
turns it into a commercial decision: it says that the two disagree, and where to look.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.data_overview.metrics import is_over_capacity
from tests.data_overview_support import AS_OF, overview_of, overview_url, seed_run, uniform_nights
from tests.decision_api_support import authed_tenant
from tests.support import BookingFactory

D = Decimal


@pytest.mark.parametrize(
    ("rooms_on_books", "rooms_available", "expected"),
    [
        (11, 10, True),
        (10, 10, False),  # full is not over
        (0, 10, False),
        (5, None, False),  # no capacity known: nothing to compare with
        (1, 0, True),  # a closed night with a booking on it
        (0, 0, False),
    ],
)
def test_a_night_is_over_capacity_only_when_it_holds_more_rooms_than_exist(
    rooms_on_books: int, rooms_available: int | None, expected: bool
) -> None:
    assert is_over_capacity(rooms_on_books, rooms_available) is expected


def _nights_with_one_over(day_offset: int = 0) -> dict[date, tuple[int, int | None]]:
    nights = uniform_nights(AS_OF, rooms=5, capacity=10)
    nights[AS_OF + timedelta(days=day_offset)] = (11, 10)
    return nights


def test_eleven_rooms_on_ten_is_110_percent_it_is_not_clamped_and_it_is_flagged(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    seed_run(db_session, tenant, nights=_nights_with_one_over())

    occupancy = overview_of(db_session, tenant).occupancy

    over, regular = occupancy.nights[0], occupancy.nights[1]
    assert (over.rooms_on_books, over.rooms_available) == (11, 10)
    assert over.occupancy_pct == D("110.00")  # the stored figure, never cut to 100
    assert over.over_capacity is True
    assert regular.over_capacity is False
    assert occupancy.today is not None and occupancy.today.occupancy_pct == D("110.00")
    assert occupancy.inventory_consistency.over_capacity_nights == 1
    assert occupancy.inventory_consistency.first_night == AS_OF


def test_the_period_figure_keeps_the_excess_too(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    nights = uniform_nights(AS_OF, rooms=10, capacity=10)
    nights[AS_OF] = (14, 10)
    seed_run(db_session, tenant, nights=nights)

    occupancy = overview_of(db_session, tenant, period=7).occupancy

    assert occupancy.days_7 is not None
    # 14 + 6 x 10 rooms on 7 x 10: 74 / 70, over a hundred and not hidden
    assert occupancy.days_7.occupancy_pct == D("105.71")


def test_the_warning_looks_at_the_whole_observed_window_whatever_the_period_shown(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    seed_run(db_session, tenant, nights=_nights_with_one_over(day_offset=20))

    occupancy = overview_of(db_session, tenant, period=7).occupancy

    assert len(occupancy.nights) == 7
    assert not any(night.over_capacity for night in occupancy.nights)
    # the 7-day table has no such night, but the property does: the question stays asked
    assert occupancy.inventory_consistency.over_capacity_nights == 1
    assert occupancy.inventory_consistency.first_night == AS_OF + timedelta(days=20)


def test_a_night_with_no_known_capacity_is_never_over_it(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=50, capacity=None))

    occupancy = overview_of(db_session, tenant).occupancy

    assert occupancy.inventory_consistency.over_capacity_nights == 0
    assert occupancy.inventory_consistency.first_night is None
    assert not any(night.over_capacity for night in occupancy.nights)


def test_a_consistent_inventory_has_nothing_to_say(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=10, capacity=10))

    occupancy = overview_of(db_session, tenant).occupancy

    assert occupancy.inventory_consistency.over_capacity_nights == 0


def test_over_capacity_is_not_a_decision(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    seed_run(db_session, tenant, nights=_nights_with_one_over())

    overview = overview_of(db_session, tenant)

    assert overview.occupancy.inventory_consistency.over_capacity_nights == 1
    assert overview.decisions == ()
    assert not any(night.decision_id for night in overview.occupancy.nights)


def test_the_response_carries_the_flag_and_the_count_and_the_unclamped_figure(
    api_client: TestClient,
    factory: BookingFactory,
    db_session: Session,
    authenticated_as: Callable[[UUID], None],
) -> None:
    auth = authed_tenant(factory, authenticated_as)
    seed_run(db_session, auth.tenant, nights=_nights_with_one_over())

    body = api_client.get(overview_url(auth.tenant.property.id, AS_OF.isoformat())).json()

    first = body["occupancy"]["nights"][0]
    assert first["over_capacity"] is True and first["occupancy_pct"] == "110.00"
    assert body["occupancy"]["nights"][1]["over_capacity"] is False
    assert body["occupancy"]["inventory_consistency"] == {
        "over_capacity_nights": 1,
        "first_night": AS_OF.isoformat(),
    }
    assert body["decisions"] == []
