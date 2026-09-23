"""Migration 0006 on real PostgreSQL: 0005 <-> 0006, base -> head, indexes, untouched data.

Metadata/migration agreement and constraint-name parity for the Gate 4 tables are asserted by
test_data_model_migration.py (its table sets include them).
"""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

GATE_3_HEAD = "0005_booking_snapshots_metrics"
HEAD = "0008_labor_ingestion"
GATE_4_TABLES = {"booking_expected_baselines", "booking_expected_comparables"}
GATE_3_TABLES = {"room_inventory_daily", "booking_snapshots"}
FUNCTION = "booking_expected_forbid_update"
SNAPSHOT_FK_TARGET = "uq_booking_snapshots_source_id_origin"


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


def snapshot_key_exists(engine: Engine) -> bool:
    return bool(
        scalar_set(
            engine,
            f"SELECT conname FROM pg_constraint WHERE conname = '{SNAPSHOT_FK_TARGET}'",
        )
    )


def columns_of(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(engine)
    return {
        table: [(c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)]
        for table in sorted(GATE_4_TABLES)
    }


def test_head_is_the_expected_engine_migration(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_4_TABLES | GATE_3_TABLES
    assert function_exists(db_engine) and snapshot_key_exists(db_engine)


def test_downgrade_to_0005_removes_only_gate_4(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_3_HEAD)

    assert revision(db_engine) == GATE_3_HEAD
    assert tables(db_engine) & GATE_4_TABLES == set()
    assert not function_exists(db_engine)
    assert not snapshot_key_exists(db_engine)  # the FK-target key added by 0006 goes too
    assert tables(db_engine) >= GATE_3_TABLES  # Gate 3 is untouched
    triggers = scalar_set(
        db_engine, "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'trg\\_%'"
    )
    assert triggers == {"trg_bookings_identity_immutable", "trg_booking_snapshots_immutable"}


def test_0005_to_0006_to_0005_to_0006_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = columns_of(db_engine)

    command.downgrade(config, GATE_3_HEAD)  # 0006 -> 0005
    command.upgrade(config, HEAD)  # 0005 -> 0006
    assert columns_of(db_engine) == before
    command.downgrade(config, GATE_3_HEAD)  # and once more: it is repeatable
    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert columns_of(db_engine) == before
    assert function_exists(db_engine) and snapshot_key_exists(db_engine)


def test_a_fresh_database_goes_from_base_to_head_and_back_to_0005(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}
    assert not function_exists(db_engine)

    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_4_TABLES | GATE_3_TABLES


def test_gate_3_data_survives_a_downgrade_and_upgrade_of_gate_4(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    """0006 only adds: snapshots written before it are still there after it goes and returns."""
    import uuid
    from datetime import date

    from sqlalchemy.orm import Session

    suffix = uuid.uuid4().hex[:8]
    ids = {name: uuid.uuid4() for name in ("ws", "prop", "src", "snap")}
    with Session(db_engine) as session:
        for statement in (
            "INSERT INTO workspaces (id, name, slug) VALUES (:ws, 'Survivor', :slug)",
            "INSERT INTO properties (id, workspace_id, name, slug) VALUES (:prop, :ws, 'P', :slug)",
            "INSERT INTO data_sources (id, workspace_id, property_id, name, domain, source_type)"
            " VALUES (:src, :ws, :prop, 'S', 'BOOKINGS', 'FILE_UPLOAD')",
            "INSERT INTO booking_snapshots (id, workspace_id, property_id, data_source_id,"
            " snapshot_local_date, as_of_at, stay_date, origin, booking_count_on_books,"
            " rooms_on_books, allocated_room_revenue_on_books, calculation_version,"
            " content_fingerprint) VALUES (:snap, :ws, :prop, :src, :d1, now(), :d2, 'OBSERVED',"
            " 0, 0, 0, 'booking-snapshot-v1', repeat('a', 64))",
        ):
            session.execute(
                text(statement),
                {
                    **ids,
                    "slug": f"survivor-{suffix}",
                    "d1": date(2026, 3, 1),
                    "d2": date(2026, 3, 15),
                },
            )
        session.commit()
    try:
        config = alembic_config(test_database_url)
        command.downgrade(config, GATE_3_HEAD)
        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            found = connection.execute(
                text("SELECT count(*) FROM booking_snapshots WHERE id = :snap"), ids
            ).scalar_one()
        assert found == 1
    finally:
        with Session(db_engine) as session:
            for table in ("booking_snapshots", "data_sources", "properties"):
                session.execute(text(f"DELETE FROM {table} WHERE workspace_id = :ws"), ids)
            session.execute(text("DELETE FROM workspaces WHERE id = :ws"), ids)
            session.commit()


# --- indexes -------------------------------------------------------------------------------------


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


def test_expected_indexes_are_the_keys_and_the_two_lookup_paths(
    at_head: None, db_engine: Engine
) -> None:
    baselines = index_columns(db_engine, "booking_expected_baselines")
    comparables = index_columns(db_engine, "booking_expected_comparables")

    assert baselines == {
        "pk_booking_expected_baselines": ["id"],
        # one baseline per target and version (also "the baseline of this snapshot")
        "uq_booking_expected_baselines_target_version": [
            "workspace_id",
            "target_snapshot_id",
            "calculation_version",
        ],
        # foreign-key target of the comparables (never a query path)
        "uq_booking_expected_baselines_ws_prop_src_id": [
            "workspace_id",
            "property_id",
            "data_source_id",
            "id",
        ],
        "ix_booking_expected_baselines_snapshot_date": [
            "workspace_id",
            "data_source_id",
            "target_snapshot_local_date",
        ],
        "ix_booking_expected_baselines_stay_date": [
            "workspace_id",
            "data_source_id",
            "target_stay_date",
        ],
    }
    assert comparables == {
        "pk_booking_expected_comparables": ["id"],
        # its prefix (workspace_id, baseline_id) already serves "the comparables of a baseline"
        "uq_booking_expected_comparables_baseline_snapshot": [
            "workspace_id",
            "baseline_id",
            "snapshot_id",
        ],
        "uq_booking_expected_comparables_baseline_rank": [
            "workspace_id",
            "baseline_id",
            "recency_rank",
        ],
    }


def plan(engine: Engine, sql: str) -> str:
    with engine.connect() as connection:
        connection.execute(text("SET enable_seqscan = off"))  # tiny tables: force index paths
        return "\n".join(row[0] for row in connection.execute(text(f"EXPLAIN {sql}")))


def test_the_lookups_never_need_a_full_scan(at_head: None, db_engine: Engine) -> None:
    ws = "'00000000-0000-4000-8000-000000000001'::uuid"
    source = "'00000000-0000-4000-8000-000000000002'::uuid"
    baseline = "'00000000-0000-4000-8000-000000000003'::uuid"

    by_target = plan(
        db_engine,
        "SELECT id FROM booking_expected_baselines"
        f" WHERE workspace_id = {ws} AND target_snapshot_id = {baseline}"
        " AND calculation_version = 'booking-expected-v1'",
    )
    by_day = plan(
        db_engine,
        "SELECT id FROM booking_expected_baselines"
        f" WHERE workspace_id = {ws} AND data_source_id = {source}"
        " AND target_snapshot_local_date = '2026-08-01'",
    )
    by_stay = plan(
        db_engine,
        "SELECT id FROM booking_expected_baselines"
        f" WHERE workspace_id = {ws} AND data_source_id = {source}"
        " AND target_stay_date = '2026-08-15'",
    )
    comparables = plan(
        db_engine,
        "SELECT id FROM booking_expected_comparables"
        f" WHERE workspace_id = {ws} AND baseline_id = {baseline} ORDER BY recency_rank",
    )

    # Tiny, empty test tables: the planner may pick any index sharing the (workspace, source)
    # prefix, so the check is that every lookup is an index scan on its table, never a full scan.
    for name, sql_plan in (
        ("by_target", by_target),
        ("by_day", by_day),
        ("by_stay", by_stay),
        ("comparables", comparables),
    ):
        assert "Seq Scan" not in sql_plan, (name, sql_plan)
        assert "Index" in sql_plan, (name, sql_plan)
    assert "Sort" not in comparables  # the rank unique key delivers the order itself
