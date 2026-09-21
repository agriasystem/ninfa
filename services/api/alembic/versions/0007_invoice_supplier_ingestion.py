"""Gate 6: supplier registry, invoices and their ingestion bookkeeping.

Adds eight tables:

    suppliers                      who a workspace buys from (workspace-wide, NOT per property)
    supplier_identifiers           VAT number / tax code / IBAN SHA-256 (never the raw IBAN)
    supplier_aliases               normalised spellings of a supplier's name
    supplier_resolution_reviews    possible duplicates for a person to confirm (PENDING only)
    invoices                       canonical cost documents (immutable, signed amounts)
    invoice_lines                  canonical lines with their cost category (immutable)
    invoice_mapping_profiles       the confirmed reading of a COSTS data source's CSV/XLSX files
    invoice_import_rows            data-minimised staging of an invoice import

and, on the Gate 1 table `data_sources`, one unique constraint that exists only to be a foreign-key
target (an addition; no existing object is altered):

    data_sources (workspace_id, id)

Tenant integrity (see ADR 0006), composite foreign keys carrying workspace_id, all RESTRICT:

    supplier_identifiers / aliases / reviews   (workspace, supplier[s])          -> suppliers
    supplier_aliases                           (workspace, data_source)          -> data_sources
    invoices     (workspace, property)                                           -> properties
    invoices     (workspace, property, data_source)                              -> data_sources
    invoices     (workspace, supplier)                                           -> suppliers
    invoices     (workspace, property, data_source, import_job)                  -> import_jobs
    invoices     (workspace, import_job, import_file)                            -> import_files
    invoice_lines (workspace, invoice)                                           -> invoices
    invoice_mapping_profiles (workspace, property, data_source)                  -> data_sources
    invoice_import_rows (workspace, import_job, import_file)                     -> import_files

Invoices and their lines are immutable evidence: a trigger refuses every UPDATE. Suppliers are not
(identifiers, aliases, verification and the default category evolve). DELETE is not blocked: the
foreign keys are RESTRICT and retention belongs to a later gate.

Written by hand; tests keep the ORM metadata in sync with it. Migrations 0001-0006 are untouched.

Revision ID: 0007_invoice_supplier_ingestion
Revises: 0006_expected_engine
Create Date: 2026-09-24
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_invoice_supplier_ingestion"
down_revision: str | None = "0006_expected_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COST_CATEGORIES = (
    "'PERSONNEL', 'LAUNDRY', 'CLEANING', 'AMENITIES', 'FOOD', 'BEVERAGE', 'UTILITIES',"
    " 'MAINTENANCE', 'SOFTWARE', 'MARKETING', 'OTA_COMMISSIONS', 'PROFESSIONAL_SERVICES',"
    " 'TRANSPORT', 'OTHER'"
)


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


_IMMUTABLE_FUNCTION = """
CREATE FUNCTION invoices_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'invoices: a canonical invoice and its lines are immutable accounting evidence'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # --- foreign-key target on the Gate 1 table -------------------------------------------------
    op.create_unique_constraint(
        op.f("uq_data_sources_workspace_id_id"), "data_sources", ["workspace_id", "id"]
    )

    # --- suppliers ------------------------------------------------------------------------------
    op.create_table(
        "suppliers",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(300), nullable=False),
        sa.Column("normalized_name", sa.String(300), nullable=False),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("default_cost_category", sa.String(32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_suppliers_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_suppliers_workspace_id_id")),
        sa.CheckConstraint(
            "btrim(legal_name) <> ''", name=op.f("ck_suppliers_legal_name_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(normalized_name) <> ''", name=op.f("ck_suppliers_normalized_name_not_blank")
        ),
        sa.CheckConstraint(
            "country IS NULL OR country ~ '^[A-Z]{2}$'", name=op.f("ck_suppliers_country_format")
        ),
        sa.CheckConstraint(
            f"default_cost_category IS NULL OR default_cost_category IN ({COST_CATEGORIES})",
            name=op.f("ck_suppliers_default_cost_category_valid"),
        ),
    )
    op.create_index(
        op.f("ix_suppliers_workspace_id_normalized_name"),
        "suppliers",
        ["workspace_id", "normalized_name"],
    )

    # --- supplier_identifiers -------------------------------------------------------------------
    op.create_table(
        "supplier_identifiers",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("normalized_value", sa.String(64), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_identifiers")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name=op.f("fk_supplier_identifiers_workspace_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "kind",
            "normalized_value",
            name=op.f("uq_supplier_identifiers_workspace_id_kind_normalized_value"),
        ),
        sa.CheckConstraint(
            "kind IN ('VAT_NUMBER', 'TAX_CODE', 'IBAN_SHA256')",
            name=op.f("ck_supplier_identifiers_kind_valid"),
        ),
        sa.CheckConstraint(
            "btrim(normalized_value) <> ''",
            name=op.f("ck_supplier_identifiers_normalized_value_not_blank"),
        ),
        sa.CheckConstraint(
            "kind <> 'IBAN_SHA256' OR normalized_value ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_supplier_identifiers_iban_value_is_sha256"),
        ),
    )
    op.create_index(
        op.f("ix_supplier_identifiers_workspace_id_supplier_id"),
        "supplier_identifiers",
        ["workspace_id", "supplier_id"],
    )

    # --- supplier_aliases -----------------------------------------------------------------------
    op.create_table(
        "supplier_aliases",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_name", sa.String(300), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_aliases")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name=op.f("fk_supplier_aliases_workspace_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.id"],
            name=op.f("fk_supplier_aliases_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "supplier_id",
            "normalized_name",
            name=op.f("uq_supplier_aliases_workspace_id_supplier_id_normalized_name"),
        ),
        sa.CheckConstraint(
            "btrim(normalized_name) <> ''",
            name=op.f("ck_supplier_aliases_normalized_name_not_blank"),
        ),
    )
    op.create_index(
        op.f("ix_supplier_aliases_workspace_id_normalized_name"),
        "supplier_aliases",
        ["workspace_id", "normalized_name"],
    )

    # --- supplier_resolution_reviews ------------------------------------------------------------
    op.create_table(
        "supplier_resolution_reviews",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provisional_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_supplier_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("similarity_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        _created_at(),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_resolution_reviews")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "provisional_supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name=op.f("fk_supplier_reviews_workspace_id_provisional_supplier"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "candidate_supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name=op.f("fk_supplier_reviews_workspace_id_candidate_supplier"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "provisional_supplier_id",
            "candidate_supplier_id",
            name=op.f("uq_supplier_reviews_workspace_id_provisional_candidate"),
        ),
        sa.CheckConstraint(
            "provisional_supplier_id <> candidate_supplier_id",
            name=op.f("ck_supplier_resolution_reviews_provisional_is_not_candidate"),
        ),
        sa.CheckConstraint(
            "reason IN ('FUZZY_NAME_SIMILARITY', 'NAME_MATCH_IDENTITY_CONFLICT')",
            name=op.f("ck_supplier_resolution_reviews_reason_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED_DUPLICATE', 'NOT_DUPLICATE')",
            name=op.f("ck_supplier_resolution_reviews_status_valid"),
        ),
        sa.CheckConstraint(
            "similarity_score BETWEEN 0 AND 1",
            name=op.f("ck_supplier_resolution_reviews_similarity_score_range"),
        ),
        sa.CheckConstraint(
            "(status = 'PENDING') = (resolved_at IS NULL)",
            name=op.f("ck_supplier_resolution_reviews_resolved_matches_status"),
        ),
    )
    op.create_index(
        op.f("ix_supplier_reviews_workspace_id_status"),
        "supplier_resolution_reviews",
        ["workspace_id", "status"],
    )

    # --- invoices -------------------------------------------------------------------------------
    op.create_table(
        "invoices",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_number", sa.String(255), nullable=False),
        sa.Column("normalized_invoice_number", sa.String(255), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("document_type_code", sa.String(20), nullable=True),
        sa.Column("document_kind", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("net_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("source_format", sa.String(16), nullable=False),
        sa.Column("source_import_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_import_file_id", sa.Uuid(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("supplier_resolution_method", sa.String(24), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_invoices_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_invoices_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supplier_id"],
            ["suppliers.workspace_id", "suppliers.id"],
            name=op.f("fk_invoices_workspace_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "source_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name=op.f("fk_invoices_source_import_job"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_import_job_id", "source_import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name=op.f("fk_invoices_source_import_file"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "property_id",
            "supplier_id",
            "normalized_invoice_number",
            "invoice_date",
            "document_kind",
            name=op.f("uq_invoices_identity"),
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_invoices_workspace_id_id")),
        sa.CheckConstraint(
            "btrim(invoice_number) <> ''", name=op.f("ck_invoices_invoice_number_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(normalized_invoice_number) <> ''",
            name=op.f("ck_invoices_normalized_invoice_number_not_blank"),
        ),
        sa.CheckConstraint(
            "document_type_code IS NULL OR btrim(document_type_code) <> ''",
            name=op.f("ck_invoices_document_type_code_not_blank"),
        ),
        sa.CheckConstraint(
            "document_kind IN ('INVOICE', 'CREDIT_NOTE')",
            name=op.f("ck_invoices_document_kind_valid"),
        ),
        sa.CheckConstraint(
            "source_format IN ('FATTURAPA_XML', 'CSV', 'XLSX')",
            name=op.f("ck_invoices_source_format_valid"),
        ),
        sa.CheckConstraint(
            "supplier_resolution_method IN ('VAT_NUMBER', 'TAX_CODE', 'IBAN_SHA256',"
            " 'EXACT_NAME', 'EXACT_ALIAS', 'CREATED_NEW', 'CREATED_NEW_WITH_REVIEW')",
            name=op.f("ck_invoices_supplier_resolution_method_valid"),
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_invoices_currency_format")),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_invoices_source_fingerprint_format"),
        ),
        sa.CheckConstraint(
            "document_kind <> 'CREDIT_NOTE' OR ((net_amount IS NULL OR net_amount <= 0)"
            " AND (tax_amount IS NULL OR tax_amount <= 0)"
            " AND (gross_amount IS NULL OR gross_amount <= 0))",
            name=op.f("ck_invoices_credit_note_amounts_not_positive"),
        ),
    )
    op.create_index(
        op.f("ix_invoices_workspace_id_property_id_invoice_date_supplier_id"),
        "invoices",
        ["workspace_id", "property_id", "invoice_date", "supplier_id"],
    )

    # --- invoice_lines --------------------------------------------------------------------------
    op.create_table(
        "invoice_lines",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("source_line_number", sa.Integer(), nullable=False),
        sa.Column("description_raw", sa.Text(), nullable=False),
        sa.Column("description_normalized", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=True),
        sa.Column("unit", sa.String(30), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(6, 2), nullable=True),
        sa.Column("cost_category", sa.String(32), nullable=False),
        sa.Column("classification_confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("classification_method", sa.String(20), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "invoice_id"],
            ["invoices.workspace_id", "invoices.id"],
            name=op.f("fk_invoice_lines_workspace_id_invoices"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "invoice_id",
            "source_line_number",
            name=op.f("uq_invoice_lines_workspace_id_invoice_id_source_line_number"),
        ),
        sa.CheckConstraint(
            "source_line_number > 0", name=op.f("ck_invoice_lines_source_line_number_positive")
        ),
        sa.CheckConstraint(
            "btrim(description_raw) <> ''", name=op.f("ck_invoice_lines_description_raw_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(description_normalized) <> ''",
            name=op.f("ck_invoice_lines_description_normalized_not_blank"),
        ),
        sa.CheckConstraint(
            "unit IS NULL OR btrim(unit) <> ''", name=op.f("ck_invoice_lines_unit_not_blank")
        ),
        sa.CheckConstraint(
            "vat_rate IS NULL OR vat_rate BETWEEN 0 AND 100",
            name=op.f("ck_invoice_lines_vat_rate_range"),
        ),
        sa.CheckConstraint(
            f"cost_category IN ({COST_CATEGORIES})",
            name=op.f("ck_invoice_lines_cost_category_valid"),
        ),
        sa.CheckConstraint(
            "classification_method IN ('EXPLICIT_SOURCE', 'SUPPLIER_DEFAULT',"
            " 'DETERMINISTIC_RULE', 'UNCLASSIFIED')",
            name=op.f("ck_invoice_lines_classification_method_valid"),
        ),
        sa.CheckConstraint(
            "classification_confidence BETWEEN 0 AND 100",
            name=op.f("ck_invoice_lines_classification_confidence_range"),
        ),
        sa.CheckConstraint(
            "(classification_method = 'UNCLASSIFIED') = (classification_confidence = 0)"
            " AND (classification_method <> 'UNCLASSIFIED' OR cost_category = 'OTHER')",
            name=op.f("ck_invoice_lines_classification_consistent"),
        ),
    )
    op.create_index(
        op.f("ix_invoice_lines_workspace_id_cost_category"),
        "invoice_lines",
        ["workspace_id", "cost_category"],
    )

    # --- invoice_mapping_profiles ---------------------------------------------------------------
    op.create_table(
        "invoice_mapping_profiles",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=False),
        sa.Column(
            "category_mapping",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "format_options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("header_signature", sa.String(64), nullable=False),
        _created_at(),
        _updated_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_mapping_profiles")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_invoice_mapping_profiles_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "data_source_id",
            name=op.f("uq_invoice_mapping_profiles_workspace_id_data_source_id"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(column_mapping) = 'object' AND jsonb_typeof(category_mapping) = 'object'"
            " AND jsonb_typeof(format_options) = 'object'",
            name=op.f("ck_invoice_mapping_profiles_json_shapes"),
        ),
        sa.CheckConstraint(
            "header_signature ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_invoice_mapping_profiles_header_signature_format"),
        ),
    )

    # --- invoice_import_rows --------------------------------------------------------------------
    op.create_table(
        "invoice_import_rows",
        _id(),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("import_file_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_document_index", sa.Integer(), nullable=False),
        sa.Column("source_line_number", sa.Integer(), nullable=True),
        sa.Column("mapped_payload", postgresql.JSONB(none_as_null=False), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "validation_warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_import_rows")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_job_id", "import_file_id"],
            ["import_files.workspace_id", "import_files.import_job_id", "import_files.id"],
            name=op.f("fk_invoice_import_rows_workspace_id_import_files"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "import_file_id",
            "row_number",
            name=op.f("uq_invoice_import_rows_workspace_id_import_file_id_row_number"),
        ),
        sa.CheckConstraint(
            "row_number > 0", name=op.f("ck_invoice_import_rows_row_number_positive")
        ),
        sa.CheckConstraint(
            "source_document_index > 0",
            name=op.f("ck_invoice_import_rows_source_document_index_positive"),
        ),
        sa.CheckConstraint(
            "source_line_number IS NULL OR source_line_number >= 0",
            name=op.f("ck_invoice_import_rows_source_line_number_non_negative"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'IMPORTED')",
            name=op.f("ck_invoice_import_rows_status_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(mapped_payload) = 'object' AND jsonb_typeof(validation_errors) = 'array'"
            " AND jsonb_typeof(validation_warnings) = 'array'"
            " AND (normalized_payload IS NULL OR jsonb_typeof(normalized_payload) = 'object')",
            name=op.f("ck_invoice_import_rows_payload_shapes"),
        ),
        sa.CheckConstraint(
            "(validation_status = 'INVALID' AND jsonb_array_length(validation_errors) > 0)"
            " OR (validation_status IN ('VALID', 'IMPORTED') AND normalized_payload IS NOT NULL"
            " AND jsonb_array_length(validation_errors) = 0)",
            name=op.f("ck_invoice_import_rows_status_consistent"),
        ),
    )
    op.create_index(
        op.f("ix_invoice_import_rows_workspace_id_import_job_id"),
        "invoice_import_rows",
        ["workspace_id", "import_job_id"],
    )

    # --- immutability of the canonical documents ------------------------------------------------
    op.execute(sa.text(_IMMUTABLE_FUNCTION))
    for table in ("invoices", "invoice_lines"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table}"
                " FOR EACH ROW EXECUTE FUNCTION invoices_forbid_update()"
            )
        )


def downgrade() -> None:
    # Children first; the triggers go with their tables. Gate 0-5 objects are untouched apart
    # from the extra unique key added to data_sources.
    op.drop_table("invoice_import_rows")
    op.drop_table("invoice_mapping_profiles")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("supplier_resolution_reviews")
    op.drop_table("supplier_aliases")
    op.drop_table("supplier_identifiers")
    op.drop_table("suppliers")
    op.execute(sa.text("DROP FUNCTION invoices_forbid_update()"))
    op.drop_constraint(op.f("uq_data_sources_workspace_id_id"), "data_sources", type_="unique")
