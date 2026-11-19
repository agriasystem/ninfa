"""Migration 0018_cost_record_identity: the technical identity of a cost record (ADR 0057).

What must hold, on a real PostgreSQL and not only in the application layer:

  - it sits on 0017, is the one head and the one migration numbered 0018
  - upgrade on an EMPTY database, and from 0017 WITH HISTORICAL invoices: every old row keeps its
    number, its revision and its lines, gets `source_record_key = normalised number` and the origin
    DOCUMENT_NUMBER, and the immutability trigger is back in force (it was lifted for the backfill)
  - the constraints that keep a synthetic record honest exist and are enforced by the database
  - the downgrade REFUSES to destroy evidence: a synthetic record, or a removal, blocks it
  - the removals are immutable too
"""

import pathlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.support import alembic_config

HEAD = "0018_cost_record_identity"
PREVIOUS = "0017_mia_conversations"
FP = "d" * 64
KEY = "cost:v1:" + "e" * 64 + "#1"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _columns(engine: Engine, table: str) -> dict[str, bool]:
    """{column: nullable}."""
    return {c["name"]: bool(c["nullable"]) for c in inspect(engine).get_columns(table)}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


# --- the chain ------------------------------------------------------------------------------------


def test_01_it_is_the_one_head_and_sits_on_0017(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(HEAD).down_revision == PREVIOUS


def test_02_one_migration_is_numbered_0018_and_only_one_creates_the_removals(
    test_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))
    assert [r.revision for r in scripts.walk_revisions() if r.revision.startswith("0018")] == [HEAD]
    versions = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    creators = [
        path.name
        for path in versions.glob("*.py")
        if '"invoice_removals",' in path.read_text(encoding="utf-8")
        and "op.create_table(" in path.read_text(encoding="utf-8")
    ]
    assert creators == ["0018_cost_record_identity.py"]


# --- upgrade and downgrade on an empty database -------------------------------------------------


def test_03_the_empty_database_goes_down_and_up_again(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    columns = _columns(db_engine, "invoices")
    assert "source_record_key" in columns and "identity_origin" in columns
    assert columns["invoice_number"] and columns["normalized_invoice_number"]  # nullable now
    assert not columns["source_record_key"] and not columns["identity_origin"]
    assert "invoice_removals" in _tables(db_engine)

    command.downgrade(config, PREVIOUS)

    assert _revision(db_engine) == PREVIOUS
    old = _columns(db_engine, "invoices")
    assert "source_record_key" not in old and "identity_origin" not in old
    assert not old["invoice_number"] and not old["normalized_invoice_number"]  # NOT NULL again
    assert "invoice_removals" not in _tables(db_engine)

    command.upgrade(config, "head")
    assert _revision(db_engine) == HEAD
    assert "invoice_removals" in _tables(db_engine)


def test_04_the_constraints_that_keep_a_synthetic_record_honest_exist(
    at_head: None, db_engine: Engine
) -> None:
    with db_engine.connect() as connection:
        names = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid IN"
                    " ('invoices'::regclass, 'invoice_removals'::regclass)"
                )
            ).scalars()
        )
        rules: dict[str, str] = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                text(
                    "SELECT constraint_name, delete_rule"
                    " FROM information_schema.referential_constraints"
                    " WHERE constraint_name LIKE 'fk\\_invoice\\_removals\\_%'"
                )
            )
        }
    assert {
        "ck_invoices_identity_origin_valid",
        "ck_invoices_identity_consistent",
        "ck_invoices_source_record_key_not_blank",
        "ck_invoices_synthetic_only_for_spreadsheets",
        "uq_invoices_identity_revision",
        "uq_invoices_workspace_id_id_identity_origin",
        "ck_invoice_removals_only_synthetic_records",
        "uq_invoice_removals_workspace_id_invoice_id",
        "fk_invoice_removals_workspace_id_invoices",
    } <= names
    assert "ck_invoices_invoice_number_not_blank" not in names  # replaced by identity_consistent
    assert set(rules.values()) == {"RESTRICT"}  # a removal never cascades into evidence


# --- from 0017, with history --------------------------------------------------------------------


