"""The ONE canonical file convention NINFA accepts for bookings and labor (CSV), shared by every
caller that turns a file into an import: the pilot CLI (`app/cli/imports.py`, Gate 21B) and the
data-source API (`app/modules/data_sources`).

The column headers ARE the import services' own canonical field names
(`app.modules.bookings.mapping.CanonicalField`, `app.modules.labor.mapping.LaborField`), dates are
`YYYY-MM-DD`, decimals use `.`, the encoding is UTF-8 and the delimiter is `,`. The mapping a caller
confirms is derived from whichever of those names are present as headers - there is deliberately no
mapping-suggestion step and no generic user-configurable mapping engine (see
docs/architecture/pilot-readiness-v1.md, "Data intake"; "Smart Import V2" is the follow-up).

Nothing here parses, validates or canonicalises a row: that stays in the import services.
"""

import csv
import io
from enum import StrEnum

from app.modules.bookings.mapping import CanonicalField, normalize_header
from app.modules.labor.mapping import LaborField

_BOOKING_DATE_FIELDS = (
    CanonicalField.BOOKED_AT,
    CanonicalField.CHECK_IN,
    CanonicalField.CHECK_OUT,
    CanonicalField.CANCELLED_AT,
)


def booking_format_options() -> dict[str, object]:
    return {
        "delimiter": ",",
        "encoding": "utf-8",
        "date_formats": {field.value: "%Y-%m-%d" for field in _BOOKING_DATE_FIELDS},
        "decimal_separator": ".",
    }


def labor_format_options() -> dict[str, object]:
    return {
        "delimiter": ",",
        "encoding": "utf-8",
        "date_formats": {LaborField.WORK_DATE.value: "%Y-%m-%d"},
        "decimal_separator": ".",
    }


def identity_column_mapping(headers: list[str], fields: type[StrEnum]) -> dict[str, dict[str, str]]:
    """Map every canonical field whose exact name is present as a header, verbatim, to itself -
    the one convention this module supports. Never a fuzzy or suggested mapping."""
    present = {normalize_header(h) for h in headers}
    return {
        field.value: {"column": field.value}
        for field in fields
        if normalize_header(field.value) in present
    }


def read_headers(content: bytes) -> list[str]:
    """The header row only, exactly as the reader will see it (UTF-8, comma-delimited).

    Raises `UnicodeDecodeError` when the bytes are not UTF-8: the caller turns that into its own
    "unreadable file" outcome."""
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    return next(reader, [])


def unrecognized_columns(headers: list[str], fields: type[StrEnum]) -> list[str]:
    """Every header that does NOT normalize-match any of `fields`' canonical names - the exact
    complement of what `identity_column_mapping` maps. Original header spelling is kept, order is
    first-occurrence-in-the-file and duplicates are dropped, so the output is deterministic. A typo
    of an optional field and a genuinely irrelevant extra column are indistinguishable here, on
    purpose (no fuzzy matching anywhere in this codebase)."""
    known = {normalize_header(field.value) for field in fields}
    seen: set[str] = set()
    unrecognized: list[str] = []
    for header in headers:
        key = normalize_header(header)
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        unrecognized.append(header)
    return unrecognized


__all__ = [
    "booking_format_options",
    "identity_column_mapping",
    "labor_format_options",
    "read_headers",
    "unrecognized_columns",
]
