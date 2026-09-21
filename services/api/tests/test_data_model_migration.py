"""The migrations on real PostgreSQL: their lifecycle, and their agreement with the ORM models."""

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

HEAD = "0005_booking_snapshots_metrics"
GATE_2_HEAD = "0004_booking_ingestion"
GATE_1_HEAD = "0003_canonical_data_model"
GATE_0_HEAD = "0002_procrastinate_schema"
GATE_1_TABLES = {
    "users",
    "workspaces",
    "workspace_memberships",
    "properties",
    "data_sources",
    "import_jobs",
    "import_files",
}
GATE_2_TABLES = {"booking_channels", "booking_mapping_profiles", "bookings", "booking_import_rows"}
GATE_3_TABLES = {"room_inventory_daily", "booking_snapshots"}
MODEL_TABLES = GATE_1_TABLES | GATE_2_TABLES | GATE_3_TABLES
GATE_0_TABLES = {
    "alembic_version",
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
}
TENANT_OWNED_TABLES = (
    {
        "workspace_memberships",
        "properties",
        "data_sources",
        "import_jobs",
        "import_files",
    }
    | GATE_2_TABLES
    | GATE_3_TABLES
)


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def columns_of(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(engine)
    return {
        table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)]
        for table in sorted(MODEL_TABLES)
    }


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    """Guarantee the shared test database is back at head after a test that moves it."""
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


# --- revision history ------------------------------------------------------------------------


def test_gate_0_1_2_migrations_are_untouched_and_gate_3_sits_on_top(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    revisions = {rev.revision: rev.down_revision for rev in scripts.walk_revisions()}
    assert revisions == {
        HEAD: GATE_2_HEAD,
        GATE_2_HEAD: GATE_1_HEAD,
        GATE_1_HEAD: GATE_0_HEAD,
        GATE_0_HEAD: "0001_baseline",
        "0001_baseline": None,
    }


# --- upgrade / downgrade / re-upgrade --------------------------------------------------------


def test_upgrade_creates_the_gate_1_2_3_schema_next_to_gate_0(
    db_engine: Engine, at_head: None
) -> None:
    assert table_names(db_engine) == GATE_0_TABLES | MODEL_TABLES
    assert current_revision(db_engine) == HEAD


def test_downgrade_to_gate_0_removes_the_model_tables(
    db_engine: Engine, test_database_url: str, at_head: None
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_0_HEAD)

    assert table_names(db_engine) == GATE_0_TABLES
    assert current_revision(db_engine) == GATE_0_HEAD
    with db_engine.connect() as connection:  # the job queue is still intact
        assert connection.execute(text("SELECT to_regclass('procrastinate_jobs')")).scalar_one()


def test_re_upgrade_after_downgrade_recreates_an_identical_schema(
    db_engine: Engine, test_database_url: str, at_head: None
) -> None:
    before = columns_of(db_engine)

    config = alembic_config(test_database_url)
    command.downgrade(config, GATE_0_HEAD)
    command.upgrade(config, "head")

    assert columns_of(db_engine) == before
    assert current_revision(db_engine) == HEAD
    assert table_names(db_engine) == GATE_0_TABLES | MODEL_TABLES


def test_upgrade_is_idempotent_at_head(test_database_url: str, at_head: None) -> None:
    command.upgrade(alembic_config(test_database_url), "head")


# --- models and migration describe the same database -----------------------------------------


def test_orm_metadata_and_migration_agree(db_engine: Engine, at_head: None) -> None:
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object, "compare_type": True},
        )
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_constraint_and_index_names_match_the_models(db_engine: Engine, at_head: None) -> None:
    """CHECK constraints are invisible to Alembic's diff, so compare names explicitly."""
    with db_engine.connect() as connection:
        database_constraints = set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid"
                    " WHERE t.relname = ANY(:tables) AND c.contype IN ('p', 'f', 'u', 'c')"
                ),
                {"tables": sorted(MODEL_TABLES)},
            ).scalars()
        )
        database_indexes = set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                    " AND tablename = ANY(:tables)"
                ),
                {"tables": sorted(MODEL_TABLES)},
            ).scalars()
        )

    tables = [Base.metadata.tables[name] for name in MODEL_TABLES]
    model_constraints = {c.name for table in tables for c in table.constraints}
    model_indexes = {index.name for table in tables for index in table.indexes}

    assert database_constraints == model_constraints
    # Primary keys and unique constraints are backed by indexes of the same name.
    unique_backing = {n for n in database_constraints if n.startswith(("pk_", "uq_"))}
    assert database_indexes - unique_backing == model_indexes


# --- the structural guarantees the design relies on ------------------------------------------


def test_tenant_foreign_keys_are_composite_and_carry_workspace_id(
    db_engine: Engine, at_head: None
) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE contype = 'f' AND conname LIKE ANY (ARRAY['fk_data_sources%',"
                " 'fk_import_jobs%', 'fk_import_files%'])"
            )
        )
        definitions: dict[str, str] = {row[0]: row[1] for row in rows}

    assert definitions == {
        "fk_data_sources_workspace_id_properties": (
            "FOREIGN KEY (workspace_id, property_id)"
            " REFERENCES properties(workspace_id, id) ON DELETE RESTRICT"
        ),
        "fk_import_jobs_workspace_id_data_sources": (
            "FOREIGN KEY (workspace_id, property_id, data_source_id)"
            " REFERENCES data_sources(workspace_id, property_id, id) ON DELETE RESTRICT"
        ),
        "fk_import_files_workspace_id_import_jobs": (
            "FOREIGN KEY (workspace_id, import_job_id)"
            " REFERENCES import_jobs(workspace_id, id) ON DELETE RESTRICT"
        ),
    }


def test_delete_policy_only_memberships_cascade(db_engine: Engine, at_head: None) -> None:
    with db_engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT constraint_name, delete_rule"
                " FROM information_schema.referential_constraints"
                " WHERE constraint_schema = 'public' AND constraint_name LIKE 'fk\\_%'"
            )
        )
        rules: dict[str, str] = {row[0]: row[1] for row in result}

    assert {name for name, rule in rules.items() if rule == "CASCADE"} == {
        "fk_workspace_memberships_workspace_id_workspaces",
        "fk_workspace_memberships_user_id_users",
    }
    assert {rule for name, rule in rules.items() if "membership" not in name} == {"RESTRICT"}
    assert len(rules) == 16  # 6 Gate 1 + 7 Gate 2 + 3 Gate 3; a new FK must be classified here


def test_every_tenant_owned_table_has_a_not_null_workspace_id(
    db_engine: Engine, at_head: None
) -> None:
    inspector = inspect(db_engine)

    for table in TENANT_OWNED_TABLES:
        column = next(c for c in inspector.get_columns(table) if c["name"] == "workspace_id")
        assert column["nullable"] is False, table
        assert "UUID" in str(column["type"]).upper(), table


def test_identifiers_and_timestamps_use_uuid_and_timestamptz(
    db_engine: Engine, at_head: None
) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable, column_default"
                " FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = ANY(:tables)"
                " AND (column_name = 'id' OR column_name LIKE '%\\_at')"
            ),
            {"tables": sorted(MODEL_TABLES)},
        ).all()

    assert rows
    for table, column, data_type, nullable, default in rows:
        where = f"{table}.{column}"
        if column == "id":
            assert (data_type, default) == ("uuid", "gen_random_uuid()"), where
        else:
            assert data_type == "timestamp with time zone", where
            if column in {"created_at", "updated_at"}:
                assert (nullable, default) == ("NO", "now()"), where
