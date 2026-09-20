"""Booking column mapping ("mapping memory"): what a confirmed mapping is, and when it still holds.

A mapping says which source column feeds each canonical field (or gives a constant where that is
safe), how to read the file (`format_options`) and how to interpret status/channel labels.
Only mapped columns are ever read into NINFA: that is how unneeded personal data is kept out.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from app.modules.bookings.channels import ChannelOverride, normalize_channel_name
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.models import BookingStatus, ChannelType
from app.modules.bookings.statuses import resolve_status
from app.modules.bookings.text import normalize_key


class CanonicalField(StrEnum):
    SOURCE_RECORD_ID = "source_record_id"
    BOOKED_AT = "booked_at"
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    STATUS = "status"
    ROOMS = "rooms"
    ROOM_REVENUE = "room_revenue"
    CHANNEL = "channel"
    GUESTS = "guests"
    TOTAL_REVENUE = "total_revenue"
    COMMISSION_AMOUNT = "commission_amount"
    COMMISSION_RATE = "commission_rate"
    CANCELLED_AT = "cancelled_at"
    ROOM_TYPE = "room_type"
    RATE_PLAN = "rate_plan"


F = CanonicalField
REQUIRED_FIELDS = frozenset(
    {
        F.SOURCE_RECORD_ID,
        F.BOOKED_AT,
        F.CHECK_IN,
        F.CHECK_OUT,
        F.STATUS,
        F.ROOMS,
        F.ROOM_REVENUE,
        F.CHANNEL,
    }
)
# A constant is only safe where it cannot invent facts about individual bookings.
CONSTANT_FIELDS = frozenset({F.ROOMS, F.STATUS, F.CHANNEL})
DATE_FIELDS = frozenset({F.BOOKED_AT, F.CHECK_IN, F.CHECK_OUT, F.CANCELLED_AT})
DATETIME_FIELDS = frozenset({F.BOOKED_AT, F.CANCELLED_AT})
DECIMAL_FIELDS = frozenset(
    {F.ROOM_REVENUE, F.TOTAL_REVENUE, F.COMMISSION_AMOUNT, F.COMMISSION_RATE}
)
INTEGER_FIELDS = frozenset({F.ROOMS, F.GUESTS})
FIELD_ORDER: tuple[CanonicalField, ...] = tuple(CanonicalField)

# Date patterns are a small explicit subset of strptime: numeric directives only (month names are
# locale dependent) and a four-digit year (two-digit years are ambiguous).
_PATTERN_TOKENS = {"%d", "%m", "%Y", "%H", "%M", "%S"}
_PATTERN_LITERALS = set("/-. :T")


def validate_date_pattern(pattern: str) -> str:
    tokens = re.findall(r"%.", pattern)
    if any(token not in _PATTERN_TOKENS for token in tokens):
        raise ValueError("only %d %m %Y %H %M %S are allowed in a date format")
    if any(pattern.count(token) != 1 for token in ("%d", "%m", "%Y")):
        raise ValueError("a date format must contain %d, %m and %Y exactly once")
    if any(pattern.count(token) > 1 for token in ("%H", "%M", "%S")):
        raise ValueError("a date format may contain each of %H %M %S at most once")
    literals = re.sub(r"%.", "", pattern)
    if any(char not in _PATTERN_LITERALS for char in literals):
        raise ValueError("date formats may only use / - . : T and spaces between fields")
    return pattern


class FieldSource(BaseModel):
    """Where one canonical field comes from: a source column, or (where allowed) a constant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    column: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    constant: str | int | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "FieldSource":
        if (self.column is None) == (self.constant is None):
            raise ValueError("give exactly one of 'column' or 'constant'")
        return self


