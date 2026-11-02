"""A bookings export need not count rooms: with no such column, one row is one room.

The field the engine used to demand was `Booking.rooms`, the rooms OF A BOOKING, which every export
that writes one room per line simply leaves out. The rooms OF THE HOTEL are the room inventory
(property data, `RoomInventoryDaily`): no file has to provide them and none is read for them, not
even a "Camere struttura: 32" written above the table.

What is pinned here: a valid file with no such column is READY and imports; a column that counts
them still wins; a column that MIGHT be it keeps the question open; nothing of this turns another
kind of file, or an unknown status, into an automatic import.

The rows are a minimal synthetic fixture of "a valid booking, no room count": no real data.
"""

import io
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking
from app.modules.data_sources.domain_adapters import BookingsDomain
from app.modules.data_sources.understanding import _meaning_of_absent_columns
from app.modules.snapshots.models import RoomInventoryDaily
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import csv_bytes, import_mapped, understand
from tests.support import BookingFactory

HEADER = [
    "Codice prenotazione",
    "Ospite principale",
    "Email",
    "Telefono",
    "Data prenotazione",
    "Check-in",
    "Check-out",
    "Tipologia camera",
    "Canale",
    "Ricavo camere",
    "Stato",
]
GUEST = "Mario Esempio"
EMAIL = "mario.esempio@example.com"
PHONE = "+39 333 0000000"


def _rows(status: str = "Confermata") -> list[list[str]]:
    rows = []
    for index in range(1, 7):
        rows.append(
            [
                f"AUR-{index:03d}",
                GUEST,
                EMAIL,
                PHONE,
                "01/10/2026",
                f"{10 + index}/11/2026",
                f"{12 + index}/11/2026",
                "Doppia",
                "Booking.com" if index % 2 else "Sito diretto",
                f"{100 + index},50",
                status,
            ]
        )
    return rows


def _csv(status: str = "Confermata") -> bytes:
    return csv_bytes([HEADER, *_rows(status)], delimiter=";", bom=True)


def _xlsx_like_a_front_desk_keeps_it() -> bytes:
    """A title, a block of facts about the hotel, then the table; a summary on a second sheet."""
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Prenotazioni"
    sheet.append(["REGISTRO PRENOTAZIONI | Hotel Esempio"])
    sheet.append(["Struttura: Hotel Esempio", "Periodo: novembre 2026", "Camere struttura: 32"])
    sheet.append([])
    sheet.append(HEADER)
    for row in _rows():
        sheet.append(row)
    summary = book.create_sheet("Riepilogo")
    summary.append(["Indicatore", "Valore"])
    summary.append(["Prenotazioni", 6])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _ready(body: dict[str, Any]) -> dict[str, Any]:
    understanding: dict[str, Any] = body["understanding"]
    assert understanding["level"] == "READY", understanding
    assert understanding["questions"] == []
    assert understanding["blockers"] == []
    return understanding


def test_a_valid_file_with_no_room_count_is_ready_and_says_what_it_assumed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(api_client, env, "BOOKINGS", "prenotazioni.csv", _csv())

    understanding = _ready(body)

    assert body["proposal"]["constants"] == {"rooms": 1}
    assert understanding["assumed"] == ["rooms"]
    # what the file does not say is not something NINFA read from it
    assert "rooms" not in {item["field"] for item in understanding["recognized"]}


def test_the_rooms_of_the_hotel_written_above_the_table_are_read_as_nothing(
    api_client: TestClient, env: SourcesEnv
) -> None:
    body = understand(
        api_client, env, "BOOKINGS", "prenotazioni.xlsx", _xlsx_like_a_front_desk_keeps_it()
    )

    _ready(body)

    assert body["proposal"]["constants"] == {"rooms": 1}  # never 32


def test_the_import_succeeds_with_one_room_a_row_and_writes_no_room_inventory(
    api_client: TestClient, env: SourcesEnv, db_session: Session
) -> None:
    content = _xlsx_like_a_front_desk_keeps_it()
    proposal = understand(api_client, env, "BOOKINGS", "p.xlsx", content)["proposal"]

    response = import_mapped(api_client, env, "BOOKINGS", "p.xlsx", content, proposal)

    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] is True
    bookings = db_session.scalars(
        select(Booking).where(Booking.workspace_id == env.workspace.id)
    ).all()
    assert len(bookings) == 6
    assert {booking.rooms for booking in bookings} == {1}
    inventory = db_session.scalars(
        select(RoomInventoryDaily).where(RoomInventoryDaily.property_id == env.property.id)
    ).all()
    assert inventory == []  # capacity stays property data: not inferred from anything in the file


def test_the_next_file_of_the_same_layout_asks_nothing_and_still_says_it(
    api_client: TestClient, env: SourcesEnv
) -> None:
    first = _csv()
    proposal = understand(api_client, env, "BOOKINGS", "p.csv", first)["proposal"]
    assert import_mapped(api_client, env, "BOOKINGS", "p.csv", first, proposal).status_code == 200

    later = csv_bytes(
        [HEADER, *[[f"NEXT-{r[0]}", *r[1:]] for r in _rows()]], delimiter=";", bom=True
    )
    body = understand(api_client, env, "BOOKINGS", "p2.csv", later)

    assert _ready(body)["assumed"] == ["rooms"]
    assert body["profile"]["status"] == "RECOGNIZED"


