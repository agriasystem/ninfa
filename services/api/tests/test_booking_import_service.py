"""BookingImportService end to end on real PostgreSQL: mapping memory, formats, validation,
atomicity, idempotency, data minimisation and tenant/data-source rules.
"""

import datetime as dt
import logging
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    BookingStatus,
    ChannelType,
    ImportRowStatus,
)
from app.modules.bookings.parsers import open_table
from app.modules.bookings.repository import BookingRepository
from app.modules.bookings.service import BookingImportResult, BookingImportService
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.properties.models import Property
from app.modules.tenancy.models import Workspace
from tests.booking_support import (
    FIXTURES,
    STANDARD_COLUMNS,
    STANDARD_HEADERS,
    csv_bytes,
    xlsx_bytes,
)
from tests.support import BookingFactory

Code = BookingErrorCode

IT_COLUMNS: dict[str, dict[str, Any]] = {
    "source_record_id": {"column": "ID Prenotazione"},
    "booked_at": {"column": "Data Prenotazione"},
    "check_in": {"column": "Data Arrivo"},
    "check_out": {"column": "Data Partenza"},
    "status": {"column": "Stato"},
    "rooms": {"column": "Camere"},
    "room_revenue": {"column": "Importo Camera"},
    "channel": {"column": "Canale"},
}
IT_FORMAT: dict[str, Any] = {
    "date_formats": {
        "booked_at": "%d/%m/%Y %H:%M",
        "check_in": "%d/%m/%Y",
        "check_out": "%d/%m/%Y",
    },
    "decimal_separator": ",",
    "thousands_separator": ".",
}


# --- environment ------------------------------------------------------------------------------


