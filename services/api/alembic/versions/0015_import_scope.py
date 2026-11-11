"""What the absence of a record means (Import Scope Semantics V1.2.1).

A record missing from a later file does not always say the same thing. If the file holds everything
of the period it covers, the record is no longer there; if it holds a part of it, or only what is
new, its absence says nothing. NINFA now knows which, and acts on it:

    import_jobs.file_scope               what this import was known to be (NULL: not known)
    bookings.removed_by_import_job_id    the complete file that no longer held this booking
    bookings.removed_at                  when
    bookings.last_seen_import_job_id     the last import that did hold it

Nothing is deleted. A booking no longer in the source stays, marked, with where it went and where it
was last seen; a later file that holds it again brings it back. Labor needs no column of its own:
snapshots are kept anyway, and `labor.current_plan` reads the job's `file_scope`.

Every existing row keeps meaning what it meant: no job has a scope (absence says nothing), no
booking is removed. Written by hand; the model tests keep the ORM metadata in sync with it.
Migrations 0001-0014 are untouched (the head before this gate was `0014_same_day_revisions`).

The downgrade refuses to run once it would change what the data say: a removed booking would count
again, and a complete staff file would stop clearing what it cleared.

Revision ID: 0015_import_scope
Revises: 0014_same_day_revisions
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_import_scope"
down_revision: str | None = "0014_same_day_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_COLUMNS = [
    "import_jobs.workspace_id",
    "import_jobs.property_id",
    "import_jobs.data_source_id",
    "import_jobs.id",
]


def upgrade() -> None:
    op.add_column("import_jobs", sa.Column("file_scope", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f("ck_import_jobs_file_scope_valid"),
        "import_jobs",
        "file_scope IS NULL OR file_scope IN ('FULL', 'PARTIAL', 'DELTA')",
    )

    op.add_column("bookings", sa.Column("removed_by_import_job_id", sa.Uuid(), nullable=True))
    op.add_column("bookings", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("last_seen_import_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bookings_removed_by_import_job"),
        "bookings",
        "import_jobs",
        ["workspace_id", "property_id", "data_source_id", "removed_by_import_job_id"],
        ["workspace_id", "property_id", "data_source_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_bookings_last_seen_import_job"),
        "bookings",
        "import_jobs",
        ["workspace_id", "property_id", "data_source_id", "last_seen_import_job_id"],
        ["workspace_id", "property_id", "data_source_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_bookings_removal_is_whole"),
        "bookings",
        "(removed_by_import_job_id IS NULL) = (removed_at IS NULL)"
        " AND (last_seen_import_job_id IS NULL OR removed_at IS NOT NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM bookings WHERE removed_at IS NOT NULL)")):
        raise RuntimeError("a booking is marked removed: going back would count it again")
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM import_jobs WHERE file_scope = 'FULL')")):
        raise RuntimeError("an import was a complete file: going back would forget what it cleared")

    op.drop_constraint(op.f("ck_bookings_removal_is_whole"), "bookings", type_="check")
    op.drop_constraint(op.f("fk_bookings_last_seen_import_job"), "bookings", type_="foreignkey")
    op.drop_constraint(op.f("fk_bookings_removed_by_import_job"), "bookings", type_="foreignkey")
    op.drop_column("bookings", "last_seen_import_job_id")
    op.drop_column("bookings", "removed_at")
    op.drop_column("bookings", "removed_by_import_job_id")

    op.drop_constraint(op.f("ck_import_jobs_file_scope_valid"), "import_jobs", type_="check")
    op.drop_column("import_jobs", "file_scope")
