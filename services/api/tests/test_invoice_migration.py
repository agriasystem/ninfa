"""Migration 0007 on real PostgreSQL: 0006 <-> 0007, base -> head, indexes, untouched data.

Metadata/migration agreement and constraint-name parity for the Gate 6 tables are asserted by
test_data_model_migration.py (its table sets include them); the FK count and the tenant-owned
tables are classified there too.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from tests.support import alembic_config

GATE_4_HEAD = "0006_expected_engine"
# Gate 6's own migration. Gate 7 added none; Gate 8 (0008_labor_ingestion) sits on top of it and
# is the real chain head, but never touches these tables/triggers/keys.
GATE_6_HEAD = "0007_invoice_supplier_ingestion"
HEAD = "0008_labor_ingestion"
GATE_6_TABLES = {
    "suppliers",
    "supplier_identifiers",
    "supplier_aliases",
    "supplier_resolution_reviews",
    "invoices",
    "invoice_lines",
    "invoice_mapping_profiles",
    "invoice_import_rows",
}
GATE_4_TABLES = {"booking_expected_baselines", "booking_expected_comparables"}
FUNCTION = "invoices_forbid_update"
DATA_SOURCE_KEY = "uq_data_sources_workspace_id_id"
EXPECTED_INDEXES = {
    "suppliers": {
        "pk_suppliers",
        "uq_suppliers_workspace_id_id",
        "ix_suppliers_workspace_id_normalized_name",
    },
    "supplier_identifiers": {
        "pk_supplier_identifiers",
        "uq_supplier_identifiers_workspace_id_kind_normalized_value",
        "ix_supplier_identifiers_workspace_id_supplier_id",
    },
    "supplier_aliases": {
        "pk_supplier_aliases",
        "uq_supplier_aliases_workspace_id_supplier_id_normalized_name",
        "ix_supplier_aliases_workspace_id_normalized_name",
    },
    "supplier_resolution_reviews": {
        "pk_supplier_resolution_reviews",
        "uq_supplier_reviews_workspace_id_provisional_candidate",
        "ix_supplier_reviews_workspace_id_status",
    },
    "invoices": {
        "pk_invoices",
        "uq_invoices_identity",
        "uq_invoices_workspace_id_id",
        "ix_invoices_workspace_id_property_id_invoice_date_supplier_id",
    },
    "invoice_lines": {
        "pk_invoice_lines",
        "uq_invoice_lines_workspace_id_invoice_id_source_line_number",
        "ix_invoice_lines_workspace_id_cost_category",
    },
    "invoice_mapping_profiles": {
        "pk_invoice_mapping_profiles",
        "uq_invoice_mapping_profiles_workspace_id_data_source_id",
    },
    "invoice_import_rows": {
        "pk_invoice_import_rows",
        "uq_invoice_import_rows_workspace_id_import_file_id_row_number",
        "ix_invoice_import_rows_workspace_id_import_job_id",
    },
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


def function_exists(engine: Engine) -> bool:
    return bool(scalar_set(engine, f"SELECT proname FROM pg_proc WHERE proname = '{FUNCTION}'"))


def key_exists(engine: Engine) -> bool:
    return bool(
        scalar_set(engine, f"SELECT conname FROM pg_constraint WHERE conname = '{DATA_SOURCE_KEY}'")
    )


def triggers(engine: Engine) -> set[str]:
    return scalar_set(
        engine, "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'trg\\_%'"
    )


def schema_of(engine: Engine) -> dict[str, object]:
    """Columns, constraints and indexes of the Gate 6 tables: a comparable picture."""
    inspector = inspect(engine)
    with engine.connect() as connection:
        constraints = sorted(
            connection.execute(
                text(
                    "SELECT t.relname || '.' || c.conname || ' ' || pg_get_constraintdef(c.oid)"
                    " FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid"
                    " WHERE t.relname = ANY(:tables)"
                ),
                {"tables": sorted(GATE_6_TABLES)},
            ).scalars()
        )
        indexes = sorted(
            connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'"
                    " AND tablename = ANY(:tables)"
                ),
                {"tables": sorted(GATE_6_TABLES)},
            ).scalars()
        )
    return {
        "columns": {
            table: [
                (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)
            ]
            for table in sorted(GATE_6_TABLES)
        },
        "constraints": constraints,
        "indexes": indexes,
    }


# --- history --------------------------------------------------------------------------------------


def test_0007_is_the_only_gate_6_migration_and_sits_on_top_of_0006(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]  # Gate 8's 0008 is the real chain head
    revision_0007 = scripts.get_revision(GATE_6_HEAD)
    assert revision_0007 is not None and revision_0007.down_revision == GATE_4_HEAD
    revision_0008 = scripts.get_revision(HEAD)
    assert revision_0008 is not None and revision_0008.down_revision == GATE_6_HEAD


# --- lifecycle ------------------------------------------------------------------------------------


def test_head_creates_the_gate_6_tables_function_triggers_and_key(
    at_head: None, db_engine: Engine
) -> None:
    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_6_TABLES | GATE_4_TABLES
    assert function_exists(db_engine) and key_exists(db_engine)
    assert {"trg_invoices_immutable", "trg_invoice_lines_immutable"} <= triggers(db_engine)


def test_downgrade_to_0006_removes_only_gate_6(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    command.downgrade(alembic_config(test_database_url), GATE_4_HEAD)

    assert revision(db_engine) == GATE_4_HEAD
    assert tables(db_engine) & GATE_6_TABLES == set()
    assert not function_exists(db_engine)
    assert not key_exists(db_engine)  # the FK-target key added by 0007 goes too
    assert tables(db_engine) >= GATE_4_TABLES  # Gate 4 is untouched
    assert "trg_invoices_immutable" not in triggers(db_engine)
    assert "trg_booking_expected_baselines_immutable" in triggers(db_engine)


def test_0006_to_0007_to_0006_to_0007_recreates_an_identical_schema(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    before = schema_of(db_engine)

    command.downgrade(config, GATE_4_HEAD)  # 0007 -> 0006
    command.upgrade(config, HEAD)  # 0006 -> 0007
    assert schema_of(db_engine) == before
    command.downgrade(config, GATE_4_HEAD)  # and once more: it is repeatable
    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert schema_of(db_engine) == before
    assert function_exists(db_engine) and key_exists(db_engine)


def test_a_fresh_database_goes_from_base_to_head_and_back_to_base(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)

    command.downgrade(config, "base")
    assert tables(db_engine) == {"alembic_version"}
    assert not function_exists(db_engine) and not key_exists(db_engine)

    command.upgrade(config, "head")

    assert revision(db_engine) == HEAD
    assert tables(db_engine) >= GATE_6_TABLES | GATE_4_TABLES


def test_the_database_is_at_the_current_head(at_head: None, db_engine: Engine) -> None:
    assert revision(db_engine) == HEAD


def test_alembic_check_finds_no_difference_between_the_models_and_the_database(
    at_head: None, test_database_url: str
) -> None:
    command.check(alembic_config(test_database_url))  # raises when a migration is missing


def test_gate_1_to_5_data_survives_a_downgrade_and_upgrade_of_gate_6(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    """0007 only adds: rows written before it are still there after it goes and returns."""
    suffix = uuid.uuid4().hex[:8]
    ids = {name: uuid.uuid4() for name in ("ws", "prop", "src", "job")}
    with Session(db_engine) as session:
        for statement in (
            "INSERT INTO workspaces (id, name, slug) VALUES (:ws, 'Survivor', :slug)",
            "INSERT INTO properties (id, workspace_id, name, slug) VALUES (:prop, :ws, 'P', :slug)",
            "INSERT INTO data_sources (id, workspace_id, property_id, name, domain, source_type)"
            " VALUES (:src, :ws, :prop, 'S', 'COSTS', 'FILE_UPLOAD')",
            "INSERT INTO import_jobs (id, workspace_id, property_id, data_source_id)"
            " VALUES (:job, :ws, :prop, :src)",
        ):
            session.execute(text(statement), {**ids, "slug": f"survivor-{suffix}"})
        session.commit()
    try:
        config = alembic_config(test_database_url)
        command.downgrade(config, GATE_4_HEAD)
        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            found = connection.execute(
                text("SELECT count(*) FROM import_jobs WHERE id = :job"), ids
            ).scalar_one()
        assert found == 1
    finally:
        with Session(db_engine) as session:
            for table in ("import_jobs", "data_sources", "properties"):
                session.execute(text(f"DELETE FROM {table} WHERE workspace_id = :ws"), ids)
            session.execute(text("DELETE FROM workspaces WHERE id = :ws"), ids)
            session.commit()


# --- indexes --------------------------------------------------------------------------------------


def test_the_gate_6_tables_have_exactly_the_planned_indexes(
    at_head: None, db_engine: Engine
) -> None:
    for table, expected in EXPECTED_INDEXES.items():
        found = scalar_set(
            db_engine,
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            f" AND tablename = '{table}'",
        )
        assert found == expected, table


def test_no_index_repeats_or_merely_prefixes_another_one(at_head: None, db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT t.relname, i.relname, ARRAY(SELECT a.attname FROM unnest(x.indkey)"
                " WITH ORDINALITY AS k(attnum, ord) JOIN pg_attribute a ON a.attrelid = t.oid"
                " AND a.attnum = k.attnum ORDER BY k.ord)"
                " FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid"
                " JOIN pg_class i ON i.oid = x.indexrelid WHERE t.relname = ANY(:tables)"
            ),
            {"tables": sorted(GATE_6_TABLES)},
        ).all()
    by_table: dict[str, list[tuple[str, list[str]]]] = {}
    for table, index, columns in rows:
        by_table.setdefault(table, []).append((index, list(columns)))
    for table, indexes in by_table.items():
        for name, columns in indexes:
            for other, other_columns in indexes:
                if other == name:
                    continue
                assert other_columns[: len(columns)] != columns, (table, name, other)


def test_categories_are_stored_as_text_with_checks_not_postgres_enums(
    at_head: None, db_engine: Engine
) -> None:
    ours = scalar_set(
        db_engine,
        "SELECT typname FROM pg_type WHERE typtype = 'e' AND typname NOT LIKE 'procrastinate%'",
    )
    assert ours == set()  # only the third-party queue schema defines PostgreSQL enums
