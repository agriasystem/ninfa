"""Labor column mapping ("mapping memory") for structured CSV/XLSX files.

A confirmed mapping says which source column feeds each canonical field (or gives a constant
where that is safe), how to read the file, and how to read role labels into a category. Only
mapped columns are ever read into NINFA: that is how employee identity and every other
unrequested column are kept out. It is NOT the booking or invoice mapping: it has its own fields
and rules, and shares only the header/date helpers of Gate 2.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.core.iso4217 import ISO_4217_CODES
from app.modules.bookings.mapping import (
    FieldSource,
    compute_header_signature,
    header_index,
    normalize_header,
    validate_date_pattern,
)
from app.modules.bookings.text import normalize_key
from app.modules.labor.errors import LaborErrorCode, LaborImportError
from app.modules.labor.roles import LaborCategory

__all__ = ["compute_header_signature", "header_index", "normalize_header"]


class LaborField(StrEnum):
    WORK_DATE = "work_date"
    ROLE = "role"
    LABOR_CATEGORY = "labor_category"
    PLANNED_HOURS = "planned_hours"
    ACTUAL_HOURS = "actual_hours"
    PLANNED_COST = "planned_cost"
    ACTUAL_COST = "actual_cost"
    CURRENCY = "currency"


F = LaborField
# work_date is always required; at least one of {planned_hours, actual_hours} and at least one
# of {role, labor_category} must ALSO be mapped (checked below: it is not a fixed set).
REQUIRED_FIELDS = frozenset({F.WORK_DATE})
HOURS_FIELDS = frozenset({F.PLANNED_HOURS, F.ACTUAL_HOURS})
ROLE_OR_CATEGORY_FIELDS = frozenset({F.ROLE, F.LABOR_CATEGORY})
# A constant is only safe where it cannot invent a fact about one entry: never the work date or
# the hours (an employee-identity-free file may still legitimately vary role/category by row).
CONSTANT_FIELDS = frozenset({F.LABOR_CATEGORY, F.CURRENCY})
DATE_FIELDS = frozenset({F.WORK_DATE})
DECIMAL_FIELDS = frozenset({F.PLANNED_HOURS, F.ACTUAL_HOURS, F.PLANNED_COST, F.ACTUAL_COST})


def resolve_labor_category(label: str) -> LaborCategory | None:
    """A source label as a canonical category: only when the label IS a canonical category name
    (case, spacing and punctuation aside). Anything else is unknown (never guessed)."""
    key = normalize_key(label)
    for category in LaborCategory:
        if normalize_key(category.value) == key:
            return category
    return None


class LaborFormatOptions(BaseModel):
    """How to read the file. Everything is explicit: nothing is inferred while importing."""

    model_config = ConfigDict(extra="forbid")

    sheet_name: str | None = None
    delimiter: Literal[",", ";", "\t"] | None = None
    encoding: Literal["utf-8", "cp1252"] | None = None
    date_formats: dict[LaborField, str] = {}
    decimal_separator: Literal[".", ","] | None = None
    thousands_separator: Literal[",", ".", " ", "'"] | None = None

    @field_validator("date_formats")
    @classmethod
    def _date_formats(cls, value: dict[LaborField, str]) -> dict[LaborField, str]:
        for field, pattern in value.items():
            if field not in DATE_FIELDS:
                raise ValueError(f"{field.value} is not a date field")
            validate_date_pattern(pattern)
        return value

    @model_validator(mode="after")
    def _separators_differ(self) -> "LaborFormatOptions":
        if self.decimal_separator and self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal_separator and thousands_separator must differ")
        return self


class LaborMappingConfig(BaseModel):
    """A validated mapping. Invalid configurations cannot be constructed."""

    model_config = ConfigDict(extra="forbid")

    column_mapping: dict[LaborField, FieldSource]
    role_mapping: dict[str, LaborCategory] = {}
    format_options: LaborFormatOptions = LaborFormatOptions()

    @field_validator("role_mapping")
    @classmethod
    def _normalise_role_keys(cls, value: dict[str, LaborCategory]) -> dict[str, LaborCategory]:
        normalised: dict[str, LaborCategory] = {}
        for raw_key, category in value.items():
            key = normalize_key(raw_key)
            if not key:
                raise ValueError("a role label has no letters or digits")
            if normalised.get(key, category) != category:
                raise ValueError(
                    "two role labels differ only in case/punctuation but map differently"
                )
            normalised[key] = category
        return normalised

    @model_validator(mode="after")
    def _check_fields(self) -> "LaborMappingConfig":
        missing = sorted(f.value for f in REQUIRED_FIELDS if f not in self.column_mapping)
        if missing:
            raise ValueError(f"required fields not mapped: {', '.join(missing)}")
        if not any(f in self.column_mapping for f in HOURS_FIELDS):
            raise ValueError("at least one of planned_hours or actual_hours must be mapped")
        if not any(f in self.column_mapping for f in ROLE_OR_CATEGORY_FIELDS):
            raise ValueError("at least one of role or labor_category must be mapped")
        for field, source in self.column_mapping.items():
            if source.constant is not None and field not in CONSTANT_FIELDS:
                allowed = ", ".join(sorted(f.value for f in CONSTANT_FIELDS))
                raise ValueError(f"{field.value} cannot be a constant (allowed: {allowed})")
        self._check_constants()
        return self

    def _check_constants(self) -> None:
        currency = self.column_mapping.get(F.CURRENCY)
        if (
            currency is not None
            and currency.constant is not None
            and str(currency.constant).strip().upper() not in ISO_4217_CODES
        ):
            raise ValueError("the constant for currency is not an ISO 4217 code")
        category = self.column_mapping.get(F.LABOR_CATEGORY)
        if (
            category is not None
            and category.constant is not None
            and resolve_labor_category(str(category.constant)) is None
        ):
            raise ValueError("the constant for labor_category is not a recognised category")

    # --- conversions ---------------------------------------------------------------------------

    def mapped_columns(self) -> dict[LaborField, str]:
        return {f: s.column for f, s in self.column_mapping.items() if s.column is not None}

    def constants(self) -> dict[LaborField, str | int]:
        return {f: s.constant for f, s in self.column_mapping.items() if s.constant is not None}

    def to_stored(self) -> dict[str, dict[str, Any]]:
        """The three JSON documents persisted in the mapping profile."""
        return {
            "column_mapping": {
                field.value: source.model_dump(mode="json", exclude_none=True)
                for field, source in self.column_mapping.items()
            },
            "role_mapping": {key: cat.value for key, cat in self.role_mapping.items()},
            "format_options": self.format_options.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            ),
        }

    @classmethod
    def parse(cls, data: Mapping[str, Any]) -> "LaborMappingConfig":
        """Build from untrusted/stored data; failures become LABOR_INVALID_MAPPING."""
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            problems = [
                {"loc": ".".join(str(part) for part in err["loc"]), "msg": err["msg"]}
                for err in exc.errors()
            ]
            raise LaborImportError(
                LaborErrorCode.INVALID_MAPPING,
                "The labor mapping is not valid",
                details={"problems": problems},
            ) from exc


@dataclass(frozen=True)
class SchemaCheck:
    compatible: bool
    signature_matches: bool
    missing_columns: tuple[str, ...]


def check_schema(
    config: LaborMappingConfig, stored_signature: str, headers: Sequence[str]
) -> SchemaCheck:
    """Can the confirmed mapping still be applied? Yes when every MAPPED column is still there
    (extra columns are harmless); a renamed or removed mapped column means the schema changed."""
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
