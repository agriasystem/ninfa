"""The file domains behind Smart Import - bookings, labor and structured costs - seen through ONE
interface.

Each import service keeps its own mapping rules, its own validation and its own canonical model; the
adapters add nothing of that. They only let the data-source layer ask the same questions of both:
which fields exist, which are required, what does a column probably mean, how is a saved
configuration read and written, what would importing this file do.

Costs arrive mostly as FatturaPA XML, which keeps its own flow (there are no columns to match);
a cost REGISTER in CSV / Excel is read through the same invoice model by `CostsDomain`.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings import mapping as booking_mapping
from app.modules.bookings.mapping import CanonicalField, MappingConfig
from app.modules.bookings.models import BookingStatus
from app.modules.bookings.repository import BookingMappingProfileRepository
from app.modules.bookings.service import BookingImportService
from app.modules.bookings.suggestions import FIELD_ALIASES as BOOKING_ALIASES
from app.modules.data_sources.mapping_types import (
    ConstantKind,
    ConstantSpec,
    DryRunSummary,
    FieldKind,
    FieldSpec,
)
from app.modules.document_understanding.layout import LayoutSpec
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.suggestions import SuggestionConfidence, suggest_fields
from app.modules.invoices import mapping as invoice_mapping
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.mapping import InvoiceField, InvoiceMappingConfig
from app.modules.invoices.repository import InvoiceMappingProfileRepository
from app.modules.invoices.service import InvoiceImportService
from app.modules.invoices.suggestions import FIELD_ALIASES as INVOICE_ALIASES
from app.modules.invoices.suggestions import FIELD_ORDER as INVOICE_ORDER
from app.modules.labor import mapping as labor_mapping
from app.modules.labor.mapping import LaborField, LaborMappingConfig
from app.modules.labor.repository import LaborMappingProfileRepository
from app.modules.labor.roles import LaborCategory
from app.modules.labor.service import LaborImportService
from app.modules.labor.suggestions import (
    EXCLUDED_HEADERS as LABOR_EXCLUDED_HEADERS,
)
from app.modules.labor.suggestions import (
    FIELD_ALIASES as LABOR_ALIASES,
)
from app.modules.labor.suggestions import excluded_reason as labor_excluded_reason


@dataclass(frozen=True, slots=True)
class StoredProfile:
    """The saved way to read one source's files, as it is stored."""

    data_source_id: UUID
    documents: dict[str, dict[str, Any]]
    header_signature: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DryRunData:
    file_type: str
    rows_total: int
    rows_valid: int
    rows_invalid: int
    error_summary: dict[str, int]
    sample_payloads: list[dict[str, Any]]
    invalid_rows: list[tuple[int, list[dict[str, str]]]]
    # Valid rows whose category could not be worked out (labor only; 0 for every other domain).
    rows_unclassified: int = 0
    # The words behind those rows (department labels, with how many rows each).
    unclassified_labels: tuple[tuple[str, int], ...] = ()
    # What the valid rows add up to.
    summary: DryRunSummary | None = None
    # The stored document the unclassified words belong to ("role_mapping", "category_mapping").
    labels_document: str = "role_mapping"


@dataclass(frozen=True, slots=True)
class ConfigFormat:
    """How a mapping says the file is read, in plain values."""

    sheet_name: str | None
    schema_version: int | None
    date_formats: dict[str, str]
    decimal_separator: str | None
    thousands_separator: str | None
    layout: LayoutSpec | None = None


@dataclass(frozen=True, slots=True)
class Suggested:
    field: str
    column: str | None
    confidence: SuggestionConfidence