def _tenant(connection: Connection) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in ("w", "p", "d", "j", "f", "s")}
    suffix = uuid.uuid4().hex[:10]
    connection.execute(
        text("INSERT INTO workspaces (id, name, slug) VALUES (:w, 'Storico', :slug)"),
        {"w": ids["w"], "slug": f"cost-{suffix}"},
    )
    connection.execute(
        text(
            "INSERT INTO properties (id, workspace_id, name, slug, timezone, currency)"
            " VALUES (:p, :w, 'Storico', :slug, 'Europe/Rome', 'EUR')"
        ),
        {"p": ids["p"], "w": ids["w"], "slug": f"cost-{suffix}"},
    )
    connection.execute(
        text(
            "INSERT INTO data_sources (id, workspace_id, property_id, name, domain, source_type)"
            " VALUES (:d, :w, :p, 'Costi', 'COSTS', 'FILE_UPLOAD')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO import_jobs (id, workspace_id, property_id, data_source_id)"
            " VALUES (:j, :w, :p, :d)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO import_files (id, workspace_id, import_job_id, original_filename)"
            " VALUES (:f, :w, :j, 'storico.xml')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO suppliers (id, workspace_id, legal_name, normalized_name)"
            " VALUES (:s, :w, 'Fornitore Storico', 'fornitore storico')"
        ),
        ids,
    )
    return ids


def _old_invoice(
    connection: Connection,
    ids: dict[str, uuid.UUID],
    number: str,
    *,
    revision: int = 1,
    kind: str = "INVOICE",
    source_format: str = "FATTURAPA_XML",
    amount: str = "100.00",
) -> uuid.UUID:
    """An invoice as 0017 wrote it: no key, no origin. Returns its id."""
    invoice = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
            " invoice_number, normalized_invoice_number, invoice_date, revision, document_kind,"
            " currency, net_amount, tax_amount, gross_amount, source_format, source_import_job_id,"
            " source_import_file_id, source_fingerprint, supplier_resolution_method)"
            " VALUES (:id, :w, :p, :d, :s, CAST(:n AS varchar), upper(CAST(:n AS varchar)),"
            " '2026-03-10', :rev, :kind, 'EUR', :amount, 0, :amount, :fmt, :j, :f, :fp,"
            " 'CREATED_NEW')"
        ),
        {
            **ids,
            "id": invoice,
            "n": number,
            "rev": revision,
            "kind": kind,
            "fmt": source_format,
            "amount": amount,
            "fp": FP,
        },
    )
    connection.execute(
        text(
            "INSERT INTO invoice_lines (id, workspace_id, invoice_id, source_line_number,"
            " description_raw, description_normalized, line_total, cost_category,"
            " classification_confidence, classification_method)"
            " VALUES (gen_random_uuid(), :w, :id, 1, 'Servizio', 'servizio', :amount, 'OTHER', 0,"
            " 'UNCLASSIFIED')"
        ),
        {**ids, "id": invoice, "amount": amount},
    )
    return invoice


def _purge(engine: Engine, ids: dict[str, uuid.UUID]) -> None:
    """The shared test database is left as it was found."""
    with engine.begin() as connection:
        for table in (
            "invoice_removals",
            "invoice_lines",
            "invoices",
            "import_files",
            "import_jobs",
            "suppliers",
            "data_sources",
            "properties",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE workspace_id = :w"),  # noqa: S608 - fixed names
                ids,
            )
        connection.execute(text("DELETE FROM workspaces WHERE id = :w"), ids)