@dataclass
class Env:
    session: Session
    workspace: Workspace
    property: Property
    data_source: DataSource
    context: TenantContext
    service: BookingImportService
    factory: BookingFactory

    def confirm(
        self,
        headers: list[str],
        columns: dict[str, dict[str, Any]] | None = None,
        **sections: Any,
    ) -> BookingMappingProfile:
        return self.service.save_mapping(
            self.data_source.id,
            headers=headers,
            column_mapping=columns or STANDARD_COLUMNS,
            **sections,
        )

    def run(self, content: bytes, name: str = "bookings.csv") -> BookingImportResult:
        return self.service.import_file(self.data_source.id, filename=name, content=content)

    def bookings(self) -> list[Booking]:
        return list(
            BookingRepository(self.session, self.context).list_for_property(self.property.id)
        )

    def count(self, model: type[Any]) -> int:
        return int(self.session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.fixture
def env(db_session: Session, factory: BookingFactory) -> Env:
    workspace = factory.workspace()
    prop = factory.property(workspace, "masseria-ninfa")  # Europe/Rome, EUR by default
    data_source = factory.data_source(prop)
    context = TenantContext(workspace.id)
    return Env(
        db_session,
        workspace,
        prop,
        data_source,
        context,
        BookingImportService(db_session, context),
        factory,
    )


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def headers_of(content: bytes, name: str = "f.csv") -> list[str]:
    return open_table(content, name).headers


def confirmed_env(env: Env, fixture: str = "en_comma.csv", **sections: Any) -> tuple[Env, bytes]:
    content = fixture_bytes(fixture)
    env.confirm(headers_of(content, fixture), **sections)
    return env, content


def job_of(env: Env, result: BookingImportResult) -> ImportJob:
    job = env.session.get(ImportJob, result.import_job_id)
    assert job is not None
    return job


@contextmanager
def sql_log(session: Session) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(bind, "before_cursor_execute", record)


# --- mapping suggestion and mapping memory (tests 15-22) -------------------------------------


def test_suggesting_a_mapping_reads_the_file_and_writes_nothing(env: Env) -> None:
    result = env.service.suggest_mapping(
        env.data_source.id, filename="it.csv", content=fixture_bytes("it_semicolon.csv")
    )

    suggested = {s.canonical_field.value: s.suggested_source_column for s in result.suggestions}
    assert suggested["check_in"] == "Data Arrivo"
    assert suggested["source_record_id"] == "ID Prenotazione"
    assert result.file_type == "csv"
    assert env.count(BookingMappingProfile) == 0 and env.count(ImportJob) == 0
    assert env.count(BookingImportRow) == env.count(Booking) == 0


def test_the_suggestion_offers_date_order_evidence_for_suggested_date_columns(env: Env) -> None:
    golden = fixture_bytes("masseria_ninfa_bookings_v1.csv")

    hints = env.service.suggest_mapping(
        env.data_source.id, filename="g.csv", content=golden
    ).date_order_hints

    assert hints == {
        "booked_at": "DMY",
        "check_in": "DMY",
        "check_out": "DMY",
        "cancelled_at": "DMY",
    }
    ambiguous = env.service.suggest_mapping(
        env.data_source.id, filename="a.csv", content=fixture_bytes("it_semicolon.csv")
    ).date_order_hints
    assert ambiguous["check_in"] == "AMBIGUOUS"  # all days <= 12: only the customer can say


def test_a_suggestion_is_not_a_mapping_the_import_asks_for_confirmation(env: Env) -> None:
    content = fixture_bytes("en_comma.csv")
    suggestions = env.service.suggest_mapping(env.data_source.id, filename="f.csv", content=content)
    assert all(
        s.suggested_source_column
        for s in suggestions.suggestions
        if s.canonical_field.value in STANDARD_COLUMNS
    )

    result = env.run(content)

    assert (result.status, result.error_code) == (ImportJobStatus.FAILED, Code.MAPPING_REQUIRED)
    assert result.details == {"reason": "no_confirmed_mapping"}
    assert env.bookings() == []
    assert job_of(env, result).error_code == "BOOKING_MAPPING_REQUIRED"


def test_confirming_a_mapping_remembers_it_with_the_header_signature(env: Env) -> None:
    headers = STANDARD_HEADERS
    profile = env.confirm(headers, format_options={"decimal_separator": "."})

    assert (profile.workspace_id, profile.property_id, profile.data_source_id) == (
        env.workspace.id,
        env.property.id,
        env.data_source.id,
    )
    assert profile.column_mapping["check_in"] == {"column": "Check-in"}
    assert profile.format_options == {"decimal_separator": "."}
    assert len(profile.header_signature) == 64


def test_there_is_one_current_profile_per_data_source(env: Env) -> None:
    first = env.confirm(STANDARD_HEADERS)
    second = env.confirm(STANDARD_HEADERS, status_mapping={"Waitlist": "CONFIRMED"})

    assert first.id == second.id
    assert env.count(BookingMappingProfile) == 1
    assert second.status_mapping == {"waitlist": "CONFIRMED"}


@pytest.mark.parametrize(
    "columns",
    [
        {k: v for k, v in STANDARD_COLUMNS.items() if k != "source_record_id"},
        {**STANDARD_COLUMNS, "source_record_id": {"constant": "X"}},
        {**STANDARD_COLUMNS, "check_in": {"constant": "2026-03-10"}},
        {**STANDARD_COLUMNS, "room_revenue": {"constant": 100}},
    ],
)
def test_an_incomplete_or_unsafe_mapping_is_refused(env: Env, columns: dict[str, Any]) -> None:
    with pytest.raises(BookingImportError) as info:
        env.confirm(STANDARD_HEADERS, columns)

    assert info.value.error_code == Code.INVALID_MAPPING
    assert env.count(BookingMappingProfile) == 0


def test_a_mapping_must_refer_to_columns_of_the_file(env: Env) -> None:
    with pytest.raises(BookingImportError) as info:
        env.confirm([h for h in STANDARD_HEADERS if h != "Rooms"])

    assert info.value.error_code == Code.INVALID_MAPPING
    assert info.value.details == {"unknown_columns": ["Rooms"]}


def test_constants_stand_in_for_columns_the_file_does_not_have(env: Env) -> None:
    columns = {k: v for k, v in STANDARD_COLUMNS.items() if k not in ("rooms", "status", "channel")}
    columns.update(
        rooms={"constant": 1}, status={"constant": "CONFIRMED"}, channel={"constant": "Direct"}
    )
    content = csv_bytes(
        [
            ["Booking ID", "Booked At", "Check-in", "Check-out", "Room Revenue"],
            ["K-1", "2026-01-15 10:30", "2026-03-10", "2026-03-13", "450.00"],
            ["K-2", "2026-01-16 11:00", "2026-03-12", "2026-03-14", "300.50"],
        ]
    )
    env.confirm(headers_of(content), columns)

    result = env.run(content)

    assert result.succeeded and result.bookings_created == 2
    for booking in env.bookings():
        assert (booking.rooms, booking.status, booking.channel.name) == (
            1,
            BookingStatus.CONFIRMED,
            "Direct",
        )


def test_a_matching_schema_reuses_the_mapping_and_extra_columns_are_harmless(env: Env) -> None:
    env, content = confirmed_env(env)
    same = env.run(content)
    extended = env.run(
        csv_bytes(
            [
                [*STANDARD_HEADERS, "Notes"],
                [
                    "NEW-1",
                    "2026-01-15 10:30",
                    "2026-03-10",
                    "2026-03-13",
                    "Confirmed",
                    "1",
                    "450.00",
                    "Direct",
                    "free text",
                ],
            ]
        )
    )

    assert same.succeeded and same.details["schema_signature_matches"] is True
    assert extended.succeeded and extended.details["schema_signature_matches"] is False


def test_a_changed_source_schema_is_reported_and_the_old_mapping_is_not_applied(env: Env) -> None:
    env, _ = confirmed_env(env)

    result = env.run(fixture_bytes("changed_schema.csv"))

    assert (result.status, result.error_code) == (
        ImportJobStatus.FAILED,
        Code.SOURCE_SCHEMA_CHANGED,
    )
    assert result.details["missing_columns"] == ["Check-in"]
    assert env.bookings() == []
    assert env.count(BookingImportRow) == 0  # nothing was even staged


def test_a_workbook_with_several_data_sheets_asks_which_one(env: Env) -> None:
    rows = [
        STANDARD_HEADERS,
        ["W-1", "2026-01-15 10:30", "2026-03-10", "2026-03-13", "Confirmed", 1, 450.0, "Direct"],
    ]
    workbook = xlsx_bytes({"Prenotazioni": rows, "Legenda": [["k", "v"], ["a", "b"]]})

    suggestion = env.service.suggest_mapping(
        env.data_source.id, filename="w.xlsx", content=workbook
    )
    assert (suggestion.requires_sheet_selection, suggestion.sheet_names) == (
        True,
        ["Prenotazioni", "Legenda"],
    )
    picked = env.service.suggest_mapping(
        env.data_source.id, filename="w.xlsx", content=workbook, sheet_name="Prenotazioni"
    )
    assert picked.sheet_name == "Prenotazioni" and picked.headers == STANDARD_HEADERS

    env.confirm(STANDARD_HEADERS)  # no sheet_name in the profile yet
    unresolved = env.run(workbook, "w.xlsx")
    assert (unresolved.error_code, unresolved.details["reason"]) == (
        Code.MAPPING_REQUIRED,
        "sheet_selection_required",
    )

    env.confirm(STANDARD_HEADERS, format_options={"sheet_name": "Prenotazioni"})
    resolved = env.run(workbook, "w.xlsx")
    assert resolved.succeeded and resolved.bookings_created == 1


# --- formats: every supported file yields the same canonical bookings (tests 23-27) ----------


def canonical_rows(env: Env) -> list[tuple[Any, ...]]:
    return [
        (
            b.source_record_id,
            b.status,
            b.rooms,
            b.room_revenue,
            b.channel.normalized_name,
            b.check_in,
            b.booked_at,
        )
        for b in sorted(env.bookings(), key=lambda booking: booking.source_record_id)
    ]


EN_EXPECTED_COMMON = [
    ("BK-1", BookingStatus.CONFIRMED, 1, Decimal("450.00"), "booking com"),
    ("BK-2", BookingStatus.CANCELLED, 2, Decimal("300.50"), "direct"),
]


def en_rows() -> list[list[Any]]:
    return [
        STANDARD_HEADERS,
        [
            "BK-1",
            "2026-01-15 10:30",
            "2026-03-10",
            "2026-03-13",
            "Confirmed",
            "1",
            "450.00",
            "Booking.com",
        ],
        [
            "BK-2",
            "2026-01-16 11:00",
            "2026-03-12",
            "2026-03-14",
            "Cancelled",
            "2",
            "300.50",
            "Direct",
        ],
    ]


@pytest.mark.parametrize(
    ("label", "content", "name"),
    [
        ("comma", csv_bytes(en_rows()), "b.csv"),
        ("semicolon", csv_bytes(en_rows(), delimiter=";"), "b.csv"),
        ("tab", csv_bytes(en_rows(), delimiter="\t"), "b.csv"),
        ("utf8-bom", csv_bytes(en_rows(), bom=True), "b.csv"),
        ("crlf", csv_bytes(en_rows(), newline="\r\n"), "b.csv"),
        ("cp1252", csv_bytes(en_rows(), encoding="cp1252"), "b.csv"),
        ("xlsx-text", xlsx_bytes({"Sheet1": en_rows()}), "b.xlsx"),
    ],
)
def test_every_supported_file_format_imports_to_the_same_canonical_bookings(
    env: Env, label: str, content: bytes, name: str
) -> None:
    env.confirm(STANDARD_HEADERS)

    result = env.run(content, name)

    assert result.succeeded, (label, result.error_code, result.error_message)
    rows = canonical_rows(env)
    assert [r[:5] for r in rows] == EN_EXPECTED_COMMON
    assert rows[0][6].isoformat() == "2026-01-15T09:30:00+00:00"


def test_xlsx_native_dates_and_numbers_import_like_text(env: Env) -> None:
    import datetime as dt

    rows = [
        STANDARD_HEADERS,
        [
            "BK-1",
            dt.datetime(2026, 1, 15, 10, 30),
            dt.date(2026, 3, 10),
            dt.datetime(2026, 3, 13),
            "Confirmed",
            1,
            450.0,
            "Booking.com",
        ],
        [
            "BK-2",
            dt.datetime(2026, 1, 16, 11, 0),
            dt.datetime(2026, 3, 12),
            dt.datetime(2026, 3, 14),
            "Cancelled",
            2.0,
            300.5,
            "Direct",
        ],
    ]
    env.confirm(STANDARD_HEADERS)

    result = env.run(xlsx_bytes({"S": rows}), "native.xlsx")

    assert result.succeeded
    assert [r[:5] for r in canonical_rows(env)] == EN_EXPECTED_COMMON


def test_italian_export_with_semicolons_decimal_commas_and_day_first_dates(env: Env) -> None:
    content = fixture_bytes("it_semicolon.csv")
    env.confirm(headers_of(content), IT_COLUMNS, format_options=IT_FORMAT)

    result = env.run(content)

    assert result.succeeded and result.bookings_created == 3
    by_id = {b.source_record_id: b for b in env.bookings()}
    assert by_id["IT-3"].room_revenue == Decimal("1050.00")  # "1.050,00"
    assert by_id["IT-3"].check_in.isoformat() == "2026-04-01"  # day first
    assert by_id["IT-2"].status == BookingStatus.CANCELLED  # "Annullato"


def test_utf8_bom_fixture(env: Env) -> None:
    env, content = confirmed_env(env, "utf8_bom.csv")

    assert env.run(content).succeeded


def test_windows_1252_fixture_keeps_accented_text(env: Env) -> None:
    content = fixture_bytes("cp1252.csv")
    columns = {**IT_COLUMNS, "room_type": {"column": "Tipologia Camera"}}
    env.confirm(headers_of(content), columns, format_options=IT_FORMAT)

    result = env.run(content)

    assert result.succeeded
    assert {b.room_type for b in env.bookings()} == {
        "Camera con vista sulla città",
        "Suite più balcone",
    }


def test_unsupported_and_unreadable_files_fail_the_job_with_a_stable_code(env: Env) -> None:
    env.confirm(STANDARD_HEADERS)

    cases = [
        (b"a,b\n1,2\n", "legacy.xls", Code.UNSUPPORTED_FILE_TYPE),
        (b"a,b\n1,2\n", "macros.xlsm", Code.UNSUPPORTED_FILE_TYPE),
        (b"", "empty.csv", Code.EMPTY_FILE),
        (b"garbage, not a workbook", "broken.xlsx", Code.UNREADABLE_FILE),
        (csv_bytes([["ID", "Note", "note"], ["1", "a", "b"]]), "dup.csv", Code.DUPLICATE_HEADER),
    ]
    for content, name, code in cases:
        result = env.run(content, name)
        assert (result.status, result.error_code) == (ImportJobStatus.FAILED, code), name
        assert job_of(env, result).error_code == code.value
    assert env.bookings() == []


# --- normalisation through the service (tests 31-37) -----------------------------------------


def test_naive_datetimes_use_the_property_timezone_and_are_stored_in_utc(
    env: Env, factory: BookingFactory
) -> None:
    ny = factory.workspace()
    prop = factory.property(ny, "new-york")
    prop.timezone = "America/New_York"
    db = env.session
    db.flush()
    source = factory.data_source(prop)
    service = BookingImportService(db, TenantContext(ny.id))
    service.save_mapping(source.id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS)

    result = service.import_file(source.id, filename="ny.csv", content=csv_bytes(en_rows()))

    assert result.succeeded
    booking = BookingRepository(db, TenantContext(ny.id)).get_by_source_record_id(source.id, "BK-1")
    assert booking is not None
    assert booking.booked_at == __import__("datetime").datetime(2026, 1, 15, 15, 30, tzinfo=UTC)
    assert booking.booked_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_an_ambiguous_date_format_stops_the_import_and_asks_for_configuration(env: Env) -> None:
    env, content = confirmed_env(env, "ambiguous_dates.csv")

    result = env.run(content)

    assert (result.status, result.error_code) == (
        ImportJobStatus.FAILED,
        Code.AMBIGUOUS_DATE_FORMAT,
    )
    assert result.details == {"fields": ["check_in", "check_out"]}
    assert env.bookings() == [] and env.count(BookingImportRow) == 0

    env.confirm(
        headers_of(content),
        format_options={"date_formats": {"check_in": "%d/%m/%Y", "check_out": "%d/%m/%Y"}},
    )
    assert env.run(content).succeeded  # explicit configuration removes the ambiguity


def test_ambiguous_number_separators_stop_the_import_and_ask_for_configuration(env: Env) -> None:
    content = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "N-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.234,56",
                "Direct",
            ],
        ]
    )
    env.confirm(STANDARD_HEADERS)

    result = env.run(content)

    assert (result.error_code, result.details) == (
        Code.AMBIGUOUS_NUMBER_FORMAT,
        {"fields": ["room_revenue"]},
    )
    env.confirm(
        STANDARD_HEADERS, format_options={"decimal_separator": ",", "thousands_separator": "."}
    )
    assert env.run(content).succeeded
    assert env.bookings()[0].room_revenue == Decimal("1234.56")


