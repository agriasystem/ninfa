"""Migration 0009 on real PostgreSQL: 0008 <-> 0009, base -> head, alembic current/heads/check
(tests 138-145).

Metadata/migration agreement and constraint-name parity for the Gate 11 tables are asserted by
`test_data_model_migration.py` (its table sets include them).
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

GATE_8_HEAD = "0008_labor_ingestion"
HEAD = "0009_decision_layer"
GATE_11_TABLES = {"decision_runs", "decisions", "decision_observations"}
FUNCTION = "decisions_forbid_update"
TRIGGERS = {"trg_decision_runs_immutable", "trg_decision_observations_immutable"}


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


def scalar_set(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text(sql)).scalars())


def function_exists(engine: Engine) -> bool:
    return bool(scalar_set(engine, f"SELECT proname FROM pg_proc WHERE proname = '{FUNCTION}'"))


def triggers_of(engine: Engine) -> set[str]:
    return scalar_set(
        engine,
        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname IN "
        "('trg_decision_runs_immutable', 'trg_decision_observations_immutable')",
    )


def columns_of(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(engine)
    return {
        table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)]
        for table in sorted(GATE_11_TABLES)
    }


# --- 138-140: 0008 <-> 0009 round trip -----------------------------------------------------------


def test_head_is_the_decision_layer_migration(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_11_TABLES
    assert function_exists(db_engine)
    assert triggers_of(db_engine) == TRIGGERS


def test_downgrade_to_0008_removes_only_gate_11(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_8_HEAD)

    assert revision(db_engine) == GATE_8_HEAD
    assert tables(db_engine) & GATE_11_TABLES == set()
    assert not function_exists(db_engine)
    assert triggers_of(db_engine) == set()
    # Gate 8's own tables and function are untouched
    assert {"labor_snapshots", "labor_entries"} <= tables(db_engine)
    assert bool(
        scalar_set(db_engine, "SELECT proname FROM pg_proc WHERE proname = 'labor_forbid_update'")
    )


def test_0008_to_0009_to_0008_to_0009_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = columns_of(db_engine)

    command.downgrade(config, GATE_8_HEAD)  # 0009 -> 0008
    command.upgrade(config, HEAD)  # 0008 -> 0009
    assert columns_of(db_engine) == before

    command.downgrade(config, GATE_8_HEAD)  # once more: it is repeatable
    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert columns_of(db_engine) == before
    assert function_exists(db_engine)
    assert triggers_of(db_engine) == TRIGGERS


# --- 141: base -> head ----------------------------------------------------------------------------


def test_a_fresh_database_goes_from_base_to_head(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}

    command.upgrade(config, "head")
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_11_TABLES


# --- 142-144: alembic current / heads / check -----------------------------------------------------


def test_alembic_current_is_0009(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD


def test_alembic_has_exactly_one_head(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    assert scripts.get_heads() == [HEAD]


def test_alembic_check_reports_no_pending_model_changes(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    """The moral equivalent of `alembic check`: no autogenerate diff remains against `head`."""
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_object": include_object, "compare_type": True}
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


# --- 145: 0001-0008 untouched ---------------------------------------------------------------------


def test_migrations_0001_to_0008_are_untouched_and_0009_sits_on_top(
    test_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    revisions = {rev.revision: rev.down_revision for rev in scripts.walk_revisions()}
    assert revisions[HEAD] == GATE_8_HEAD
    assert revisions[GATE_8_HEAD] == "0007_invoice_supplier_ingestion"
    assert revisions["0007_invoice_supplier_ingestion"] == "0006_expected_engine"
    assert revisions["0006_expected_engine"] == "0005_booking_snapshots_metrics"
    assert revisions["0005_booking_snapshots_metrics"] == "0004_booking_ingestion"
    assert revisions["0004_booking_ingestion"] == "0003_canonical_data_model"
    assert revisions["0003_canonical_data_model"] == "0002_procrastinate_schema"
    assert revisions["0002_procrastinate_schema"] == "0001_baseline"
    assert revisions["0001_baseline"] is None
