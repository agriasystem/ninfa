"""Golden mini import: `masseria_ninfa_bookings_v1`.

SOURCE FILE -> CANONICAL BOOKINGS, end to end and reproducibly. The expected result
(`masseria_ninfa_bookings_v1.expected.json`) was computed independently of the application code
with the standard library only. No metrics, snapshots or decisions are derived here.
"""

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import Booking, BookingChannel, BookingImportRow, ImportRowStatus
from app.modules.bookings.repository import BookingRepository
from app.modules.bookings.service import BookingImportService
from app.modules.bookings.suggestions import SuggestionConfidence
from app.modules.ingestion.models import ImportJobStatus
from tests.booking_support import FIXTURES, xlsx_bytes
from tests.support import BookingFactory

GOLDEN_CSV = FIXTURES / "masseria_ninfa_bookings_v1.csv"
EXPECTED = json.loads((FIXTURES / "masseria_ninfa_bookings_v1.expected.json").read_text("utf-8"))
ITALIAN_FORMAT: dict[str, Any] = {
    "date_formats": {
        "booked_at": "%d/%m/%Y %H:%M",
        "check_in": "%d/%m/%Y",
        "check_out": "%d/%m/%Y",
        "cancelled_at": "%d/%m/%Y %H:%M",
    },
    "decimal_separator": ",",
    "thousands_separator": ".",
}
# What must never end up in the database: the fixture's guest names and phone numbers.
GUEST_COLUMNS = ("Ospite", "Telefono")


@pytest.fixture
def masseria(db_session: Session, factory: BookingFactory) -> tuple[BookingImportService, Any, Any]:
    workspace = factory.workspace()
    prop = factory.property(workspace, "masseria-ninfa")
    assert (prop.timezone, prop.currency) == (EXPECTED["property"]["timezone"], "EUR")
    source = factory.data_source(prop)
    return BookingImportService(db_session, TenantContext(workspace.id)), prop, source


def confirm_suggested_mapping(
    service: BookingImportService, source: Any, content: bytes
) -> list[str]:
    """The customer accepts the HIGH-confidence suggestions and states the date/number formats."""
    suggestion = service.suggest_mapping(source.id, filename=GOLDEN_CSV.name, content=content)
    columns = {
        s.canonical_field.value: {"column": s.suggested_source_column}
        for s in suggestion.suggestions
        if s.suggested_source_column and s.confidence == SuggestionConfidence.HIGH
    }
    assert set(suggestion.date_order_hints.values()) == {"DMY"}  # evidence behind the formats
    service.save_mapping(
        source.id, headers=suggestion.headers, column_mapping=columns, format_options=ITALIAN_FORMAT
    )
    return suggestion.headers


