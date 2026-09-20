"""Migration 0004 on real PostgreSQL: 0003 <-> 0004, base -> head, and what it must not disturb.

Metadata/migration agreement and constraint-name parity for the Gate 2 tables are asserted by
test_data_model_migration.py (its table sets include them).
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from app.modules.tenancy.models import Workspace
from tests.support import alembic_config

GATE_1_HEAD = "0003_canonical_data_model"
HEAD = "0004_booking_ingestion"
GATE_2_TABLES = {"booking_channels", "booking_mapping_profiles", "bookings", "booking_import_rows"}
GATE_1_TABLES = {
    "users",
    "workspaces",
    "workspace_memberships",
    "properties",
    "data_sources",
    "import_jobs",
    "import_files",
}
GATE_2_FUNCTION = "bookings_forbid_identity_change"
EXTRA_UNIQUES = {
    "uq_import_jobs_workspace_id_property_id_data_source_id_id",
    "uq_import_files_workspace_id_import_job_id_id",
}


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


def extra_uniques(engine: Engine) -> set[str]:
    return scalar_set(
        engine,
        "SELECT conname FROM pg_constraint WHERE contype = 'u'"
        " AND conname IN ('uq_import_jobs_workspace_id_property_id_data_source_id_id',"
        " 'uq_import_files_workspace_id_import_job_id_id')",
    )


def function_exists(engine: Engine) -> bool:
    return bool(
        scalar_set(engine, f"SELECT proname FROM pg_proc WHERE proname = '{GATE_2_FUNCTION}'")
    )


def test_head_is_the_booking_ingestion_migration(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_2_TABLES
    assert extra_uniques(db_engine) == EXTRA_UNIQUES
    assert function_exists(db_engine)


def test_upgrade_from_0003_downgrade_to_0003_and_upgrade_again(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, GATE_1_HEAD)  # 0004 -> 0003
    assert revision(db_engine) == GATE_1_HEAD
    assert tables(db_engine) & GATE_2_TABLES == set()
    assert tables(db_engine) >= GATE_1_TABLES  # Gate 1 is untouched
    assert extra_uniques(db_engine) == set()
    assert not function_exists(db_engine)

    command.upgrade(config, "head")  # 0003 -> 0004
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_2_TABLES
    assert extra_uniques(db_engine) == EXTRA_UNIQUES
    assert function_exists(db_engine)

    command.downgrade(config, GATE_1_HEAD)  # and once more, to prove it is repeatable
    command.upgrade(config, "head")
    assert revision(db_engine) == HEAD


def test_a_fresh_database_goes_from_base_to_head(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}
    assert not function_exists(db_engine)

    command.upgrade(config, "head")
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_1_TABLES | GATE_2_TABLES


def test_gate_1_data_survives_a_downgrade_and_upgrade_of_gate_2(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    """0004 only adds: rows of Gate 1 tables are still there after 0004 goes away and returns."""
    slug = f"survivor-{uuid.uuid4().hex[:8]}"
    with Session(db_engine) as session:
        session.add(Workspace(name="Survivor", slug=slug))
        session.commit()
    try:
        config = alembic_config(test_database_url)
        command.downgrade(config, GATE_1_HEAD)
        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            found = connection.execute(
                text("SELECT count(*) FROM workspaces WHERE slug = :slug"), {"slug": slug}
            ).scalar_one()
        assert found == 1
    finally:
        with Session(db_engine) as session:
            session.execute(text("DELETE FROM workspaces WHERE slug = :slug"), {"slug": slug})
            session.commit()


def test_the_extra_unique_keys_exist_to_be_targets_of_the_booking_foreign_keys(
    at_head: None, db_engine: Engine
) -> None:
    """Which is why the downgrade drops the booking tables before the two unique constraints."""
    with db_engine.connect() as connection:
        dependants = (
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'f' AND confrelid = ANY("
                    " ARRAY['import_jobs'::regclass, 'import_files'::regclass])"
                    " AND conname LIKE ANY (ARRAY['fk_bookings%', 'fk_booking_import_rows%'])"
                )
            )
            .scalars()
            .all()
        )
    assert set(dependants) == {
        "fk_bookings_first_import_job",
        "fk_bookings_last_import_job",
        "fk_booking_import_rows_workspace_id_import_files",
    }


def test_the_identity_trigger_is_installed_on_bookings_only(
    at_head: None, db_engine: Engine
) -> None:
    triggers = scalar_set(
        db_engine,
        "SELECT tgrelid::regclass::text || ':' || tgname FROM pg_trigger WHERE NOT tgisinternal"
        " AND tgname LIKE 'trg\\_bookings%'",
    )

    assert triggers == {"bookings:trg_bookings_identity_immutable"}
