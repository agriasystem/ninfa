"""Turning mapped source values into a canonical booking, deterministically.

No guessing anywhere: a value is either read by an explicit rule (ISO formats, a date pattern
or separators chosen in the mapping profile) or reported as a problem. Money is `Decimal` from
the first character to the database column; there is no float in the pipeline (floats coming
from Excel cells are converted through their shortest repr and must be exact to the cent).
"""

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.bookings.channels import ChannelSpec, resolve_channel
from app.modules.bookings.errors import BookingErrorCode, RowIssue
from app.modules.bookings.mapping import DATETIME_FIELDS, CanonicalField, MappingConfig
from app.modules.bookings.models import MAX_MONEY, BookingStatus, ChannelType
from app.modules.bookings.parsers import Cell
from app.modules.bookings.statuses import resolve_status

F = CanonicalField
_CENT = Decimal("0.01")
_RATE_STEP = Decimal("0.0001")
_MAX_INT = 2_147_483_647
_MAX_TEXT = 200
_MAX_SOURCE_ID = 255
_MAX_DIAGNOSTIC_VALUE = 80

# Unambiguous ISO-like forms: year first, so day/month order is never in question.
_ISO_DATE = re.compile(
    r"^\d{4}[-/]\d{2}[-/]\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
# Day/month first or month/day first: the two cannot be told apart without configuration.
_SLASHED_DATE = re.compile(
    r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?$"
)


# --- the canonical value ----------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedBooking:
    source_record_id: str
    booked_at: datetime  # timezone-aware, UTC
    check_in: date
    check_out: date
    status: BookingStatus
    rooms: int
    guests: int | None
    room_revenue: Decimal
    total_revenue: Decimal | None
    channel: ChannelSpec
    commission_amount: Decimal | None
    commission_rate: Decimal | None
    cancelled_at: datetime | None
    room_type: str | None
    rate_plan: str | None

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe form stored in the staging table (Decimals as strings, dates as ISO)."""
        return {
            "source_record_id": self.source_record_id,
            "booked_at": self.booked_at.isoformat(),
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat(),
            "status": self.status.value,
            "rooms": self.rooms,
            "guests": self.guests,
            "room_revenue": _money(self.room_revenue),
            "total_revenue": _money(self.total_revenue),
            "channel_name": self.channel.name,
            "channel_key": self.channel.normalized_name,
            "channel_type": self.channel.channel_type.value,
            "channel_verified": self.channel.is_verified,
            "commission_amount": _money(self.commission_amount),
            "commission_rate": _rate(self.commission_rate),
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "room_type": self.room_type,
            "rate_plan": self.rate_plan,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "NormalizedBooking":
        def opt_decimal(key: str) -> Decimal | None:
            return Decimal(payload[key]) if payload[key] is not None else None

        def opt_datetime(key: str) -> datetime | None:
            return datetime.fromisoformat(payload[key]) if payload[key] is not None else None

        return cls(
            source_record_id=payload["source_record_id"],
            booked_at=datetime.fromisoformat(payload["booked_at"]),
            check_in=date.fromisoformat(payload["check_in"]),
            check_out=date.fromisoformat(payload["check_out"]),
            status=BookingStatus(payload["status"]),
            rooms=payload["rooms"],
            guests=payload["guests"],
            room_revenue=Decimal(payload["room_revenue"]),
            total_revenue=opt_decimal("total_revenue"),
            channel=ChannelSpec(
                payload["channel_name"],
                payload["channel_key"],
                ChannelType(payload["channel_type"]),
                payload["channel_verified"],
            ),
            commission_amount=opt_decimal("commission_amount"),
            commission_rate=opt_decimal("commission_rate"),
            cancelled_at=opt_datetime("cancelled_at"),
            room_type=payload["room_type"],
            rate_plan=payload["rate_plan"],
        )

    def fingerprint(self) -> str:
        """SHA-256 of the business content of the record, and of nothing technical.

        Same source record + same fingerprint = nothing changed. Excludes import timestamps and
        job ids by construction; includes the channel by its normalised name (not its id).
        """
        document = {
            "v": 1,
            "source_record_id": self.source_record_id,
            "booked_at": self.booked_at.astimezone(UTC).isoformat(),
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat(),
            "status": self.status.value,
            "rooms": self.rooms,
            "guests": self.guests,
            "room_revenue": _money(self.room_revenue),
            "total_revenue": _money(self.total_revenue),
            "channel": self.channel.normalized_name,
            "commission_amount": _money(self.commission_amount),
            "commission_rate": _rate(self.commission_rate),
            "cancelled_at": self.cancelled_at.astimezone(UTC).isoformat()
            if self.cancelled_at
            else None,
            "room_type": self.room_type,
            "rate_plan": self.rate_plan,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, ".2f")


def _rate(value: Decimal | None) -> str | None:
    return None if value is None else format(value, ".4f")


# --- context ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizationContext:
    """Everything a row needs besides its own values: the property's timezone and the profile."""

    timezone: ZoneInfo
    config: MappingConfig

    @property
    def date_formats(self) -> Mapping[CanonicalField, str]:
        return self.config.format_options.date_formats

    @property
    def decimal_separator(self) -> str | None:
        return self.config.format_options.decimal_separator

    @property
    def thousands_separator(self) -> str | None:
        return self.config.format_options.thousands_separator


class _FieldError(Exception):
    """Internal: a field cannot be normalised. Converted to a RowIssue by the caller."""

    def __init__(
        self, code: BookingErrorCode, detail: str | None = None, value: str | None = None
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.detail = detail
        self.value = value


# --- dates and datetimes ----------------------------------------------------------------------


def _parse_datetime_string(field: CanonicalField, text: str, ctx: NormalizationContext) -> datetime:
    """Read a date/datetime text by the configured pattern or an ISO form. May be naive."""
    pattern = ctx.date_formats.get(field)
    try:
        if pattern is not None:
            return datetime.strptime(text, pattern)
        if _ISO_DATE.match(text):
            return datetime.fromisoformat(text.replace("/", "-", 2))
    except ValueError:
        raise _FieldError(
            _date_code(field), "value does not match the expected date format"
        ) from None
    raise _FieldError(_date_code(field), "unrecognised date format (configure a date format)")


def _date_code(field: CanonicalField) -> BookingErrorCode:
    return (
        BookingErrorCode.INVALID_DATETIME
        if field in DATETIME_FIELDS
        else BookingErrorCode.INVALID_DATE
    )


def _as_utc(moment: datetime, ctx: NormalizationContext) -> datetime:
    """The instant a datetime denotes, in UTC, without ever choosing between two readings.

    - With an explicit offset/timezone: converted as it is.
    - Naive: read in the property's timezone, but only if that local time identifies exactly one
      instant. During a daylight-saving change it may not (the clock skips an hour, or shows an
      hour twice): the two candidate readings (`fold=0` / `fold=1`) then have different offsets
      and the value is rejected instead of guessed: NONEXISTENT_LOCAL_TIME when the local time
      never happens, AMBIGUOUS_LOCAL_TIME when it happens twice.
    """
    if moment.tzinfo is not None:
        return moment.astimezone(UTC)
    first = moment.replace(tzinfo=ctx.timezone, fold=0)
    second = moment.replace(tzinfo=ctx.timezone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first.astimezone(UTC)  # the one and only instant
    if first.astimezone(UTC).astimezone(ctx.timezone).replace(tzinfo=None) != moment:
        raise _FieldError(
            BookingErrorCode.NONEXISTENT_LOCAL_TIME,
            "this local time does not exist in the property timezone (daylight-saving change): "
            "the source must give an explicit UTC offset",
        )
    raise _FieldError(
        BookingErrorCode.AMBIGUOUS_LOCAL_TIME,
        "this local time happens twice in the property timezone (daylight-saving change): "
        "the source must give an explicit UTC offset",
    )


def parse_datetime_value(field: CanonicalField, value: Cell, ctx: NormalizationContext) -> datetime:
    """A timezone-aware UTC datetime. A value with an explicit offset is converted; a naive one
    is read in the property's timezone if that identifies a single instant, otherwise it is
    rejected (see `_as_utc`). A date without time means local midnight, under the same rule.
    """
    if isinstance(value, datetime):
        return _as_utc(value, ctx)
    if isinstance(value, date):
        return _as_utc(datetime(value.year, value.month, value.day), ctx)
    if isinstance(value, str):
        return _as_utc(_parse_datetime_string(field, value, ctx), ctx)
    raise _FieldError(_date_code(field), "not a date")


def parse_date_value(field: CanonicalField, value: Cell, ctx: NormalizationContext) -> date:
    """A calendar date in the property's own timezone (no timezone conversion for naive input)."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(ctx.timezone).date()
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        moment = _parse_datetime_string(field, value, ctx)
        if moment.tzinfo is not None:
            return moment.astimezone(ctx.timezone).date()
        return moment.date()
    raise _FieldError(_date_code(field), "not a date")


# --- numbers ----------------------------------------------------------------------------------


def parse_decimal_string(
    text: str, decimal_separator: str | None, thousands_separator: str | None
) -> Decimal:
    """Parse "1234.56", "1,234.56", "1234,56" or "1.234,56" as configured; never guess.

    Without configuration only plain "1234" / "1234.56" is accepted. With a decimal separator
    configured, digit grouping is optional but must be exactly three digits when present.
    """
    cleaned = text.replace(" ", " ").strip()
    decimal = decimal_separator or "."
    if decimal == thousands_separator:
        raise _FieldError(
            BookingErrorCode.INVALID_NUMBER, "decimal and thousands separators coincide"
        )
    dec = re.escape(decimal)
    if thousands_separator:
        thou = re.escape(thousands_separator)
        pattern = rf"^-?(?:\d+|\d{{1,3}}(?:{thou}\d{{3}})+)(?:{dec}\d+)?$"
    else:
        pattern = rf"^-?\d+(?:{dec}\d+)?$"
    if not re.match(pattern, cleaned):
        raise _FieldError(BookingErrorCode.INVALID_NUMBER, "not a number in the configured format")
    normalised = cleaned
    if thousands_separator:
        normalised = normalised.replace(thousands_separator, "")
    normalised = normalised.replace(decimal, ".")
    try:
        return Decimal(normalised)
    except InvalidOperation:
        raise _FieldError(BookingErrorCode.INVALID_NUMBER, "not a number") from None


def _decimal_from_cell(value: Cell, ctx: NormalizationContext) -> Decimal:
    if isinstance(value, bool):
        raise _FieldError(BookingErrorCode.INVALID_NUMBER, "a boolean is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Excel stores binary doubles: go through the shortest repr and accept only values that
        # are exact to the cent (or 4 decimals for rates) within float noise.
        if not math.isfinite(value):
            raise _FieldError(BookingErrorCode.INVALID_NUMBER, "not a finite number")
        return Decimal(repr(value))
    if isinstance(value, str):
        return parse_decimal_string(value, ctx.decimal_separator, ctx.thousands_separator)
    raise _FieldError(BookingErrorCode.INVALID_NUMBER, "not a number")


def parse_amount(field: CanonicalField, value: Cell, ctx: NormalizationContext) -> Decimal:
    """A non-negative Decimal: two decimals for money, four for a percentage in 0..100."""
    number = _decimal_from_cell(value, ctx)
    is_rate = field == F.COMMISSION_RATE
    step = _RATE_STEP if is_rate else _CENT
    try:
        quantised = number.quantize(step)
    except InvalidOperation:
        raise _FieldError(BookingErrorCode.OUT_OF_RANGE, "number too large") from None
    tolerance = Decimal("1e-9") if isinstance(value, float) else Decimal(0)
    if abs(number - quantised) > tolerance:
        raise _FieldError(
            BookingErrorCode.AMOUNT_PRECISION,
            f"more than {4 if is_rate else 2} decimal places",
        )
    if quantised < 0:
        raise _FieldError(BookingErrorCode.NEGATIVE_VALUE, "must not be negative")
    if is_rate and quantised > 100:
        raise _FieldError(BookingErrorCode.OUT_OF_RANGE, "a percentage must be between 0 and 100")
    if not is_rate and quantised > MAX_MONEY:
        raise _FieldError(BookingErrorCode.OUT_OF_RANGE, "amount too large")
    return quantised


def parse_integer(value: Cell) -> int:
    if isinstance(value, bool):
        raise _FieldError(BookingErrorCode.INVALID_INTEGER, "a boolean is not a number")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float | Decimal):
        try:
            number = int(value)
        except (ValueError, OverflowError, InvalidOperation):
            raise _FieldError(BookingErrorCode.INVALID_INTEGER, "not a whole number") from None
        if number != value:
            raise _FieldError(BookingErrorCode.INVALID_INTEGER, "not a whole number")
    elif isinstance(value, str):
        match = re.match(r"^(\d+)(?:[.,]0+)?$", value.strip())
        if not match:
            raise _FieldError(BookingErrorCode.INVALID_INTEGER, "not a whole number")
        number = int(match.group(1))
    else:
        raise _FieldError(BookingErrorCode.INVALID_INTEGER, "not a whole number")
    if number > _MAX_INT:
        raise _FieldError(BookingErrorCode.OUT_OF_RANGE, "number too large")
    return number


# --- text -------------------------------------------------------------------------------------


def _is_blank(value: Cell) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Cell, limit: int) -> str:
    if isinstance(value, bool) or value is None:
        raise _FieldError(BookingErrorCode.REQUIRED_VALUE_MISSING)
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    elif isinstance(value, datetime | date):
        text = value.isoformat()
    else:
        text = str(value).strip()
    if not text:
        raise _FieldError(BookingErrorCode.REQUIRED_VALUE_MISSING)
    if len(text) > limit:
        raise _FieldError(BookingErrorCode.VALUE_TOO_LONG, f"longer than {limit} characters")
    return text


def parse_source_record_id(value: Cell) -> str | None:
    """The source record id as the importer will store it, or None if it is unusable."""
    try:
        return _text(value, _MAX_SOURCE_ID)
    except _FieldError:
        return None


def diagnostic_text(value: Cell) -> str | None:
    """Short text form of a mapped value for the staging payload (never an unmapped one)."""
    if value is None:
        return None
    text = value.isoformat() if isinstance(value, datetime | date) else str(value)
    return text if len(text) <= 500 else text[:500] + "…"


# --- one row ----------------------------------------------------------------------------------


def normalize_row(
    raw: Mapping[CanonicalField, Cell], ctx: NormalizationContext
) -> tuple[NormalizedBooking | None, list[RowIssue]]:
    """Normalise the mapped values of one source row.

    Returns the booking, or None plus every problem found (all fields are checked, so the
    customer sees the full list at once). Issues name the field and a stable code only.
    """
    values: dict[CanonicalField, Cell] = dict(raw)
    for field, constant in ctx.config.constants().items():
        values[field] = constant
    issues: list[RowIssue] = []
    parsed: dict[CanonicalField, Any] = {}

    def attempt(
        field: CanonicalField, parse: Callable[[Cell], object], *, required: bool = False
    ) -> None:
        value = values.get(field)
        if _is_blank(value):
            if required:
                issues.append(RowIssue(field.value, BookingErrorCode.REQUIRED_VALUE_MISSING))
            return
        try:
            parsed[field] = parse(value)
        except _FieldError as problem:
            issues.append(RowIssue(field.value, problem.code, problem.detail, problem.value))

    def positive_int(value: Cell) -> int:
        number = parse_integer(value)
        if number <= 0:
            raise _FieldError(BookingErrorCode.NOT_POSITIVE, "must be greater than zero")
        return number

    def status(value: Cell) -> BookingStatus:
        label = _text(value, _MAX_TEXT)
        resolved = resolve_status(label, ctx.config.status_mapping)
        if resolved is None:
            raise _FieldError(
                BookingErrorCode.UNKNOWN_STATUS,
                "status value is not recognised",
                value=label[:_MAX_DIAGNOSTIC_VALUE],
            )
        return resolved

    def channel(value: Cell) -> ChannelSpec:
        label = _text(value, _MAX_TEXT)
        try:
            return resolve_channel(label, ctx.config.channel_overrides())
        except ValueError:
            raise _FieldError(
                BookingErrorCode.REQUIRED_VALUE_MISSING, "channel has no letters or digits"
            ) from None

    attempt(F.SOURCE_RECORD_ID, lambda v: _text(v, _MAX_SOURCE_ID), required=True)
    attempt(F.BOOKED_AT, lambda v: parse_datetime_value(F.BOOKED_AT, v, ctx), required=True)
    attempt(F.CHECK_IN, lambda v: parse_date_value(F.CHECK_IN, v, ctx), required=True)
    attempt(F.CHECK_OUT, lambda v: parse_date_value(F.CHECK_OUT, v, ctx), required=True)
    attempt(F.STATUS, status, required=True)
    attempt(F.ROOMS, positive_int, required=True)
    attempt(F.ROOM_REVENUE, lambda v: parse_amount(F.ROOM_REVENUE, v, ctx), required=True)
    attempt(F.CHANNEL, channel, required=True)
    attempt(F.GUESTS, positive_int)
    attempt(F.TOTAL_REVENUE, lambda v: parse_amount(F.TOTAL_REVENUE, v, ctx))
    attempt(F.COMMISSION_AMOUNT, lambda v: parse_amount(F.COMMISSION_AMOUNT, v, ctx))
    attempt(F.COMMISSION_RATE, lambda v: parse_amount(F.COMMISSION_RATE, v, ctx))
    attempt(F.CANCELLED_AT, lambda v: parse_datetime_value(F.CANCELLED_AT, v, ctx))
    attempt(F.ROOM_TYPE, lambda v: _text(v, _MAX_TEXT))
    attempt(F.RATE_PLAN, lambda v: _text(v, _MAX_TEXT))

    check_in, check_out = parsed.get(F.CHECK_IN), parsed.get(F.CHECK_OUT)
    if check_in is not None and check_out is not None and check_out <= check_in:
        issues.append(RowIssue(F.CHECK_OUT.value, BookingErrorCode.CHECK_OUT_NOT_AFTER_CHECK_IN))
    row_status = parsed.get(F.STATUS)
    if (
        F.CANCELLED_AT in parsed
        and row_status is not None
        and row_status != BookingStatus.CANCELLED
    ):
        issues.append(
            RowIssue(F.CANCELLED_AT.value, BookingErrorCode.CANCELLED_AT_WITHOUT_CANCELLED_STATUS)
        )
    if issues:
        return None, issues
    assert check_in is not None and check_out is not None and row_status is not None

    return (
        NormalizedBooking(
            source_record_id=parsed[F.SOURCE_RECORD_ID],
            booked_at=parsed[F.BOOKED_AT],
            check_in=check_in,
            check_out=check_out,
            status=row_status,
            rooms=parsed[F.ROOMS],
            guests=parsed.get(F.GUESTS),
            room_revenue=parsed[F.ROOM_REVENUE],
            total_revenue=parsed.get(F.TOTAL_REVENUE),
            channel=parsed[F.CHANNEL],
            commission_amount=parsed.get(F.COMMISSION_AMOUNT),
            commission_rate=parsed.get(F.COMMISSION_RATE),
            cancelled_at=parsed.get(F.CANCELLED_AT),
            room_type=parsed.get(F.ROOM_TYPE),
            rate_plan=parsed.get(F.RATE_PLAN),
        ),
        [],
    )


# --- formats that must be configured (job level) ----------------------------------------------


class DateOrder(StrEnum):
    ISO = "ISO"  # year first: unambiguous
    DMY = "DMY"  # proven day-first by at least one value with a first part above 12
    MDY = "MDY"  # proven month-first by at least one value with a second part above 12
    AMBIGUOUS = "AMBIGUOUS"  # every value fits both readings
    CONFLICT = "CONFLICT"  # values prove both orders: the column is inconsistent
    UNKNOWN = "UNKNOWN"  # no recognisable dates


def detect_date_order(values: Sequence[str]) -> DateOrder:
    """What the values of ONE column prove about their day/month order (evidence only).

    Used to *suggest* a date format when a mapping is being confirmed. Importing never relies
    on it: a non-ISO date column without a configured pattern is reported as ambiguous.
    """
    iso = slashed = proves_dmy = proves_mdy = 0
    for value in values:
        text = value.strip()
        if _ISO_DATE.match(text):
            iso += 1
            continue
        match = _SLASHED_DATE.match(text)
        if match:
            slashed += 1
            first, second = int(match.group(1)), int(match.group(2))
            proves_dmy += first > 12
            proves_mdy += second > 12
    if slashed == 0:
        return DateOrder.ISO if iso else DateOrder.UNKNOWN
    if proves_dmy and proves_mdy:
        return DateOrder.CONFLICT
    if proves_dmy:
        return DateOrder.DMY
    if proves_mdy:
        return DateOrder.MDY
    return DateOrder.AMBIGUOUS


def needs_date_format(
    field: CanonicalField, values: Sequence[Cell], ctx: NormalizationContext
) -> bool:
    """True when a date column has day/month-first text and no configured pattern."""
    if field in ctx.date_formats:
        return False
    return any(isinstance(v, str) and _SLASHED_DATE.match(v.strip()) for v in values)


def needs_number_format(values: Sequence[Cell], ctx: NormalizationContext) -> bool:
    """True when a numeric column has text that cannot be read without separator settings."""
    if ctx.decimal_separator is not None or ctx.thousands_separator is not None:
        return False
    for value in values:
        if isinstance(value, str) and ("," in value or value.count(".") > 1):
            return True
    return False
