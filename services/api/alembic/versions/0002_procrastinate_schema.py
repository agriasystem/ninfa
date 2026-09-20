"""Procrastinate job-queue schema (worker foundation).

The SQL is a vendored copy of `procrastinate/sql/schema.sql` from procrastinate 3.9.0, so this
migration stays reproducible when the library is upgraded. Upgrading Procrastinate later means
adding a new revision with the matching `migrations/*.sql` from that release (see ADR 0005).

Revision ID: 0002_procrastinate_schema
Revises: 0001_baseline
Create Date: 2026-09-20
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002_procrastinate_schema"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_SQL = Path(__file__).parent / "sql" / "procrastinate_3.9.0_schema.sql"

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers,
    procrastinate_jobs, procrastinate_workers CASCADE;
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT p.oid::regprocedure AS signature
        FROM pg_proc p
        WHERE p.proname LIKE 'procrastinate\\_%'
          AND p.pronamespace = current_schema()::regnamespace
    LOOP
        EXECUTE 'DROP FUNCTION ' || r.signature || ' CASCADE';
    END LOOP;
END $$;
DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, procrastinate_job_event_type,
    procrastinate_job_status CASCADE;
"""


def _run_script(sql: str) -> None:
    """Run a multi-statement script through the raw psycopg connection.

    SQLAlchemy's `op.execute` binds a parameter set, which makes psycopg use the extended
    protocol (one statement only) and interpret `%`. Without parameters psycopg uses the simple
    protocol, which accepts a whole script verbatim, inside the current Alembic transaction.
    """
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(sql)


def upgrade() -> None:
    _run_script(_SCHEMA_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    _run_script(_DOWNGRADE_SQL)
