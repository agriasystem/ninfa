"""An import costs a bounded number of statements, whatever its size (Gate 6 group O).

The tests count SQL statements (never time): the number must not grow with the number of invoices,
lines or suppliers of the file. That is what "no N+1" means here.
"""

import re

import pytest
from sqlalchemy.orm import Session

from tests.invoice_support import (
    Body,
    Cedente,
    CostWorld,
    Line,
    fattura_xml,
    sql_log,
    standard_csv,
)
from tests.support import BookingFactory

INVOICES = 100
LINES_PER_INVOICE = 10


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


def bodies(count: int, lines: int = LINES_PER_INVOICE) -> list[Body]:
    return [
        Body(
            number=f"FA/{n}",
            date=f"2026-{(n % 12) + 1:02d}-15",
            lines=[Line(i, f"Servizio lavanderia {n}-{i}", f"{i}.50") for i in range(1, lines + 1)],
        )
        for n in range(1, count + 1)
    ]


def statements_of(statements: list[str], keyword: str, table: str) -> list[str]:
    pattern = re.compile(rf"^\s*{keyword}\b.*\b{table}\b", re.IGNORECASE | re.DOTALL)
    return [s for s in statements if pattern.match(s)]


def import_statements(world: CostWorld, content: bytes, name: str = "f.xml") -> list[str]:
    with sql_log(world.session) as statements:
        result = world.import_bytes(name, content)
    assert result.succeeded, result
    return statements


def test_a_hundred_invoices_and_a_thousand_lines_import_in_a_bounded_number_of_statements(
    world: CostWorld,
) -> None:
    content = fattura_xml(bodies(INVOICES))

    statements = import_statements(world, content)

    assert len(world.invoices()) == INVOICES
    assert len(statements) <= 60  # the whole pipeline: ~25 today, and nothing per invoice


def test_the_number_of_statements_does_not_grow_with_the_size_of_the_file(
    db_session: Session, factory: BookingFactory
) -> None:
    small = import_statements(CostWorld.create(db_session, factory), fattura_xml(bodies(5, 2)))
    large = import_statements(
        CostWorld.create(db_session, factory), fattura_xml(bodies(INVOICES, LINES_PER_INVOICE))
    )

    assert abs(len(large) - len(small)) <= 4  # the same statements, with more rows in each


def test_suppliers_are_loaded_in_batches_never_one_by_one(world: CostWorld) -> None:
    rows = [
        {
            "supplier_name": f"Fornitore {n:03d} S.r.l.",
            "supplier_vat_number": f"{10_000_000_000 + n}",
            "invoice_number": f"{n}",
            "invoice_date": "2026-03-10",
            "line_description": "Servizio",
            "line_total": "10.00",
        }
        for n in range(1, INVOICES + 1)
    ]
    world.confirm()

    with sql_log(world.session) as statements:
        result = world.import_bytes("f.csv", standard_csv(rows))

    assert result.succeeded and result.suppliers_created == INVOICES
    # the registry is read once (one statement per table), whatever the number of suppliers
    assert len(statements_of(statements, "SELECT", "suppliers")) <= 2  # registry (+ nothing else)
    assert len(statements_of(statements, "SELECT", "supplier_identifiers")) == 1
    assert len(statements_of(statements, "SELECT", "supplier_aliases")) == 1
    # ... and written in bulk: one INSERT per kind of row
    for table in ("suppliers", "supplier_identifiers", "supplier_aliases"):
        assert len(statements_of(statements, "INSERT", table)) == 1, table
    assert len(statements) <= 60


def test_existing_invoices_are_found_with_one_statement_per_block_not_one_per_invoice(
    world: CostWorld,
) -> None:
    content = fattura_xml(bodies(INVOICES))
    world.import_bytes("f.xml", content)

    with sql_log(world.session) as statements:
        again = world.import_bytes("f.xml", content)

    assert again.succeeded and again.invoices_unchanged == INVOICES
    lookups = [s for s in statements_of(statements, "SELECT", "invoices") if "VALUES" in s.upper()]
    assert len(lookups) == 1  # a join with a VALUES list, once for the 100 invoices
    assert not statements_of(statements, "INSERT", "invoices")  # nothing written twice
    assert not statements_of(statements, "INSERT", "invoice_lines")


def test_invoices_lines_and_staging_are_written_in_bulk(world: CostWorld) -> None:
    content = fattura_xml(bodies(INVOICES))

    with sql_log(world.session) as statements:
        world.import_bytes("f.xml", content)

    assert len(statements_of(statements, "INSERT", "invoices")) == 1
    assert len(statements_of(statements, "INSERT", "invoice_lines")) == 1
    assert len(statements_of(statements, "INSERT", "invoice_import_rows")) == 1
    assert len(statements_of(statements, "UPDATE", "invoice_import_rows")) == 1


def test_a_rerun_with_many_known_suppliers_still_loads_the_registry_once(
    world: CostWorld,
) -> None:
    for n in range(20):
        world.import_bytes(
            f"{n}.xml",
            fattura_xml(
                [Body(number=str(n))],
                cedente=Cedente(name=f"Fornitore {n}", vat=f"{10_000_000_000 + n}"),
            ),
        )

    with sql_log(world.session) as statements:
        result = world.import_bytes(
            "again.xml",
            fattura_xml(
                [Body(number="99")], cedente=Cedente(name="Fornitore 3", vat="10000000003")
            ),
        )

    assert result.succeeded and result.suppliers_matched == 1
    assert len(statements_of(statements, "SELECT", "supplier_identifiers")) == 1
