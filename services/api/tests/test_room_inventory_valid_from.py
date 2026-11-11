"""The day an inventory is valid from: the form's "Valido dal".

A hotel that starts with last month's costs needs last month's capacity too, so the number can be
said to hold from an earlier day. What is pinned: the nights from that day are written (the past
ones included), a day to come or one beyond the limit is refused, the limits are the backend's, the
same refresh as any save follows, and nothing already analysed is rewritten - the runs, and the
observations that copied their capacity when they were taken.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.analysis.queue import ANALYSIS_REFRESH_TASK
from app.modules.analysis.room_inventory import (
    INVENTORY_HORIZON_DAYS,
    MAX_BACKFILL_DAYS,
    InventoryDateError,
    RoomInventoryService,
)
from app.modules.decisions.models import DecisionRun
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily
from tests.data_overview_support import seed_run, uniform_nights
from tests.data_sources_support import SourcesEnv, import_ok, sources_env
from tests.support import BookingFactory

NOON = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)  # 12:00 in Rome
TODAY = date(2026, 11, 9)
OCTOBER_FIRST = date(2026, 10, 1)


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _url(property_id: UUID) -> str:
    return f"/api/v1/properties/{property_id}/room-inventory"


def _rome_today() -> date:
    return datetime.now(ZoneInfo("Europe/Rome")).date()


def _put(client: TestClient, env: SourcesEnv, rooms: int, valid_from: Any) -> Any:
    return client.put(
        _url(env.property.id), json={"rooms_available": rooms, "valid_from": valid_from}
    )


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
                "SELECT status::text FROM procrastinate_jobs "
                "WHERE task_name = :t AND args ->> 'property_id' = :p ORDER BY id"
            ),
            {"t": ANALYSIS_REFRESH_TASK, "p": str(property_id)},
        ).all()
    )


# --- the service ---------------------------------------------------------------------------------


def test_a_valid_from_in_the_past_writes_those_nights_too_and_the_state_says_since_when(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    saved = RoomInventoryService(db_session, tenant.context).save(
        tenant.property.id, 10, NOON, valid_from=OCTOBER_FIRST
    )

    nights = _nights(db_session, tenant.property.id)
    assert min(nights) == OCTOBER_FIRST
    assert max(nights) == TODAY + timedelta(days=INVENTORY_HORIZON_DAYS - 1)
    assert set(nights.values()) == {10}
    # the 39 nights from 1 October to 8 November, and every night from today on
    assert saved.changed_nights == 39 + INVENTORY_HORIZON_DAYS
    assert saved.state.known_since == OCTOBER_FIRST
    # what is configured "from today on" is still read from today
    assert saved.state.first_night == TODAY
    assert saved.state.rooms_available == 10


def test_the_state_gives_the_limits_of_the_next_save_in_the_property_own_days(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    state = RoomInventoryService(db_session, tenant.context).state(tenant.property.id, NOON)

    assert state.today == TODAY
    assert state.earliest_valid_from == TODAY - timedelta(days=MAX_BACKFILL_DAYS)
    assert state.known_since is None


def test_a_valid_from_of_today_is_what_no_valid_from_has_always_meant(
    db_session: Session, factory: BookingFactory
) -> None:
    first, second = factory.tenant(), factory.tenant()

    RoomInventoryService(db_session, first.context).save(first.property.id, 12, NOON)
    RoomInventoryService(db_session, second.context).save(
        second.property.id, 12, NOON, valid_from=TODAY
    )

    assert (
        _nights(db_session, first.property.id).keys()
        == _nights(db_session, second.property.id).keys()
    )


def test_a_valid_from_after_today_is_refused_and_nothing_is_written(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()

    with pytest.raises(InventoryDateError) as refused:
        RoomInventoryService(db_session, tenant.context).save(
            tenant.property.id, 10, NOON, valid_from=TODAY + timedelta(days=1)
        )

    assert refused.value.reason == "in_future"
    assert refused.value.status_code == 422
    assert _nights(db_session, tenant.property.id) == {}


def test_a_valid_from_older_than_the_limit_is_refused_and_the_limit_itself_is_accepted(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = factory.tenant()
    service = RoomInventoryService(db_session, tenant.context)
    oldest = TODAY - timedelta(days=MAX_BACKFILL_DAYS)

    with pytest.raises(InventoryDateError) as refused:
        service.save(tenant.property.id, 10, NOON, valid_from=oldest - timedelta(days=1))
    assert refused.value.reason == "too_old"
    assert _nights(db_session, tenant.property.id) == {}

    service.save(tenant.property.id, 10, NOON, valid_from=oldest)
    assert min(_nights(db_session, tenant.property.id)) == oldest


def test_a_retroactive_inventory_rewrites_no_observation_and_no_run(
    db_session: Session, factory: BookingFactory
) -> None:
    """What was analysed stays exactly what it was: the nights before today are new rows, the stored
    observation copied its capacity when it was taken, and the runs are not touched at all."""
    tenant = factory.tenant()
    seed_run(db_session, tenant, as_of=TODAY, nights=uniform_nights(TODAY, rooms=5, capacity=None))

    def observed() -> tuple[dict[Any, tuple[Any, ...]], dict[Any, tuple[Any, ...]]]:
        db_session.expire_all()
        snapshots = db_session.scalars(
            select(BookingSnapshot).where(BookingSnapshot.property_id == tenant.property.id)
        ).all()
        runs = db_session.scalars(
            select(DecisionRun).where(DecisionRun.property_id == tenant.property.id)
        ).all()
        return (
            {
                row.id: (row.content_fingerprint, row.rooms_available, row.revision)
                for row in snapshots
            },
            {run.id: (run.as_of_local_date, run.run_sequence) for run in runs},
        )

    before_snapshots, before_runs = observed()
    assert len(before_snapshots) == 30 and len(before_runs) == 1
    assert all(rooms is None for _, rooms, _ in before_snapshots.values())

    RoomInventoryService(db_session, tenant.context).save(
        tenant.property.id, 10, NOON, valid_from=OCTOBER_FIRST
    )

    assert observed() == (before_snapshots, before_runs)


# --- the API -------------------------------------------------------------------------------------


def test_the_api_takes_a_valid_from_and_says_since_when_it_knows(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    valid_from = _rome_today() - timedelta(days=40)

    response = _put(api_client, env, 10, valid_from.isoformat())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["known_since"] == valid_from.isoformat()
    assert body["today"] == _rome_today().isoformat()
    assert (
        body["earliest_valid_from"]
        == (_rome_today() - timedelta(days=MAX_BACKFILL_DAYS)).isoformat()
    )
    assert min(_nights(db_session, env.property.id)) == valid_from
    assert api_client.get(_url(env.property.id)).json()["known_since"] == valid_from.isoformat()


def test_a_null_valid_from_is_today(api_client: TestClient, env: SourcesEnv) -> None:
    response = _put(api_client, env, 10, None)

    assert response.status_code == 200
    assert response.json()["known_since"] == _rome_today().isoformat()


@pytest.mark.parametrize("valid_from", ["yesterday", "20261031", "2026-13-40", 20261031, True, ""])
def test_a_valid_from_that_is_not_a_day_is_refused_before_it_reaches_the_service(
    api_client: TestClient, env: SourcesEnv, db_session: Session, valid_from: Any
) -> None:
    response = _put(api_client, env, 10, valid_from)

    assert response.status_code == 422
    assert _nights(db_session, env.property.id) == {}


def test_a_valid_from_after_today_is_a_422_with_its_limits_and_writes_nothing(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    response = _put(api_client, env, 10, (_rome_today() + timedelta(days=1)).isoformat())

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "room_inventory_invalid_valid_from"
    assert error["details"]["reason"] == "in_future"
    assert error["details"]["latest"] == _rome_today().isoformat()
    assert _nights(db_session, env.property.id) == {}


def test_a_past_valid_from_asks_for_the_same_refresh_any_save_asks_for(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    import_ok(api_client, env, "BOOKINGS")
    api_client.put(_url(env.property.id), json={"rooms_available": 24})
    db_session.execute(
        text("DELETE FROM procrastinate_jobs WHERE args ->> 'property_id' = :p"),
        {"p": str(env.property.id)},
    )

    # the same number, from an earlier day: new nights, and so a refresh that can use them
    body = _put(api_client, env, 24, (_rome_today() - timedelta(days=30)).isoformat()).json()

    assert body["changed_nights"] == 30
    assert body["analysis_requested"] is True
    assert _refresh_jobs(db_session, env.property.id) == [("todo",)]