def test_an_unknown_status_is_reported_never_defaulted_to_confirmed(env: Env) -> None:
    env, content = confirmed_env(env, "unknown_status.csv")

    result = env.run(content)

    assert (result.status, result.error_code) == (ImportJobStatus.FAILED, Code.VALIDATION_FAILED)
    assert result.row_error_summary == {"BOOKING_UNKNOWN_STATUS": 1}
    assert env.bookings() == []
    invalid = env.session.scalars(
        select(BookingImportRow).where(
            BookingImportRow.validation_status == ImportRowStatus.INVALID
        )
    ).one()
    assert invalid.validation_errors == [
        {
            "field": "status",
            "code": "BOOKING_UNKNOWN_STATUS",
            "detail": "status value is not recognised",
            "value": "Pending guarantee",
        }
    ]


def test_the_mapping_profile_can_resolve_an_unknown_status(env: Env) -> None:
    env, content = confirmed_env(
        env, "unknown_status.csv", status_mapping={"Pending guarantee": "CONFIRMED"}
    )

    result = env.run(content)

    assert result.succeeded and result.bookings_created == 2
    assert {b.status for b in env.bookings()} == {BookingStatus.CONFIRMED}


def dst_rows(gap: str, fold: str) -> list[list[str]]:
    def row(record: str, booked_at: str) -> list[str]:
        return [record, booked_at, "2026-11-10", "2026-11-12", "Confirmed", "1", "100.00", "Direct"]

    return [
        STANDARD_HEADERS,
        row("OK-1", "2026-01-15 10:30"),
        row("GAP-1", gap),
        row("FOLD-1", fold),
        row("OFFSET-1", "2026-03-29T02:30:00+01:00"),
    ]


