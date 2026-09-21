"""InvoiceImportService end to end on real PostgreSQL: the pipeline, atomicity, idempotency, data
source rules, credit notes and explainability (Gate 6 groups C, D, J, K, L). Synthetic data only.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import (
    DataSourceDomain,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError
from app.modules.invoices.models import (
    DocumentKind,
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    ResolutionMethod,
    SourceFormat,
)
from app.modules.invoices.repository import InvoiceRepository
from app.modules.suppliers.models import (
    IdentifierKind,
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from tests.invoice_support import (
    IBAN_A,
    Body,
    Cedente,
    CostWorld,
    Line,
    Payment,
    all_invoices,
    count,
    fattura_xml,
    job_of,
    lines_of,
    persisted_hits,
)
from tests.support import BookingFactory

D = Decimal
Code = InvoiceErrorCode
DOCTYPE_XML = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


def canonical_counts(world: CostWorld) -> dict[str, int]:
    """Every table an import can write to (workspace scoped)."""
    return {
        model.__tablename__: world.count(model)
        for model in (
            Supplier,
            SupplierIdentifier,
            SupplierAlias,
            SupplierResolutionReview,
            Invoice,
            InvoiceLine,
        )
    }


ZERO = dict.fromkeys(
    (
        "suppliers",
        "supplier_identifiers",
        "supplier_aliases",
        "supplier_resolution_reviews",
        "invoices",
        "invoice_lines",
    ),
    0,
)


# --- the pipeline -------------------------------------------------------------------------------


def test_an_xml_import_creates_supplier_invoice_and_lines_and_a_succeeded_job(
    world: CostWorld,
) -> None:
    body = Body(
        number="FA/1",
        date="2026-03-10",
        lines=[
            Line(1, "Servizio di lavanderia biancheria", "100.00"),
            Line(2, "Materiale vario", "20.00"),
        ],
        payments=[Payment(due="2026-04-10", iban=IBAN_A)],
    )

    result = world.import_xml(fattura_xml([body]))

    assert result.succeeded and result.error_code is None
    assert (result.documents_total, result.rows_total, result.rows_valid) == (1, 2, 2)
    assert (result.invoices_created, result.invoices_unchanged, result.lines_created) == (1, 0, 2)
    assert (result.suppliers_created, result.suppliers_matched) == (1, 0)
    assert result.source_format == SourceFormat.FATTURAPA_XML

    (invoice,) = world.invoices()
    assert invoice.invoice_number == "FA/1" and invoice.normalized_invoice_number == "FA/1"
    assert invoice.invoice_date == date(2026, 3, 10) and invoice.due_date == date(2026, 4, 10)
    assert invoice.document_kind == DocumentKind.INVOICE and invoice.document_type_code == "TD01"
    assert invoice.currency == "EUR" and invoice.source_format == SourceFormat.FATTURAPA_XML
    assert invoice.property_id == world.tenant.property.id
    assert invoice.data_source_id == world.source.id
    assert invoice.source_import_job_id == result.import_job_id
    assert invoice.source_import_file_id == result.import_file_id
    assert invoice.supplier_resolution_method == ResolutionMethod.CREATED_NEW
    lines = lines_of(world.session, invoice)
    assert [(line.source_line_number, line.line_total) for line in lines] == [
        (1, D("100.00")),
        (2, D("20.00")),
    ]
    job = job_of(world.session, result)
    assert job.status == ImportJobStatus.SUCCEEDED
    assert job.started_at is not None and job.finished_at is not None
    assert job.error_code is None and job.error_message is None


def test_staged_rows_are_marked_imported_after_a_successful_import(world: CostWorld) -> None:
    result = world.import_xml(
        fattura_xml([Body(lines=[Line(1, "Uno", "1.00"), Line(2, "Due", "2.00")])])
    )

    staged = list(
        world.session.scalars(
            select(InvoiceImportRow).where(InvoiceImportRow.import_job_id == result.import_job_id)
        )
    )
    assert len(staged) == 2
    assert {row.validation_status for row in staged} == {ImportRowStatus.IMPORTED}
    assert all(row.validation_errors == [] for row in staged)
    assert sorted(row.source_line_number or 0 for row in staged) == [1, 2]


def test_a_multi_body_xml_becomes_one_invoice_per_body_for_one_supplier(world: CostWorld) -> None:
    bodies = [
        Body(number="1", date="2026-03-01", lines=[Line(1, "Servizio", "10.00")]),
        Body(number="2", date="2026-03-02", lines=[Line(1, "Servizio", "20.00")]),
        Body(
            number="3",
            date="2026-03-03",
            type_code="TD04",
            lines=[Line(1, "Storno", "5.00")],
        ),
    ]

    result = world.import_xml(fattura_xml(bodies))

    assert result.succeeded and result.documents_total == 3
    assert (result.invoices_created, result.suppliers_created) == (3, 1)
    assert len({invoice.supplier_id for invoice in world.invoices()}) == 1
    assert [i.document_kind for i in world.invoices()] == [
        DocumentKind.INVOICE,
        DocumentKind.INVOICE,
        DocumentKind.CREDIT_NOTE,
    ]


def test_the_same_supplier_from_a_second_file_is_matched_by_vat(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="1")], cedente=Cedente(name="Rossi Food S.r.l.")))

    result = world.import_xml(
        fattura_xml([Body(number="2")], cedente=Cedente(name="ROSSI FOOD SOCIETA' SRL")),
        name="seconda.xml",
    )

    assert result.succeeded
    assert (result.suppliers_created, result.suppliers_matched) == (0, 1)
    assert result.aliases_added == 1  # the new spelling is remembered
    assert world.count(Supplier) == 1
    assert {i.supplier_resolution_method for i in world.invoices()} == {
        ResolutionMethod.CREATED_NEW,
        ResolutionMethod.VAT_NUMBER,
    }


def test_a_new_identifier_of_a_known_supplier_is_added_by_a_later_import(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="1")]))

    result = world.import_xml(
        fattura_xml(
            [Body(number="2", payments=[Payment(iban=IBAN_A)])],
            cedente=Cedente(tax_code="RSSMRA80A01H501U"),
        ),
        name="due.xml",
    )

    assert result.succeeded and result.identifiers_added == 2  # tax code + IBAN hash
    kinds = {
        i.kind
        for i in world.session.scalars(
            select(SupplierIdentifier).where(
                SupplierIdentifier.workspace_id == world.tenant.workspace.id
            )
        )
    }
    assert kinds == set(IdentifierKind)


def test_a_similar_supplier_gets_a_review_but_its_invoice_stays_on_the_new_supplier(
    world: CostWorld,
) -> None:
    world.import_xml(
        fattura_xml(
            [Body(number="1")], cedente=Cedente(name="Rossi Food S.r.l.", vat="01234567890")
        )
    )

    result = world.import_xml(
        fattura_xml(
            [Body(number="9")], cedente=Cedente(name="Rossi Foods S.r.l.", vat=None, tax_code=None)
        ),
        name="simile.xml",
    )

    assert result.succeeded and result.reviews_created == 1 and result.suppliers_created == 1
    suppliers = {s.normalized_name: s for s in world.session.scalars(select(Supplier))}
    new_invoice = next(i for i in world.invoices() if i.normalized_invoice_number == "9")
    assert new_invoice.supplier_id == suppliers["rossi foods srl"].id  # never the candidate
    assert new_invoice.supplier_resolution_method == ResolutionMethod.CREATED_NEW_WITH_REVIEW


def test_lines_are_classified_and_keep_their_method_and_confidence(world: CostWorld) -> None:
    body = Body(
        lines=[
            Line(1, "Servizio lavanderia biancheria", "50.00"),
            Line(2, "Cose varie", "10.00"),
        ]
    )

    world.import_xml(fattura_xml([body]))

    (invoice,) = world.invoices()
    first, second = lines_of(world.session, invoice)
    assert (first.cost_category, first.classification_method) == (
        CostCategory.LAUNDRY,
        ClassificationMethod.DETERMINISTIC_RULE,
    )
    assert first.classification_confidence == D("80.00")
    assert (second.cost_category, second.classification_method) == (
        CostCategory.OTHER,
        ClassificationMethod.UNCLASSIFIED,
    )
    assert second.classification_confidence == D("0.00")


def test_the_supplier_default_category_classifies_lines_that_no_rule_matches(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Cose varie", "10.00")])]))
    supplier = world.session.scalars(select(Supplier)).one()
    supplier.default_cost_category = CostCategory.MAINTENANCE
    world.session.flush()

    world.import_xml(
        fattura_xml([Body(number="2", lines=[Line(1, "Cose varie", "10.00")])]), name="b.xml"
    )

    second = next(i for i in world.invoices() if i.normalized_invoice_number == "2")
    (line,) = lines_of(world.session, second)
    assert (line.cost_category, line.classification_method, line.classification_confidence) == (
        CostCategory.MAINTENANCE,
        ClassificationMethod.SUPPLIER_DEFAULT,
        D("90.00"),
    )


# --- D. credit notes, end to end ----------------------------------------------------------------


@pytest.mark.parametrize("type_code", ["TD04", "TD08"])
def test_an_xml_credit_note_is_stored_as_a_negative_credit_note(
    world: CostWorld, type_code: str
) -> None:
    body = Body(
        number="NC/1",
        type_code=type_code,
        lines=[Line(1, "Storno lavanderia", "60.00"), Line(2, "Storno trasporto", "40.00")],
        total="122.00",
    )

    result = world.import_xml(fattura_xml([body]))

    assert result.succeeded
    (invoice,) = world.invoices()
    assert invoice.document_kind == DocumentKind.CREDIT_NOTE
    assert invoice.document_type_code == type_code
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        D("-100.00"),
        D("-22.00"),
        D("-122.00"),
    )
    assert [line.line_total for line in lines_of(world.session, invoice)] == [
        D("-60.00"),
        D("-40.00"),
    ]


def test_a_plain_sum_of_signed_lines_nets_a_credit_note_against_its_invoice(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "100.00")])]))
    world.import_xml(
        fattura_xml([Body(number="1", type_code="TD04", lines=[Line(1, "Storno", "30.00")])]),
        name="nc.xml",
    )

    total = sum(
        (
            line.line_total
            for invoice in world.invoices()
            for line in lines_of(world.session, invoice)
        ),
        D(0),
    )

    assert total == D("70.00")
    assert len(world.invoices()) == 2  # same number, but an invoice and a credit note differ


def test_a_credit_note_is_not_a_conflict_with_the_invoice_it_reverses(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="7", date="2026-03-10")]))

    result = world.import_xml(
        fattura_xml([Body(number="7", date="2026-03-10", type_code="TD04")]), name="nc.xml"
    )

    assert result.succeeded and result.invoices_created == 1


# --- K. the data source -------------------------------------------------------------------------


def refused(world: CostWorld, source_id: Any, **kwargs: Any) -> InvoiceImportError:
    with pytest.raises(InvoiceImportError) as info:
        world.service().import_file(source_id, filename="f.xml", content=fattura_xml(), **kwargs)
    return info.value


def test_a_bookings_data_source_is_refused_and_nothing_is_created(
    world: CostWorld, factory: BookingFactory
) -> None:
    bookings = factory.data_source(world.tenant.property, DataSourceDomain.BOOKINGS)

    error = refused(world, bookings.id)

    assert (
        error.error_code == Code.INVALID_DATA_SOURCE
        and Code.INVALID_DATA_SOURCE.value == "INVOICE_INVALID_DATA_SOURCE"
    )
    assert error.details == {"reason": "wrong_domain"}
    assert world.count(ImportJob) == 1  # only the factory's own job: the attempt created none
    assert canonical_counts(world) == ZERO


def test_a_labor_data_source_is_refused(world: CostWorld, factory: BookingFactory) -> None:
    labor = factory.data_source(world.tenant.property, DataSourceDomain.LABOR)
    assert refused(world, labor.id).details == {"reason": "wrong_domain"}


def test_an_inactive_data_source_is_refused(world: CostWorld) -> None:
    world.source.is_active = False
    world.session.flush()
    assert refused(world, world.source.id).details == {"reason": "inactive"}


def test_a_data_source_of_another_property_is_refused_when_a_property_is_stated(
    world: CostWorld, factory: BookingFactory
) -> None:
    other = factory.property(world.tenant.workspace)

    error = refused(world, world.source.id, property_id=other.id)

    assert error.details == {"reason": "property_mismatch"}


def test_a_foreign_data_source_is_indistinguishable_from_an_unknown_one(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)

    foreign = refused(world, stranger.source.id)
    from uuid import uuid4

    unknown = refused(world, uuid4())

    assert foreign.error_code == unknown.error_code == Code.INVALID_DATA_SOURCE
    assert foreign.details == unknown.details == {"reason": "not_found"}
    assert foreign.message == unknown.message
    assert stranger.count(ImportJob) == 1 and canonical_counts(stranger) == ZERO


def test_an_archived_property_cannot_receive_imports(world: CostWorld) -> None:
    from app.modules.properties.repository import PropertyRepository

    PropertyRepository(world.session, world.context).archive(world.tenant.property.id)

    assert refused(world, world.source.id).details == {"reason": "property_unavailable"}


def test_only_xml_csv_and_xlsx_are_supported_pdf_and_p7m_are_refused(world: CostWorld) -> None:
    for name, reason in (
        ("fattura.xml.p7m", "signed_p7m_not_supported"),
        ("fattura.pdf", "pdf_not_supported"),
        ("scan.png", "unsupported_extension"),
        ("nofile", "unsupported_extension"),
    ):
        result = world.import_bytes(name, b"%PDF-1.4 whatever")
        assert result.status == ImportJobStatus.FAILED, name
        assert (
            result.error_code == Code.UNSUPPORTED_FILE_TYPE
            and Code.UNSUPPORTED_FILE_TYPE.value == "INVOICE_UNSUPPORTED_FILE_TYPE"
        )
        assert result.details["reason"] == reason
        assert result.details["supported"] == [".xml", ".csv", ".xlsx"]
    assert canonical_counts(world) == ZERO


# --- J. atomicity -------------------------------------------------------------------------------


def test_one_invalid_document_keeps_the_staging_and_creates_nothing_else(world: CostWorld) -> None:
    bodies = [
        Body(number="1", date="2026-03-01"),
        Body(number="2", date="2026-13-45"),  # invalid
        Body(number="3", date="2026-03-03"),
    ]

    result = world.import_xml(fattura_xml(bodies))

    assert result.status == ImportJobStatus.FAILED
    assert (
        result.error_code == Code.VALIDATION_FAILED
        and Code.VALIDATION_FAILED.value == "INVOICE_VALIDATION_FAILED"
    )
    assert (result.rows_total, result.rows_valid, result.rows_invalid) == (3, 2, 1)
    assert result.row_error_summary == {"INVOICE_INVALID_DATE": 1}
    assert canonical_counts(world) == ZERO  # not even the supplier of the two valid ones
    staged = list(
        world.session.scalars(
            select(InvoiceImportRow)
            .where(InvoiceImportRow.import_job_id == result.import_job_id)
            .order_by(InvoiceImportRow.row_number)
        )
    )
    assert [row.validation_status for row in staged] == [
        ImportRowStatus.VALID,
        ImportRowStatus.INVALID,
        ImportRowStatus.VALID,
    ]
    assert staged[1].validation_errors == [
        {"field": "invoice_date", "code": "INVOICE_INVALID_DATE"}
    ]
    job = job_of(world.session, result)
    assert job.status == ImportJobStatus.FAILED and job.error_code == "INVOICE_VALIDATION_FAILED"
    assert job.finished_at is not None


def test_a_rejected_file_never_touches_the_canonical_tables(world: CostWorld) -> None:
    for content in (
        b"<x>not fattura</x>",
        b"<a><b>",
        fattura_xml([Body()], version="FSM10"),
        DOCTYPE_XML,
    ):
        assert world.import_xml(content).status == ImportJobStatus.FAILED
    assert canonical_counts(world) == ZERO


def test_the_job_codes_of_rejected_files_are_stable(world: CostWorld) -> None:
    cases = {
        Code.UNSUPPORTED_FATTURAPA: b"<x>not fattura</x>",
        Code.UNREADABLE_FILE: b"<a><b>",
        Code.XML_SECURITY_REJECTED: DOCTYPE_XML,
    }
    for code, content in cases.items():
        result = world.import_xml(content)
        assert result.error_code == code
        assert job_of(world.session, result).error_code == code.value
    assert Code.XML_SECURITY_REJECTED.value == "INVOICE_XML_SECURITY_REJECTED"
    assert Code.UNSUPPORTED_FATTURAPA.value == "INVOICE_UNSUPPORTED_FATTURAPA"


def test_a_failure_while_writing_rolls_back_everything_and_fails_the_job(
    world: CostWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database refuses the batch after suppliers and invoices were already inserted."""
    original = InvoiceRepository.insert_lines

    def corrupt(self: InvoiceRepository, rows: Any) -> None:
        rows[-1]["classification_confidence"] = D("150")  # violates the 0..100 CHECK
        original(self, rows)

    monkeypatch.setattr(InvoiceRepository, "insert_lines", corrupt)
    body = Body(lines=[Line(1, "Uno", "1.00"), Line(2, "Due", "2.00")])

    result = world.import_xml(fattura_xml([body], cedente=Cedente(name="Nuovo Fornitore S.r.l.")))

    assert result.status == ImportJobStatus.FAILED
    assert (
        result.error_code == Code.CANONICALIZATION_FAILED
        and Code.CANONICALIZATION_FAILED.value == "INVOICE_CANONICALIZATION_FAILED"
    )
    assert result.details == {"constraint": "ck_invoice_lines_classification_confidence_range"}
    assert canonical_counts(world) == ZERO  # suppliers, identifiers, aliases, invoices, lines
    job = job_of(world.session, result)
    assert job.status == ImportJobStatus.FAILED
    assert job.error_code == "INVOICE_CANONICALIZATION_FAILED"
    staged = list(
        world.session.scalars(
            select(InvoiceImportRow).where(InvoiceImportRow.import_job_id == result.import_job_id)
        )
    )
    assert len(staged) == 2 and {r.validation_status for r in staged} == {ImportRowStatus.VALID}


