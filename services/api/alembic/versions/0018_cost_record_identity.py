"""Costs: the technical identity of a cost record is not the fiscal number of a document.

Until now the identity of a canonical cost was `(workspace, property, supplier, normalised invoice
number, date, kind, revision)`, and `invoice_number` was NOT NULL. A cost register that carries no
document number at all (utilities, laundry, a month of commissions: operating costs) could not be
imported, and the only way around it would have been to INVENT a number, which is a fiscal fact.

This migration separates the two things:

* `invoices.source_record_key` is the technical identity NINFA needs for idempotency, revisions and
  removals. For a real document it IS the normalised invoice number (the backfill, and a CHECK that
  keeps it so): nothing changes for an invoice. For an operating cost with no document number NINFA
  derives it from the content of the record (`identity_origin = SYNTHETIC_COST_RECORD`).
* `invoices.invoice_number` / `normalized_invoice_number` become NULLABLE, and only for a synthetic
  record: a CHECK says a DOCUMENT_NUMBER record has both (non-blank) and a synthetic one has
  neither.
  An invented number is never stored. A FatturaPA, a credit note or anything that is not a
  CSV/XLSX invoice can never be synthetic (CHECK).
* `invoice_removals` records that a SYNTHETIC record stopped counting because a person said a later
  file held everything of its period. `invoices` stays immutable (its trigger is untouched); a
  removal is a row of its own, and a foreign key on `(workspace_id, invoice_id, identity_origin)`
  makes it impossible for a fiscal document to be removed.

The unique identity key moves from `normalized_invoice_number` to `source_record_key`: the same
columns otherwise, so a row that was unique stays unique. The immutability trigger is lifted for the
single backfill statement and put back in the same transaction. Written by hand; the model tests
keep the ORM metadata in sync with it. Migrations 0001-0017 are untouched.

The downgrade refuses once a synthetic record or a removal exists: going back would have to destroy
evidence (or invent the number the record never had).

Revision ID: 0018_cost_record_identity
Revises: 0017_mia_conversations
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_cost_record_identity"
down_revision: str | None = "0017_mia_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY_KEY = "uq_invoices_identity_revision"
_IDENTITY_COLUMNS_OLD = [
    "workspace_id",
    "property_id",
    "supplier_id",
    "normalized_invoice_number",
    "invoice_date",
    "document_kind",
    "revision",
]
_IDENTITY_COLUMNS_NEW = [
    "workspace_id",
    "property_id",
    "supplier_id",
    "source_record_key",
    "invoice_date",
    "document_kind",
    "revision",
]
_CONSISTENT = (
    "(identity_origin = 'DOCUMENT_NUMBER'"
    " AND invoice_number IS NOT NULL AND btrim(invoice_number) <> ''"
    " AND normalized_invoice_number IS NOT NULL AND btrim(normalized_invoice_number) <> ''"
    " AND source_record_key = normalized_invoice_number)"
    " OR (identity_origin = 'SYNTHETIC_COST_RECORD'"
    " AND invoice_number IS NULL AND normalized_invoice_number IS NULL)"
)
_SPREADSHEETS_ONLY = (
    "identity_origin <> 'SYNTHETIC_COST_RECORD'"
    " OR (source_format IN ('CSV', 'XLSX') AND document_kind = 'INVOICE')"
)


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "identity_origin",
            sa.String(length=24),
            nullable=False,
            server_default="DOCUMENT_NUMBER",
        ),
    )
    op.add_column("invoices", sa.Column("source_record_key", sa.String(length=255), nullable=True))

    # The canonical rows are immutable: the one statement that fills the new column lifts the
    # trigger and puts it back, inside this transaction.
    op.execute(sa.text("ALTER TABLE invoices DISABLE TRIGGER trg_invoices_immutable"))
    op.execute(sa.text("UPDATE invoices SET source_record_key = normalized_invoice_number"))
    op.execute(sa.text("ALTER TABLE invoices ENABLE TRIGGER trg_invoices_immutable"))
    op.alter_column("invoices", "source_record_key", nullable=False)

    op.drop_constraint(op.f("ck_invoices_invoice_number_not_blank"), "invoices", type_="check")
    op.drop_constraint(
        op.f("ck_invoices_normalized_invoice_number_not_blank"), "invoices", type_="check"
    )
    op.alter_column("invoices", "invoice_number", nullable=True)
    op.alter_column("invoices", "normalized_invoice_number", nullable=True)

    op.create_check_constraint(
        op.f("ck_invoices_identity_origin_valid"),
        "invoices",
        "identity_origin IN ('DOCUMENT_NUMBER', 'SYNTHETIC_COST_RECORD')",
    )
    op.create_check_constraint(op.f("ck_invoices_identity_consistent"), "invoices", _CONSISTENT)
    op.create_check_constraint(
        op.f("ck_invoices_source_record_key_not_blank"),
        "invoices",
        "btrim(source_record_key) <> ''",
    )
    op.create_check_constraint(
        op.f("ck_invoices_synthetic_only_for_spreadsheets"), "invoices", _SPREADSHEETS_ONLY
    )

    op.drop_constraint(op.f(_IDENTITY_KEY), "invoices", type_="unique")
    op.create_unique_constraint(op.f(_IDENTITY_KEY), "invoices", _IDENTITY_COLUMNS_NEW)
    # Foreign-key target of the removals: ties a removal to the KIND of identity of its invoice.
    op.create_unique_constraint(
        op.f("uq_invoices_workspace_id_id_identity_origin"),
        "invoices",
        ["workspace_id", "id", "identity_origin"],
    )

    op.create_table(
        "invoice_removals",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column(
            "identity_origin",
            sa.String(length=24),
            nullable=False,
            server_default="SYNTHETIC_COST_RECORD",
        ),
        sa.Column("removed_by_import_job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_removals")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id"],
            ["properties.workspace_id", "properties.id"],
            name=op.f("fk_invoice_removals_workspace_id_properties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id"],
            ["data_sources.workspace_id", "data_sources.property_id", "data_sources.id"],
            name=op.f("fk_invoice_removals_workspace_id_data_sources"),
            ondelete="RESTRICT",
        ),
        # Only a SYNTHETIC record can be removed: the pair (id, kind of identity) must exist.
        sa.ForeignKeyConstraint(
            ["workspace_id", "invoice_id", "identity_origin"],
            ["invoices.workspace_id", "invoices.id", "invoices.identity_origin"],
            name=op.f("fk_invoice_removals_workspace_id_invoices"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "property_id", "data_source_id", "removed_by_import_job_id"],
            [
                "import_jobs.workspace_id",
                "import_jobs.property_id",
                "import_jobs.data_source_id",
                "import_jobs.id",
            ],
            name=op.f("fk_invoice_removals_removed_by_import_job"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id", "invoice_id", name=op.f("uq_invoice_removals_workspace_id_invoice_id")
        ),
        sa.CheckConstraint(
            "identity_origin = 'SYNTHETIC_COST_RECORD'",
            name=op.f("ck_invoice_removals_only_synthetic_records"),
        ),
    )
    op.create_index(
        op.f("ix_invoice_removals_workspace_id_data_source_id"),
        "invoice_removals",
        ["workspace_id", "data_source_id"],
    )
    # A removal is evidence of what a person said a file held: it is never edited.
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_invoice_removals_immutable BEFORE UPDATE ON invoice_removals"
            " FOR EACH ROW EXECUTE FUNCTION invoices_forbid_update()"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM invoices WHERE identity_origin <> 'DOCUMENT_NUMBER')"
            " OR EXISTS (SELECT 1 FROM invoice_removals)"
        )
    ).scalar()
    if held:
        raise RuntimeError(
            "invoices holds a cost record with no document number (or a removal): going back "
            "would destroy evidence, or invent the number it never had"
        )
    op.drop_table("invoice_removals")
    op.drop_constraint(
        op.f("uq_invoices_workspace_id_id_identity_origin"), "invoices", type_="unique"
    )
    op.drop_constraint(op.f(_IDENTITY_KEY), "invoices", type_="unique")
    op.create_unique_constraint(op.f(_IDENTITY_KEY), "invoices", _IDENTITY_COLUMNS_OLD)
    op.drop_constraint(
        op.f("ck_invoices_synthetic_only_for_spreadsheets"), "invoices", type_="check"
    )
    op.drop_constraint(op.f("ck_invoices_source_record_key_not_blank"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_identity_consistent"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_identity_origin_valid"), "invoices", type_="check")
    op.alter_column("invoices", "normalized_invoice_number", nullable=False)
    op.alter_column("invoices", "invoice_number", nullable=False)
    op.create_check_constraint(
        op.f("ck_invoices_normalized_invoice_number_not_blank"),
        "invoices",
        "btrim(normalized_invoice_number) <> ''",
    )
    op.create_check_constraint(
        op.f("ck_invoices_invoice_number_not_blank"), "invoices", "btrim(invoice_number) <> ''"
    )
    op.drop_column("invoices", "source_record_key")
    op.drop_column("invoices", "identity_origin")
