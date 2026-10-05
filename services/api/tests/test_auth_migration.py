"""Migration 0010 on real PostgreSQL: 0009 <-> 0010, base -> head, alembic current/heads/check
(review items 112-119).

Gate 22 added `0011_analysis_coverage` on top of `0010_auth_session`, and Gate 23B added
`0012_input_provenance` on top of THAT: "is 0010 the global head" questions now belong to
`test_input_provenance_migration.py` (which owns the real current head); this file keeps only
what is still actually about Gate 13's own schema - that it round-trips cleanly and survives
being reached via `base -> ... -> head` regardless of what sits on top of it.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

import app.models  # noqa: F401
from app.db.base import Base
from app.db.migration_filters import include_object
from tests.support import alembic_config

GATE_9_HEAD = "0009_decision_layer"
HEAD = "0010_auth_session"
# Gate 22 added 0011_analysis_coverage on top, then Gate 23B added 0012_input_provenance on top
# of THAT; owned/asserted by test_input_provenance_migration.py.
CURRENT_GLOBAL_HEAD = "0013_property_analysis_policy"
GATE_13_TABLES = {"user_credentials", "auth_sessions"}


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def columns_of(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(engine)
    return {
        table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)]
        for table in sorted(GATE_13_TABLES)
    }


# --- 112-114: 0009 <-> 0010 round trip -------------------------------------------------------


def test_head_is_the_auth_session_migration(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == CURRENT_GLOBAL_HEAD
    assert tables(db_engine) >= GATE_13_TABLES


def test_downgrade_to_0009_removes_only_gate_13(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_9_HEAD)
    assert revision(db_engine) == GATE_9_HEAD
    assert tables(db_engine) & GATE_13_TABLES == set()
    # Gate 11's own tables are untouched
    assert {"decision_runs", "decisions", "decision_observations"} <= tables(db_engine)


def test_0009_to_0010_to_0009_to_0010_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = columns_of(db_engine)

    command.downgrade(config, GATE_9_HEAD)
    command.upgrade(config, HEAD)
    assert columns_of(db_engine) == before

    command.downgrade(config, GATE_9_HEAD)
    command.upgrade(config, "head")  # back to the real current head (0012, post Gate 23B)
    assert revision(db_engine) == CURRENT_GLOBAL_HEAD
    assert columns_of(db_engine) == before


# --- 115: base -> head -------------------------------------------------------------------------


def test_a_fresh_database_goes_from_base_to_head(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}
    command.upgrade(config, "head")
    assert revision(db_engine) == CURRENT_GLOBAL_HEAD
    assert tables(db_engine) >= GATE_13_TABLES


# --- 116-118: alembic current / heads / check -----------------------------------------------------
#
# "alembic current is the one true head" / "exactly one head" are now owned by
# test_input_provenance_migration.py, which asserts them against the real current head
# (0012_input_provenance); duplicating them here under a stale name would only reassert a fact
# about the global chain, not about Gate 13's own schema. The "no pending model changes" check
# below stays here too (and in every later gate's own file): it is driven by the REAL head via
# `at_head`, so it is never stale, whichever revision that head happens to be.


def test_alembic_check_reports_no_pending_model_changes(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_object": include_object, "compare_type": True}
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


# --- 119: 0001-0009 untouched --------------------------------------------------------------------


def test_migrations_0001_to_0009_are_untouched_and_0010_sits_on_top(
    test_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    revisions = {rev.revision: rev.down_revision for rev in scripts.walk_revisions()}
    assert revisions[HEAD] == GATE_9_HEAD
    assert revisions[GATE_9_HEAD] == "0008_labor_ingestion"
    assert revisions["0008_labor_ingestion"] == "0007_invoice_supplier_ingestion"
    assert revisions["0007_invoice_supplier_ingestion"] == "0006_expected_engine"
    assert revisions["0006_expected_engine"] == "0005_booking_snapshots_metrics"
    assert revisions["0005_booking_snapshots_metrics"] == "0004_booking_ingestion"
    assert revisions["0004_booking_ingestion"] == "0003_canonical_data_model"
    assert revisions["0003_canonical_data_model"] == "0002_procrastinate_schema"
    assert revisions["0002_procrastinate_schema"] == "0001_baseline"
    assert revisions["0001_baseline"] is None