def test_local_times_that_a_dst_change_leaves_undetermined_stop_the_import(env: Env) -> None:
    """A naive booked_at in the skipped hour, or in the repeated one, is rejected: NINFA does not
    invent the instant (pickup and booking curves will depend on booked_at)."""
    env.confirm(STANDARD_HEADERS)

    result = env.run(csv_bytes(dst_rows(gap="2026-03-29 02:30", fold="2026-10-25 02:30")))

    assert (result.status, result.error_code) == (ImportJobStatus.FAILED, Code.VALIDATION_FAILED)
    assert result.row_error_summary == {
        "BOOKING_AMBIGUOUS_LOCAL_TIME": 1,
        "BOOKING_NONEXISTENT_LOCAL_TIME": 1,
    }
    assert (result.rows_total, result.rows_valid, result.rows_invalid) == (4, 2, 2)
    assert env.bookings() == []  # not even the valid rows: the import is atomic
    rows = env.session.scalars(select(BookingImportRow).order_by(BookingImportRow.row_number)).all()
    assert [r.validation_status for r in rows] == [
        ImportRowStatus.VALID,
        ImportRowStatus.INVALID,
        ImportRowStatus.INVALID,
        ImportRowStatus.VALID,  # the explicit-offset row is fine on its own
    ]
    assert [(e["field"], e["code"]) for e in rows[1].validation_errors] == [
        ("booked_at", "BOOKING_NONEXISTENT_LOCAL_TIME")
    ]
    assert [(e["field"], e["code"]) for e in rows[2].validation_errors] == [
        ("booked_at", "BOOKING_AMBIGUOUS_LOCAL_TIME")
    ]
    assert "2026-03-29" not in str([r.validation_errors for r in rows])  # diagnostics hold no value


def test_an_explicit_offset_resolves_a_dst_undetermined_time_and_the_import_succeeds(
    env: Env,
) -> None:
    env.confirm(STANDARD_HEADERS)
    fixed = csv_bytes(dst_rows(gap="2026-03-29T02:30:00+01:00", fold="2026-10-25T02:30:00+01:00"))

    result = env.run(fixed)

    assert result.succeeded and result.bookings_created == 4
    booked = {b.source_record_id: b.booked_at for b in env.bookings()}
    assert booked["GAP-1"] == dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert booked["FOLD-1"] == dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC)  # the later occurrence
    assert booked["OK-1"] == dt.datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


# --- channels through the service (tests 12-14) -----------------------------------------------


