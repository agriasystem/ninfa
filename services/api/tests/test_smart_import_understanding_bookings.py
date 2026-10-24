"""Smart Import V3: a bookings file in the hotel's own words.

"Dal / Al", "Check-in date", "Provenienza prenotazione", "Canale vendita"; a title and a total; the
name of the guest in a column of its own. NINFA recognises the columns by their words, checks them
against their values, NEVER reads a guest (name, email, phone), and says plainly when a field the
analysis really needs is not in the file.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.models import Booking, BookingMappingProfile
from tests import understanding_support as corpus
from tests.data_sources_support import SourcesEnv, sources_env
from tests.smart_import_support import (
    by_header,
    import_mapped,
    profiles_of,
    understand,
    validation,
    writes,
)
from tests.support import BookingFactory

BOOKINGS = "BOOKINGS"

# header sets of the same eight things (code, booked on, arrival, departure, status, rooms, room
# revenue, channel), as hotels and their software write them
ENGLISH = [
    "Reservation ID",
    "Booking date",
    "Check-in date",
    "Check-out date",
    "Status",
    "Rooms",
    "Room revenue",
    "Booking source",
]
ABBREVIATED = [
    "N. pren.",
    "Data pren.",
    "Arr.",
    "Part.",
    "Stato",
    "N. cam.",
    "Ricavo camere",
    "Canale vendita",
]
ITALIAN_FREE = [
    "Id prenotazione",
    "Prenotata il",
    "Data arrivo",
    "Data partenza",
    "Stato prenotazione",
    "Camere",
    "Importo camere",
    "Provenienza prenotazione",
]
FIELDS = [
    "source_record_id",
    "booked_at",
    "check_in",
    "check_out",
    "status",
    "rooms",
    "room_revenue",
    "channel",
]


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _kinds(body: dict[str, Any]) -> list[str]:
    return [q["kind"] for q in body["understanding"]["questions"]]


def _field_by_header(body: dict[str, Any]) -> dict[str, str | None]:
    return {c["header"]: c["field"] for c in body["columns"]}


@pytest.mark.parametrize("header", [ENGLISH, ABBREVIATED, ITALIAN_FREE])
def test_the_same_eight_things_are_recognised_whatever_words_the_file_uses(
    api_client: TestClient, env: SourcesEnv, header: list[str]
) -> None:
    content = corpus.bookings_xlsx(header)

    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    assert [_field_by_header(body)[name] for name in header] == FIELDS
    assert body["understanding"]["level"] == "READY" and _kinds(body) == []
    tried = validation(api_client, env, BOOKINGS, content, body["proposal"], name="pren.xlsx")
    assert tried["can_import"] is True and tried["rows_invalid"] == 0


def test_dal_and_al_are_an_arrival_and_a_departure_only_as_a_pair(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.bookings_dal_al_xlsx()

    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    mapped = _field_by_header(body)
    assert (mapped["Dal"], mapped["Al"]) == ("check_in", "check_out")
    assert mapped["Provenienza"] == "channel" and mapped["Importo camere"] == "room_revenue"
    # a lone "Dal" is only a maybe: with no "Al" next to it, it is proposed to be CONFIRMED
    alone = corpus.bookings_xlsx(["Id prenotazione", "Data prenotazione", "Dal", "Stato", "Camere"])
    lone = understand(api_client, env, BOOKINGS, "pren.xlsx", alone)
    arrival = next(r for r in lone["understanding"]["recognized"] if r["field"] == "check_in")
    assert arrival["level"] == "MEDIUM"  # never "recognised" on the strength of one word


def test_a_bare_code_column_is_confirmed_with_one_question_and_the_answer_is_enough(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.bookings_dal_al_xlsx()

    asked = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    assert asked["understanding"]["level"] == "ASK" and _kinds(asked) == ["COLUMN_MEANING"]
    question = asked["understanding"]["questions"][0]
    assert (question["column"], question["candidate"]) == ("Codice", "source_record_id")

    answered = understand(
        api_client,
        env,
        BOOKINGS,
        "pren.xlsx",
        content,
        {"column_fields": {"Codice": "source_record_id"}},
    )

    assert answered["understanding"]["level"] == "READY" and _kinds(answered) == []


def test_a_title_and_a_total_are_not_bookings(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.bookings_xlsx(title="REGISTRO PRENOTAZIONI", total=True)

    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    document = body["understanding"]["document"]
    assert document["title"] == "REGISTRO PRENOTAZIONI"
    assert document["skipped"]["totals"] == 1 and document["totals"] == "MATCH"
    assert document["table"]["data_rows"] == 8
    done = import_mapped(api_client, env, BOOKINGS, "pren.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    assert done.json()["created"] == 8
    assert db_session.scalar(select(Booking).limit(1)) is not None


def test_the_name_of_a_guest_is_never_read_stored_or_sent_back(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.bookings_xlsx(extra=["Nome ospite"])

    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    guest = by_header(body)["Nome ospite"]
    assert guest["field"] is None and guest["not_used_reason"] == "PERSON"
    assert guest["examples"] == []  # not even as an example on screen
    assert "Ospite 0 Rossi" not in repr(body)
    done = import_mapped(api_client, env, BOOKINGS, "pren.xlsx", content, body["proposal"])
    assert done.status_code == 200 and done.json()["succeeded"] is True
    (profile,) = profiles_of(db_session, env, BookingMappingProfile)
    stored = repr((profile.column_mapping, profile.status_mapping, profile.format_options))
    assert "Nome ospite" not in stored and "Rossi" not in stored
    bookings = list(db_session.scalars(select(Booking)))
    assert bookings and not any("Rossi" in repr(vars(b)) for b in bookings)


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        ("Cliente", "PERSON"),
        ("Guest name", "PERSON"),
        ("Email ospite", "CONTACT"),
        ("Telefono", "CONTACT"),
    ],
)
def test_every_kind_of_guest_data_is_left_out_with_its_reason(
    api_client: TestClient, env: SourcesEnv, header: str, reason: str
) -> None:
    rows: list[list[object]] = [["Codice", "Arrivo", "Partenza", header]]
    for i in range(6):
        value = (
            (f"Mario Rossi{i}" if i else "Anna Verdi")
            if reason == "PERSON"
            else (f"guest{i}@example.com" if "mail" in header else f"+39 333 12345{i}")
        )
        rows.append([f"R{i}", f"0{i + 1}/11/2026", f"0{i + 3}/11/2026", value])

    body = understand(api_client, env, BOOKINGS, "pren.csv", corpus.csv_of(rows))

    column = by_header(body)[header]
    assert column["field"] is None and column["not_used_reason"] == reason
    assert column["examples"] == []


def test_a_count_of_guests_is_not_a_guest(api_client: TestClient, env: SourcesEnv) -> None:
    rows: list[list[object]] = [
        ["Codice", "Arrivo", "Partenza", "Ospiti"],
        *[[f"R{i}", f"0{i + 1}/11/2026", f"0{i + 3}/11/2026", 2 + i % 2] for i in range(6)],
    ]

    body = understand(api_client, env, BOOKINGS, "pren.csv", corpus.csv_of(rows))

    assert by_header(body)["Ospiti"]["not_used_reason"] is None


def test_a_missing_departure_date_is_named_and_nothing_is_imported(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.bookings_missing_checkout_xlsx()
    before = writes(db_session, env)

    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    understanding = body["understanding"]
    assert understanding["level"] == "MANUAL"
    (blocker,) = understanding["blockers"]
    assert blocker["code"] == "MISSING_REQUIRED"
    assert ["check_out"] in blocker["groups"]  # said plainly: this is not in the file
    tried = validation(api_client, env, BOOKINGS, content, body["proposal"], name="pren.xlsx")
    assert tried["can_import"] is False
    done = import_mapped(api_client, env, BOOKINGS, "pren.xlsx", content, body["proposal"])
    assert done.json()["succeeded"] is False
    assert writes(db_session, env) == before


def test_the_next_bookings_file_is_recognised_and_asks_nothing(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    content = corpus.bookings_xlsx(ABBREVIATED, title="Estrazione del 24/10", total=True)
    proposal = understand(api_client, env, BOOKINGS, "a.xlsx", content)["proposal"]
    assert import_mapped(api_client, env, BOOKINGS, "a.xlsx", content, proposal).json()["succeeded"]

    again = understand(
        api_client,
        env,
        BOOKINGS,
        "b.xlsx",
        corpus.bookings_xlsx(ABBREVIATED, title="Estrazione del 31/10", total=True, rows=5),
    )

    assert again["profile"]["status"] == "RECOGNIZED"
    assert again["understanding"]["level"] == "READY" and _kinds(again) == []
    assert again["understanding"]["document"]["table"]["data_rows"] == 5


def test_unknown_booking_statuses_are_asked_once_and_remembered(
    api_client: TestClient, db_session: Session, env: SourcesEnv
) -> None:
    rows: list[list[object]] = [
        [
            "Codice",
            "Data prenotazione",
            "Arrivo",
            "Partenza",
            "Stato",
            "Camere",
            "Importo",
            "Canale",
        ],
        *[
            [
                f"R{i}",
                f"0{i + 1}/10/2026",
                f"0{i + 1}/11/2026",
                f"0{i + 3}/11/2026",
                ["OK", "Annullata da cliente", "OK"][i % 3],
                1,
                "120,00",
                "Booking.com",
            ]
            for i in range(6)
        ],
    ]
    content = corpus.csv_of(rows)

    asked = understand(api_client, env, BOOKINGS, "pren.csv", content)

    questions = [q for q in asked["understanding"]["questions"] if q["kind"] == "VALUE_LABELS"]
    assert [q["document"] for q in questions] == ["status_mapping"]
    assert {item["label"] for item in questions[0]["labels"]} == {"OK", "Annullata da cliente"}


def test_the_dry_run_adds_up_the_bookings_from_the_validated_rows(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = corpus.bookings_xlsx(title="REGISTRO PRENOTAZIONI", total=True)
    body = understand(api_client, env, BOOKINGS, "pren.xlsx", content)

    tried = validation(api_client, env, BOOKINGS, content, body["proposal"], name="pren.xlsx")

    summary = tried["summary"]
    assert tried["can_import"] is True and tried["rows_total"] == 8
    assert summary["channels"] == 4 and Decimal(summary["revenue"]) == Decimal("988.00")
    assert (summary["date_from"], summary["date_to"]) == ("2026-11-02", "2026-11-09")