def test_the_import_can_be_retried_after_a_rolled_back_canonicalisation(
    world: CostWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = fattura_xml([Body(number="R1")])
    with monkeypatch.context() as patch:
        patch.setattr(
            InvoiceRepository,
            "insert_invoices",
            lambda self, rows: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        first = world.import_xml(content)
    assert first.error_code == Code.CANONICALIZATION_FAILED
    assert canonical_counts(world) == ZERO

    second = world.import_xml(content)

    assert second.succeeded and second.invoices_created == 1
    assert world.count(Invoice) == 1 and world.count(Supplier) == 1


def test_an_unexpected_error_fails_the_job_and_never_leaves_it_running(
    world: CostWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("secret internal detail with IT60X0542811101000000123456")

    monkeypatch.setattr("app.modules.invoices.service.parse_fatturapa", crash)

    result = world.import_xml(fattura_xml())

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.INTERNAL_ERROR
    assert "secret" not in repr(result) and IBAN_A not in repr(result)
    job = job_of(world.session, result)
    assert job.status == ImportJobStatus.FAILED and job.finished_at is not None
    assert "secret" not in (job.error_message or "")


def test_a_supplier_identity_conflict_creates_nothing_not_even_the_valid_documents(
    world: CostWorld,
) -> None:
    world.confirm()
    world.import_rows(
        [
            {
                "supplier_name": "Uno",
                "supplier_vat_number": "01234567890",
                "supplier_iban": IBAN_A,
                "invoice_number": "1",
                "invoice_date": "2026-03-01",
                "line_description": "x",
                "line_total": "1.00",
            }
        ]
    )
    before = canonical_counts(world)

    result = world.import_rows(
        [
            {  # a brand-new supplier: valid
                "supplier_name": "Nuovo Fornitore",
                "supplier_vat_number": "09876543210",
                "invoice_number": "2",
                "invoice_date": "2026-03-02",
                "line_description": "x",
                "line_total": "1.00",
            },
            {  # the bank account of Uno with another VAT number: a conflict
                "supplier_name": "Uno",
                "supplier_vat_number": "05555555559",
                "supplier_iban": IBAN_A,
                "invoice_number": "3",
                "invoice_date": "2026-03-03",
                "line_description": "x",
                "line_total": "1.00",
            },
        ],
        name="second.csv",
    )

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == "SUPPLIER_IDENTITY_CONFLICT"
    assert canonical_counts(world) == before  # the new supplier was NOT created either
    assert job_of(world.session, result).error_code == "SUPPLIER_IDENTITY_CONFLICT"
    staged = world.session.scalars(
        select(InvoiceImportRow).where(InvoiceImportRow.import_job_id == result.import_job_id)
    ).all()
    assert len(staged) == 2 and {r.validation_status for r in staged} == {ImportRowStatus.VALID}


def test_an_ambiguous_supplier_name_fails_the_import_with_its_code(world: CostWorld) -> None:
    world.import_xml(
        fattura_xml([Body(number="1")], cedente=Cedente(name="Bar Uno", vat="01234567890"))
    )
    world.import_xml(
        fattura_xml([Body(number="2")], cedente=Cedente(name="Bar Due", vat="09876543210")),
        name="b.xml",
    )
    for supplier in world.session.scalars(select(Supplier)):
        world.session.add(
            SupplierAlias(
                workspace_id=world.tenant.workspace.id,
                supplier_id=supplier.id,
                normalized_name="bar",
            )
        )
    world.session.flush()
    before = canonical_counts(world)

    result = world.import_xml(
        fattura_xml([Body(number="3")], cedente=Cedente(name="Bar", vat=None)), name="c.xml"
    )

    assert result.error_code == "SUPPLIER_NAME_AMBIGUOUS"
    assert canonical_counts(world) == before


# --- L. idempotency -----------------------------------------------------------------------------


def test_importing_the_same_file_twice_creates_nothing_the_second_time(world: CostWorld) -> None:
    content = fattura_xml([Body(number="1"), Body(number="2", lines=[Line(1, "Servizio", "5.00")])])
    first = world.import_xml(content)
    before = canonical_counts(world)

    second = world.import_xml(content)

    assert first.succeeded and second.succeeded
    assert (second.invoices_created, second.invoices_unchanged, second.lines_created) == (0, 2, 0)
    assert (second.suppliers_created, second.identifiers_added, second.aliases_added) == (0, 0, 0)
    assert canonical_counts(world) == before
    assert second.duplicate_of_import_file_id == first.import_file_id  # informational only
    assert second.import_job_id != first.import_job_id  # the attempt itself is recorded


def test_the_same_invoice_with_a_different_content_is_a_conflict_never_an_update(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "100.00")])]))
    (original,) = world.invoices()
    before = canonical_counts(world)

    result = world.import_xml(
        fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "999.00")])]), name="changed.xml"
    )

    assert result.status == ImportJobStatus.FAILED
    assert (
        result.error_code == Code.DOCUMENT_CONFLICT
        and Code.DOCUMENT_CONFLICT.value == "INVOICE_DOCUMENT_CONFLICT"
    )
    assert result.details == {"reason": "different_content", "documents": [1]}
    assert canonical_counts(world) == before
    (still,) = world.invoices()
    assert still.id == original.id and still.source_fingerprint == original.source_fingerprint
    assert [line.line_total for line in lines_of(world.session, still)] == [D("100.00")]