def test_05_historical_invoices_keep_everything_and_gain_their_number_as_the_key(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    command.downgrade(config, PREVIOUS)
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        plain = _old_invoice(connection, ids, "fa/1")
        corrected = _old_invoice(connection, ids, "fa/2", revision=1)
        revised = _old_invoice(connection, ids, "fa/2", revision=2, source_format="CSV")
        credit = _old_invoice(
            connection, ids, "nc/1", kind="CREDIT_NOTE", amount="-50.00", source_format="XLSX"
        )
    try:
        command.upgrade(config, "head")

        with db_engine.connect() as connection:
            rows = {
                str(r.id): r
                for r in connection.execute(
                    text(
                        "SELECT id, invoice_number, normalized_invoice_number, source_record_key,"
                        " identity_origin, revision, document_kind FROM invoices"
                        " WHERE workspace_id = :w"
                    ),
                    ids,
                )
            }
            lines = connection.execute(
                text("SELECT count(*) FROM invoice_lines WHERE workspace_id = :w"), ids
            ).scalar_one()
        assert len(rows) == 4 and lines == 4  # nothing lost, nothing added
        for invoice in (plain, corrected, revised, credit):
            row = rows[str(invoice)]
            assert row.source_record_key == row.normalized_invoice_number  # the key IS the number
            assert row.identity_origin == "DOCUMENT_NUMBER"
            assert row.invoice_number is not None
        assert sorted(r.revision for r in rows.values()) == [1, 1, 1, 2]  # revisions untouched
        assert rows[str(credit)].document_kind == "CREDIT_NOTE"

        # the immutability is back in force: the backfill lifted it for one statement only
        with db_engine.connect() as connection:
            enabled = (
                connection.execute(
                    text(
                        "SELECT tgenabled FROM pg_trigger WHERE tgname IN"
                        " ('trg_invoices_immutable', 'trg_invoice_removals_immutable')"
                    )
                )
                .scalars()
                .all()
            )
        assert enabled == ["O", "O"]
        with pytest.raises(DBAPIError, match="immutable"), db_engine.begin() as connection:
            connection.execute(
                text("UPDATE invoices SET currency = 'USD' WHERE id = :id"), {"id": plain}
            )
        # and the old identity is still unique: the same number again is refused
        with pytest.raises(IntegrityError), db_engine.begin() as connection:
            _old_invoice_after(connection, ids, "fa/1")
    finally:
        _purge(db_engine, ids)


def _old_invoice_after(connection: Connection, ids: dict[str, uuid.UUID], number: str) -> None:
    """The same document again, written by 0018's rules (key and origin given)."""
    connection.execute(
        text(
            "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
            " invoice_number, normalized_invoice_number, source_record_key, identity_origin,"
            " invoice_date, revision, document_kind, currency, source_format,"
            " source_import_job_id, source_import_file_id, source_fingerprint,"
            " supplier_resolution_method)"
            " VALUES (gen_random_uuid(), :w, :p, :d, :s, CAST(:n AS varchar),"
            " upper(CAST(:n AS varchar)), upper(CAST(:n AS varchar)), 'DOCUMENT_NUMBER',"
            " '2026-03-10', 1, 'INVOICE', 'EUR', 'FATTURAPA_XML', :j, :f, :fp, 'CREATED_NEW')"
        ),
        {**ids, "n": number, "fp": FP},
    )


# --- the downgrade refuses to destroy evidence --------------------------------------------------


def _synthetic(connection: Connection, ids: dict[str, uuid.UUID]) -> uuid.UUID:
    invoice = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
            " invoice_number, normalized_invoice_number, source_record_key, identity_origin,"
            " invoice_date, revision, document_kind, currency, source_format,"
            " source_import_job_id, source_import_file_id, source_fingerprint,"
            " supplier_resolution_method)"
            " VALUES (:id, :w, :p, :d, :s, NULL, NULL, :key, 'SYNTHETIC_COST_RECORD',"
            " '2026-10-05', 1, 'INVOICE', 'EUR', 'CSV', :j, :f, :fp, 'CREATED_NEW')"
        ),
        {**ids, "id": invoice, "key": KEY, "fp": FP},
    )
    return invoice


