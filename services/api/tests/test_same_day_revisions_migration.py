"""Migration 0014_same_day_revisions: additive, every existing row is revision 1, one head, and it
will not go back once going back would destroy evidence.

The current global head lives in `test_import_scope_migration.py`.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

HEAD = "0014_same_day_revisions"
PREVIOUS_HEAD = "0013_property_analysis_policy"
CURRENT_GLOBAL_HEAD = "0015_import_scope"
REVISED_TABLES = ("booking_snapshots", "labor_snapshots", "invoices")


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


def _uniques(engine: Engine, table: str) -> dict[str, list[str]]:
    return {
        str(constraint["name"]): list(constraint["column_names"])
        for constraint in inspect(engine).get_unique_constraints(table)
    }


def test_01_it_sits_on_0013(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_revision(HEAD).down_revision == PREVIOUS_HEAD


def test_02_the_keys_gain_a_revision_and_the_downgrade_restores_them(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    assert _uniques(db_engine, "booking_snapshots")[
        "uq_booking_snapshots_source_snapshot_stay_revision"
    ] == ["workspace_id", "data_source_id", "snapshot_local_date", "stay_date", "revision"]
    assert _uniques(db_engine, "labor_snapshots")[
        "uq_labor_snapshots_data_source_id_snapshot_local_date_revision"
    ] == ["workspace_id", "data_source_id", "snapshot_local_date", "revision"]
    assert "revision" in _uniques(db_engine, "invoices")["uq_invoices_identity_revision"]
    assert "changed_data" in _columns(db_engine, "import_jobs")

    command.downgrade(config, PREVIOUS_HEAD)

    assert _revision(db_engine) == PREVIOUS_HEAD
    for table in REVISED_TABLES:
        assert "revision" not in _columns(db_engine, table)
    assert "changed_data" not in _columns(db_engine, "import_jobs")
    assert _uniques(db_engine, "booking_snapshots")[
        "uq_booking_snapshots_data_source_snapshot_date_stay_date"
    ] == ["workspace_id", "data_source_id", "snapshot_local_date", "stay_date"]
    assert "uq_invoices_identity" in _uniques(db_engine, "invoices")

    command.upgrade(config, "head")
    assert _revision(db_engine) == CURRENT_GLOBAL_HEAD
    for table in REVISED_TABLES:
        assert "revision" in _columns(db_engine, table)


def _seed_snapshot(engine: Engine, *, revision: int | None) -> tuple[uuid.UUID, uuid.UUID]:
    """A workspace, a property, a source and one observed row, through plain SQL."""
    workspace, prop, source, snapshot = (uuid.uuid4() for _ in range(4))
    suffix = uuid.uuid4().hex[:10]
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    columns = "" if revision is None else ", revision"
    value = "" if revision is None else f", {revision}"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": workspace, "name": "Migrazione", "slug": f"migr-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO properties (id, workspace_id, name, slug, timezone, currency)"
                " VALUES (:id, :w, :name, :slug, 'Europe/Rome', 'EUR')"
            ),
            {"id": prop, "w": workspace, "name": "Migrazione", "slug": f"migr-{suffix}"},
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
                "INSERT INTO booking_snapshots (id, workspace_id, property_id, data_source_id,"
                " snapshot_local_date, as_of_at, stay_date, origin, booking_count_on_books,"
                " rooms_on_books, allocated_room_revenue_on_books, adr_on_books,"
                f" calculation_version, content_fingerprint{columns})"
                " VALUES (:id, :w, :p, :s, :day, :now, :stay, 'OBSERVED', 1, 1, :money, :money,"
                f" 'v1', :fp{value})"
            ),
            {
                "id": snapshot,
                "w": workspace,
                "p": prop,
                "s": source,
                "day": date(2026, 8, 1),
                "now": now,
                "stay": date(2026, 8, 15),
                "money": Decimal("100.00"),
                "fp": "a" * 64,
            },
        )
    return workspace, snapshot


def _purge(engine: Engine, workspace: uuid.UUID) -> None:
    with engine.begin() as connection:
        for table in ("booking_snapshots", "data_sources", "properties"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": workspace}
            )
        connection.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})


def test_03_a_row_from_before_the_migration_is_revision_1(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, PREVIOUS_HEAD)
    workspace, snapshot = _seed_snapshot(db_engine, revision=None)

    command.upgrade(config, "head")

    try:
        with db_engine.connect() as connection:
            revision = connection.execute(
                text("SELECT revision FROM booking_snapshots WHERE id = :id"), {"id": snapshot}
            ).scalar_one()
        assert revision == 1
    finally:
        _purge(db_engine, workspace)


def test_04_a_job_from_before_the_migration_has_no_answer_to_changed_data(
    at_head: None, db_engine: Engine
) -> None:
    [column] = [
        column
        for column in inspect(db_engine).get_columns("import_jobs")
        if column["name"] == "changed_data"
    ]
    assert column["nullable"] is True
    assert column["default"] is None


def test_05_the_downgrade_refuses_to_destroy_a_second_revision(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    workspace, _ = _seed_snapshot(db_engine, revision=2)
    try:
        with pytest.raises(RuntimeError, match="second revision"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS_HEAD)
        assert _revision(db_engine) == CURRENT_GLOBAL_HEAD  # refused: nothing moved at all
    finally:
        _purge(db_engine, workspace)