def test_a_conflicting_import_rolls_back_the_supplier_it_would_have_enriched(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "100.00")])]))
    before = canonical_counts(world)

    result = world.import_xml(
        fattura_xml(
            [
                Body(
                    number="1", lines=[Line(1, "Servizio", "1.00")], payments=[Payment(iban=IBAN_A)]
                )
            ],
            cedente=Cedente(tax_code="RSSMRA80A01H501U"),
        ),
        name="changed.xml",
    )

    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert canonical_counts(world) == before  # neither the new IBAN nor the tax code was kept


def test_the_same_invoice_from_another_data_source_of_the_property_is_reused(
    world: CostWorld, factory: BookingFactory
) -> None:
    content = fattura_xml([Body(number="1")])
    first = world.import_xml(content)
    second_source = factory.data_source(world.tenant.property, DataSourceDomain.COSTS)

    second = world.service().import_file(second_source.id, filename="altra.xml", content=content)

    assert first.succeeded and second.succeeded
    assert (second.invoices_created, second.invoices_unchanged) == (0, 1)
    (invoice,) = world.invoices()
    assert invoice.data_source_id == world.source.id  # the first one stays the source of record
    assert invoice.source_import_job_id == first.import_job_id


def test_the_same_invoice_from_another_data_source_with_other_content_is_a_conflict(
    world: CostWorld, factory: BookingFactory
) -> None:
    world.import_xml(fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "100.00")])]))
    other = factory.data_source(world.tenant.property, DataSourceDomain.COSTS)

    result = world.service().import_file(
        other.id,
        filename="altra.xml",
        content=fattura_xml([Body(number="1", lines=[Line(1, "Servizio", "80.00")])]),
    )

    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert world.count(Invoice) == 1