def test_06_a_synthetic_record_blocks_the_downgrade(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        _synthetic(connection, ids)
    try:
        with pytest.raises(RuntimeError, match="destroy evidence"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS)
        assert _revision(db_engine) == HEAD  # nothing happened
        assert "source_record_key" in _columns(db_engine, "invoices")
    finally:
        _purge(db_engine, ids)


def test_07_a_removal_blocks_the_downgrade_too(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        invoice = _synthetic(connection, ids)
        connection.execute(
            text(
                "INSERT INTO invoice_removals (workspace_id, property_id, data_source_id,"
                " invoice_id, removed_by_import_job_id) VALUES (:w, :p, :d, :inv, :j)"
            ),
            {**ids, "inv": invoice},
        )
    try:
        with pytest.raises(RuntimeError, match="destroy evidence"):
            command.downgrade(alembic_config(test_database_url), PREVIOUS)
        assert _revision(db_engine) == HEAD
        assert "invoice_removals" in _tables(db_engine)
    finally:
        _purge(db_engine, ids)


def test_08_the_downgrade_is_allowed_again_once_the_evidence_is_gone(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        _synthetic(connection, ids)
    _purge(db_engine, ids)

    command.downgrade(alembic_config(test_database_url), PREVIOUS)

    assert _revision(db_engine) == PREVIOUS


# --- what the database refuses by itself ---------------------------------------------------------


def _refused(engine: Engine, statement: str, params: dict[str, object]) -> str:
    with pytest.raises(IntegrityError) as raised, engine.begin() as connection:
        connection.execute(text(statement), params)
    return str(raised.value.orig)


def test_09_the_database_refuses_an_invented_number_a_synthetic_fatturapa_and_a_removed_invoice(
    at_head: None, db_engine: Engine
) -> None:
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        real = _old_invoice_after_with_key(connection, ids)
    try:
        base = (
            "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
            " invoice_number, normalized_invoice_number, source_record_key, identity_origin,"
            " invoice_date, revision, document_kind, currency, source_format,"
            " source_import_job_id, source_import_file_id, source_fingerprint,"
            " supplier_resolution_method) VALUES (gen_random_uuid(), :w, :p, :d, :s, :n, :nn,"
            " :key, :origin, '2026-10-06', 1, 'INVOICE', 'EUR', :fmt, :j, :f, :fp, 'CREATED_NEW')"
        )
        common = {**ids, "key": KEY, "fp": FP, "fmt": "CSV"}
        # a synthetic record that carries a number
        assert "identity_consistent" in _refused(
            db_engine, base, {**common, "n": "FA/9", "nn": None, "origin": "SYNTHETIC_COST_RECORD"}
        )
        # a real document with no number
        assert "identity_consistent" in _refused(
            db_engine, base, {**common, "n": None, "nn": None, "origin": "DOCUMENT_NUMBER"}
        )
        # a synthetic FatturaPA
        assert "synthetic_only_for_spreadsheets" in _refused(
            db_engine,
            base,
            {
                **common,
                "n": None,
                "nn": None,
                "origin": "SYNTHETIC_COST_RECORD",
                "fmt": "FATTURAPA_XML",
            },
        )
        # the removal of a fiscal document
        assert "fk_invoice_removals_workspace_id_invoices" in _refused(
            db_engine,
            "INSERT INTO invoice_removals (workspace_id, property_id, data_source_id, invoice_id,"
            " removed_by_import_job_id) VALUES (:w, :p, :d, :inv, :j)",
            {**ids, "inv": real},
        )
    finally:
        _purge(db_engine, ids)


def _old_invoice_after_with_key(connection: Connection, ids: dict[str, uuid.UUID]) -> uuid.UUID:
    invoice = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
            " invoice_number, normalized_invoice_number, source_record_key, identity_origin,"
            " invoice_date, revision, document_kind, currency, source_format,"
            " source_import_job_id, source_import_file_id, source_fingerprint,"
            " supplier_resolution_method)"
            " VALUES (:id, :w, :p, :d, :s, 'FA/1', 'FA/1', 'FA/1', 'DOCUMENT_NUMBER',"
            " '2026-03-10', 1, 'INVOICE', 'EUR', 'FATTURAPA_XML', :j, :f, :fp, 'CREATED_NEW')"
        ),
        {**ids, "id": invoice, "fp": FP},
    )
    return invoice


def test_10_a_removal_can_never_be_edited(at_head: None, db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        ids = _tenant(connection)
        invoice = _synthetic(connection, ids)
        connection.execute(
            text(
                "INSERT INTO invoice_removals (workspace_id, property_id, data_source_id,"
                " invoice_id, removed_by_import_job_id) VALUES (:w, :p, :d, :inv, :j)"
            ),
            {**ids, "inv": invoice},
        )
    try:
        with pytest.raises(DBAPIError, match="immutable"), db_engine.begin() as connection:
            connection.execute(
                text("UPDATE invoice_removals SET created_at = :now WHERE invoice_id = :inv"),
                {"now": datetime(2026, 1, 1, tzinfo=UTC), "inv": invoice},
            )
    finally:
        _purge(db_engine, ids)