class FileDomain(ABC):
    domain: ClassVar[DataSourceDomain]
    # Prefix of this domain's own error codes (BOOKING_..., LABOR_...).
    schema_version: ClassVar[int]
    fields: ClassVar[tuple[FieldSpec, ...]]
    # Each group is "at least one of"; a single-field group is a required field.
    groups: ClassVar[tuple[tuple[str, ...], ...]]
    date_fields: ClassVar[frozenset[str]]
    decimal_fields: ClassVar[frozenset[str]]
    # The fields shown in the sample of what would be imported, in order.
    sample_fields: ClassVar[tuple[str, ...]]
    # The stored documents that map VALUES (status, channel, role labels), kept when the columns
    # are re-matched.
    value_documents: ClassVar[tuple[str, ...]]

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    # --- what a column probably means ---------------------------------------------------------

    @abstractmethod
    def suggest(self, headers: list[str]) -> list[Suggested]: ...

    def excluded_reason(self, header: str) -> str | None:
        return None

    # --- the mapping, as the import service reads it --------------------------------------------

    @abstractmethod
    def parse_config(self, documents: dict[str, Any]) -> Any:
        """Build the validated mapping. Raises the domain's own error when it is not valid."""

    @abstractmethod
    def documents_of(self, config: Any) -> dict[str, dict[str, Any]]: ...

    @abstractmethod
    def columns_of(self, config: Any) -> dict[str, str]: ...

    @abstractmethod
    def constants_of(self, config: Any) -> dict[str, str | int]: ...

    @abstractmethod
    def format_of(self, config: Any) -> ConfigFormat: ...

    # --- the saved configuration ----------------------------------------------------------------

    @abstractmethod
    def get_profile(self, data_source_id: UUID) -> StoredProfile | None: ...

    @abstractmethod
    def delete_profile(self, data_source_id: UUID) -> bool: ...

    @abstractmethod
    def save_profile(
        self,
        data_source_id: UUID,
        property_id: UUID,
        headers: list[str],
        documents: dict[str, dict[str, Any]],
    ) -> None: ...

    # --- trying a file --------------------------------------------------------------------------

    @abstractmethod
    def dry_run(
        self, property_id: UUID, filename: str, content: bytes, config: Any
    ) -> DryRunData: ...

    @abstractmethod
    def sample_row(self, payload: dict[str, Any]) -> dict[str, str | None]: ...


# --- bookings -------------------------------------------------------------------------------------


def _with_canonical_names[F: StrEnum](
    aliases: Mapping[F, tuple[str, ...]],
) -> dict[F, tuple[str, ...]]:
    """A file already written in NINFA's own column names is recognised as exactly that."""
    return {field: (*names, field.value) for field, names in aliases.items()}