def test_the_same_invoice_number_in_another_property_is_another_invoice(
    world: CostWorld, factory: BookingFactory
) -> None:
    content = fattura_xml([Body(number="1")])
    world.import_xml(content)
    other_property = factory.property(world.tenant.workspace)
    other_source = factory.data_source(other_property, DataSourceDomain.COSTS)

    result = world.service().import_file(other_source.id, filename="f.xml", content=content)

    assert result.succeeded and result.invoices_created == 1
    assert (result.suppliers_created, result.suppliers_matched) == (
        0,
        1,
    )  # one supplier, two properties
    invoices = world.invoices()
    assert len(invoices) == 2 and len({i.property_id for i in invoices}) == 2
    assert len({i.supplier_id for i in invoices}) == 1
    assert world.count(Supplier) == 1


def test_the_same_number_on_another_date_is_another_invoice(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="1", date="2026-03-10")]))
    result = world.import_xml(fattura_xml([Body(number="1", date="2027-03-10")]), name="y.xml")
    assert result.succeeded and world.count(Invoice) == 2


def test_the_same_number_from_two_suppliers_is_two_invoices(world: CostWorld) -> None:
    world.import_xml(
        fattura_xml([Body(number="1")], cedente=Cedente(name="Uno", vat="01234567890"))
    )
    result = world.import_xml(
        fattura_xml([Body(number="1")], cedente=Cedente(name="Due", vat="09876543210")),
        name="b.xml",
    )
    assert result.succeeded and world.count(Invoice) == 2 and world.count(Supplier) == 2


