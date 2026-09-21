"""The canonical cost documents: invoices and their lines, plus the import bookkeeping.

An Invoice belongs to ONE property (its supplier belongs to the workspace). It is a canonical
accounting document: immutable once written (a database trigger refuses every UPDATE), identified
by (workspace, property, supplier, normalised number, date, kind) and NOT by the data source it
came from, so the same invoice arriving through an XML file and an accounting export is one cost.

Amounts are signed CANONICAL amounts: a CREDIT_NOTE carries negative amounts, so a plain
SUM(line_total) is always right without anyone re-reading TD04.
"""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column, values_check
from app.modules.bookings.models import ImportRowStatus
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory

# Money: NUMERIC(14, 2). Quantities and unit prices keep the eight decimals FatturaPA allows.
MONEY_PRECISION, MONEY_SCALE = 14, 2
MAX_MONEY = Decimal("99999999999.99")
QUANTITY_PRECISION, QUANTITY_SCALE = 18, 8


class DocumentKind(StrEnum):
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"


class SourceFormat(StrEnum):
    FATTURAPA_XML = "FATTURAPA_XML"
    CSV = "CSV"
    XLSX = "XLSX"


class ResolutionMethod(StrEnum):
    """How the invoice's supplier was determined (which identifier, or that it was created)."""

    VAT_NUMBER = "VAT_NUMBER"
    TAX_CODE = "TAX_CODE"
    IBAN_SHA256 = "IBAN_SHA256"
    EXACT_NAME = "EXACT_NAME"
    EXACT_ALIAS = "EXACT_ALIAS"
    CREATED_NEW = "CREATED_NEW"
    CREATED_NEW_WITH_REVIEW = "CREATED_NEW_WITH_REVIEW"


class Invoice(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "invoices"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    invoice_number: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_invoice_number: Mapped[str] = mapped_column(String(255), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)

    document_type_code: Mapped[str | None] = mapped_column(String(20))
    document_kind: Mapped[DocumentKind] = mapped_column(
        enum_column(DocumentKind, 16), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE))

    source_format: Mapped[SourceFormat] = mapped_column(
        enum_column(SourceFormat, 16), nullable=False
    )
    source_import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_import_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_resolution_method: Mapped[ResolutionMethod] = mapped_column(
        enum_column(ResolutionMethod, 24), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name="fk_invoices_workspace_id_properties",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_invoices_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name="fk_invoices_workspace_id_suppliers",
            ondelete="RESTRICT",
        ),
        # The import job must be a job of the invoice's own data source and property.
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "source_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name="fk_invoices_source_import_job",
            ondelete="RESTRICT",
        ),
        # ... and the file must belong to that job.
        ForeignKeyConstraint(
            ["workspace_id", "source_import_job_id", "source_import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name="fk_invoices_source_import_file",
            ondelete="RESTRICT",
        ),
        # The canonical identity of a document: NO data source in it, on purpose.
        UniqueConstraint(
            "workspace_id",
            "property_id",
            "supplier_id",
            "normalized_invoice_number",
            "invoice_date",
            "document_kind",
            name="uq_invoices_identity",
        ),
        # Foreign-key target of the lines.
        UniqueConstraint("workspace_id", "id", name="uq_invoices_workspace_id_id"),
        # "Costs of a property in a period, by supplier": the cost query and the date lookup.
        Index(
            "ix_invoices_workspace_id_property_id_invoice_date_supplier_id",
            "workspace_id",
            "property_id",
            "invoice_date",
            "supplier_id",
        ),
        CheckConstraint("btrim(invoice_number) <> ''", name="invoice_number_not_blank"),
        CheckConstraint(
            "btrim(normalized_invoice_number) <> ''", name="normalized_invoice_number_not_blank"
        ),
        CheckConstraint(
            "document_type_code IS NULL OR btrim(document_type_code) <> ''",
            name="document_type_code_not_blank",
        ),
        CheckConstraint(values_check("document_kind", DocumentKind), name="document_kind_valid"),
        CheckConstraint(values_check("source_format", SourceFormat), name="source_format_valid"),
        CheckConstraint(
            values_check("supplier_resolution_method", ResolutionMethod),
            name="supplier_resolution_method_valid",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="source_fingerprint_format"),
        # A credit note is stored as a negative cost: the header amounts can never be positive.
        CheckConstraint(
            "document_kind <> 'CREDIT_NOTE' OR ((net_amount IS NULL OR net_amount <= 0)"
            " AND (tax_amount IS NULL OR tax_amount <= 0)"
            " AND (gross_amount IS NULL OR gross_amount <= 0))",
            name="credit_note_amounts_not_positive",
        ),
    )