def test_channels_are_created_once_normalised_and_unclassified_when_unknown(env: Env) -> None:
    content = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "C-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "Booking.com",
            ],
            [
                "C-2",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "BOOKING.COM",
            ],
            [
                "C-3",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                " booking com ",
            ],
            [
                "C-4",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "Portale Ignoto",
            ],
            [
                "C-5",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "Diretto",
            ],
        ]
    )
    env.confirm(STANDARD_HEADERS)

    assert env.run(content).succeeded

    channels = {c.normalized_name: c for c in env.session.scalars(select(BookingChannel))}
    assert set(channels) == {"booking com", "portale ignoto", "diretto"}
    assert channels["booking com"].name == "Booking.com"  # first-seen spelling
    assert (channels["booking com"].channel_type, channels["booking com"].is_verified) == (
        ChannelType.OTA,
        False,
    )
    assert (channels["portale ignoto"].channel_type, channels["portale ignoto"].is_verified) == (
        ChannelType.OTHER,
        False,
    )
    assert channels["diretto"].channel_type == ChannelType.DIRECT
    assert (
        len({b.channel_id for b in env.bookings() if b.source_record_id in ("C-1", "C-2", "C-3")})
        == 1
    )


def test_an_existing_channel_is_reused_and_never_reclassified(env: Env) -> None:
    existing = env.factory.channel(
        env.property, "Agenzia Rossi", channel_type=ChannelType.AGENCY, is_verified=True
    )
    content = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "R-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "agenzia rossi",
            ],
        ]
    )
    env.confirm(STANDARD_HEADERS, channel_mapping={"agenzia rossi": {"channel_type": "CORPORATE"}})

    assert env.run(content).succeeded

    assert env.count(BookingChannel) == 1
    assert env.bookings()[0].channel_id == existing.id
    assert env.session.get(BookingChannel, existing.id).channel_type == ChannelType.AGENCY  # type: ignore[union-attr]


def test_the_profile_can_type_a_new_channel_and_merge_labels(env: Env) -> None:
    content = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "M-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "BKG",
            ],
            [
                "M-2",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "Booking.com",
            ],
            [
                "M-3",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "1.00",
                "Gruppo Ulivi",
            ],
        ]
    )
    env.confirm(
        STANDARD_HEADERS,
        channel_mapping={
            "BKG": {"name": "Booking.com", "channel_type": "OTA"},
            "Gruppo Ulivi": {"channel_type": "TOUR_OPERATOR"},
        },
    )

    assert env.run(content).succeeded

    channels = {c.normalized_name: c for c in env.session.scalars(select(BookingChannel))}
    assert set(channels) == {"booking com", "gruppo ulivi"}
    assert (channels["gruppo ulivi"].channel_type, channels["gruppo ulivi"].is_verified) == (
        ChannelType.TOUR_OPERATOR,
        True,
    )
    assert channels["booking com"].is_verified is True  # the customer said OTA explicitly


def test_the_same_channel_name_lives_separately_in_two_properties(env: Env) -> None:
    other_property = env.factory.property(env.workspace, "second-hotel")
    other_source = env.factory.data_source(other_property)
    content = fixture_bytes("en_comma.csv")
    env.confirm(headers_of(content))
    env.service.save_mapping(
        other_source.id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS
    )

    assert env.run(content).succeeded
    assert env.service.import_file(other_source.id, filename="f.csv", content=content).succeeded

    booking_com = env.session.scalars(
        select(BookingChannel).where(BookingChannel.normalized_name == "booking com")
    ).all()
    assert {c.property_id for c in booking_com} == {env.property.id, other_property.id}


# --- atomicity (tests 40-44) ------------------------------------------------------------------


def test_a_fully_valid_file_succeeds_with_a_coherent_job_and_staging(env: Env) -> None:
    env, content = confirmed_env(env)

    result = env.run(content)

    job = job_of(env, result)
    assert result.succeeded and (result.rows_total, result.rows_valid, result.rows_invalid) == (
        3,
        3,
        0,
    )
    assert (job.status, job.error_code, job.error_message) == (
        ImportJobStatus.SUCCEEDED,
        None,
        None,
    )
    assert (
        job.started_at is not None
        and job.finished_at is not None
        and job.started_at <= job.finished_at
    )
    statuses = env.session.scalars(select(BookingImportRow.validation_status)).all()
    assert set(statuses) == {ImportRowStatus.IMPORTED}
    assert all(b.first_import_job_id == b.last_import_job_id == job.id for b in env.bookings())


def test_one_invalid_row_fails_the_job_and_imports_nothing(env: Env) -> None:
    env, content = confirmed_env(env, "invalid_row.csv")

    result = env.run(content)

    assert (result.status, result.error_code) == (ImportJobStatus.FAILED, Code.VALIDATION_FAILED)
    assert (result.rows_total, result.rows_valid, result.rows_invalid) == (3, 2, 1)
    assert result.row_error_summary == {
        "BOOKING_CHECK_OUT_NOT_AFTER_CHECK_IN": 1,
        "BOOKING_NEGATIVE_VALUE": 1,
        "BOOKING_NOT_POSITIVE": 1,
    }
    assert env.bookings() == []  # not even the two valid rows
    assert env.count(BookingChannel) == 0  # nor their channels
    job = job_of(env, result)
    assert (job.status, job.error_code) == (ImportJobStatus.FAILED, "BOOKING_VALIDATION_FAILED")
    assert job.finished_at is not None and "1 of 3 rows" in (job.error_message or "")


def test_the_staging_diagnostics_of_a_failed_import_stay_available(env: Env) -> None:
    env, content = confirmed_env(env, "invalid_row.csv")

    result = env.run(content)

    rows = env.session.scalars(
        select(BookingImportRow)
        .where(BookingImportRow.import_job_id == result.import_job_id)
        .order_by(BookingImportRow.row_number)
    ).all()
    assert [(r.row_number, r.validation_status) for r in rows] == [
        (2, ImportRowStatus.VALID),
        (3, ImportRowStatus.INVALID),
        (4, ImportRowStatus.VALID),
    ]
    bad = rows[1]
    assert {(e["field"], e["code"]) for e in bad.validation_errors} == {
        ("check_out", "BOOKING_CHECK_OUT_NOT_AFTER_CHECK_IN"),
        ("rooms", "BOOKING_NOT_POSITIVE"),
        ("room_revenue", "BOOKING_NEGATIVE_VALUE"),
    }
    assert bad.normalized_payload is None and rows[0].normalized_payload is not None
    assert env.session.scalar(select(func.count()).select_from(ImportFile)) == 1