def test_invoice_numbers_are_compared_in_normal_form(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="fa  12/2026")]))

    again = world.import_xml(fattura_xml([Body(number="FA 12/2026 ")]), name="b.xml")

    assert again.succeeded and (again.invoices_created, again.invoices_unchanged) == (0, 1)
    (invoice,) = world.invoices()
    assert invoice.invoice_number == "fa  12/2026"  # the source spelling is kept as it was
    assert invoice.normalized_invoice_number == "FA 12/2026"


def test_slash_and_dash_are_part_of_the_invoice_number(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="123/A")]))
    result = world.import_xml(fattura_xml([Body(number="123A")]), name="b.xml")
    assert result.succeeded and world.count(Invoice) == 2


def test_the_same_document_twice_in_one_import_is_refused(world: CostWorld) -> None:
    body = Body(number="1")

    result = world.import_xml(fattura_xml([body, body]))

    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert result.details == {"reason": "duplicate_in_import", "documents": [2]}
    assert canonical_counts(world) == ZERO


def test_a_rerun_with_one_more_invoice_adds_only_that_invoice(world: CostWorld) -> None:
    world.import_xml(fattura_xml([Body(number="1"), Body(number="2")]))

    result = world.import_xml(
        fattura_xml([Body(number="1"), Body(number="2"), Body(number="3")]), name="b.xml"
    )

    assert result.succeeded
    assert (result.invoices_created, result.invoices_unchanged) == (1, 2)
    assert world.count(Invoice) == 3


