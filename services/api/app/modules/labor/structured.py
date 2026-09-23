"""Structured CSV/XLSX labor files: mapped columns -> validated canonical entries.

Reading the file (encodings, delimiters, sheets, header row, duplicate headers) is the Gate 2
reader, reused as it is. Here the MAPPED columns of every row are read (every other column is
dropped at once: an employee name, e-mail, phone, tax code, address or medical note that was not
mapped never reaches a `Cell`), values are normalised by explicit rules (ISO dates or a configured
pattern, configured number separators: never guessed), and each row becomes ONE canonical entry
(there is no document/header grouping: a labor file has no invoice-like nesting).
"""

import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.iso4217 import ISO_4217_CODES
from app.modules.bookings.parsers import Cell, SourceTable
from app.modules.bookings.text import normalize_key
from app.modules.labor.canonical import CanonicalEntry, hours_to_minutes
from app.modules.labor.classification import classify_role
from app.modules.labor.errors import LaborErrorCode, LaborImportError, RowIssue
from app.modules.labor.mapping import (
    DATE_FIELDS,
    DECIMAL_FIELDS,
    LaborField,
    LaborMappingConfig,
    header_index,
    normalize_header,
    resolve_labor_category,
)

F = LaborField
_ISO_DATE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
_SLASHED_DATE = re.compile(
    r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_MAX_ROLE_LENGTH = 200


def is_slashed_date(text: str) -> bool:
    """Day/month or month/day first: cannot be read without a configured pattern."""
    return bool(_SLASHED_DATE.match(text.strip()))


# --- extraction: the data-minimisation boundary -----------------------------------------------


def extract(table: SourceTable, config: LaborMappingConfig) -> list[tuple[int, dict[F, Cell]]]:
    """(row number, values of the MAPPED columns) for every row that has at least one. Whatever
    else the row holds (an unmapped employee name, e-mail, ...) is dropped here and never reaches
    staging, logs or errors."""
    index = header_index(table.headers)
    positions = {
        field: index[normalize_header(column)] for field, column in config.mapped_columns().items()
    }
    constants = config.constants()
    rows: list[tuple[int, dict[F, Cell]]] = []
    for row in table.rows():
        values: dict[F, Cell] = {field: row.cells[i] for field, i in positions.items()}
        if all(value is None for value in values.values()):
            continue
        values.update(constants)
        rows.append((row.number, values))
    return rows


def require_explicit_formats(
    rows: list[tuple[int, dict[F, Cell]]], config: LaborMappingConfig
) -> None:
    """`01/02/2026` and `1,234` mean two things: the profile must say which, before any row is
    judged, so the customer is asked once."""
    options = config.format_options
    ambiguous_dates = sorted(
        field.value
        for field in DATE_FIELDS
        if field in config.column_mapping
        and field not in options.date_formats
        and any(
            isinstance(values.get(field), str) and is_slashed_date(str(values[field]))
            for _, values in rows
        )
    )
    if ambiguous_dates:
        raise LaborImportError(
            LaborErrorCode.AMBIGUOUS_DATE_FORMAT,
            "Some date columns are written day/month/year or month/day/year: set the date format",
            details={"fields": ambiguous_dates},
        )
    if options.decimal_separator is None and options.thousands_separator is None:
        ambiguous_numbers = sorted(
            field.value
            for field in DECIMAL_FIELDS
            if field in config.column_mapping
            and any(
                isinstance(values.get(field), str)
                and ("," in str(values[field]) or str(values[field]).count(".") > 1)
                for _, values in rows
            )
        )
        if ambiguous_numbers:
            raise LaborImportError(
                LaborErrorCode.AMBIGUOUS_NUMBER_FORMAT,
                "Some hour/cost columns use separators that can mean two things: set them",
                details={"fields": ambiguous_numbers},
            )


# --- one value -----------------------------------------------------------------------------------


class _BadValueError(Exception):
    def __init__(self, code: LaborErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _text(cell: Cell) -> str | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER)
    if isinstance(cell, float):
        return str(int(cell)) if cell.is_integer() else repr(cell)
    if isinstance(cell, datetime | date):
        return cell.isoformat()
    text = str(cell).strip()
    return text or None


def _date(cell: Cell, field: LaborField, config: LaborMappingConfig) -> date | None:
    if cell is None:
        return None
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    if not isinstance(cell, str):
        raise _BadValueError(LaborErrorCode.INVALID_DATE)
    text = cell.strip()
    pattern = config.format_options.date_formats.get(field)
    try:
        if pattern is not None:
            return datetime.strptime(text, pattern).date()
        if _ISO_DATE.match(text):
            return datetime.fromisoformat(text.replace("/", "-", 2)).date()
    except ValueError:
        raise _BadValueError(LaborErrorCode.INVALID_DATE) from None
    raise _BadValueError(LaborErrorCode.INVALID_DATE)


def _decimal(cell: Cell, config: LaborMappingConfig) -> Decimal | None:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER)
    if isinstance(cell, Decimal):
        value = cell
    elif isinstance(cell, int):
        value = Decimal(cell)
    elif isinstance(cell, float):
        value = Decimal(repr(cell))  # Excel doubles: through the shortest repr, never the binary
    elif isinstance(cell, str):
        value = _parse_decimal_text(cell, config)
    else:
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER)
    if not value.is_finite():
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER)
    return value


