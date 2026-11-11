"""Migration 0016_remembered_scope: additive, one head, and it will not lose why an import acted.

The current global head lives here (`test_01`); the older migration files name it as a constant.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

HEAD = "0016_remembered_scope"
PREVIOUS_HEAD = "0015_import_scope"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _columns(engine: Engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("import_jobs")}


def _seed_job(engine: Engine, *, remembered: str | None) -> uuid.UUID:
    workspace, prop, source, job = (uuid.uuid4() for _ in range(4))
    suffix = uuid.uuid4().hex[:10]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Migrazione', :slug)"),
            {"id": workspace, "slug": f"memo-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO properties (id, workspace_id, name, slug, timezone, currency)"
                " VALUES (:id, :w, 'Migrazione', :slug, 'Europe/Rome', 'EUR')"
            ),
            {"id": prop, "w": workspace, "slug": f"memo-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO data_sources"
                " (id, workspace_id, property_id, name, domain, source_type)"
                " VALUES (:id, :w, :p, 'Prenotazioni', 'BOOKINGS', 'FILE_UPLOAD')"
            ),
            {"id": source, "w": workspace, "p": prop},
        )
        connection.execute(
            text(
                "INSERT INTO import_jobs (id, workspace_id, property_id, data_source_id, status,"
                " started_at, finished_at, remembered_file_scope)"
                " VALUES (:id, :w, :p, :s, 'SUCCEEDED', now(), now(), :r)"
            ),
            {"id": job, "w": workspace, "p": prop, "s": source, "r": remembered},
        )
    return workspace


def _purge(engine: Engine, workspace: uuid.UUID) -> None:
    with engine.begin() as connection:
        for table in ("import_jobs", "data_sources", "properties"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": workspace}
            )
        connection.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})


def test_01_there_is_exactly_one_head_and_it_sits_on_0015(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS_HEAD


def test_02_there_is_one_migration_numbered_0015(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    numbered = [rev.revision for rev in scripts.walk_revisions() if rev.revision.startswith("0015")]

    assert numbered == [PREVIOUS_HEAD]


def test_03_the_column_comes_and_goes_with_it(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    assert "remembered_file_scope" in _columns(db_engine)

    command.downgrade(config, PREVIOUS_HEAD)

    assert _revision(db_engine) == PREVIOUS_HEAD
    assert "remembered_file_scope" not in _columns(db_engine)

    command.upgrade(config, "head")
    assert _revision(db_engine) == HEAD
    assert "remembered_file_scope" in _columns(db_engine)


def test_04_the_downgrade_refuses_to_lose_why_an_import_acted(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    workspace = _seed_job(db_engine, remembered="FULL")
    try:
        with pytest.raises(RuntimeError, match="what was remembered"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS_HEAD)
        assert _revision(db_engine) == HEAD
    finally:
        _purge(db_engine, workspace)


def test_05_it_holds_only_the_three_words(at_head: None, db_engine: Engine) -> None:
    with pytest.raises(Exception, match="remembered_file_scope_valid"):
        _seed_job(db_engine, remembered="NOT_A_SCOPE")