def canonical(bookings: list[Booking]) -> list[dict[str, Any]]:
    def money(value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")

    def moment(value: dt.datetime | None) -> str | None:
        return None if value is None else value.astimezone(dt.UTC).isoformat()

    return [
        {
            "source_record_id": b.source_record_id,
            "booked_at": moment(b.booked_at),
            "check_in": b.check_in.isoformat(),
            "check_out": b.check_out.isoformat(),
            "status": b.status.value,
            "rooms": b.rooms,
            "guests": b.guests,
            "room_revenue": money(b.room_revenue),
            "total_revenue": money(b.total_revenue),
            "channel": b.channel.normalized_name,
            "commission_amount": money(b.commission_amount),
            "room_type": b.room_type,
            "cancelled_at": moment(b.cancelled_at),
        }
        for b in sorted(bookings, key=lambda booking: booking.source_record_id)
    ]


def stored_bookings(session: Session, service_context: TenantContext, prop: Any) -> list[Booking]:
    return list(BookingRepository(session, service_context).list_for_property(prop.id))


def test_the_golden_file_imports_to_exactly_the_expected_canonical_bookings(
    db_session: Session, masseria: tuple[BookingImportService, Any, Any]
) -> None:
    service, prop, source = masseria
    content = GOLDEN_CSV.read_bytes()
    confirm_suggested_mapping(service, source, content)

    result = service.import_file(source.id, filename=GOLDEN_CSV.name, content=content)

    assert (result.status, result.error_code) == (ImportJobStatus.SUCCEEDED, None)
    assert (result.rows_total, result.rows_valid, result.rows_invalid) == (16, 16, 0)
    assert (result.bookings_created, result.bookings_updated, result.bookings_unchanged) == (
        16,
        0,
        0,
    )
    context = TenantContext(prop.workspace_id)
    assert canonical(stored_bookings(db_session, context, prop)) == EXPECTED["bookings"]


def test_the_golden_channels_are_normalised_merged_and_left_unverified(
    db_session: Session, masseria: tuple[BookingImportService, Any, Any]
) -> None:
    service, prop, source = masseria
    content = GOLDEN_CSV.read_bytes()
    confirm_suggested_mapping(service, source, content)
    service.import_file(source.id, filename=GOLDEN_CSV.name, content=content)

    channels = {c.normalized_name: c for c in db_session.scalars(select(BookingChannel))}

    assert set(channels) == set(
        EXPECTED["channels"]
    )  # 7: Booking.com/BOOKING.COM/booking com merge
    for key, expected in EXPECTED["channels"].items():
        assert channels[key].name == expected["first_label"], key
        assert channels[key].channel_type.value == expected["channel_type"], key
        assert channels[key].is_verified is expected["is_verified"], key
    assert (
        channels["agenzia viaggi rossi"].channel_type.value == "OTHER"
    )  # not guessed from its name
    assert channels["tour operator sole"].channel_type.value == "OTHER"


def test_the_golden_import_is_reproducible_and_idempotent(
    db_session: Session, masseria: tuple[BookingImportService, Any, Any]
) -> None:
    service, prop, source = masseria
    content = GOLDEN_CSV.read_bytes()
    confirm_suggested_mapping(service, source, content)

    first = service.import_file(source.id, filename=GOLDEN_CSV.name, content=content)
    second = service.import_file(source.id, filename=GOLDEN_CSV.name, content=content)

    assert (second.bookings_created, second.bookings_updated, second.bookings_unchanged) == (
        0,
        0,
        16,
    )
    assert second.duplicate_of_import_file_id == first.import_file_id
    context = TenantContext(prop.workspace_id)
    assert canonical(stored_bookings(db_session, context, prop)) == EXPECTED["bookings"]
    assert len(db_session.scalars(select(BookingChannel)).all()) == 7


def test_the_golden_file_keeps_guest_data_out_of_the_database(
    db_session: Session, masseria: tuple[BookingImportService, Any, Any]
) -> None:
    service, prop, source = masseria
    content = GOLDEN_CSV.read_bytes()
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8")), delimiter=";"))
    guest_values = {row[column] for row in rows for column in GUEST_COLUMNS}
    assert "Anna Bianchi" in guest_values  # the file has them...
    confirm_suggested_mapping(service, source, content)

    service.import_file(source.id, filename=GOLDEN_CSV.name, content=content)

    staged = db_session.scalars(select(BookingImportRow)).all()
    assert {r.validation_status for r in staged} == {ImportRowStatus.IMPORTED}
    dump = json.dumps(
        [[r.mapped_payload, r.normalized_payload, r.validation_errors] for r in staged]
    )
    for value in guest_values:
        assert value not in dump  # ...the staging does not


def test_the_same_golden_data_as_native_spreadsheet_cells_gives_the_same_bookings(
    db_session: Session, masseria: tuple[BookingImportService, Any, Any]
) -> None:
    """An .xlsx typed as a spreadsheet (real dates, real numbers) needs no format settings."""
    service, prop, source = masseria
    csv_rows = list(csv.reader(io.StringIO(GOLDEN_CSV.read_text("utf-8")), delimiter=";"))
    headers = csv_rows[0]
    rome = ZoneInfo("Europe/Rome")

    def local(value: str) -> dt.datetime | None:
        return dt.datetime.strptime(value, "%d/%m/%Y %H:%M") if value else None

    def number(value: str) -> float | None:
        return float(value.replace(".", "").replace(",", ".")) if value else None

    native: list[list[Any]] = [headers]
    for row in csv_rows[1:]:
        native.append(
            [
                row[0],
                local(row[1]),
                dt.datetime.strptime(row[2], "%d/%m/%Y"),
                dt.datetime.strptime(row[3], "%d/%m/%Y"),
                row[4],
                int(row[5]),
                int(row[6]),
                number(row[7]),
                number(row[8]),
                row[9],
                number(row[10]),
                row[11] or None,
                local(row[12]),
                row[13],
                row[14],
            ]
        )
    workbook = xlsx_bytes({"Prenotazioni": native})
    suggestion = service.suggest_mapping(source.id, filename="golden.xlsx", content=workbook)
    columns = {
        s.canonical_field.value: {"column": s.suggested_source_column}
        for s in suggestion.suggestions
        if s.suggested_source_column and s.confidence == SuggestionConfidence.HIGH
    }
    service.save_mapping(source.id, headers=suggestion.headers, column_mapping=columns)

    result = service.import_file(source.id, filename="golden.xlsx", content=workbook)

    assert result.succeeded and result.bookings_created == 16, (result.error_code, result.details)
    context = TenantContext(prop.workspace_id)
    assert canonical(stored_bookings(db_session, context, prop)) == EXPECTED["bookings"]
    assert rome  # the property timezone is what interprets the naive spreadsheet datetimes


def test_the_golden_expected_file_is_self_consistent() -> None:
    """Guards the fixture itself: 16 bookings, several statuses, cancellation dates and a booking
    made right after the spring clock change (03:30 on 29 March: the skipped hour is not used)."""
    bookings = EXPECTED["bookings"]

    assert len(bookings) == 16
    assert {b["status"] for b in bookings} == {"CONFIRMED", "CANCELLED", "NO_SHOW"}
    assert sum(1 for b in bookings if b["cancelled_at"]) == 2
    assert next(b for b in bookings if b["source_record_id"] == "MN-0007")["cancelled_at"] is None
    assert (
        next(b for b in bookings if b["source_record_id"] == "MN-0009")["booked_at"]
        == "2026-03-29T01:30:00+00:00"
    )
    assert {b["room_type"] for b in bookings} >= {None, "Suite", "Camera Doppia"}
    lead_days = {
        (
            dt.date.fromisoformat(b["check_in"]) - dt.datetime.fromisoformat(b["booked_at"]).date()
        ).days
        for b in bookings
    }
    assert len(lead_days) >= 10  # a spread of lead times
    assert len({b["channel"] for b in bookings}) == 7 == len(EXPECTED["channels"])
