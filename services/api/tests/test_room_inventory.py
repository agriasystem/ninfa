"""How many rooms a property can sell, from the form to the occupancy on the page.

Through the real API and database. What is pinned: one number becomes the nights the backend reads,
no night already gone is touched, no stored observation is rewritten, a foreign property is the
usual 404, and the occupancy follows by itself, with the same job an import asks for.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.modules.analysis.queue import ANALYSIS_REFRESH_TASK
from app.modules.analysis.room_inventory import (
    INVENTORY_HORIZON_DAYS,
    MAX_BACKFILL_DAYS,
    MAX_ROOMS,
    MIN_ROOMS,
    RoomInventoryService,
)
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import CapacityState
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily
from app.modules.snapshots.repository import RoomInventoryRepository
from tests.analysis_policy_support import import_at
from tests.data_sources_support import SourcesEnv, import_ok, sources_env
from tests.decision_api_support import authed_tenant
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel
from tests.refresh_support import purge as purge_hotel
from tests.support import BookingFactory

NOON = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)  # 12:00 in Rome
TODAY = date(2026, 11, 9)


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _url(property_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/room-inventory"


def _put(client: TestClient, env: SourcesEnv, rooms: Any) -> Any:
    return client.put(_url(env.property.id), json={"rooms_available": rooms})


def _nights(session: Session, property_id: UUID) -> dict[date, int]:
    session.expire_all()
    rows = session.execute(
        select(RoomInventoryDaily.stay_date, RoomInventoryDaily.rooms_available).where(
            RoomInventoryDaily.property_id == property_id
        )
    ).all()
    return {stay_date: rooms for stay_date, rooms in rows}


def _refresh_jobs(session: Session, property_id: UUID) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT status::text, args FROM procrastinate_jobs "
                "WHERE task_name = :t AND args ->> 'property_id' = :p ORDER BY id"
            ),
            {"t": ANALYSIS_REFRESH_TASK, "p": str(property_id)},
        ).all()
    )


# --- nothing configured --------------------------------------------------------------------------


def test_a_property_with_no_inventory_says_so_and_gives_the_limits(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = api_client.get(_url(env.property.id))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    # the limits of the next save are the property's own days: the page works none of them out
    assert body.pop("today") == datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    assert (
        body.pop("earliest_valid_from")
        == (
            datetime.now(ZoneInfo("Europe/Rome")).date() - timedelta(days=MAX_BACKFILL_DAYS)
        ).isoformat()
    )
    assert body == {
        "configured": False,
        "rooms_available": None,
        "varies": False,
        "first_night": None,
        "last_night": None,
        "known_since": None,
        "min_rooms": MIN_ROOMS,
        "max_rooms": MAX_ROOMS,
    }


def test_an_inventory_only_of_nights_gone_is_not_a_configured_inventory(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    RoomInventoryRepository(db_session, tenant.context).set_for_date(
        tenant.property.id, TODAY - timedelta(days=1), rooms_available=10
    )

    state = RoomInventoryService(db_session, tenant.context).state(tenant.property.id, NOON)

    assert state.configured is False and state.rooms_available is None


# --- saving --------------------------------------------------------------------------------------


def test_one_number_becomes_every_night_from_today_on(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    saved = RoomInventoryService(db_session, tenant.context).save(tenant.property.id, 24, NOON)

    nights = _nights(db_session, tenant.property.id)
    assert saved.changed_nights == len(nights) == INVENTORY_HORIZON_DAYS
    assert min(nights) == TODAY
    assert max(nights) == TODAY + timedelta(days=INVENTORY_HORIZON_DAYS - 1)
    assert set(nights.values()) == {24}
    assert saved.state.configured and saved.state.rooms_available == 24
    assert saved.state.varies is False
    assert (saved.state.first_night, saved.state.last_night) == (min(nights), max(nights))


def test_today_is_the_propertys_own_day(db_session: Session, factory: BookingFactory) -> None:
    tenant = factory.tenant()
    tenant.property.timezone = "Asia/Tokyo"
    db_session.flush()

    # 20:00 UTC on the 9th is already the 10th in Tokyo
    saved = RoomInventoryService(db_session, tenant.context).save(
        tenant.property.id, 12, datetime(2026, 11, 9, 20, 0, tzinfo=UTC)
    )

    assert saved.state.first_night == date(2026, 11, 10)


def test_the_api_saves_the_number_and_reads_it_back(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response = _put(api_client, env, 24)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True and body["rooms_available"] == 24
    assert body["changed_nights"] == INVENTORY_HORIZON_DAYS
    # No bookings yet: nothing to analyse, and no job waiting for nothing.
    assert body["analysis_requested"] is False
    assert api_client.get(_url(env.property.id)).json()["rooms_available"] == 24


@pytest.mark.parametrize("rooms", [0, -1, MAX_ROOMS + 1, 1.5, "24", None, True])
def test_a_number_that_is_not_a_capacity_is_refused_and_nothing_is_written(
    api_client: TestClient, env: SourcesEnv, db_session: Session, rooms: Any
) -> None:
    response = _put(api_client, env, rooms)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _nights(db_session, env.property.id) == {}


def test_a_field_nobody_asked_for_is_refused(api_client: TestClient, env: SourcesEnv) -> None:
    response = api_client.put(
        _url(env.property.id),
        json={"rooms_available": 24, "first_night": "2020-01-01"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("rooms", [MIN_ROOMS, MAX_ROOMS])
def test_the_limits_themselves_are_accepted(
    api_client: TestClient, env: SourcesEnv, rooms: int
) -> None:
    assert _put(api_client, env, rooms).status_code == 200


def test_the_service_refuses_what_the_route_refuses(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    with pytest.raises(ValueError):
        RoomInventoryService(db_session, tenant.context).save(tenant.property.id, 0, NOON)


# --- modifying -----------------------------------------------------------------------------------


def test_a_change_counts_from_today_and_no_night_gone_is_touched(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    service = RoomInventoryService(db_session, tenant.context)
    service.save(tenant.property.id, 24, NOON - timedelta(days=10))

    saved = service.save(tenant.property.id, 30, NOON)

    nights = _nights(db_session, tenant.property.id)
    assert nights[TODAY - timedelta(days=10)] == 24
    assert nights[TODAY - timedelta(days=1)] == 24
    assert nights[TODAY] == 30
    assert saved.state.rooms_available == 30
    assert saved.changed_nights == INVENTORY_HORIZON_DAYS


def test_the_same_number_again_changes_nothing_and_asks_for_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    _put(api_client, env, 24)
    before = _refresh_jobs(db_session, env.property.id)

    body = _put(api_client, env, 24).json()

    assert body["changed_nights"] == 0 and body["analysis_requested"] is False
    assert _refresh_jobs(db_session, env.property.id) == before


def test_rooms_out_of_order_said_by_an_operator_stay(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    RoomInventoryRepository(db_session, tenant.context).set_for_date(
        tenant.property.id, TODAY, rooms_available=20, rooms_out_of_order=2
    )

    RoomInventoryService(db_session, tenant.context).save(tenant.property.id, 24, NOON)

    db_session.expire_all()
    row = RoomInventoryRepository(db_session, tenant.context).get_for_date(
        tenant.property.id, TODAY
    )
    assert row is not None and (row.rooms_available, row.rooms_out_of_order) == (24, 2)


def test_nights_set_per_period_are_shown_as_varying_and_never_averaged(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    inventory = RoomInventoryRepository(db_session, tenant.context)
    for offset, rooms in enumerate((20, 20, 18)):
        inventory.set_for_date(
            tenant.property.id, TODAY + timedelta(days=offset), rooms_available=rooms
        )

    state = RoomInventoryService(db_session, tenant.context).state(tenant.property.id, NOON)

    assert state.configured and state.varies
    assert state.rooms_available == 20  # the first night's, not a mean


def test_a_gap_in_the_nights_is_shown_as_varying(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    inventory = RoomInventoryRepository(db_session, tenant.context)
    inventory.set_for_date(tenant.property.id, TODAY, rooms_available=20)
    inventory.set_for_date(tenant.property.id, TODAY + timedelta(days=5), rooms_available=20)

    state = RoomInventoryService(db_session, tenant.context).state(tenant.property.id, NOON)

    assert state.varies


def test_saving_a_single_number_over_varying_nights_makes_them_uniform(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    inventory = RoomInventoryRepository(db_session, tenant.context)
    inventory.set_for_date(tenant.property.id, TODAY, rooms_available=20)
    inventory.set_for_date(tenant.property.id, TODAY + timedelta(days=1), rooms_available=18)
    service = RoomInventoryService(db_session, tenant.context)

    saved = service.save(tenant.property.id, 20, NOON)

    assert saved.state.varies is False and saved.state.rooms_available == 20


# --- tenancy -------------------------------------------------------------------------------------


def test_a_property_of_another_workspace_is_the_usual_404(
    api_client: TestClient,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    foreign = factory.tenant()
    authed_tenant(factory, authenticated_as)

    for response in (
        api_client.get(_url(foreign.property.id)),
        api_client.put(_url(foreign.property.id), json={"rooms_available": 24}),
    ):
        assert response.status_code == 404
    assert _nights(db_session, foreign.property.id) == {}


def test_an_unknown_property_is_the_same_404(api_client: TestClient, env: SourcesEnv) -> None:
    assert api_client.get(_url(uuid4())).status_code == 404


def test_the_service_refuses_a_property_of_another_tenant(
    db_session: Session, factory: BookingFactory
) -> None:
    mine, other = factory.tenant(), factory.tenant()

    with pytest.raises(Exception, match="Property"):
        RoomInventoryService(db_session, mine.context).save(other.property.id, 24, NOON)
    assert _nights(db_session, other.property.id) == {}


def test_one_propertys_save_touches_no_other(db_session: Session, factory: BookingFactory) -> None:
    first, second = factory.tenant(), factory.tenant()

    RoomInventoryService(db_session, first.context).save(first.property.id, 24, NOON)

    assert _nights(db_session, second.property.id) == {}


# --- the analysis follows ------------------------------------------------------------------------


def test_saving_with_bookings_asks_for_the_same_job_an_import_asks_for(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    db_session.execute(
        text("DELETE FROM procrastinate_jobs WHERE args ->> 'property_id' = :p"),
        {"p": str(env.property.id)},
    )

    body = _put(api_client, env, 24).json()

    assert body["analysis_requested"] is True
    [job] = _refresh_jobs(db_session, env.property.id)
    assert job[0] == "todo"
    assert job[1] == {"workspace_id": str(env.workspace.id), "property_id": str(env.property.id)}


def test_a_refresh_that_cannot_be_queued_does_not_undo_the_inventory(
    db_session: Session, factory: BookingFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from app.modules.analysis import room_inventory as module

    tenant = factory.tenant()
    import_at(factory, tenant.data_source, NOON - timedelta(hours=1))

    def broken(*args: Any, **kwargs: Any) -> None:
        raise SQLAlchemyError("queue unavailable")

    monkeypatch.setattr(module, "enqueue_refresh", broken)

    saved = RoomInventoryService(db_session, tenant.context).save(tenant.property.id, 24, NOON)

    assert saved.analysis_requested is False
    assert saved.state.rooms_available == 24


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Path) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge_hotel(db_engine, built.tenant.workspace_id)


def _occupancy(hotel: Hotel) -> Any:
    with hotel.session() as session:
        return (
            DataOverviewService(session, hotel.tenant)
            .overview(hotel.property_id, local_today(), 30)
            .occupancy
        )


def test_the_whole_way_from_saving_to_the_occupancy_on_the_page(hotel: Hotel) -> None:
    """Bookings and an analysis with no capacity; the number is saved; the refresh that asks for
    runs with real commits; the occupancy is there, and the observation before it is still what it
    was."""
    hotel.import_bookings(
        "a.csv", [booking_row("R-1", 0), booking_row("R-2", 1), booking_row("R-3", 1)]
    )
    hotel.refresh()
    before = _occupancy(hotel)
    assert before.selected.capacity is CapacityState.MISSING
    assert before.selected.occupancy_pct is None
    room_nights = before.selected.room_nights
    assert room_nights == 3
    with hotel.session() as session:
        first_revision = session.scalars(
            select(BookingSnapshot).where(
                BookingSnapshot.property_id == hotel.property_id, BookingSnapshot.revision == 1
            )
        ).all()
        assert first_revision and all(row.rooms_available is None for row in first_revision)
        kept = {row.id: row.content_fingerprint for row in first_revision}

    with hotel.session() as session:
        saved = RoomInventoryService(session, hotel.tenant).save(hotel.property_id, 10)
    assert saved.analysis_requested is True

    # Saved, and not analysed yet: the page says the capacity is on its way, not that it is missing.
    assert _occupancy(hotel).selected.capacity is CapacityState.AWAITING_ANALYSIS

    outcome = hotel.refresh()
    assert outcome.result is not None

    after = _occupancy(hotel)
    assert after.selected.capacity is CapacityState.KNOWN
    assert after.selected.room_nights == room_nights  # nothing else moved
    assert after.selected.rooms_available == 300  # 10 rooms x 30 nights
    assert after.selected.occupancy_pct == 1
    assert after.days_7.occupancy_pct is not None
    assert after.today.rooms_available == 10
    assert {night.rooms_available for night in after.nights} == {10}

    # Nothing already observed was rewritten: the day has a next revision, and the first stays.
    with hotel.session() as session:
        still = session.scalars(
            select(BookingSnapshot).where(BookingSnapshot.id.in_(list(kept)))
        ).all()
        assert {row.id: row.content_fingerprint for row in still} == kept
        assert all(row.rooms_available is None for row in still)
        newest = session.scalar(
            select(func.max(BookingSnapshot.revision)).where(
                BookingSnapshot.property_id == hotel.property_id
            )
        )
        assert newest == 2
