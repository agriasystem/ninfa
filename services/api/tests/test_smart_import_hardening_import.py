"""Smart Import V3 - deterministic hardening 1, all the way to the database.

The tests of `test_smart_import_hardening.py` say what NINFA understands. These say that what it
understands is also what the import reads: the same rows, in the same places, through the real
routes, the real dry run and the real importers.
"""

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking
from app.modules.invoices.models import Invoice, InvoiceLine
from tests.data_sources_support import SourcesEnv, sources_env
from tests.hardening_support import BOOKING_HEADER, booking_row, costs, with_weekday, xlsx
from tests.smart_import_support import (
    by_header,
    import_mapped,
    inspection,
    understand,
    validation,
)
from tests.support import BookingFactory


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def test_bookings_with_the_weekday_before_the_dates_are_imported_with_the_right_dates(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [list(BOOKING_HEADER)]
    expected = {}
    for index in range(15):
        base = booking_row(index)
        expected[base[0]] = (base[2].date(), base[3].date())
        rows.append(
            [base[0], base[1], with_weekday(base[2]), with_weekday(base[3], long=True), *base[4:]]
        )
    content = xlsx(rows)

    body = understand(api_client, env, "BOOKINGS", "pren.xlsx", content)

    assert by_header(body)["Arrivo"]["field"] == "check_in"
    assert by_header(body)["Partenza"]["field"] == "check_out"
    tried = validation(api_client, env, "BOOKINGS", content, body["proposal"], name="pren.xlsx")
    assert tried["rows_total"] == 15 and tried["rows_invalid"] == 0 and tried["can_import"] is True
    done = import_mapped(api_client, env, "BOOKINGS", "pren.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    imported = {
        b.source_record_id: (b.check_in, b.check_out) for b in db_session.scalars(select(Booking))
    }
    assert imported == expected


def test_a_printed_list_with_page_breaks_is_imported_whole(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [["ELENCO PRENOTAZIONI (stampa)"], [], list(BOOKING_HEADER)]
    for index in range(24):
        if index and index % 8 == 0:
            rows += [["--- pagina successiva ---"], list(BOOKING_HEADER)]
        rows.append(booking_row(index))
    content = xlsx(rows)

    body = understand(api_client, env, "BOOKINGS", "stampa.xlsx", content)

    assert body["understanding"]["document"]["table"]["data_rows"] == 24
    tried = validation(api_client, env, "BOOKINGS", content, body["proposal"], name="stampa.xlsx")
    assert (
        tried["rows_total"] == 24 and tried["rows_invalid"] == 0
    )  # the import reads what was said
    done = import_mapped(api_client, env, "BOOKINGS", "stampa.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    assert len(list(db_session.scalars(select(Booking)))) == 24


def test_amounts_written_with_the_currency_are_imported_as_the_amount(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    amounts = [Decimal(1000 + 25 * i) for i in range(12)]
    rows = costs(
        ["Imponibile"],
        [(f"{a:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", "."),) for a in amounts],
    )
    content = xlsx(rows)

    body = understand(api_client, env, "COSTS", "costi.xlsx", content)

    assert by_header(body)["Imponibile"]["field"] == "line_total"
    tried = validation(api_client, env, "COSTS", content, body["proposal"], name="costi.xlsx")
    assert tried["rows_total"] == 12 and tried["rows_invalid"] == 0
    done = import_mapped(api_client, env, "COSTS", "costi.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    lines = sorted(line.line_total for line in db_session.scalars(select(InvoiceLine)))
    assert lines == sorted(amounts)
    assert len(list(db_session.scalars(select(Invoice)))) == 12


def test_no_name_reaches_the_browser_whatever_the_header_says(
    api_client: TestClient, env: SourcesEnv
) -> None:
    people = ["Giulia Ferretti", "Marco Rinaldi", "Elena Orlandi", "Davide Dallari"]
    rows: list[list[object]] = [["Data", "Addetto", "Ore previste", "Ore effettive"]]
    for day in range(1, 7):
        for person in people:
            rows.append([f"{day:02d}/11/2026", person, "8", "7,5"])
    content = xlsx(rows)

    body = understand(api_client, env, "LABOR", "turni.xlsx", content)

    assert by_header(body)["Addetto"]["not_used_reason"] == "PERSON"
    assert by_header(body)["Addetto"]["examples"] == []
    text = repr(body)
    assert not any(person in text for person in people)


def test_an_email_in_a_free_column_is_replaced_by_the_gate_of_the_route(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [["Data", "Reparto", "Ore previste", "Ore effettive", "Annotazioni"]]
    for day in range(1, 8):
        rows.append(
            [f"{day:02d}/11/2026", "Reception", "8", "7,5", "scrivere a anna.verdi@example.org"]
        )
    content = xlsx(rows)

    body = understand(api_client, env, "LABOR", "turni.xlsx", content)

    assert "anna.verdi@example.org" not in repr(body)


@pytest.mark.parametrize("header", ["Nome dipendente", "Addetto"])
def test_the_plain_matching_screen_shows_no_name_either(
    api_client: TestClient, env: SourcesEnv, header: str
) -> None:
    people = ["Giulia Ferretti", "Marco Rinaldi", "Elena Orlandi", "Davide Dallari"]
    rows: list[list[object]] = [["Data", header, "Reparto", "Ore previste", "Ore effettive"]]
    for day in range(1, 5):
        for person in people:
            rows.append([f"{day:02d}/11/2026", person, "Reception", "8", "7,5"])

    body = inspection(api_client, env, "LABOR", "turni.xlsx", xlsx(rows))

    assert by_header(body)[header]["examples"] == []
    assert not any(person in repr(body) for person in people)
    assert (
        by_header(body)["Reparto"]["examples"] == ["Reception"] * 3
    )  # a department is still shown