class BookingsDomain(FileDomain):
    domain = DataSourceDomain.BOOKINGS
    schema_version = booking_mapping.MAPPING_SCHEMA_VERSION
    fields = (
        FieldSpec(CanonicalField.SOURCE_RECORD_ID.value, FieldKind.TEXT),
        FieldSpec(CanonicalField.BOOKED_AT.value, FieldKind.DATETIME),
        FieldSpec(CanonicalField.CHECK_IN.value, FieldKind.DATE),
        FieldSpec(CanonicalField.CHECK_OUT.value, FieldKind.DATE),
        FieldSpec(
            CanonicalField.STATUS.value,
            FieldKind.CHOICE,
            ConstantSpec(
                ConstantKind.CHOICE,
                choices=tuple(status.value for status in BookingStatus),
                default=BookingStatus.CONFIRMED.value,
            ),
        ),
        FieldSpec(
            CanonicalField.ROOMS.value,
            FieldKind.INTEGER,
            ConstantSpec(ConstantKind.INTEGER, default=1),
        ),
        FieldSpec(CanonicalField.ROOM_REVENUE.value, FieldKind.DECIMAL),
        FieldSpec(CanonicalField.CHANNEL.value, FieldKind.TEXT, ConstantSpec(ConstantKind.TEXT)),
        FieldSpec(CanonicalField.GUESTS.value, FieldKind.INTEGER),
        FieldSpec(CanonicalField.TOTAL_REVENUE.value, FieldKind.DECIMAL),
        FieldSpec(CanonicalField.COMMISSION_AMOUNT.value, FieldKind.DECIMAL),
        FieldSpec(CanonicalField.COMMISSION_RATE.value, FieldKind.DECIMAL),
        FieldSpec(CanonicalField.CANCELLED_AT.value, FieldKind.DATETIME),
        FieldSpec(CanonicalField.ROOM_TYPE.value, FieldKind.TEXT),
        FieldSpec(CanonicalField.RATE_PLAN.value, FieldKind.TEXT),
    )
    groups = tuple(
        (field.value,)
        for field in booking_mapping.FIELD_ORDER
        if field in booking_mapping.REQUIRED_FIELDS
    )
    date_fields = frozenset(field.value for field in booking_mapping.DATE_FIELDS)
    decimal_fields = frozenset(field.value for field in booking_mapping.DECIMAL_FIELDS)
    sample_fields = (
        "source_record_id",
        "check_in",
        "check_out",
        "rooms",
        "room_revenue",
        "channel",
        "status",
    )
    value_documents = ("status_mapping", "channel_mapping")

    def suggest(self, headers: list[str]) -> list[Suggested]:
        suggestions = suggest_fields(
            headers,
            aliases=_with_canonical_names(BOOKING_ALIASES),
            order=booking_mapping.FIELD_ORDER,
        )
        return [Suggested(s.field.value, s.column, s.confidence) for s in suggestions]

    def parse_config(self, documents: dict[str, Any]) -> MappingConfig:
        return MappingConfig.parse(documents)

    def documents_of(self, config: MappingConfig) -> dict[str, dict[str, Any]]:
        return config.to_stored()

    def columns_of(self, config: MappingConfig) -> dict[str, str]:
        return {field.value: column for field, column in config.mapped_columns().items()}

    def constants_of(self, config: MappingConfig) -> dict[str, str | int]:
        return {field.value: value for field, value in config.constants().items()}

    def format_of(self, config: MappingConfig) -> ConfigFormat:
        options = config.format_options
        return ConfigFormat(
            options.sheet_name,
            options.schema_version,
            {field.value: pattern for field, pattern in options.date_formats.items()},
            options.decimal_separator,
            options.thousands_separator,
            options.layout,
        )

    def get_profile(self, data_source_id: UUID) -> StoredProfile | None:
        profile = BookingMappingProfileRepository(self._session, self._tenant).get_for_data_source(
            data_source_id
        )
        if profile is None:
            return None
        return StoredProfile(
            data_source_id,
            {
                "column_mapping": profile.column_mapping,
                "status_mapping": profile.status_mapping,
                "channel_mapping": profile.channel_mapping,
                "format_options": profile.format_options,
            },
            profile.header_signature,
            profile.updated_at,
        )

    def delete_profile(self, data_source_id: UUID) -> bool:
        return BookingMappingProfileRepository(self._session, self._tenant).delete_for_data_source(
            data_source_id
        )

    def save_profile(
        self,
        data_source_id: UUID,
        property_id: UUID,
        headers: list[str],
        documents: dict[str, dict[str, Any]],
    ) -> None:
        BookingImportService(self._session, self._tenant).save_mapping(
            data_source_id,
            headers=headers,
            column_mapping=documents["column_mapping"],
            status_mapping=documents.get("status_mapping"),
            channel_mapping=documents.get("channel_mapping"),
            format_options=documents.get("format_options"),
            property_id=property_id,
        )

    def dry_run(
        self, property_id: UUID, filename: str, content: bytes, config: MappingConfig
    ) -> DryRunData:
        result = BookingImportService(self._session, self._tenant).dry_run(
            property_id, filename=filename, content=content, mapping=config
        )
        return DryRunData(
            result.file_type,
            result.rows_total,
            result.rows_valid,
            result.rows_invalid,
            result.row_error_summary,
            result.sample_payloads,
            result.invalid_rows,
            summary=DryRunSummary(
                date_from=result.summary.get("date_from"),
                date_to=result.summary.get("date_to"),
                channels=result.summary.get("channels"),
                revenue=result.summary.get("revenue"),
            ),
        )

    def sample_row(self, payload: dict[str, Any]) -> dict[str, str | None]:
        rooms = payload.get("rooms")
        return {
            "source_record_id": payload.get("source_record_id"),
            "check_in": payload.get("check_in"),
            "check_out": payload.get("check_out"),
            "rooms": None if rooms is None else str(rooms),
            "room_revenue": payload.get("room_revenue"),
            "channel": payload.get("channel_name"),
            "status": payload.get("status"),
        }


# --- labor ----------------------------------------------------------------------------------------