class FormatOptions(BaseModel):
    """How to read the file. Everything is explicit: nothing is inferred while importing."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    delimiter: Literal[",", ";", "\t"] | None = None
    encoding: Literal["utf-8", "cp1252"] | None = None
    date_formats: dict[CanonicalField, str] = {}
    decimal_separator: Literal[".", ","] | None = None
    thousands_separator: Literal[",", ".", " ", "'"] | None = None

    @field_validator("date_formats")
    @classmethod
    def _date_formats(cls, value: dict[CanonicalField, str]) -> dict[CanonicalField, str]:
        for field, pattern in value.items():
            if field not in DATE_FIELDS:
                raise ValueError(f"{field.value} is not a date field")
            validate_date_pattern(pattern)
        return value

    @model_validator(mode="after")
    def _separators_differ(self) -> "FormatOptions":
        if self.decimal_separator and self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal_separator and thousands_separator must differ")
        return self


class ChannelOverrideConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    channel_type: ChannelType | None = None

    @field_validator("name")
    @classmethod
    def _name_has_content(cls, value: str | None) -> str | None:
        if value is not None and not normalize_channel_name(value):
            raise ValueError("channel name has no letters or digits")
        return value


class MappingConfig(BaseModel):
    """A validated mapping. Invalid configurations cannot be constructed."""

    model_config = ConfigDict(extra="forbid")

    column_mapping: dict[CanonicalField, FieldSource]
    status_mapping: dict[str, BookingStatus] = {}
    channel_mapping: dict[str, ChannelOverrideConfig] = {}
    format_options: FormatOptions = FormatOptions()

    @field_validator("status_mapping")
    @classmethod
    def _normalise_status_keys(cls, value: dict[str, BookingStatus]) -> dict[str, BookingStatus]:
        normalised: dict[str, BookingStatus] = {}
        for raw_key, status in value.items():
            key = normalize_key(raw_key)
            if not key:
                raise ValueError("a status label has no letters or digits")
            if normalised.get(key, status) != status:
                raise ValueError(
                    "two status labels differ only in case/punctuation but map differently"
                )
            normalised[key] = status
        return normalised

    @field_validator("channel_mapping")
    @classmethod
    def _normalise_channel_keys(
        cls, value: dict[str, ChannelOverrideConfig]
    ) -> dict[str, ChannelOverrideConfig]:
        normalised: dict[str, ChannelOverrideConfig] = {}
        for raw_key, override in value.items():
            key = normalize_channel_name(raw_key)
            if not key:
                raise ValueError("a channel label has no letters or digits")
            if key in normalised and normalised[key] != override:
                raise ValueError(
                    "two channel labels differ only in case/punctuation but map differently"
                )
            normalised[key] = override
        return normalised

    @model_validator(mode="after")
    def _check_fields(self) -> "MappingConfig":
        missing = sorted(f.value for f in REQUIRED_FIELDS if f not in self.column_mapping)
        if missing:
            raise ValueError(f"required fields not mapped: {', '.join(missing)}")
        for field, source in self.column_mapping.items():
            if source.constant is not None and field not in CONSTANT_FIELDS:
                allowed = ", ".join(sorted(f.value for f in CONSTANT_FIELDS))
                raise ValueError(f"{field.value} cannot be a constant (allowed: {allowed})")
        self._check_constants()
        return self

    def _check_constants(self) -> None:
        rooms = self.column_mapping.get(CanonicalField.ROOMS)
        if rooms is not None and rooms.constant is not None:
            value = rooms.constant
            if isinstance(value, bool) or not str(value).strip().isdigit() or int(str(value)) <= 0:
                raise ValueError("the constant for rooms must be a positive integer")
        status = self.column_mapping.get(CanonicalField.STATUS)
        if (
            status is not None
            and status.constant is not None
            and resolve_status(str(status.constant), self.status_mapping) is None
        ):
            raise ValueError("the constant for status is not a recognised status")
        channel = self.column_mapping.get(CanonicalField.CHANNEL)
        if (
            channel is not None
            and channel.constant is not None
            and not normalize_channel_name(str(channel.constant))
        ):
            raise ValueError("the constant for channel has no letters or digits")

    # --- conversions ---------------------------------------------------------------------------

    def mapped_columns(self) -> dict[CanonicalField, str]:
        return {f: s.column for f, s in self.column_mapping.items() if s.column is not None}

    def constants(self) -> dict[CanonicalField, str | int]:
        return {f: s.constant for f, s in self.column_mapping.items() if s.constant is not None}

    def channel_overrides(self) -> dict[str, ChannelOverride]:
        return {
            key: ChannelOverride(name=cfg.name, channel_type=cfg.channel_type)
            for key, cfg in self.channel_mapping.items()
        }

    def to_stored(self) -> dict[str, dict[str, Any]]:
        """The four JSON documents persisted in the mapping profile."""
        return {
            "column_mapping": {
                field.value: source.model_dump(mode="json", exclude_none=True)
                for field, source in self.column_mapping.items()
            },
            "status_mapping": {key: status.value for key, status in self.status_mapping.items()},
            "channel_mapping": {
                key: cfg.model_dump(mode="json", exclude_none=True)
                for key, cfg in self.channel_mapping.items()
            },
            "format_options": self.format_options.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            ),
        }

    @classmethod
    def parse(cls, data: Mapping[str, Any]) -> "MappingConfig":
        """Build from untrusted/stored data; failures become BOOKING_INVALID_MAPPING."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            problems = [
                {"loc": ".".join(str(part) for part in err["loc"]), "msg": err["msg"]}
                for err in exc.errors()
            ]
            raise BookingImportError(
                BookingErrorCode.INVALID_MAPPING,
                "The booking mapping is not valid",
                details={"problems": problems},
            ) from exc


# --- headers, signature, schema compatibility ------------------------------------------------


def normalize_header(header: str) -> str:
    return normalize_key(header)


def find_duplicate_headers(headers: Sequence[str]) -> list[str]:
    """Normalised non-empty headers that occur more than once (an ambiguous file)."""
    seen: set[str] = set()
    duplicated: list[str] = []
    for header in headers:
        key = normalize_header(header)
        if not key:
            continue
        if key in seen and key not in duplicated:
            duplicated.append(key)
        seen.add(key)
    return duplicated


def compute_header_signature(headers: Iterable[str]) -> str:
    """Order-insensitive fingerprint of a file's column set (SHA-256 of the normalised names)."""
    keys = sorted({normalize_header(h) for h in headers if normalize_header(h)})
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def header_index(headers: Sequence[str]) -> dict[str, int]:
    return {normalize_header(h): i for i, h in enumerate(headers) if normalize_header(h)}


@dataclass(frozen=True)
class SchemaCheck:
    compatible: bool
    signature_matches: bool
    missing_columns: tuple[str, ...]


def check_schema(
    config: MappingConfig, stored_signature: str, headers: Sequence[str]
) -> SchemaCheck:
    """Can the confirmed mapping still be applied to a file with these headers?

    Yes when every *mapped* column is still present (unrelated columns may come and go: an
    extra column in the export must not invalidate a mapping). If a mapped column is missing
    (renamed, removed) the mapping is NOT applied and the schema is reported as changed.
    """
    index = header_index(headers)
    missing = tuple(
        column
        for column in config.mapped_columns().values()
        if normalize_header(column) not in index
    )
    return SchemaCheck(
        compatible=not missing,
        signature_matches=compute_header_signature(headers) == stored_signature,
        missing_columns=missing,
    )
