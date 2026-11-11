"""A day may hold several observations, and a document several versions (Pilot Reliability V1.2).

Until now one property-local day could hold one observation of the bookings and one labor snapshot
per source, and an invoice one content for ever. A hotel exports in the morning and again in the
afternoon, corrects a file, sends two weeks of shifts: all of that was refused or postponed.

    booking_snapshots.revision   which observation of its day this row belongs to
    labor_snapshots.revision     which labor file of its day this snapshot is
    invoices.revision            which version of the document this row is
    import_jobs.changed_data     did this import change anything? (NULL: not recorded, an old job)

Nothing is rewritten. A row keeps saying what it said: the newest revision of a key is what a new
analysis reads, the older ones stay for the runs that read them, and every existing row is
revision 1. The columns are additive and backfilled by their default; the immutability triggers do
not fire, because no existing row is updated by ADD COLUMN.

Written by hand; the model tests keep the ORM metadata in sync with it. Migrations 0001-0013 are
untouched (the head before this gate was `0013_property_analysis_policy`).

The downgrade refuses to run once a second revision exists: going back would have to destroy
evidence that a run may point at, and that is not a decision a migration makes on its own.

Revision ID: 0014_same_day_revisions
Revises: 0013_property_analysis_policy
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_same_day_revisions"
down_revision: str | None = "0013_property_analysis_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOOKING_KEY_OLD = "uq_booking_snapshots_data_source_snapshot_date_stay_date"
_BOOKING_KEY = "uq_booking_snapshots_source_snapshot_stay_revision"
_LABOR_KEY_OLD = "uq_labor_snapshots_data_source_id_snapshot_local_date"
_LABOR_KEY = "uq_labor_snapshots_data_source_id_snapshot_local_date_revision"
_INVOICE_KEY_OLD = "uq_invoices_identity"
_INVOICE_KEY = "uq_invoices_identity_revision"

_INVOICE_IDENTITY = (
    "workspace_id",
    "property_id",
    "supplier_id",
    "normalized_invoice_number",
    "invoice_date",
    "document_kind",
)


def _add_revision(table: str) -> None:
    op.add_column(
        table, sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1"))
    )
    op.create_check_constraint(op.f(f"ck_{table}_revision_positive"), table, "revision >= 1")


def upgrade() -> None:
    _add_revision("booking_snapshots")
    op.drop_constraint(op.f(_BOOKING_KEY_OLD), "booking_snapshots", type_="unique")
    op.create_unique_constraint(
        op.f(_BOOKING_KEY),
        "booking_snapshots",
        ["workspace_id", "data_source_id", "snapshot_local_date", "stay_date", "revision"],
    )
    # A reconstruction is one inference of a finished day: only what NINFA saw can be seen again.
    op.create_check_constraint(
        op.f("ck_booking_snapshots_only_an_observation_is_revised"),
        "booking_snapshots",
        "revision = 1 OR origin = 'OBSERVED'",
    )

    _add_revision("labor_snapshots")
    op.drop_constraint(op.f(_LABOR_KEY_OLD), "labor_snapshots", type_="unique")
    op.create_unique_constraint(
        op.f(_LABOR_KEY),
        "labor_snapshots",
        ["workspace_id", "data_source_id", "snapshot_local_date", "revision"],
    )

    _add_revision("invoices")
    op.drop_constraint(op.f(_INVOICE_KEY_OLD), "invoices", type_="unique")
    op.create_unique_constraint(op.f(_INVOICE_KEY), "invoices", [*_INVOICE_IDENTITY, "revision"])

    op.add_column("import_jobs", sa.Column("changed_data", sa.Boolean(), nullable=True))


def _refuse_if_revised(table: str) -> None:
    query = sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE revision > 1)")
    if op.get_bind().scalar(query):
        raise RuntimeError(
            f"{table} holds a second revision: going back would destroy evidence a run may point at"
        )


def _drop_revision(table: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_revision_positive"), table, type_="check")
    op.drop_column(table, "revision")


def downgrade() -> None:
    for table in ("booking_snapshots", "labor_snapshots", "invoices"):
        _refuse_if_revised(table)

    op.drop_column("import_jobs", "changed_data")

    op.drop_constraint(op.f(_INVOICE_KEY), "invoices", type_="unique")
    op.create_unique_constraint(op.f(_INVOICE_KEY_OLD), "invoices", list(_INVOICE_IDENTITY))
    _drop_revision("invoices")

    op.drop_constraint(op.f(_LABOR_KEY), "labor_snapshots", type_="unique")
    op.create_unique_constraint(
        op.f(_LABOR_KEY_OLD),
        "labor_snapshots",
        ["workspace_id", "data_source_id", "snapshot_local_date"],
    )
    _drop_revision("labor_snapshots")

    op.drop_constraint(
        op.f("ck_booking_snapshots_only_an_observation_is_revised"),
        "booking_snapshots",
        type_="check",
    )
    op.drop_constraint(op.f(_BOOKING_KEY), "booking_snapshots", type_="unique")
    op.create_unique_constraint(
        op.f(_BOOKING_KEY_OLD),
        "booking_snapshots",
        ["workspace_id", "data_source_id", "snapshot_local_date", "stay_date"],
    )
    _drop_revision("booking_snapshots")