def test_the_file_hash_is_not_globally_unique_across_workspaces(
    world: CostWorld, factory: BookingFactory
) -> None:
    content = fattura_xml([Body(number="1")])
    stranger = CostWorld.create(world.session, factory)

    first = world.import_xml(content)
    second = stranger.import_xml(content)

    assert first.succeeded and second.succeeded
    assert second.duplicate_of_import_file_id is None  # the other workspace's file is invisible
    hashes = [
        f.sha256
        for f in world.session.scalars(select(ImportFile))
        if f.id in (first.import_file_id, second.import_file_id)
    ]
    assert len(hashes) == 2 and hashes[0] == hashes[1]
    assert world.count(Invoice) == 1 and stranger.count(Invoice) == 1


def test_the_import_reports_the_job_and_file_it_created(world: CostWorld) -> None:
    result = world.import_xml(fattura_xml(), name="C:\\Users\\mario\\Desktop\\fattura marzo.xml")

    stored = world.session.get(ImportFile, result.import_file_id)
    assert stored is not None and stored.original_filename == "fattura marzo.xml"
    assert stored.sha256 is not None and len(stored.sha256) == 64
    assert persisted_hits(world.session, ["mario", "Desktop"]) == []


# --- explainability ----------------------------------------------------------------------------


def test_an_invoice_can_be_explained_from_the_database_alone(world: CostWorld) -> None:
    body = Body(
        number="FA/9",
        lines=[Line(1, "Servizio lavanderia", "80.00", quantity="4", unit="kg", unit_price="20")],
        payments=[Payment(due="2026-05-01", iban=IBAN_A)],
    )
    result = world.import_xml(
        fattura_xml([body], cedente=Cedente(name="Rossi Food S.r.l.", tax_code="RSSMRA80A01H501U")),
        name="marzo.xml",
    )
    (invoice,) = world.invoices()

    # where it came from
    job = world.session.get(ImportJob, invoice.source_import_job_id)
    file = world.session.get(ImportFile, invoice.source_import_file_id)
    assert job is not None and file is not None
    assert (job.id, file.id) == (result.import_job_id, result.import_file_id)
    assert file.original_filename == "marzo.xml" and job.data_source_id == invoice.data_source_id
    assert invoice.source_format == SourceFormat.FATTURAPA_XML
    # who the supplier is, how it was resolved, with which identifiers (never a raw IBAN)
    supplier = world.session.get(Supplier, invoice.supplier_id)
    assert supplier is not None and supplier.legal_name == "Rossi Food S.r.l."
    assert invoice.supplier_resolution_method == ResolutionMethod.CREATED_NEW
    identifiers = {
        (i.kind, i.normalized_value)
        for i in world.session.scalars(
            select(SupplierIdentifier).where(SupplierIdentifier.supplier_id == supplier.id)
        )
    }
    assert {kind for kind, _ in identifiers} == set(IdentifierKind)
    assert not [value for _, value in identifiers if value == IBAN_A]
    # its identity, kind, totals and lines with category, method and confidence
    assert (invoice.normalized_invoice_number, invoice.invoice_date, invoice.document_kind) == (
        "FA/9",
        date(2026, 3, 10),
        DocumentKind.INVOICE,
    )
    assert invoice.net_amount == D("80.00") and invoice.gross_amount is None
    (line,) = lines_of(world.session, invoice)
    assert (line.quantity, line.unit, line.unit_price) == (D("4"), "kg", D("20"))
    assert (line.cost_category, line.classification_method, line.classification_confidence) == (
        CostCategory.LAUNDRY,
        ClassificationMethod.DETERMINISTIC_RULE,
        D("80.00"),
    )


