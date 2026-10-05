"""Gate 26B: migration 0013_property_analysis_policy - additive, opt-in, one head.

Adds ONE table. No row is inserted: a property that existed before the migration stays NOT
automated (absence of a row means disabled). Migrations 0001-0012 are untouched.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

HEAD = "0013_property_analysis_policy"
PREVIOUS_HEAD = "0012_input_provenance"
TABLE = "property_analysis_policies"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def test_01_there_is_exactly_one_head_and_it_sits_on_0012(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS_HEAD


def test_02_downgrade_removes_only_the_new_table_and_upgrade_restores_it(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    columns = {c["name"] for c in inspect(db_engine).get_columns(TABLE)}
    assert columns == {
        "id",
        "workspace_id",
        "property_id",
        "enabled",
        "booking_data_source_id",
        "created_at",
        "updated_at",
    }

    command.downgrade(config, PREVIOUS_HEAD)
    assert _revision(db_engine) == PREVIOUS_HEAD
    assert TABLE not in inspect(db_engine).get_table_names()
    assert {"decision_runs", "properties", "data_sources"} <= set(
        inspect(db_engine).get_table_names()
    )

    command.upgrade(config, "head")
    assert _revision(db_engine) == HEAD
    assert {c["name"] for c in inspect(db_engine).get_columns(TABLE)} == columns


def test_03_a_property_that_existed_before_the_migration_is_not_automated(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    workspace_id, property_id = uuid.uuid4(), uuid.uuid4()
    slug = f"mig-{uuid.uuid4().hex[:10]}"
    command.downgrade(config, PREVIOUS_HEAD)
    try:
        with db_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Old', :slug)"),
                {"id": workspace_id, "slug": slug},
            )
            connection.execute(
                text(
                    "INSERT INTO properties (id, workspace_id, name, slug)"
                    " VALUES (:id, :workspace_id, 'Old', :slug)"
                ),
                {"id": property_id, "workspace_id": workspace_id, "slug": slug},
            )

        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
            assert (
                connection.execute(
                    text("SELECT count(*) FROM properties WHERE id = :id"), {"id": property_id}
                ).scalar_one()
                == 1
            )
    finally:
        command.upgrade(config, "head")
        with db_engine.begin() as connection:
            connection.execute(text("DELETE FROM properties WHERE id = :id"), {"id": property_id})
            connection.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": workspace_id})


def test_04_a_fresh_database_goes_from_base_to_head(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    assert TABLE not in inspect(db_engine).get_table_names()

    command.upgrade(config, "head")

    assert _revision(db_engine) == HEAD
    assert TABLE in inspect(db_engine).get_table_names()
