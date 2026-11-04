"""Migration 0015_import_scope: additive, every existing row keeps meaning what it meant, one head,
and it will not go back once going back would change what the data say.

The current global head lives here (`test_01`); the older migration files name it as a constant.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

HEAD = "0015_import_scope"
PREVIOUS_HEAD = "0014_same_day_revisions"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_01_there_is_exactly_one_head_and_it_sits_on_0014(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS_HEAD


def test_02_there_is_one_migration_numbered_0014_on_this_chain(test_database_url: str) -> None:
    """`feature/mia-v3-company-intelligence` has its own 0014: renumbered when it is rebased."""
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    numbered = [rev.revision for rev in scripts.walk_revisions() if rev.revision.startswith("0014")]

    assert numbered == [PREVIOUS_HEAD]


def test_03_the_columns_come_and_go_with_it(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    removal = {"removed_by_import_job_id", "removed_at", "last_seen_import_job_id"}
    assert removal <= _columns(db_engine, "bookings")
    assert "file_scope" in _columns(db_engine, "import_jobs")

    command.downgrade(config, PREVIOUS_HEAD)

    assert _revision(db_engine) == PREVIOUS_HEAD
    assert not removal & _columns(db_engine, "bookings")
    assert "file_scope" not in _columns(db_engine, "import_jobs")

    command.upgrade(config, "head")
    assert _revision(db_engine) == HEAD
    assert removal <= _columns(db_engine, "bookings")


def _seed(engine: Engine, *, removed: bool = False, scope: str | None = None) -> uuid.UUID:
    """A booking and its job, through plain SQL: this test runs on both sides of the migration."""
    workspace, prop, source, job, channel, booking = (uuid.uuid4() for _ in range(6))
    suffix = uuid.uuid4().hex[:10]
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Migrazione', :slug)"),
            {"id": workspace, "slug": f"migr-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO properties (id, workspace_id, name, slug, timezone, currency)"
                " VALUES (:id, :w, 'Migrazione', :slug, 'Europe/Rome', 'EUR')"
            ),
            {"id": prop, "w": workspace, "slug": f"migr-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO data_sources"
                " (id, workspace_id, property_id, name, domain, source_type)"
                " VALUES (:id, :w, :p, 'Prenotazioni', 'BOOKINGS', 'FILE_UPLOAD')"
            ),
            {"id": source, "w": workspace, "p": prop},
        )
        job_columns = "" if scope is None else ", file_scope"
        job_value = "" if scope is None else f", '{scope}'"
        connection.execute(
            text(
                "INSERT INTO import_jobs (id, workspace_id, property_id, data_source_id, status,"
                f" started_at, finished_at{job_columns})"
                f" VALUES (:id, :w, :p, :s, 'SUCCEEDED', :now, :now{job_value})"
            ),
            {"id": job, "w": workspace, "p": prop, "s": source, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO booking_channels (id, workspace_id, property_id, name,"
                " normalized_name, channel_type)"
                " VALUES (:id, :w, :p, 'Diretto', 'diretto', 'DIRECT')"
            ),
            {"id": channel, "w": workspace, "p": prop},
        )
        removal_columns = ", removed_by_import_job_id, removed_at" if removed else ""
        removal_values = ", :j, :now" if removed else ""
        connection.execute(
            text(
                "INSERT INTO bookings (id, workspace_id, property_id, data_source_id,"
                " source_record_id, booked_at, check_in, check_out, status, rooms, room_revenue,"
                " channel_id, source_fingerprint, first_import_job_id, last_import_job_id"
                f"{removal_columns}) VALUES (:id, :w, :p, :s, 'R-1', :now, '2026-09-01',"
                " '2026-09-02', 'CONFIRMED', 1, :money, :c, :fp, :j, :j"
                f"{removal_values})"
            ),
            {
                "id": booking,
                "w": workspace,
                "p": prop,
                "s": source,
                "now": now,
                "money": Decimal("100.00"),
                "c": channel,
                "fp": "a" * 64,
                "j": job,
            },
        )
    return workspace


def _purge(engine: Engine, workspace: uuid.UUID) -> None:
    with engine.begin() as connection:
        for table in ("bookings", "booking_channels", "import_jobs", "data_sources", "properties"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": workspace}
            )
        connection.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})


def test_04_what_existed_before_stays_current_and_of_unknown_scope(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, PREVIOUS_HEAD)
    workspace = _seed(db_engine)

    command.upgrade(config, "head")

    try:
        with db_engine.connect() as connection:
            removed = connection.execute(
                text("SELECT removed_at FROM bookings WHERE workspace_id = :w"), {"w": workspace}
            ).scalar_one()
            scope = connection.execute(
                text("SELECT file_scope FROM import_jobs WHERE workspace_id = :w"), {"w": workspace}
            ).scalar_one()
        assert removed is None
        assert scope is None
    finally:
        _purge(db_engine, workspace)


def test_05_the_downgrade_refuses_to_bring_a_removed_booking_back(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    workspace = _seed(db_engine, removed=True)
    try:
        with pytest.raises(RuntimeError, match="count it again"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS_HEAD)
        assert _revision(db_engine) == HEAD
    finally:
        _purge(db_engine, workspace)


def test_06_the_downgrade_refuses_to_forget_a_complete_file(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    workspace = _seed(db_engine, scope="FULL")
    try:
        with pytest.raises(RuntimeError, match="complete file"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS_HEAD)
        assert _revision(db_engine) == HEAD
    finally:
        _purge(db_engine, workspace)


def test_07_a_removal_is_whole_or_it_is_not_one(at_head: None, db_engine: Engine) -> None:
    workspace = _seed(db_engine)
    try:
        with pytest.raises(Exception, match="removal_is_whole"), db_engine.begin() as connection:
            connection.execute(
                text("UPDATE bookings SET removed_at = now() WHERE workspace_id = :w"),
                {"w": workspace},
            )
    finally:
        _purge(db_engine, workspace)