def test_a_fuzzy_review_can_be_explained_from_the_database_alone(world: CostWorld) -> None:
    world.import_xml(
        fattura_xml(
            [Body(number="1")], cedente=Cedente(name="Rossi Food S.r.l.", vat="01234567890")
        )
    )
    world.import_xml(
        fattura_xml([Body(number="2")], cedente=Cedente(name="Rossi Foods S.r.l.", vat=None)),
        name="b.xml",
    )

    (review,) = world.session.scalars(select(SupplierResolutionReview))

    provisional = world.session.get(Supplier, review.provisional_supplier_id)
    candidate = world.session.get(Supplier, review.candidate_supplier_id)
    assert provisional is not None and candidate is not None
    assert (provisional.normalized_name, candidate.normalized_name) == (
        "rossi foods srl",
        "rossi food srl",
    )
    assert review.reason.value == "FUZZY_NAME_SIMILARITY"
    assert D("0.85") <= review.similarity_score < D("1")  # similar, but not the same name
    assert review.status.value == "PENDING"  # nothing was merged: a person decides


# --- observability ------------------------------------------------------------------------------


def test_the_import_logs_ids_and_counts_only(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    body = Body(
        number="SECRET-INV-77",
        lines=[Line(1, "Descrizione riservata della riga", "12.34")],
        payments=[Payment(iban=IBAN_A)],
    )

    result = world.import_xml(
        fattura_xml(
            [body], cedente=Cedente(name="Fornitore Segreto S.r.l.", tax_code="RSSMRA80A01H501U")
        )
    )

    text_ = caplog.text
    for expected in (
        str(world.tenant.workspace.id),
        str(world.tenant.property.id),
        str(world.source.id),
        str(result.import_job_id),
        str(result.import_file_id),
        "invoice import started",
        "invoice import finished",
        "invoices_created=1",
    ):
        assert expected in text_, expected
    for hidden in (
        "SECRET-INV-77",
        "Descrizione riservata",
        "Fornitore Segreto",
        "12.34",
        "01234567890",
        "RSSMRA80A01H501U",
        IBAN_A,
    ):
        assert hidden not in text_, hidden


def test_each_workspace_sees_only_its_own_invoices_and_staging(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)
    world.import_xml(fattura_xml([Body(number="1")]))
    stranger.import_xml(fattura_xml([Body(number="1")]))

    assert world.count(Invoice) == stranger.count(Invoice) == 1
    assert {i.workspace_id for i in all_invoices(world.session, world.tenant.workspace.id)} == {
        world.tenant.workspace.id
    }
    assert count(world.session, Invoice) == 2
    assert world.count(InvoiceImportRow) == stranger.count(InvoiceImportRow) == 1


def test_one_supplier_created_by_an_import_tells_one_story_to_all_its_documents(
    world: CostWorld,
) -> None:
    """The second body has no IBAN, so its evidence differs from the first's: it still meets the
    supplier the first one created, and is counted and explained as the same supplier."""
    bodies = [
        Body(number="1", payments=[Payment(iban=IBAN_A)]),
        Body(number="2"),
        Body(number="3", payments=[Payment(iban=IBAN_A)]),
    ]

    result = world.import_xml(fattura_xml(bodies))

    assert result.succeeded and result.invoices_created == 3
    assert (result.suppliers_created, result.suppliers_matched) == (1, 0)
    assert {i.supplier_resolution_method for i in world.invoices()} == {
        ResolutionMethod.CREATED_NEW
    }
    assert world.count(Supplier) == 1


def test_a_known_supplier_is_counted_once_however_many_spellings_the_file_uses(
    world: CostWorld,
) -> None:
    world.import_xml(fattura_xml([Body(number="0")], cedente=Cedente(name="Rossi Food S.r.l.")))

    result = world.import_xml(
        fattura_xml(
            [Body(number="1"), Body(number="2", payments=[Payment(iban=IBAN_A)])],
            cedente=Cedente(name="Rossi Food S.r.l."),
        ),
        name="b.xml",
    )

    assert result.succeeded
    assert (result.suppliers_created, result.suppliers_matched) == (0, 1)


def test_reconciliation_diagnostics_live_in_staging_only_and_are_never_a_requirement(
    world: CostWorld,
) -> None:
    """Lines that do not add up to the stated net are legitimate (discounts, stamp duty, rounding):
    the difference is a diagnostic of the staged header, not a column of the invoice."""
    body = Body(
        lines=[Line(1, "Servizio", "100.00"), Line(2, "Altro", "20.00")],
        summaries=[("22.00", "130.00", "28.60")],  # the stated net is 10.00 above the lines
    )

    result = world.import_xml(fattura_xml([body]))

    assert result.succeeded  # SUM(lines) = net is not required
    (header_row, _) = world.session.scalars(
        select(InvoiceImportRow)
        .where(InvoiceImportRow.import_job_id == result.import_job_id)
        .order_by(InvoiceImportRow.row_number)
    ).all()
    header = (header_row.normalized_payload or {})["header"]["diagnostics"]
    assert (
        header["line_net_sum"],
        header["document_net_amount"],
        header["reconciliation_delta"],
    ) == (
        "120.00",
        "130.00",
        "10.00",
    )
    stored_columns = {c.name for c in Invoice.__table__.columns} | {
        c.name for c in InvoiceLine.__table__.columns
    }
    assert not stored_columns & {"line_net_sum", "document_net_amount", "reconciliation_delta"}
