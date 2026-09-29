"""Migration 0011 on real PostgreSQL: 0010 <-> 0011, base -> head, alembic current/heads/check.

Gate 22 added `0011_analysis_coverage` on top of `0010_auth_session`: "is X the global head"
questions now belong HERE (see `test_decision_migration.py`'s own docstring for the same pattern
one gate earlier) - `test_auth_migration.py` keeps only what is still actually about Gate 13's own
schema.
"""

from collections.abc import Iterator

import psycopg.errors as pg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.db.migration_filters import include_object
from app.modules.properties.models import Property
from app.modules.tenancy.models import Workspace
from tests.support import Rejects, alembic_config

GATE_10_HEAD = "0010_auth_session"
HEAD = "0011_analysis_coverage"
GATE_22_COLUMN = "analysis_coverage"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def columns_of(engine: Engine, table: str) -> list[str]:
    return [c["name"] for c in inspect(engine).get_columns(table)]


def nullable_of(engine: Engine, table: str, column: str) -> bool:
    [info] = [c for c in inspect(engine).get_columns(table) if c["name"] == column]
    return bool(info["nullable"])


# --- 0010 <-> 0011 round trip --------------------------------------------------------------------


def test_head_is_the_analysis_coverage_migration(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD
    assert GATE_22_COLUMN in columns_of(db_engine, "decision_runs")
    assert nullable_of(db_engine, "decision_runs", GATE_22_COLUMN) is True


def test_downgrade_to_0010_removes_only_the_new_column(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_10_HEAD)
    assert revision(db_engine) == GATE_10_HEAD
    assert GATE_22_COLUMN not in columns_of(db_engine, "decision_runs")
    # decision_runs itself, and every other Gate 11 table, is untouched
    assert {"decision_runs", "decisions", "decision_observations"} <= set(
        inspect(db_engine).get_table_names()
    )


def test_0010_to_0011_to_0010_to_0011_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = columns_of(db_engine, "decision_runs")

    command.downgrade(config, GATE_10_HEAD)
    command.upgrade(config, HEAD)
    assert columns_of(db_engine, "decision_runs") == before

    command.downgrade(config, GATE_10_HEAD)
    command.upgrade(config, "head")
    assert revision(db_engine) == HEAD
    assert columns_of(db_engine, "decision_runs") == before


# --- base -> head ---------------------------------------------------------------------------------


def test_a_fresh_database_goes_from_base_to_head(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    assert set(inspect(db_engine).get_table_names()) == {"alembic_version"}
    command.upgrade(config, "head")
    assert revision(db_engine) == HEAD
    assert GATE_22_COLUMN in columns_of(db_engine, "decision_runs")


# --- alembic current / heads / check --------------------------------------------------------------


def test_alembic_current_is_0011(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD


def test_alembic_has_exactly_one_head(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    assert scripts.get_heads() == [HEAD]


def test_alembic_check_reports_no_pending_model_changes(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_object": include_object, "compare_type": True}
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


# --- 0001-0010 untouched, 0011 sits on top -----------------------------------------------------


def test_migrations_0001_to_0010_are_untouched_and_0011_sits_on_top(
    test_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    revisions = {rev.revision: rev.down_revision for rev in scripts.walk_revisions()}
    assert revisions[HEAD] == GATE_10_HEAD
    assert revisions[GATE_10_HEAD] == "0009_decision_layer"
    assert revisions["0009_decision_layer"] == "0008_labor_ingestion"
    assert revisions["0008_labor_ingestion"] == "0007_invoice_supplier_ingestion"
    assert revisions["0007_invoice_supplier_ingestion"] == "0006_expected_engine"
    assert revisions["0006_expected_engine"] == "0005_booking_snapshots_metrics"
    assert revisions["0005_booking_snapshots_metrics"] == "0004_booking_ingestion"
    assert revisions["0004_booking_ingestion"] == "0003_canonical_data_model"
    assert revisions["0003_canonical_data_model"] == "0002_procrastinate_schema"
    assert revisions["0002_procrastinate_schema"] == "0001_baseline"
    assert revisions["0001_baseline"] is None


# --- the CHECK constraint itself --------------------------------------------------------------


def test_analysis_coverage_check_constraint_rejects_a_non_object_jsonb_value(
    at_head: None, db_engine: Engine, rejects: Rejects, db_session: Session
) -> None:
    workspace = Workspace(name="W", slug="ck-analysis-coverage")
    db_session.add(workspace)
    db_session.flush()
    prop = Property(workspace_id=workspace.id, name="P", slug="ck-analysis-coverage")
    db_session.add(prop)
    db_session.flush()

    with rejects(pg.CheckViolation, "ck_decision_runs_analysis_coverage_is_object"):
        db_session.execute(
            text(
                "INSERT INTO decision_runs (id, run_sequence, workspace_id, property_id, "
                "as_of_local_date, input_fingerprint, priority_ranking_fingerprint, "
                "evaluation_count, triggered_count, clear_count, insufficient_count, "
                "not_applicable_count, suppressed_count, duplicate_input_count, "
                "analysis_coverage) VALUES (gen_random_uuid(), DEFAULT, :workspace_id, "
                ":property_id, CURRENT_DATE, repeat('a', 64), repeat('b', 64), 0, 0, 0, 0, 0, "
                "0, 0, '[1, 2, 3]'::jsonb)"
            ),
            {"workspace_id": workspace.id, "property_id": prop.id},
        )
