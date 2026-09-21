"""Migration 0005 on real PostgreSQL: 0004 <-> 0005, base -> head, indexes, untouched data.

Metadata/migration agreement and constraint-name parity for the Gate 3 tables are asserted by
test_data_model_migration.py (its table sets include them). The database is at the current head
(0006, Gate 4) while these tests run: 0005 is the migration under test, 0006 sits on top.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from tests.support import alembic_config

GATE_2_HEAD = "0004_booking_ingestion"
GATE_3_HEAD = "0005_booking_snapshots_metrics"
HEAD = "0006_expected_engine"
GATE_3_TABLES = {"room_inventory_daily", "booking_snapshots"}
GATE_2_TABLES = {"booking_channels", "booking_mapping_profiles", "bookings", "booking_import_rows"}
GATE_3_FUNCTION = "booking_snapshots_forbid_update"
GATE_2_FUNCTION = "bookings_forbid_identity_change"


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


def function_exists(engine: Engine, name: str) -> bool:
    return bool(scalar_set(engine, f"SELECT proname FROM pg_proc WHERE proname = '{name}'"))


def trigger_names(engine: Engine) -> set[str]:
    return scalar_set(
        engine, "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'trg\\_%'"
    )


def columns_of(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(engine)
    return {
        table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)]
        for table in sorted(GATE_3_TABLES)
    }


def test_head_is_the_snapshot_migration_with_its_tables_function_and_trigger(
    at_head: None, db_engine: Engine
) -> None:
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_3_TABLES | GATE_2_TABLES
    assert function_exists(db_engine, GATE_3_FUNCTION)
    assert trigger_names(db_engine) == {
        "trg_bookings_identity_immutable",
        "trg_booking_snapshots_immutable",
        "trg_booking_expected_baselines_immutable",  # Gate 4, on top
        "trg_booking_expected_comparables_immutable",
    }


def test_downgrade_to_0004_removes_only_gate_3(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_2_HEAD)

    assert revision(db_engine) == GATE_2_HEAD
    assert tables(db_engine) & GATE_3_TABLES == set()
    assert not function_exists(db_engine, GATE_3_FUNCTION)
    assert tables(db_engine) >= GATE_2_TABLES  # Gate 2 is untouched
    assert function_exists(db_engine, GATE_2_FUNCTION)
    assert trigger_names(db_engine) == {"trg_bookings_identity_immutable"}


def test_0004_to_0005_to_0004_to_0005_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = columns_of(db_engine)

    command.downgrade(config, GATE_2_HEAD)  # 0006 and 0005 -> 0004
    command.upgrade(config, GATE_3_HEAD)  # 0004 -> 0005
    assert revision(db_engine) == GATE_3_HEAD
    assert columns_of(db_engine) == before
    command.downgrade(config, GATE_2_HEAD)  # and once more: it is repeatable
    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert columns_of(db_engine) == before
    assert function_exists(db_engine, GATE_3_FUNCTION)


def test_a_fresh_database_goes_from_base_to_head_and_back(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}
    assert not function_exists(db_engine, GATE_3_FUNCTION)
    assert not function_exists(db_engine, GATE_2_FUNCTION)

    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_3_TABLES | GATE_2_TABLES


def test_gate_2_data_survives_a_downgrade_and_upgrade_of_gate_3(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    """0005 only adds: a real booking is still there after 0005 goes away and returns."""
    suffix = uuid.uuid4().hex[:8]
    ids = {name: uuid.uuid4() for name in ("ws", "prop", "src", "job", "channel")}
    with Session(db_engine) as session:
        statements = [
            ("INSERT INTO workspaces (id, name, slug) VALUES (:ws, 'Survivor', :slug)"),
            (
                "INSERT INTO properties (id, workspace_id, name, slug)"
                " VALUES (:prop, :ws, 'P', :slug)"
            ),
            (
                "INSERT INTO data_sources"
                " (id, workspace_id, property_id, name, domain, source_type)"
                " VALUES (:src, :ws, :prop, 'S', 'BOOKINGS', 'FILE_UPLOAD')"
            ),
            (
                "INSERT INTO import_jobs (id, workspace_id, property_id, data_source_id)"
                " VALUES (:job, :ws, :prop, :src)"
            ),
            (
                "INSERT INTO booking_channels"
                " (id, workspace_id, property_id, name, normalized_name)"
                " VALUES (:channel, :ws, :prop, 'Direct', 'direct')"
            ),
            (
                "INSERT INTO bookings (workspace_id, property_id, data_source_id, source_record_id,"
                " booked_at, check_in, check_out, status, rooms, room_revenue, channel_id,"
                " source_fingerprint, first_import_job_id, last_import_job_id)"
                " VALUES (:ws, :prop, :src, 'SURVIVOR-1', now(), '2026-03-10', '2026-03-12',"
                " 'CONFIRMED', 1, 100.00, :channel, repeat('a', 64), :job, :job)"
            ),
        ]
        for statement in statements:
            session.execute(text(statement), {**ids, "slug": f"survivor-{suffix}"})
        session.commit()
    try:
        config = alembic_config(test_database_url)
        command.downgrade(config, GATE_2_HEAD)
        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            found = connection.execute(
                text("SELECT count(*) FROM bookings WHERE source_record_id = 'SURVIVOR-1'")
            ).scalar_one()
        assert found == 1
    finally:
        with Session(db_engine) as session:
            for table in (
                "bookings",
                "booking_channels",
                "import_jobs",
                "data_sources",
                "properties",
                "workspaces",
            ):
                column = "id" if table == "workspaces" else "workspace_id"
                session.execute(text(f"DELETE FROM {table} WHERE {column} = :ws"), ids)
            session.commit()


# --- indexes ------------------------------------------------------------------------------------


def index_columns(engine: Engine, table: str) -> dict[str, list[str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT i.relname, array_agg(a.attname ORDER BY k.ord)"
                " FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid"
                " JOIN pg_class t ON t.oid = x.indrelid"
                " JOIN LATERAL unnest(x.indkey) WITH ORDINALITY AS k(attnum, ord) ON true"
                " JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum"
                " WHERE t.relname = :table GROUP BY i.relname"
            ),
            {"table": table},
        )
        return {row[0]: list(row[1]) for row in rows}


def test_snapshot_indexes_are_the_key_the_curve_and_the_gate_4_fk_target(
    at_head: None, db_engine: Engine
) -> None:
    columns = index_columns(db_engine, "booking_snapshots")

    assert columns == {
        "pk_booking_snapshots": ["id"],
        # the logical key; its order also serves "all the nights of one snapshot day"
        "uq_booking_snapshots_data_source_snapshot_date_stay_date": [
            "workspace_id",
            "data_source_id",
            "snapshot_local_date",
            "stay_date",
        ],
        # the booking curve of one stay night, already in snapshot-day order
        "ix_booking_snapshots_booking_curve": [
            "workspace_id",
            "data_source_id",
            "stay_date",
            "snapshot_local_date",
        ],
        # added by 0006, a foreign-key target only (never a query path)
        "uq_booking_snapshots_source_id_origin": [
            "workspace_id",
            "property_id",
            "data_source_id",
            "id",
            "origin",
        ],
    }
    assert index_columns(db_engine, "room_inventory_daily") == {
        "pk_room_inventory_daily": ["id"],
        "uq_room_inventory_daily_workspace_id_property_id_stay_date": [
            "workspace_id",
            "property_id",
            "stay_date",
        ],
    }


def plan(engine: Engine, sql: str) -> str:
    with engine.connect() as connection:
        connection.execute(text("SET enable_seqscan = off"))  # tiny tables: force index paths
        rows = connection.execute(text(f"EXPLAIN {sql}"))
        return "\n".join(row[0] for row in rows)


def test_the_curve_query_is_served_by_the_curve_index_in_snapshot_day_order(
    at_head: None, db_engine: Engine
) -> None:
    workspace = "'00000000-0000-4000-8000-000000000001'::uuid"
    source = "'00000000-0000-4000-8000-000000000002'::uuid"
    curve = plan(
        db_engine,
        "SELECT snapshot_local_date FROM booking_snapshots"
        f" WHERE workspace_id = {workspace} AND data_source_id = {source}"
        " AND stay_date = '2026-04-10' ORDER BY snapshot_local_date",
    )

    assert "ix_booking_snapshots_booking_curve" in curve
    assert "Sort" not in curve  # the index delivers the snapshot-day order itself