def test_a_failure_while_writing_bookings_rolls_the_whole_batch_back(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, content = confirmed_env(env)
    original = BookingRepository.upsert_from_import

    def write_then_crash(self: BookingRepository, **kwargs: Any) -> Any:
        original(self, **kwargs)  # every booking (and channel) is already flushed...
        raise RuntimeError("crash after writing")  # ...and then the transaction fails

    monkeypatch.setattr(BookingRepository, "upsert_from_import", write_then_crash)

    result = env.run(content)

    assert (result.status, result.error_code) == (
        ImportJobStatus.FAILED,
        Code.CANONICALIZATION_FAILED,
    )
    assert env.count(Booking) == 0 and env.count(BookingChannel) == 0  # nothing survived
    job = job_of(env, result)  # ...but the job outcome did
    assert (job.status, job.error_code) == (
        ImportJobStatus.FAILED,
        "BOOKING_CANONICALIZATION_FAILED",
    )
    assert job.finished_at is not None
    statuses = env.session.scalars(
        select(BookingImportRow.validation_status).where(BookingImportRow.import_job_id == job.id)
    ).all()
    assert set(statuses) == {ImportRowStatus.VALID}  # staged rows were NOT marked imported
    assert "crash" not in (job.error_message or "")


def test_a_database_constraint_error_during_canonicalisation_is_contained(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a concurrent import that inserted the same bookings between our read and write."""
    env, content = confirmed_env(env)
    assert env.run(content).succeeded
    monkeypatch.setattr(BookingRepository, "existing_by_source_record_ids", lambda *a, **k: {})

    result = env.run(content)

    assert (result.status, result.error_code) == (
        ImportJobStatus.FAILED,
        Code.CANONICALIZATION_FAILED,
    )
    assert result.details == {
        "constraint": "uq_bookings_workspace_id_data_source_id_source_record_id"
    }
    assert env.count(Booking) == 3  # the earlier import is intact, nothing duplicated


def test_the_job_outcome_survives_a_data_rollback_and_the_session_stays_usable(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, content = confirmed_env(env)
    monkeypatch.setattr(
        BookingRepository,
        "upsert_from_import",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("x")),
    )
    assert env.run(content).status == ImportJobStatus.FAILED

    monkeypatch.undo()
    assert env.run(content).succeeded  # a retry works, in the same session


def test_canonicalisation_is_serialised_per_data_source(env: Env, db_engine: Engine) -> None:
    env, content = confirmed_env(env)
    assert env.run(content).succeeded  # the advisory lock is held until the outer transaction ends
    other_source = env.factory.data_source(env.property)
    sql = text("SELECT pg_try_advisory_xact_lock(hashtextextended(CAST(:k AS text), 0))")

    with db_engine.connect() as other_connection:
        same_source = other_connection.execute(sql, {"k": str(env.data_source.id)}).scalar_one()
        another_source = other_connection.execute(sql, {"k": str(other_source.id)}).scalar_one()

    assert (same_source, another_source) == (False, True)


# --- idempotency (tests 45-50) ----------------------------------------------------------------


def test_importing_the_same_file_twice_creates_no_duplicates_and_writes_nothing(env: Env) -> None:
    env, content = confirmed_env(env)
    first = env.run(content)
    before = {
        b.id: (b.source_fingerprint, b.last_import_job_id, b.updated_at) for b in env.bookings()
    }

    with sql_log(env.session) as statements:
        second = env.run(content)

    assert (first.bookings_created, first.bookings_unchanged) == (3, 0)
    assert (
        second.succeeded,
        second.bookings_created,
        second.bookings_updated,
        second.bookings_unchanged,
    ) == (True, 0, 0, 3)
    assert env.count(Booking) == 3
    after = {
        b.id: (b.source_fingerprint, b.last_import_job_id, b.updated_at) for b in env.bookings()
    }
    assert after == before  # untouched: same fingerprint, still pointing at the first job
    assert not [
        s
        for s in statements
        if s.lstrip().upper().startswith(("UPDATE BOOKINGS", "INSERT INTO BOOKINGS"))
    ]
    assert second.import_job_id != first.import_job_id and env.count(ImportJob) == 2


def test_a_reimported_file_is_reported_as_a_duplicate_of_the_earlier_one(env: Env) -> None:
    env, content = confirmed_env(env)

    first, second = env.run(content), env.run(content)

    assert first.duplicate_of_import_file_id is None
    assert second.duplicate_of_import_file_id == first.import_file_id


def test_a_changed_record_updates_the_same_booking_and_keeps_its_origin(env: Env) -> None:
    env, content = confirmed_env(env)
    first = env.run(content)
    original = {b.source_record_id: b for b in env.bookings()}
    original_ids = {k: v.id for k, v in original.items()}
    modified = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "EN-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Cancelled",
                "1",
                "450.00",
                "Booking.com",
            ],
            [
                "EN-2",
                "2026-01-16 11:00",
                "2026-03-12",
                "2026-03-14",
                "Cancelled",
                "2",
                "300.50",
                "Direct",
            ],
            [
                "EN-3",
                "2026-02-01T09:00:00+01:00",
                "2026-04-01",
                "2026-04-04",
                "Confirmed",
                "1",
                "1050.00",
                "Expedia",
            ],
        ]
    )

    second = env.run(modified)

    assert (second.bookings_created, second.bookings_updated, second.bookings_unchanged) == (
        0,
        1,
        2,
    )
    after = {b.source_record_id: b for b in env.bookings()}
    assert {k: v.id for k, v in after.items()} == original_ids  # same internal ids
    changed = after["EN-1"]
    assert changed.status == BookingStatus.CANCELLED
    assert changed.first_import_job_id == first.import_job_id  # immutable origin
    assert changed.last_import_job_id == second.import_job_id
    assert changed.source_fingerprint != "" and env.count(Booking) == 3
    assert after["EN-2"].last_import_job_id == first.import_job_id  # untouched ones keep theirs


def test_a_changed_amount_or_channel_is_also_an_update(env: Env) -> None:
    env, content = confirmed_env(env)
    env.run(content)
    modified = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "EN-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "500.00",
                "Airbnb",
            ],
        ]
    )

    result = env.run(modified)

    assert (result.bookings_updated, result.bookings_created) == (1, 0)
    booking = next(b for b in env.bookings() if b.source_record_id == "EN-1")
    assert (booking.room_revenue, booking.channel.normalized_name) == (Decimal("500.00"), "airbnb")


def test_the_same_source_record_twice_in_one_file_is_rejected_not_resolved(env: Env) -> None:
    env, content = confirmed_env(env, "duplicate_source_id.csv")

    result = env.run(content)

    assert (result.status, result.error_code) == (ImportJobStatus.FAILED, Code.VALIDATION_FAILED)
    assert result.row_error_summary == {"BOOKING_DUPLICATE_SOURCE_ID": 2}
    assert env.bookings() == []  # no "last row wins", not even the valid DUP-2
    rows = env.session.scalars(select(BookingImportRow).order_by(BookingImportRow.row_number)).all()
    assert [r.validation_status for r in rows] == [
        ImportRowStatus.INVALID,
        ImportRowStatus.VALID,
        ImportRowStatus.INVALID,
    ]
    assert rows[0].validation_errors[0]["detail"] == "same source_record_id on row(s) 4"


def test_a_row_without_a_source_id_stops_the_import_no_id_is_invented(env: Env) -> None:
    content = csv_bytes(
        [
            STANDARD_HEADERS,
            [
                "",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "450.00",
                "Booking.com",
            ],
            [
                "OK-1",
                "2026-01-15 10:30",
                "2026-03-10",
                "2026-03-13",
                "Confirmed",
                "1",
                "450.00",
                "Booking.com",
            ],
        ]
    )
    env.confirm(STANDARD_HEADERS)

    result = env.run(content)

    assert result.error_code == Code.VALIDATION_FAILED
    assert result.row_error_summary == {"BOOKING_REQUIRED_VALUE_MISSING": 1}
    assert env.bookings() == []


def test_identity_is_per_data_source_the_same_id_in_another_source_is_another_booking(
    env: Env,
) -> None:
    other_source = env.factory.data_source(env.property)
    content = fixture_bytes("en_comma.csv")
    env.confirm(headers_of(content))
    env.service.save_mapping(
        other_source.id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS
    )

    first = env.run(content)
    second = env.service.import_file(other_source.id, filename="f.csv", content=content)

    assert (first.bookings_created, second.bookings_created, second.bookings_unchanged) == (3, 3, 0)
    assert env.count(Booking) == 6
    assert (
        second.duplicate_of_import_file_id is None
    )  # a file hash is never compared across sources


def test_file_hashes_are_recorded_and_never_globally_unique(
    env: Env, factory: BookingFactory
) -> None:
    env, content = confirmed_env(env)
    other_workspace = factory.workspace()
    other_property = factory.property(other_workspace)
    other_source = factory.data_source(other_property)
    other = BookingImportService(env.session, TenantContext(other_workspace.id))
    other.save_mapping(other_source.id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS)

    env.run(content)
    env.run(content)
    foreign = other.import_file(other_source.id, filename="same.csv", content=content)

    hashes = env.session.scalars(select(ImportFile.sha256)).all()
    assert len(hashes) == 3 and len(set(hashes)) == 1 and hashes[0] is not None
    assert foreign.succeeded and foreign.duplicate_of_import_file_id is None


# --- data source and tenant rules (tests 51-54) -----------------------------------------------


def test_only_bookings_file_upload_sources_of_this_workspace_are_accepted(
    env: Env, factory: BookingFactory
) -> None:
    content = fixture_bytes("en_comma.csv")
    env.confirm(headers_of(content))
    assert env.run(content).succeeded  # BOOKINGS: accepted

    costs = factory.data_source(env.property, DataSourceDomain.COSTS)
    labor = factory.data_source(env.property, DataSourceDomain.LABOR)
    inactive = factory.data_source(env.property)
    inactive.is_active = False
    foreign_workspace = factory.workspace()
    foreign_source = factory.data_source(factory.property(foreign_workspace))
    jobs_before = env.count(ImportJob)

    for source, reason in (
        (costs, "wrong_domain"),
        (labor, "wrong_domain"),
        (inactive, "inactive"),
        (foreign_source, "not_found"),
    ):
        with pytest.raises(BookingImportError) as info:
            env.service.import_file(source.id, filename="f.csv", content=content)
        assert info.value.error_code == Code.INVALID_DATA_SOURCE
        assert info.value.details == {"reason": reason}
    assert env.count(ImportJob) == jobs_before  # nothing was created for any of them


def test_a_data_source_of_another_property_is_refused_when_a_property_is_declared(
    env: Env, factory: BookingFactory
) -> None:
    other_property = factory.property(env.workspace, "other-hotel")
    content = fixture_bytes("en_comma.csv")
    env.confirm(headers_of(content))

    with pytest.raises(BookingImportError) as info:
        env.service.import_file(
            env.data_source.id, filename="f.csv", content=content, property_id=other_property.id
        )

    assert (info.value.error_code, info.value.details) == (
        Code.INVALID_DATA_SOURCE,
        {"reason": "property_mismatch"},
    )
    assert env.service.import_file(
        env.data_source.id, filename="f.csv", content=content, property_id=env.property.id
    ).succeeded


def test_mapping_and_suggestions_apply_the_same_data_source_rules(
    env: Env, factory: BookingFactory
) -> None:
    costs = factory.data_source(env.property, DataSourceDomain.COSTS)

    with pytest.raises(BookingImportError) as suggestion:
        env.service.suggest_mapping(costs.id, filename="f.csv", content=b"a\n1\n")
    with pytest.raises(BookingImportError) as mapping:
        env.service.save_mapping(
            costs.id, headers=STANDARD_HEADERS, column_mapping=STANDARD_COLUMNS
        )

    assert suggestion.value.error_code == mapping.value.error_code == Code.INVALID_DATA_SOURCE


def test_an_archived_property_cannot_receive_imports(env: Env) -> None:
    from app.modules.properties.repository import PropertyRepository

    PropertyRepository(env.session, env.context).archive(env.property.id)

    with pytest.raises(BookingImportError) as info:
        env.run(fixture_bytes("en_comma.csv"))

    assert info.value.details == {"reason": "property_unavailable"}


# --- data minimisation (tests 38-39) ----------------------------------------------------------

PII = [
    "Mario Rossi",
    "mario@example.com",
    "Anna Bianchi",
    "anna.bianchi@example.com",
    "+39 000 0000001",
    "+39 000 0000002",
    "Allergia ai crostacei",
    "Arrivo tardi",
]


def persisted_hits(session: Session, needles: list[str]) -> list[tuple[str, str]]:
    """Every (table, needle) pair where the needle appears anywhere in any persisted row."""
    tables = (
        session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )
    hits = []
    for table in tables:
        for needle in needles:
            found = session.execute(
                text(f'SELECT count(*) FROM "{table}" t WHERE CAST(t AS text) ILIKE :pattern'),
                {"pattern": f"%{needle}%"},
            ).scalar_one()
            if found:
                hits.append((table, needle))
    return hits


def test_unmapped_columns_are_never_persisted(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env, content = confirmed_env(env, "pii_unmapped_columns.csv")
    assert (
        b"Mario Rossi" in content and b"mario@example.com" in content
    )  # the file does contain them

    result = env.run(content)

    assert result.succeeded and result.bookings_created == 2
    assert persisted_hits(env.session, PII) == []  # not in ANY table: staging, jobs, bookings, ...
    assert not [n for n in PII if n in caplog.text]  # nor in the logs
    staged = env.session.scalars(select(BookingImportRow)).all()
    assert all(set(r.mapped_payload) <= set(STANDARD_COLUMNS) for r in staged)
    assert all(
        set(r.normalized_payload or {})
        <= {
            "source_record_id",
            "booked_at",
            "check_in",
            "check_out",
            "status",
            "rooms",
            "guests",
            "room_revenue",
            "total_revenue",
            "channel_name",
            "channel_key",
            "channel_type",
            "channel_verified",
            "commission_amount",
            "commission_rate",
            "cancelled_at",
            "room_type",
            "rate_plan",
        }
        for r in staged
    )


def test_failed_imports_do_not_leak_unmapped_values_in_errors_results_or_logs(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    env, content = confirmed_env(
        env, "unknown_status.csv"
    )  # fails: has PII columns AND a bad status

    result = env.run(content)

    assert result.status == ImportJobStatus.FAILED
    surfaces = [repr(result), caplog.text, str(job_of(env, result).error_message)]
    surfaces += [
        str(r.validation_errors) + str(r.mapped_payload)
        for r in env.session.scalars(select(BookingImportRow))
    ]
    joined = "\n".join(surfaces)
    for needle in PII:
        assert needle not in joined, needle
    assert persisted_hits(env.session, PII) == []


def test_control_a_column_that_is_explicitly_mapped_is_stored(env: Env) -> None:
    """Proves the leak detector works: data IS persisted exactly where the customer mapped it."""
    content = fixture_bytes("pii_unmapped_columns.csv")
    columns = {**STANDARD_COLUMNS, "room_type": {"column": "guest_email"}}
    env.confirm(headers_of(content), columns)

    assert env.run(content).succeeded

    assert ("bookings", "mario@example.com") in persisted_hits(env.session, ["mario@example.com"])
    assert persisted_hits(env.session, ["Mario Rossi", "+39 000 0000001"]) == []


def test_the_source_filename_is_reduced_to_a_base_name(env: Env) -> None:
    env, content = confirmed_env(env)

    result = env.run(content, "C:\\Users\\mario\\Desktop\\prenotazioni.csv")

    stored = env.session.get(ImportFile, result.import_file_id)
    assert stored is not None and stored.original_filename == "prenotazioni.csv"
    assert persisted_hits(env.session, ["mario"]) == []


# --- observability ----------------------------------------------------------------------------


def test_the_import_logs_ids_and_counts_only(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.modules.bookings")
    env, content = confirmed_env(env)

    result = env.run(content)

    text_ = caplog.text
    for expected in (
        str(env.workspace.id),
        str(env.property.id),
        str(env.data_source.id),
        str(result.import_job_id),
        str(result.import_file_id),
        "booking import started",
        "booking import finished",
        "created=3",
    ):
        assert expected in text_, expected
    for row_value in ("EN-1", "Booking.com", "450.00", "2026-03-10"):
        assert row_value not in text_, row_value


# --- architecture -----------------------------------------------------------------------------


def test_the_import_service_does_not_depend_on_the_web_framework() -> None:
    code = (
        "import sys, app.modules.bookings.service; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )

    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert output.stdout.strip() == "[]"


def test_import_errors_are_application_errors_with_stable_codes() -> None:
    error = BookingImportError(Code.MAPPING_REQUIRED, "human text may change", details={"x": 1})

    assert isinstance(error, AppError)
    assert (error.code, error.error_code, error.status_code) == (
        "BOOKING_MAPPING_REQUIRED",
        Code.MAPPING_REQUIRED,
        422,
    )
    assert {c.value for c in Code} >= {
        "BOOKING_MAPPING_REQUIRED",
        "BOOKING_SOURCE_SCHEMA_CHANGED",
        "BOOKING_VALIDATION_FAILED",
        "BOOKING_DUPLICATE_SOURCE_ID",
        "BOOKING_UNSUPPORTED_FILE_TYPE",
        "BOOKING_AMBIGUOUS_DATE_FORMAT",
        "BOOKING_UNKNOWN_STATUS",
        "BOOKING_INVALID_DATA_SOURCE",
    }