class InvoiceLine(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "invoice_lines"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_line_number: Mapped[int] = mapped_column(Integer, nullable=False)

    description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    description_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(QUANTITY_PRECISION, QUANTITY_SCALE))
    unit: Mapped[str | None] = mapped_column(String(30))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(QUANTITY_PRECISION, QUANTITY_SCALE))
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False
    )
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    cost_category: Mapped[CostCategory] = mapped_column(
        enum_column(CostCategory, 32), nullable=False
    )
    classification_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        enum_column(ClassificationMethod, 20), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "invoice_id"],
            ["invoices.workspace_id", "invoices.id"],
            name="fk_invoice_lines_workspace_id_invoices",
            ondelete="RESTRICT",
        ),
        # The lines of an invoice in source order (also the lookup by invoice).
        UniqueConstraint(
            "workspace_id",
            "invoice_id",
            "source_line_number",
            name="uq_invoice_lines_workspace_id_invoice_id_source_line_number",
        ),
        # Cost by category inside a workspace.
        Index("ix_invoice_lines_workspace_id_cost_category", "workspace_id", "cost_category"),
        CheckConstraint("source_line_number > 0", name="source_line_number_positive"),
        CheckConstraint("btrim(description_raw) <> ''", name="description_raw_not_blank"),
        CheckConstraint(
            "btrim(description_normalized) <> ''", name="description_normalized_not_blank"
        ),
        CheckConstraint("unit IS NULL OR btrim(unit) <> ''", name="unit_not_blank"),
        CheckConstraint("vat_rate IS NULL OR vat_rate BETWEEN 0 AND 100", name="vat_rate_range"),
        CheckConstraint(values_check("cost_category", CostCategory), name="cost_category_valid"),
        CheckConstraint(
            values_check("classification_method", ClassificationMethod),
            name="classification_method_valid",
        ),
        CheckConstraint(
            "classification_confidence BETWEEN 0 AND 100", name="classification_confidence_range"
        ),
        # UNCLASSIFIED <=> confidence 0 (and then the category is OTHER).
        CheckConstraint(
            "(classification_method = 'UNCLASSIFIED') = (classification_confidence = 0)"
            " AND (classification_method <> 'UNCLASSIFIED' OR cost_category = 'OTHER')",
            name="classification_consistent",
        ),
    )


class InvoiceMappingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The confirmed way to read one COSTS data source's structured files. Configuration only."""

    __tablename__ = "invoice_mapping_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    data_source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    category_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    format_options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    header_signature: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name="fk_invoice_mapping_profiles_workspace_id_data_sources",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name="uq_invoice_mapping_profiles_workspace_id_data_source_id",
        ),
        CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(category_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name="json_shapes",
        ),
        CheckConstraint("header_signature ~ '^[0-9a-f]{64}$'", name="header_signature_format"),
    )


class InvoiceImportRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Staging of one source LINE of an invoice import (a document header rides on its first line).

    Data minimisation: `mapped_payload` holds ONLY mapped/canonical values as text (the IBAN only
    as its SHA-256; nothing of the recipient, no address, no e-mail, no phone, no raw XML, no
    unmapped column). `validation_errors` carry field names and stable codes, not values.
    """

    __tablename__ = "invoice_import_rows"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    import_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_document_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_line_number: Mapped[int | None] = mapped_column(Integer)
    mapped_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    validation_status: Mapped[ImportRowStatus] = mapped_column(
        enum_column(ImportRowStatus, 16), nullable=False
    )
    validation_errors: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_warnings: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name="fk_invoice_import_rows_workspace_id_import_files",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "row_number",
            name="uq_invoice_import_rows_workspace_id_import_file_id_row_number",
        ),
        Index("ix_invoice_import_rows_workspace_id_import_job_id", "workspace_id", "import_job_id"),
        CheckConstraint("row_number > 0", name="row_number_positive"),
        CheckConstraint("source_document_index > 0", name="source_document_index_positive"),
        CheckConstraint(
            "source_line_number IS NULL OR source_line_number >= 0",
            name="source_line_number_non_negative",
        ),
        CheckConstraint(values_check("validation_status", ImportRowStatus), name="status_valid"),
        CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND jsonb_typeof(validation_warnings) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name="payload_shapes",
        ),
        CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name="status_consistent",
        ),
    )
