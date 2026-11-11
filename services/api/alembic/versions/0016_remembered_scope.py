"""What a source remembered when an import was read (Remembered Scope Safety V1.2.2).

A removal needs a reason that can be read back. `import_jobs.file_scope` says what an import
applied; this says what the family of files remembered at that moment, which the memory itself can
no longer say once it has moved on. Together:

    remembered  applied   what happened
    NULL        FULL      the first answer about this structure
    FULL        FULL      with removals, a person confirmed it on this import: a memory alone
                          takes nothing away
    FULL        PARTIAL   this import was declared a part of its period; the memory stays
    PARTIAL     FULL      a person said this one holds everything

Every existing row keeps meaning what it meant: NULL, nothing recorded. Written by hand; the model
tests keep the ORM metadata in sync with it. Migrations 0001-0015 are untouched.

The downgrade refuses to run once a row holds it: it is what explains a removal.

Revision ID: 0016_remembered_scope
Revises: 0015_import_scope
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_remembered_scope"
down_revision: str | None = "0015_import_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_jobs", sa.Column("remembered_file_scope", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_remembered_file_scope_valid"),
        "import_jobs",
        "remembered_file_scope IS NULL OR remembered_file_scope IN ('FULL', 'PARTIAL', 'DELTA')",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM import_jobs WHERE remembered_file_scope IS NOT NULL)")
    ):
        raise RuntimeError("an import says what was remembered: going back would lose why it acted")

    op.drop_constraint(
        op.f("ck_import_jobs_remembered_file_scope_valid"), "import_jobs", type_="check"
    )
    op.drop_column("import_jobs", "remembered_file_scope")
