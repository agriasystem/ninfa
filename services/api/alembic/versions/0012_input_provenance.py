"""Gate 23B: Run Input Provenance & Booking Freshness V1.

Adds ONE nullable column to the existing `decision_runs` table:

    input_provenance    JSONB, nullable - from which booking input/source freshness this run's
                         facts derived, frozen at analysis time, per
                         app.modules.decisions.provenance.RunInputProvenance.to_json()

No new table, no backfill: every row persisted before this migration keeps
`input_provenance = NULL`, which the API/frontend read as "freshness not recorded"/UNKNOWN -
never a fabricated historical freshness fact (see `decisions/provenance.py`'s own module
docstring, or docs/architecture/booking-freshness-provenance-v1.md). `decision_runs` stays
append-only: this migration only widens its shape, the existing `decisions_forbid_update` trigger
(0009_decision_layer) is untouched and still applies to the new column exactly like every other
one on this table.

Written by hand; `tests/test_decision_migration.py`/`tests/test_input_provenance_migration.py`
keep the ORM metadata in sync with it. Migrations 0001-0011 are untouched (the head before this
gate was `0011_analysis_coverage`).

Revision ID: 0012_input_provenance
Revises: 0011_analysis_coverage
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_input_provenance"
down_revision: str | None = "0011_analysis_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_runs",
        sa.Column("input_provenance", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_decision_runs_input_provenance_is_object"),
        "decision_runs",
        "input_provenance IS NULL OR jsonb_typeof(input_provenance) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_decision_runs_input_provenance_is_object"), "decision_runs", type_="check"
    )
    op.drop_column("decision_runs", "input_provenance")
