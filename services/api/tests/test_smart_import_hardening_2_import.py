"""Smart Import V3 - deterministic hardening 2, all the way to the database.

What NINFA now understands of the five files (`test_smart_import_hardening_2.py`) is also what the
import reads: the same rows, the same hours, the same dates - through the real routes, the real
dry run and the real importers - and what it refuses to understand is not imported either.
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking
from app.modules.labor.models import LaborEntry
from tests.data_sources_support import SourcesEnv, sources_env
from tests.hardening_support import (
    BOOKING_HEADER,
    PEOPLE,
    booking_row,
    staff,
    xlsx,
    xlsx_sheets,
)
from tests.smart_import_support import import_mapped, understand, validation
from tests.support import BookingFactory


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def test_hours_written_with_their_unit_are_imported_as_hours(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    header = ["Data", "Dipendente", "Reparto", "Ore previste", "Ore effettive"]
    content = xlsx(staff(header, days=2, planned="8 h", worked="7,5 ore"))

    body = understand(api_client, env, "LABOR", "turni.xlsx", content)

    assert body["understanding"]["level"] == "READY"
    tried = validation(api_client, env, "LABOR", content, body["proposal"], name="turni.xlsx")
    assert tried["rows_total"] == 12 and tried["rows_invalid"] == 0 and tried["can_import"] is True
    done = import_mapped(api_client, env, "LABOR", "turni.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    entries = list(db_session.scalars(select(LaborEntry)))
    assert len(entries) == 12
    assert {e.planned_minutes for e in entries} == {480}
    assert {e.actual_minutes for e in entries} == {450}


ITALIAN_MONTHS = (
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre"
)


def _written(moment: datetime) -> str:
    return f"{moment.day} {ITALIAN_MONTHS.split()[moment.month - 1]} {moment.year}"


def test_dates_with_the_month_written_as_a_name_are_imported_with_the_right_dates(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    expected = {}
    for index in range(15):
        base = booking_row(index)
        expected[base[0]] = (base[2].date(), base[3].date())
        rows.append([base[0], _written(base[1]), _written(base[2]), _written(base[3]), *base[4:]])
    content = xlsx(rows)

    body = understand(api_client, env, "BOOKINGS", "pren.xlsx", content)

    tried = validation(api_client, env, "BOOKINGS", content, body["proposal"], name="pren.xlsx")
    assert tried["rows_total"] == 15 and tried["rows_invalid"] == 0 and tried["can_import"] is True
    done = import_mapped(api_client, env, "BOOKINGS", "pren.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    imported = {
        b.source_record_id: (b.check_in, b.check_out) for b in db_session.scalars(select(Booking))
    }
    assert imported == expected


def test_two_sheets_with_prev_and_eff_are_imported_as_one_table_by_department(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    header = ["Giorno", "Nome", "Reparto", "Prev.", "Eff."]
    sheets = {}
    for sheet, people in (("Turni Cucina", PEOPLE[:3]), ("Turni Sala", PEOPLE[3:])):
        body_rows = staff(header, people=people, days=3)
        sheets[sheet] = [
            [f"ORE {sheet.split()[1].upper()} - SETTIMANA 43", "", "", ""],
            [],
            *[[r[0], r[1], r[3], r[4]] for r in body_rows],
        ]
    content = xlsx_sheets(sheets, merges={name: ["A1:D1"] for name in sheets})

    body = understand(api_client, env, "LABOR", "turni.xlsx", content)

    assert body["understanding"]["level"] == "READY"
    tried = validation(api_client, env, "LABOR", content, body["proposal"], name="turni.xlsx")
    assert tried["rows_total"] == 18 and tried["rows_invalid"] == 0 and tried["can_import"] is True
    done = import_mapped(api_client, env, "LABOR", "turni.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    entries = list(db_session.scalars(select(LaborEntry)))
    assert len(entries) == 18
    assert len({e.labor_category for e in entries}) == 2  # the department is the sheet
    assert {e.planned_minutes for e in entries} == {480} and {
        e.actual_minutes for e in entries
    } == {450}


def test_a_lone_total_confirmed_by_the_person_is_imported_as_the_room_revenue(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    header = [
        "Res.ID",
        "Booking date",
        "Check-in",
        "Check-out",
        "Channel",
        "Status",
        "Rooms",
        "Total",
    ]
    rows: list[list[object]] = [list(header)]
    amounts = {}
    for index in range(14):
        base = booking_row(index)
        amounts[base[0]] = Decimal(f"{237 + 10 * index}.50")
        rows.append(
            [
                base[0],
                base[1],
                base[2],
                base[3],
                "Booking.com",
                "Confirmed",
                1,
                float(amounts[base[0]]),
            ]
        )
    content = xlsx(rows)

    asked = understand(api_client, env, "BOOKINGS", "pren.xlsx", content)
    assert asked["understanding"]["level"] == "ASK"  # one confirmation: never decided silently
    body = understand(
        api_client,
        env,
        "BOOKINGS",
        "pren.xlsx",
        content,
        {"column_fields": {"Total": "room_revenue"}},
    )

    assert body["understanding"]["level"] == "READY"
    tried = validation(api_client, env, "BOOKINGS", content, body["proposal"], name="pren.xlsx")
    assert tried["rows_invalid"] == 0 and tried["can_import"] is True
    done = import_mapped(api_client, env, "BOOKINGS", "pren.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    assert {
        b.source_record_id: b.room_revenue for b in db_session.scalars(select(Booking))
    } == amounts


def test_a_file_with_every_arrival_after_its_departure_is_asked_about_and_cannot_be_imported(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    for index in range(14):
        base = booking_row(index)
        rows.append(
            [base[0], base[1], base[3], base[2], *base[4:]]
        )  # the arrival is the later date
    content = xlsx(rows)

    body = understand(api_client, env, "BOOKINGS", "pren.xlsx", content)

    assert body["understanding"]["level"] == "ASK"
    assert [q["kind"] for q in body["understanding"]["questions"]][0] == "DATES_REVERSED"
    # nothing was swapped for the person: the decision still reads the headers as they are
    assert {c["header"]: c["field"] for c in body["proposal"]["columns"]}["Arrivo"] == "check_in"
    tried = validation(api_client, env, "BOOKINGS", content, body["proposal"], name="pren.xlsx")
    assert (
        tried["can_import"] is False and tried["rows_valid"] == 0
    )  # the importer refuses them too
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 0