def _hours_text(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    hours = (Decimal(minutes) / Decimal(60)).normalize()
    return format(hours, "f")


class LaborDomain(FileDomain):
    domain = DataSourceDomain.LABOR
    schema_version = labor_mapping.MAPPING_SCHEMA_VERSION
    fields = (
        FieldSpec(LaborField.WORK_DATE.value, FieldKind.DATE),
        FieldSpec(LaborField.ROLE.value, FieldKind.TEXT),
        FieldSpec(
            LaborField.LABOR_CATEGORY.value,
            FieldKind.CHOICE,
            ConstantSpec(
                ConstantKind.CHOICE, choices=tuple(category.value for category in LaborCategory)
            ),
        ),
        FieldSpec(LaborField.PLANNED_HOURS.value, FieldKind.DECIMAL),
        FieldSpec(LaborField.ACTUAL_HOURS.value, FieldKind.DECIMAL),
        FieldSpec(LaborField.PLANNED_COST.value, FieldKind.DECIMAL),
        FieldSpec(LaborField.ACTUAL_COST.value, FieldKind.DECIMAL),
        FieldSpec(
            LaborField.CURRENCY.value,
            FieldKind.CURRENCY,
            ConstantSpec(ConstantKind.CURRENCY, default="EUR"),
        ),
    )
    groups = (
        (LaborField.WORK_DATE.value,),
        tuple(sorted(field.value for field in labor_mapping.HOURS_FIELDS)),
        tuple(sorted(field.value for field in labor_mapping.ROLE_OR_CATEGORY_FIELDS)),
    )
    date_fields = frozenset(field.value for field in labor_mapping.DATE_FIELDS)
    decimal_fields = frozenset(field.value for field in labor_mapping.DECIMAL_FIELDS)
    sample_fields = (
        "work_date",
        "labor_category",
        "planned_hours",
        "actual_hours",
        "planned_cost",
        "actual_cost",
    )
    value_documents = ("role_mapping",)

    def suggest(self, headers: list[str]) -> list[Suggested]:
        suggestions = suggest_fields(
            headers,
            aliases=_with_canonical_names(LABOR_ALIASES),
            order=tuple(LaborField),
            excluded=LABOR_EXCLUDED_HEADERS,
        )
        return [Suggested(s.field.value, s.column, s.confidence) for s in suggestions]

    def excluded_reason(self, header: str) -> str | None:
        return labor_excluded_reason(header)

    def parse_config(self, documents: dict[str, Any]) -> LaborMappingConfig:
        return LaborMappingConfig.parse(documents)

    def documents_of(self, config: LaborMappingConfig) -> dict[str, dict[str, Any]]:
        return config.to_stored()

    def columns_of(self, config: LaborMappingConfig) -> dict[str, str]:
        return {field.value: column for field, column in config.mapped_columns().items()}

    def constants_of(self, config: LaborMappingConfig) -> dict[str, str | int]:
        return {field.value: value for field, value in config.constants().items()}

    def format_of(self, config: LaborMappingConfig) -> ConfigFormat:
        options = config.format_options
        return ConfigFormat(
            options.sheet_name,
            options.schema_version,
            {field.value: pattern for field, pattern in options.date_formats.items()},
            options.decimal_separator,
            options.thousands_separator,
            options.layout,
        )

    def get_profile(self, data_source_id: UUID) -> StoredProfile | None:
        profile = LaborMappingProfileRepository(self._session, self._tenant).get_for_data_source(
            data_source_id
        )
        if profile is None:
            return None
        return StoredProfile(
            data_source_id,
            {
                "column_mapping": profile.column_mapping,
                "role_mapping": profile.role_mapping,
                "format_options": profile.format_options,
            },
            profile.header_signature,
            profile.updated_at,
        )

    def delete_profile(self, data_source_id: UUID) -> bool:
        return LaborMappingProfileRepository(self._session, self._tenant).delete_for_data_source(
            data_source_id
        )

    def save_profile(
        self,
        data_source_id: UUID,
        property_id: UUID,
        headers: list[str],
        documents: dict[str, dict[str, Any]],
    ) -> None:
        LaborImportService(self._session, self._tenant).save_mapping(
            data_source_id,
            headers=headers,
            column_mapping=documents["column_mapping"],
            role_mapping=documents.get("role_mapping"),
            format_options=documents.get("format_options"),
            property_id=property_id,
        )

    def dry_run(
        self, property_id: UUID, filename: str, content: bytes, config: LaborMappingConfig
    ) -> DryRunData:
        result = LaborImportService(self._session, self._tenant).dry_run(
            property_id, filename=filename, content=content, mapping=config
        )
        return DryRunData(
            result.file_type,
            result.rows_total,
            result.rows_valid,
            result.rows_invalid,
            result.row_error_summary,
            result.sample_payloads,
            result.invalid_rows,
            result.rows_unclassified,
            tuple(result.unclassified_labels),
            DryRunSummary(
                date_from=result.summary.get("date_from"),
                date_to=result.summary.get("date_to"),
                departments=tuple(result.summary.get("departments", ())),
                planned_hours=result.summary.get("planned_hours"),
                actual_hours=result.summary.get("actual_hours"),
                planned_cost=result.summary.get("planned_cost"),
                actual_cost=result.summary.get("actual_cost"),
                currency=result.summary.get("currency"),
            ),
        )

    def sample_row(self, payload: dict[str, Any]) -> dict[str, str | None]:
        return {
            "work_date": payload.get("work_date"),
            "labor_category": payload.get("labor_category"),
            "planned_hours": _hours_text(payload.get("planned_minutes")),
            "actual_hours": _hours_text(payload.get("actual_minutes")),
            "planned_cost": payload.get("planned_cost"),
            "actual_cost": payload.get("actual_cost"),
        }


# --- costs (a register in CSV / Excel) ---------------------------------------------------------


class CostsDomain(FileDomain):
    domain = DataSourceDomain.COSTS
    schema_version = invoice_mapping.MAPPING_SCHEMA_VERSION
    fields = (
        FieldSpec(InvoiceField.SUPPLIER_NAME.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.SUPPLIER_VAT_NUMBER.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.SUPPLIER_TAX_CODE.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.SUPPLIER_IBAN.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.INVOICE_NUMBER.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.INVOICE_DATE.value, FieldKind.DATE),
        FieldSpec(InvoiceField.DUE_DATE.value, FieldKind.DATE),
        FieldSpec(
            InvoiceField.DOCUMENT_TYPE.value,
            FieldKind.CHOICE,
            ConstantSpec(ConstantKind.CHOICE, choices=("INVOICE", "CREDIT_NOTE")),
        ),
        FieldSpec(
            InvoiceField.CURRENCY.value, FieldKind.CURRENCY, ConstantSpec(ConstantKind.CURRENCY)
        ),
        FieldSpec(InvoiceField.INVOICE_NET_AMOUNT.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.INVOICE_TAX_AMOUNT.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.INVOICE_GROSS_AMOUNT.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.LINE_NUMBER.value, FieldKind.INTEGER),
        FieldSpec(InvoiceField.LINE_DESCRIPTION.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.QUANTITY.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.UNIT.value, FieldKind.TEXT),
        FieldSpec(InvoiceField.UNIT_PRICE.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.LINE_TOTAL.value, FieldKind.DECIMAL),
        FieldSpec(InvoiceField.VAT_RATE.value, FieldKind.DECIMAL),
        FieldSpec(
            InvoiceField.COST_CATEGORY.value,
            FieldKind.CHOICE,
            ConstantSpec(
                ConstantKind.CHOICE, choices=tuple(category.value for category in CostCategory)
            ),
        ),
    )
    groups = tuple(
        (field.value,) for field in INVOICE_ORDER if field in invoice_mapping.REQUIRED_FIELDS
    )
    date_fields = frozenset(field.value for field in invoice_mapping.DATE_FIELDS)
    decimal_fields = frozenset(field.value for field in invoice_mapping.DECIMAL_FIELDS)
    sample_fields = (
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "line_description",
        "line_total",
        "cost_category",
    )
    value_documents = ("category_mapping",)

    def suggest(self, headers: list[str]) -> list[Suggested]:
        suggestions = suggest_fields(
            headers,
            aliases=_with_canonical_names(INVOICE_ALIASES),
            order=INVOICE_ORDER,
        )
        return [Suggested(s.field.value, s.column, s.confidence) for s in suggestions]

    def parse_config(self, documents: dict[str, Any]) -> InvoiceMappingConfig:
        return InvoiceMappingConfig.parse(documents)

    def documents_of(self, config: InvoiceMappingConfig) -> dict[str, dict[str, Any]]:
        return config.to_stored()

    def columns_of(self, config: InvoiceMappingConfig) -> dict[str, str]:
        return {field.value: column for field, column in config.mapped_columns().items()}

    def constants_of(self, config: InvoiceMappingConfig) -> dict[str, str | int]:
        return {field.value: value for field, value in config.constants().items()}

    def format_of(self, config: InvoiceMappingConfig) -> ConfigFormat:
        options = config.format_options
        return ConfigFormat(
            options.sheet_name,
            options.schema_version,
            {field.value: pattern for field, pattern in options.date_formats.items()},
            options.decimal_separator,
            options.thousands_separator,
            options.layout,
        )

    def get_profile(self, data_source_id: UUID) -> StoredProfile | None:
        profile = InvoiceMappingProfileRepository(self._session, self._tenant).get_for_data_source(
            data_source_id
        )
        if profile is None:
            return None
        return StoredProfile(
            data_source_id,
            {
                "column_mapping": profile.column_mapping,
                "category_mapping": profile.category_mapping,
                "format_options": profile.format_options,
            },
            profile.header_signature,
            profile.updated_at,
        )

    def delete_profile(self, data_source_id: UUID) -> bool:
        return InvoiceMappingProfileRepository(self._session, self._tenant).delete_for_data_source(
            data_source_id
        )

    def save_profile(
        self,
        data_source_id: UUID,
        property_id: UUID,
        headers: list[str],
        documents: dict[str, dict[str, Any]],
    ) -> None:
        InvoiceImportService(self._session, self._tenant).save_mapping(
            data_source_id,
            headers=headers,
            column_mapping=documents["column_mapping"],
            category_mapping=documents.get("category_mapping"),
            format_options=documents.get("format_options"),
            property_id=property_id,
        )

    def dry_run(
        self, property_id: UUID, filename: str, content: bytes, config: InvoiceMappingConfig
    ) -> DryRunData:
        result = InvoiceImportService(self._session, self._tenant).dry_run(
            property_id, filename=filename, content=content, mapping=config
        )
        summary = result.summary
        return DryRunData(
            result.file_type,
            result.rows_total,
            result.rows_valid,
            result.rows_invalid,
            result.row_error_summary,
            result.sample_payloads,
            result.invalid_rows,
            0,  # a row with an unknown category is not valid: it is not "unclassified"
            tuple(result.unknown_categories),
            DryRunSummary(
                date_from=summary.get("date_from"),
                date_to=summary.get("date_to"),
                currency=summary.get("currency"),
                documents=summary.get("documents"),
                suppliers=summary.get("suppliers"),
                net_total=summary.get("net_total"),
            ),
            labels_document="category_mapping",
        )

    def sample_row(self, payload: dict[str, Any]) -> dict[str, str | None]:
        line = payload.get("line") or {}
        header = payload.get("header") or {}
        supplier = header.get("supplier") or {}
        return {
            "invoice_number": header.get("invoice_number"),
            "invoice_date": header.get("invoice_date"),
            "supplier_name": supplier.get("legal_name"),
            "line_description": line.get("description_raw"),
            "line_total": line.get("line_total"),
            "cost_category": line.get("explicit_category"),
        }


def domain_adapter(
    domain: DataSourceDomain, session: Session, tenant: TenantContext
) -> FileDomain | None:
    """The adapter of a domain that is read from a spreadsheet-like file."""
    if domain == DataSourceDomain.BOOKINGS:
        return BookingsDomain(session, tenant)
    if domain == DataSourceDomain.LABOR:
        return LaborDomain(session, tenant)
    if domain == DataSourceDomain.COSTS:
        return CostsDomain(session, tenant)
    return None


__all__ = [
    "BookingsDomain",
    "ConfigFormat",
    "CostsDomain",
    "DryRunData",
    "FileDomain",
    "LaborDomain",
    "StoredProfile",
    "Suggested",
    "domain_adapter",
]