def test_a_column_that_counts_the_rooms_wins_and_nothing_is_assumed(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows = [[*HEADER, "Camere"], *[[*row, "2"] for row in _rows()]]

    body = understand(
        api_client, env, "BOOKINGS", "p.csv", csv_bytes(rows, delimiter=";", bom=True)
    )

    understanding = _ready(body)
    assert understanding["assumed"] == []
    assert "rooms" not in body["proposal"]["constants"]
    assert {"header": "Camere", "field": "rooms"} in body["proposal"]["columns"]


def test_a_column_with_the_number_of_the_room_is_not_a_count_of_rooms(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows = [
        [*HEADER, "Camera"],
        *[[*row, str(100 + index)] for index, row in enumerate(_rows(), start=1)],
    ]

    body = understand(
        api_client, env, "BOOKINGS", "p.csv", csv_bytes(rows, delimiter=";", bom=True)
    )

    assert _ready(body)["assumed"] == ["rooms"]


def test_a_column_that_might_be_the_rooms_is_never_overruled_by_the_assumption() -> None:
    """The file may count them: that is a question for the column, not an absence."""
    adapter = BookingsDomain(cast(Session, None), TenantContext(uuid4()))
    contested = SimpleNamespace(ambiguous_group="CONTESTED", ambiguous_fields=("rooms",))
    unrelated = SimpleNamespace(ambiguous_group="AMOUNT", ambiguous_fields=("room_revenue",))

    def proposal(*columns: SimpleNamespace, assigned: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(columns=columns, assigned=lambda: assigned or {})

    assert _meaning_of_absent_columns(adapter, proposal()) == {"rooms": 1}
    assert _meaning_of_absent_columns(adapter, proposal(unrelated)) == {"rooms": 1}
    assert _meaning_of_absent_columns(adapter, proposal(contested)) == {}
    assert _meaning_of_absent_columns(adapter, proposal(assigned={"rooms": object()})) == {}


def test_two_columns_about_the_rooms_are_read_as_a_column_never_as_the_assumption(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows = [
        [*HEADER, "Camere", "N. camere"],
        *[[*row, "1", "2"] for row in _rows()],
    ]

    body = understand(
        api_client, env, "BOOKINGS", "p.csv", csv_bytes(rows, delimiter=";", bom=True)
    )

    assert body["understanding"]["assumed"] == []
    assert "rooms" not in body["proposal"]["constants"]


@pytest.mark.parametrize(
    ("header", "row", "note"),
    [
        (
            [
                "Check-out",
                "Canale",
                "Ricavo camere",
                "Stato",
                "Codice prenotazione",
                "Data prenotazione",
                "Check-in",
            ],  # noqa: E501
            ["13/11/2026", "Expedia", "150,50", "Confermata", "A-1", "01/10/2026", "11/11/2026"],
            "columns in another order",
        ),
        (
            [
                "Reservation ID",
                "Booked on",
                "Arrival",
                "Departure",
                "Status",
                "Channel",
                "Room revenue",
            ],  # noqa: E501
            ["A-1", "2026-10-01", "2026-11-11", "2026-11-13", "Confirmed", "Expedia", "150.50"],
            "English headers and ISO dates",
        ),
        (
            [
                "Cod. prenotazione",
                "Prenotata il",
                "Arrivo",
                "Partenza",
                "Stato",
                "Canale",
                "Importo camera",
                "Colore",
                "Reparto vendite",
            ],  # noqa: E501
            [
                "A-1",
                "01/10/2026",
                "11/11/2026",
                "13/11/2026",
                "Confermata",
                "Expedia",
                "150,50",
                "Rosso",
                "Web",
            ],  # noqa: E501
            "other names and columns nobody asked for",
        ),
    ],
)
def test_other_exports_with_no_room_count_are_understood_the_same_way(
    api_client: TestClient, env: SourcesEnv, header: list[str], row: list[str], note: str
) -> None:
    rows = [header]
    for index in range(1, 7):
        rows.append([f"A-{index}" if cell == "A-1" else cell for cell in row])

    body = understand(
        api_client, env, "BOOKINGS", "p.csv", csv_bytes(rows, delimiter=";", bom=True)
    )

    assert _ready(body)["assumed"] == ["rooms"], note


def test_an_unknown_status_is_still_asked_about(api_client: TestClient, env: SourcesEnv) -> None:
    """The room count is what stopped being a question: what a word means still is one."""
    body = understand(api_client, env, "BOOKINGS", "p.csv", _csv(status="Modificata"))

    assert body["understanding"]["level"] == "ASK"
    assert [q["kind"] for q in body["understanding"]["questions"]] == ["VALUE_LABELS"]


def test_a_file_that_is_not_bookings_never_becomes_ready_because_of_it(
    api_client: TestClient, env: SourcesEnv
) -> None:
    rows = [
        ["Giorno", "Nome e cognome", "Reparto", "Ore previste", "Costo previsto"],
        *[[f"{10 + day}/11/2026", "Persona", "Reception", "8", "120,00"] for day in range(6)],
    ]

    body = understand(
        api_client, env, "BOOKINGS", "turni.csv", csv_bytes(rows, delimiter=";", bom=True)
    )

    assert body["understanding"]["level"] != "READY"
    assert body["understanding"]["detection"]["domain"] == "LABOR"


def test_no_personal_value_of_the_guest_is_in_the_answer(
    api_client: TestClient, env: SourcesEnv
) -> None:
    response_text = str(understand(api_client, env, "BOOKINGS", "p.csv", _csv()))

    for value in (GUEST, EMAIL, PHONE):
        assert value not in response_text


def test_a_mapping_by_hand_may_still_state_how_many_rooms_every_row_is(
    api_client: TestClient, env: SourcesEnv
) -> None:
    """The person's own value stands, and it is not reported as an assumption."""
    content = _csv()
    proposal = understand(api_client, env, "BOOKINGS", "p.csv", content)["proposal"]
    by_hand = {**proposal, "constants": {"rooms": 2}, "smart_import": None}

    response = import_mapped(api_client, env, "BOOKINGS", "p.csv", content, by_hand)

    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] is True
