"""Several cost files on one day. Periods add up, documents never do, and a corrected row of a
spreadsheet replaces its own document. A FatturaPA stays what it is: a fiscal document is refused,
not replaced, if it comes back different.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ingestion.models import ImportJob, ImportJobStatus
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.invoices.errors import InvoiceErrorCode as Code
from app.modules.invoices.models import Invoice, SourceFormat
from app.modules.suppliers.models import IdentifierKind, SupplierIdentifier
from tests.invoice_support import Body, CostWorld, Line, fattura_xml, lines_of, standard_csv
from tests.support import BookingFactory


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    built = CostWorld.create(db_session, factory)
    built.confirm()
    return built


def row(**values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "supplier_name": "Fornitore Uno S.r.l.",
        "supplier_vat_number": "01234567890",
        "invoice_number": "1",
        "invoice_date": "2026-03-10",
        "line_description": "Servizio generico",
        "line_total": "100.00",
    }
    base.update(values)
    return base


def spend(world: CostWorld, first: date, last: date) -> Decimal:
    """What every reading of costs sees: the detector, Dati, the refresh."""
    rows = CostLineRepository(world.session, world.context).monthly_aggregates(
        world.tenant.property.id, first, last
    )
    return sum((aggregate.net_cost for aggregate in rows), Decimal(0))


MARCH = (date(2026, 3, 1), date(2026, 3, 31))
APRIL = (date(2026, 4, 1), date(2026, 4, 30))


def job_of(world: CostWorld, result: Any) -> ImportJob:
    job = world.session.scalar(select(ImportJob).where(ImportJob.id == result.import_job_id))
    assert job is not None
    return job


def test_two_files_of_different_periods_both_count(world: CostWorld) -> None:
    first = world.import_bytes("marzo.csv", standard_csv([row()]))
    second = world.import_bytes(
        "aprile.csv", standard_csv([row(invoice_number="2", invoice_date="2026-04-10")])
    )

    assert first.changed_data and second.changed_data
    assert spend(world, *MARCH) == Decimal("100.00")
    assert spend(world, *APRIL) == Decimal("100.00")
    assert world.count(Invoice) == 2


def test_two_files_of_one_period_with_different_documents_add_up(world: CostWorld) -> None:
    world.import_bytes("a.csv", standard_csv([row()]))

    second = world.import_bytes("b.csv", standard_csv([row(invoice_number="2")]))

    assert (second.invoices_created, second.invoices_unchanged, second.invoices_revised) == (
        1,
        0,
        0,
    )
    assert spend(world, *MARCH) == Decimal("200.00")


def test_the_same_file_twice_is_a_no_op(world: CostWorld) -> None:
    content = standard_csv([row(), row(invoice_number="2")])
    world.import_bytes("c.csv", content)

    again = world.import_bytes("c-again.csv", content)

    assert again.succeeded
    assert again.changed_data is False
    assert (again.invoices_created, again.invoices_unchanged, again.invoices_revised) == (0, 2, 0)
    assert job_of(world, again).changed_data is False
    assert world.count(Invoice) == 2
    assert spend(world, *MARCH) == Decimal("200.00")


def test_a_corrected_row_replaces_its_document_and_never_adds_up(world: CostWorld) -> None:
    world.import_bytes("a.csv", standard_csv([row(line_total="100.00")]))

    second = world.import_bytes("a-v2.csv", standard_csv([row(line_total="101.00")]))

    assert second.succeeded, second
    assert second.changed_data is True
    assert (second.invoices_created, second.invoices_revised) == (0, 1)
    assert spend(world, *MARCH) == Decimal("101.00")  # never 201.00


def test_the_older_version_stays_with_the_import_that_brought_it(world: CostWorld) -> None:
    first = world.import_bytes("a.csv", standard_csv([row(line_total="100.00")]))
    second = world.import_bytes("a-v2.csv", standard_csv([row(line_total="101.00")]))

    older, newer = sorted(world.invoices(), key=lambda invoice: invoice.revision)

    assert (older.revision, older.source_import_job_id) == (1, first.import_job_id)
    assert (newer.revision, newer.source_import_job_id) == (2, second.import_job_id)
    assert [line.line_total for line in lines_of(world.session, older)] == [Decimal("100.00")]
    assert [line.line_total for line in lines_of(world.session, newer)] == [Decimal("101.00")]


def test_a_file_that_mixes_new_corrected_and_unchanged_documents(world: CostWorld) -> None:
    world.import_bytes(
        "a.csv",
        standard_csv([row(invoice_number="1"), row(invoice_number="2", line_total="50.00")]),
    )

    second = world.import_bytes(
        "b.csv",
        standard_csv(
            [
                row(invoice_number="1"),  # the same
                row(invoice_number="2", line_total="60.00"),  # corrected
                row(invoice_number="3", line_total="10.00"),  # new
            ]
        ),
    )

    assert (second.invoices_created, second.invoices_unchanged, second.invoices_revised) == (
        1,
        1,
        1,
    )
    assert spend(world, *MARCH) == Decimal("170.00")


def test_going_back_to_the_first_amount_is_a_change_too(world: CostWorld) -> None:
    world.import_bytes("a.csv", standard_csv([row(line_total="100.00")]))
    world.import_bytes("b.csv", standard_csv([row(line_total="101.00")]))

    third = world.import_bytes("a-again.csv", standard_csv([row(line_total="100.00")]))

    assert third.changed_data is True
    assert sorted(invoice.revision for invoice in world.invoices()) == [1, 2, 3]
    assert spend(world, *MARCH) == Decimal("100.00")


def test_a_document_a_later_file_does_not_mention_stays(world: CostWorld) -> None:
    world.import_bytes("a.csv", standard_csv([row(invoice_number="1"), row(invoice_number="2")]))

    world.import_bytes("b.csv", standard_csv([row(invoice_number="1")]))

    assert spend(world, *MARCH) == Decimal("200.00")


def test_a_fiscal_document_that_comes_back_different_is_refused_and_nothing_changes(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "100.00")])]))

    result = world.import_xml(
        fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "999.00")])]), name="changed.xml"
    )

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert world.count(Invoice) == 1
    assert [invoice.revision for invoice in world.invoices()] == [1]


def test_a_spreadsheet_never_replaces_a_fiscal_document(world: CostWorld) -> None:
    world.import_xml(
        fattura_xml(
            [Body(number="1", date="2026-03-10", lines=[Line(1, "Servizio", "100.00")])],
        )
    )
    [stored] = world.invoices()
    assert stored.source_format == SourceFormat.FATTURAPA_XML

    result = world.import_bytes("b.csv", _csv_for_the_same_document(world))

    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert world.count(Invoice) == 1


def _csv_for_the_same_document(world: CostWorld) -> bytes:
    [stored] = world.invoices()
    return standard_csv(
        [
            row(
                supplier_name="Fornitore Test S.r.l.",
                supplier_vat_number=_vat_of(world, stored),
                invoice_number=stored.invoice_number,
                invoice_date=stored.invoice_date.isoformat(),
                line_total="55.00",
            )
        ]
    )


def _vat_of(world: CostWorld, invoice: Invoice) -> str:
    value = world.session.scalar(
        select(SupplierIdentifier.normalized_value).where(
            SupplierIdentifier.supplier_id == invoice.supplier_id,
            SupplierIdentifier.kind == IdentifierKind.VAT_NUMBER,
        )
    )
    assert value is not None
    return str(value)


def test_the_months_with_costs_read_the_current_versions_only(world: CostWorld) -> None:
    world.import_bytes("a.csv", standard_csv([row()]))
    world.import_bytes("a-v2.csv", standard_csv([row(line_total="101.00")]))

    months = CostLineRepository(world.session, world.context).months_with_lines(
        world.tenant.property.id, before=date(2026, 6, 1), limit=12
    )

    assert months == [date(2026, 3, 1)]


def test_costs_of_another_workspace_are_never_mixed(
    world: CostWorld, db_session: Session, factory: BookingFactory
) -> None:
    other = CostWorld.create(db_session, factory)
    other.confirm()
    other.import_bytes("x.csv", standard_csv([row(line_total="7.00")]))
    world.import_bytes("a.csv", standard_csv([row(line_total="100.00")]))
    world.import_bytes("a-v2.csv", standard_csv([row(line_total="101.00")]))

    assert spend(other, *MARCH) == Decimal("7.00")
    assert [invoice.revision for invoice in other.invoices()] == [1]