def _parse_decimal_text(text: str, config: LaborMappingConfig) -> Decimal:
    """`"7.5"`, `"7,5"` as configured; never guessed."""
    cleaned = text.strip()
    decimal = config.format_options.decimal_separator or "."
    thousands = config.format_options.thousands_separator
    dec = re.escape(decimal)
    if thousands:
        thou = re.escape(thousands)
        pattern = rf"^-?(?:\d+|\d{{1,3}}(?:{thou}\d{{3}})+)(?:{dec}\d+)?$"
    else:
        pattern = rf"^-?\d+(?:{dec}\d+)?$"
    if not re.match(pattern, cleaned):
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER)
    normalised = cleaned.replace(thousands, "") if thousands else cleaned
    try:
        return Decimal(normalised.replace(decimal, "."))
    except InvalidOperation:
        raise _BadValueError(LaborErrorCode.INVALID_NUMBER) from None


# --- one row -> one canonical entry ------------------------------------------------------------


class ParsedLaborRow:
    """One source row, parsed field by field, with its issues (a bad field never hides the rest).

    `mapped` holds ONLY canonical, minimised values (as text), for staging.
    """

    def __init__(self, number: int, values: dict[F, Cell], config: LaborMappingConfig) -> None:
        self.number = number
        self.issues: list[RowIssue] = []
        self.mapped: dict[str, Any] = {}
        self._values = values
        self._config = config

        self.work_date = self._required_date(F.WORK_DATE)
        self.role_raw = self._role()
        self.explicit_category = self._category()
        self.planned_hours = self._hours(F.PLANNED_HOURS)
        self.actual_hours = self._hours(F.ACTUAL_HOURS)
        self._check_hours_present()
        self.planned_cost = self._amount(F.PLANNED_COST)
        self.actual_cost = self._amount(F.ACTUAL_COST)
        self.currency = self._currency()

        self.planned_minutes = self._minutes(F.PLANNED_HOURS, self.planned_hours)
        self.actual_minutes = self._minutes(F.ACTUAL_HOURS, self.actual_hours)

    # --- helpers ---------------------------------------------------------------------------

    def _add(self, field: F, code: LaborErrorCode, value: str | None = None) -> None:
        self.issues.append(RowIssue(field.value, code, value=value))

    def _record(self, field: F, text: str | None) -> None:
        if text is not None:
            self.mapped[field.value] = text if len(text) <= 500 else text[:500] + "…"

    def _safe(self, field: F, reader: Any) -> Any:
        try:
            return reader(self._values.get(field))
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None

    def _required_date(self, field: F) -> date | None:
        try:
            value = _date(self._values.get(field), field, self._config)
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        if value is None:
            self._add(field, LaborErrorCode.REQUIRED_VALUE_MISSING)
            return None
        self._record(field, value.isoformat())
        return value

    def _role(self) -> str | None:
        text: str | None = self._safe(F.ROLE, _text)
        if text is None:
            return None
        if len(text) > _MAX_ROLE_LENGTH:
            self._add(F.ROLE, LaborErrorCode.VALUE_TOO_LONG)
            return None
        self._record(F.ROLE, text)
        return text

    def _category(self) -> Any:
        text = self._safe(F.LABOR_CATEGORY, _text)
        if text is None:
            return None
        self._record(F.LABOR_CATEGORY, text)
        category = resolve_labor_category(text)
        if category is None:
            self._add(F.LABOR_CATEGORY, LaborErrorCode.UNKNOWN_CATEGORY, value=text[:80])
        return category

    def _hours(self, field: F) -> Decimal | None:
        try:
            value = _decimal(self._values.get(field), self._config)
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        if value is None:
            return None
        if value < 0:
            self._add(field, LaborErrorCode.NEGATIVE_VALUE)
            return None
        self._record(field, format(value, "f"))
        return value

    def _check_hours_present(self) -> None:
        if self.planned_hours is None and self.actual_hours is None:
            has_issue = any(
                issue.field in {F.PLANNED_HOURS.value, F.ACTUAL_HOURS.value}
                for issue in self.issues
            )
            if not has_issue:  # a bad value already explains the absence; do not double-report
                self._add(F.PLANNED_HOURS, LaborErrorCode.HOURS_MISSING)

    def _minutes(self, field: F, hours: Decimal | None) -> int | None:
        if hours is None:
            return None
        try:
            return hours_to_minutes(hours)
        except ValueError:
            self._add(field, LaborErrorCode.FRACTIONAL_MINUTES)
            return None

    def _amount(self, field: F) -> Decimal | None:
        try:
            value = _decimal(self._values.get(field), self._config)
        except _BadValueError as bad:
            self._add(field, bad.code)
            return None
        if value is None:
            return None
        if value < 0:
            self._add(field, LaborErrorCode.NEGATIVE_VALUE)
            return None
        self._record(field, format(value, "f"))
        return value

    def _currency(self) -> str | None:
        raw: str | None = self._safe(F.CURRENCY, _text)
        currency = None if raw is None else raw.strip().upper()
        has_cost = self.planned_cost is not None or self.actual_cost is not None
        if currency is None:
            if has_cost:
                self._add(F.CURRENCY, LaborErrorCode.CURRENCY_REQUIRED)
            return None
        if currency not in ISO_4217_CODES:
            self._add(F.CURRENCY, LaborErrorCode.INVALID_CURRENCY)
            return None
        self._record(F.CURRENCY, currency)
        return currency

    # --- assembly ----------------------------------------------------------------------------

    def to_entry(self) -> CanonicalEntry | None:
        """The canonical entry, or None while `self.issues` explains why (never both silent)."""
        if self.issues or self.work_date is None:
            return None
        role_normalized = normalize_key(self.role_raw) if self.role_raw else None
        classification = classify_role(
            role_normalized,
            explicit=self.explicit_category,
            role_mapping=self._config.role_mapping,
        )
        return CanonicalEntry(
            source_row_number=self.number,
            work_date=self.work_date,
            role_raw=self.role_raw,
            role_normalized=role_normalized,
            labor_category=classification.category,
            planned_minutes=self.planned_minutes,
            actual_minutes=self.actual_minutes,
            planned_cost=self.planned_cost,
            actual_cost=self.actual_cost,
            currency=self.currency,
            classification_method=classification.method,
            classification_confidence=classification.confidence,
        )


def parse_structured(
    rows: Iterable[tuple[int, dict[F, Cell]]], config: LaborMappingConfig
) -> list[ParsedLaborRow]:
    return [ParsedLaborRow(number, values, config) for number, values in rows]
