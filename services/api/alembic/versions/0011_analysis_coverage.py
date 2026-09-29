"""Gate 22: Analysis Coverage V1.

Adds ONE nullable column to the existing `decision_runs` table:

    analysis_coverage    JSONB, nullable - which of the four user-facing analysis domains
                          (REVENUE, DISTRIBUTION, COSTS, LABOR) a run actually attempted, per
                          app.modules.decisions.coverage.AnalysisCoverage.to_json()

No new table, no backfill: every row persisted before this migration keeps
`analysis_coverage = NULL`, which the API/frontend read as "coverage not recorded" - never as
"nothing was analysed" and never as "everything was analysed" (see
docs/architecture/pilot-readiness-v1.md's sibling doc for Gate 22, or `decisions/coverage.py`'s
own module docstring). `decision_runs` stays append-only: this migration only widens its shape,
the existing `decisions_forbid_update` trigger (0009_decision_layer) is untouched and still
applies to the new column exactly like every other one on this table.

Written by hand; `tests/test_decision_migration.py`/`test_analysis_coverage_migration.py` keep
the ORM metadata in sync with it. Migrations 0001-0010 are untouched (Gates 14-21 added no
schema; the head before this gate was `0010_auth_session`).

Revision ID: 0011_analysis_coverage
Revises: 0010_auth_session
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_analysis_coverage"
down_revision: str | None = "0010_auth_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_runs",
        sa.Column("analysis_coverage", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_decision_runs_analysis_coverage_is_object"),
        "decision_runs",
        "analysis_coverage IS NULL OR jsonb_typeof(analysis_coverage) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_decision_runs_analysis_coverage_is_object"), "decision_runs", type_="check"
    )
    op.drop_column("decision_runs", "analysis_coverage")
