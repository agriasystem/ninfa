"""Helpers for the booking tests: mapping builders and in-memory CSV/XLSX file builders."""

import csv
import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from app.modules.bookings.mapping import MappingConfig
from app.modules.bookings.normalization import NormalizationContext

# Repository-level synthetic fixtures (never real customer data).
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bookings"

# A complete mapping for a file with English headers and ISO dates.
STANDARD_COLUMNS: dict[str, dict[str, Any]] = {
    "source_record_id": {"column": "Booking ID"},
    "booked_at": {"column": "Booked At"},
    "check_in": {"column": "Check-in"},
    "check_out": {"column": "Check-out"},
    "status": {"column": "Status"},
    "rooms": {"column": "Rooms"},
    "room_revenue": {"column": "Room Revenue"},
    "channel": {"column": "Channel"},
}
STANDARD_HEADERS = [column["column"] for column in STANDARD_COLUMNS.values()]


def make_config(
    columns: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    add_columns: Mapping[str, Mapping[str, Any]] | None = None,
    **sections: Any,
) -> MappingConfig:
    """A validated MappingConfig; `sections` may set status_mapping, channel_mapping, ..."""
    column_mapping = dict(columns if columns is not None else STANDARD_COLUMNS)
    column_mapping.update(add_columns or {})
    return MappingConfig.parse({"column_mapping": column_mapping, **sections})


def make_context(
    config: MappingConfig | None = None, timezone: str = "Europe/Rome"
) -> NormalizationContext:
    return NormalizationContext(ZoneInfo(timezone), config or make_config())


def csv_bytes(
    rows: Sequence[Sequence[Any]],
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
    bom: bool = False,
    newline: str = "\n",
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator=newline)
    writer.writerows(rows)
    data = buffer.getvalue().encode(encoding)
    return (b"\xef\xbb\xbf" + data) if bom else data


def xlsx_bytes(
    sheets: Mapping[str, Sequence[Sequence[Any]]], *, hidden: Sequence[str] = ()
) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
        if name in hidden:
            sheet.sheet_state = "hidden"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
