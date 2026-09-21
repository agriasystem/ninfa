"""The committed synthetic fixtures (tests/fixtures/invoices), one test per case of the Gate 6
specification: 15 FatturaPA files and the structured CSV/XLSX cases. Synthetic data only.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ingestion.models import ImportJobStatus
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.errors import InvoiceErrorCode
from app.modules.invoices.models import DocumentKind, Invoice, InvoiceImportRow, ResolutionMethod
from app.modules.suppliers.models import (
    IdentifierKind,
    ReviewReason,
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from tests.booking_support import csv_bytes, xlsx_bytes
from tests.invoice_support import (
    IBAN_A,
    RECIPIENT_NAME,
    RECIPIENT_TAX_CODE,
    SUPPLIER_EMAIL,
    SUPPLIER_PHONE,
    SUPPLIER_STREET,
    CostWorld,
    lines_of,
    persisted_hits,
)
from tests.support import BookingFactory

D = Decimal
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "invoices"
XML_DIR = FIXTURES / "xml"
CSV_DIR = FIXTURES / "structured"
Code = InvoiceErrorCode


def xml(name: str) -> bytes:
    return (XML_DIR / name).read_bytes()


def structured(name: str) -> bytes:
    return (CSV_DIR / name).read_bytes()


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


# --- FatturaPA (1-15) ----------------------------------------------------------------------------


def test_fixture_01_a_standard_fpr12_invoice(world: CostWorld) -> None:
    result = world.import_xml(xml("01_fpr12_standard.xml"))

    assert result.succeeded and (result.invoices_created, result.lines_created) == (1, 2)
    (invoice,) = world.invoices()
    assert invoice.normalized_invoice_number == "FA-0001" and invoice.invoice_date == date(
        2026, 3, 10
    )
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        D("140.00"),
        D("30.80"),
        D("170.80"),
    )
    assert [
        (line.line_total, line.quantity, line.unit) for line in lines_of(world.session, invoice)
    ] == [
        (D("120.00"), D("4"), "pz"),
        (D("20.00"), None, None),
    ]


def test_fixture_02_a_standard_fpa12_invoice(world: CostWorld) -> None:
    assert world.import_xml(xml("02_fpa12_standard.xml")).succeeded


def test_fixture_03_a_td04_credit_note(world: CostWorld) -> None:
    assert world.import_xml(xml("03_td04_credit_note.xml")).succeeded

    (invoice,) = world.invoices()
    assert (
        invoice.document_kind == DocumentKind.CREDIT_NOTE and invoice.document_type_code == "TD04"
    )
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        D("-50.00"),
        D("-11.00"),
        D("-61.00"),
    )
    assert [line.line_total for line in lines_of(world.session, invoice)] == [D("-50.00")]


def test_fixture_04_a_td08_simplified_credit_note(world: CostWorld) -> None:
    assert world.import_xml(xml("04_td08_simplified_credit_note.xml")).succeeded

    (invoice,) = world.invoices()
    assert (
        invoice.document_kind == DocumentKind.CREDIT_NOTE and invoice.document_type_code == "TD08"
    )
    assert [line.line_total for line in lines_of(world.session, invoice)] == [D("-12.30")]


def test_fixture_05_a_multi_body_file(world: CostWorld) -> None:
    result = world.import_xml(xml("05_multi_body.xml"))

    assert result.succeeded and (result.documents_total, result.invoices_created) == (3, 3)
    assert result.suppliers_created == 1
    assert [i.document_kind for i in world.invoices()] == [
        DocumentKind.INVOICE,
        DocumentKind.CREDIT_NOTE,
        DocumentKind.INVOICE,
    ]
    assert [len(lines_of(world.session, i)) for i in world.invoices()] == [2, 1, 2]


def test_fixture_06_a_supplier_with_vat_number_and_tax_code(world: CostWorld) -> None:
    assert world.import_xml(xml("06_supplier_vat_and_tax_code.xml")).succeeded

    identifiers = {
        (i.kind, i.normalized_value) for i in world.session.scalars(select(SupplierIdentifier))
    }
    assert identifiers == {
        (IdentifierKind.VAT_NUMBER, "IT09876543210"),
        (IdentifierKind.TAX_CODE, "09876543210"),
    }


def test_fixture_07_the_same_vat_number_with_a_slightly_different_name(world: CostWorld) -> None:
    world.import_xml(xml("01_fpr12_standard.xml"))

    result = world.import_xml(xml("07_same_vat_slightly_different_name.xml"))

    assert result.succeeded and (result.suppliers_created, result.suppliers_matched) == (0, 1)
    assert world.count(Supplier) == 1
    invoice = next(i for i in world.invoices() if i.normalized_invoice_number == "FA-0701")
    assert invoice.supplier_resolution_method == ResolutionMethod.VAT_NUMBER
    aliases = {a.normalized_name for a in world.session.scalars(select(SupplierAlias))}
    assert aliases == {"rossi food srl", "rossi food societa srl"}


def test_fixture_08_no_vat_number_and_an_exact_alias(world: CostWorld) -> None:
    world.import_xml(xml("01_fpr12_standard.xml"))
    world.import_xml(xml("07_same_vat_slightly_different_name.xml"))  # registers the alias

    result = world.import_xml(xml("08_no_vat_exact_alias.xml"))

    assert result.succeeded and (result.suppliers_created, result.suppliers_matched) == (0, 1)
    invoice = next(i for i in world.invoices() if i.normalized_invoice_number == "FA-0801")
    assert invoice.supplier_resolution_method == ResolutionMethod.EXACT_ALIAS
    assert world.count(Supplier) == 1


def test_fixture_09_a_fuzzy_candidate_opens_a_review_and_merges_nothing(world: CostWorld) -> None:
    world.import_xml(xml("01_fpr12_standard.xml"))

    result = world.import_xml(xml("09_fuzzy_candidate.xml"))

    assert result.succeeded and result.suppliers_created == 1 and result.reviews_created == 1
    assert world.count(Supplier) == 2
    (review,) = world.session.scalars(select(SupplierResolutionReview))
    assert review.reason == ReviewReason.FUZZY_NAME_SIMILARITY
    assert review.similarity_score == D("0.9655")
    provisional = world.session.get(Supplier, review.provisional_supplier_id)
    assert provisional is not None and provisional.normalized_name == "rossi foods srl"
    invoice = next(i for i in world.invoices() if i.normalized_invoice_number == "FA-0901")
    assert invoice.supplier_id == provisional.id  # never assigned to the candidate


def test_fixture_10_conflicting_vat_and_tax_code_identities(world: CostWorld) -> None:
    world.import_xml(xml("01_fpr12_standard.xml"))  # owns the VAT number
    world.import_xml(xml("06_supplier_vat_and_tax_code.xml"))  # owns the tax code
    before = (world.count(Supplier), world.count(Invoice), world.count(SupplierIdentifier))

    result = world.import_xml(xml("10_conflicting_identities.xml"))

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == "SUPPLIER_IDENTITY_CONFLICT"
    assert (world.count(Supplier), world.count(Invoice), world.count(SupplierIdentifier)) == before


def test_fixture_11_one_due_date(world: CostWorld) -> None:
    result = world.import_xml(xml("11_one_due_date.xml"))
    assert result.succeeded and result.warning_summary == {}
    assert world.invoices()[0].due_date == date(2026, 4, 10)


def test_fixture_12_multiple_due_dates(world: CostWorld) -> None:
    result = world.import_xml(xml("12_multiple_due_dates.xml"))
    assert result.succeeded and result.warning_summary == {"MULTIPLE_PAYMENT_DUE_DATES": 1}
    assert world.invoices()[0].due_date is None


def test_fixture_13_a_raw_iban_in_the_source(world: CostWorld) -> None:
    assert IBAN_A.encode() in xml("13_raw_iban.xml")

    result = world.import_xml(xml("13_raw_iban.xml"))

    assert result.succeeded
    digest = hashlib.sha256(IBAN_A.encode()).hexdigest()
    hashes = [
        i.normalized_value
        for i in world.session.scalars(
            select(SupplierIdentifier).where(SupplierIdentifier.kind == IdentifierKind.IBAN_SHA256)
        )
    ]
    assert hashes == [digest]
    assert persisted_hits(world.session, [IBAN_A]) == []


def test_fixture_14_a_malicious_doctype_and_entity(world: CostWorld) -> None:
    content = xml("14_malicious_doctype_entity.xml")
    assert b"<!ENTITY xxe SYSTEM" in content

    result = world.import_xml(content)

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.XML_SECURITY_REJECTED
    assert world.count(Invoice) == world.count(Supplier) == 0
    assert "passwd" not in repr(result)


def test_fixture_15_missing_required_data(world: CostWorld) -> None:
    result = world.import_xml(xml("15_missing_required_data.xml"))

    assert result.status == ImportJobStatus.FAILED and result.error_code == Code.VALIDATION_FAILED
    assert result.row_error_summary == {"INVOICE_REQUIRED_VALUE_MISSING": 2}
    (row,) = world.session.scalars(select(InvoiceImportRow))
    assert {e["field"] for e in row.validation_errors} == {"invoice_number", "invoice_date"}
    assert world.count(Invoice) == world.count(Supplier) == 0


def test_every_xml_fixture_carries_private_data_that_never_reaches_the_database(
    world: CostWorld,
) -> None:
    private = [
        RECIPIENT_NAME,
        RECIPIENT_TAX_CODE,
        SUPPLIER_EMAIL,
        SUPPLIER_PHONE,
        SUPPLIER_STREET,
        "cliente-pec@example.com",
        "Perugia",
    ]
    for path in sorted(XML_DIR.glob("*.xml")):
        if path.name.startswith("14"):
            continue
        assert all(value.encode() in path.read_bytes() for value in private), path.name
        world.import_xml(path.read_bytes(), name=path.name)
    assert persisted_hits(world.session, private) == []


# --- structured files (1-12) ---------------------------------------------------------------------

ITALIAN_COLUMNS = {
    "supplier_name": {"column": "Fornitore"},
    "supplier_vat_number": {"column": "P.IVA"},
    "invoice_number": {"column": "Numero Fattura"},
    "invoice_date": {"column": "Data"},
    "line_description": {"column": "Descrizione"},
    "line_total": {"column": "Importo"},
}
ITALIAN_FORMAT = {
    "date_formats": {"invoice_date": "%d/%m/%Y"},
    "decimal_separator": ",",
    "thousands_separator": ".",
}
ENGLISH_COLUMNS = {
    "supplier_name": {"column": "Supplier"},
    "supplier_vat_number": {"column": "VAT"},
    "invoice_number": {"column": "Invoice No"},
    "invoice_date": {"column": "Invoice Date"},
    "line_description": {"column": "Description"},
    "line_total": {"column": "Line Total"},
}


def confirm(world: CostWorld, content: bytes, columns: dict, **sections: object) -> None:  # type: ignore[type-arg]
    headers = (
        world.service().describe_file(world.source.id, filename="f.csv", content=content).headers
    )
    world.confirm(headers, columns, **sections)


def test_structured_01_an_italian_semicolon_csv(world: CostWorld) -> None:
    content = structured("it_semicolon.csv")
    confirm(world, content, ITALIAN_COLUMNS, format_options=ITALIAN_FORMAT)

    result = world.import_bytes("it_semicolon.csv", content)

    assert result.succeeded and result.invoices_created == 2 and result.suppliers_created == 2
    first = next(i for i in world.invoices() if i.normalized_invoice_number == "IT-1")
    assert [line.line_total for line in lines_of(world.session, first)] == [
        D("1234.56"),
        D("20.00"),
    ]
    assert first.invoice_date == date(2026, 3, 10)


def test_structured_02_an_english_comma_csv(world: CostWorld) -> None:
    content = structured("en_comma.csv")
    confirm(world, content, ENGLISH_COLUMNS)

    result = world.import_bytes("en_comma.csv", content)

    assert result.succeeded and result.invoices_created == 2 and result.lines_created == 3


def test_structured_03_a_utf8_file_with_a_bom(world: CostWorld) -> None:
    content = structured("utf8_bom.csv")
    assert content.startswith(b"\xef\xbb\xbf")
    confirm(world, content, ENGLISH_COLUMNS)

    assert world.import_bytes("utf8_bom.csv", content).succeeded
    assert world.count(Invoice) == 2


def test_structured_04_a_cp1252_file(world: CostWorld) -> None:
    content = structured("cp1252.csv")
    assert "caffè".encode("cp1252") in content
    confirm(world, content, ITALIAN_COLUMNS, format_options=ITALIAN_FORMAT)

    assert world.import_bytes("cp1252.csv", content).succeeded
    descriptions = {
        line.description_raw
        for invoice in world.invoices()
        for line in lines_of(world.session, invoice)
    }
    assert "Consegna caffè" in descriptions


def test_structured_05_an_xlsx_workbook(world: CostWorld) -> None:
    from datetime import datetime

    rows: list[list[Any]] = [
        ["Supplier", "VAT", "Invoice No", "Invoice Date", "Description", "Line Total"],
        [
            "Rossi Food S.r.l.",
            "01234567890",
            "XL-1",
            datetime(2026, 3, 10),
            "Kitchen supplies",
            120.0,
        ],
        ["Rossi Food S.r.l.", "01234567890", "XL-1", datetime(2026, 3, 10), "Delivery", 20.5],
    ]
    content = xlsx_bytes({"Invoices": rows})
    world.confirm(rows[0], ENGLISH_COLUMNS)

    result = world.import_bytes("costs.xlsx", content)

    assert result.succeeded and result.invoices_created == 1
    (invoice,) = world.invoices()
    assert [line.line_total for line in lines_of(world.session, invoice)] == [
        D("120.00"),
        D("20.50"),
    ]


def test_structured_06_a_repeated_invoice_header(world: CostWorld) -> None:
    content = structured("repeated_invoice_header.csv")
    confirm(
        world,
        content,
        {**ENGLISH_COLUMNS, "invoice_gross_amount": {"column": "Gross"}},
    )

    result = world.import_bytes("repeated.csv", content)

    assert result.succeeded and (result.documents_total, result.rows_total) == (1, 3)
    (invoice,) = world.invoices()
    assert invoice.gross_amount == D("36.60") and len(lines_of(world.session, invoice)) == 3


def test_structured_07_an_explicitly_mapped_category(world: CostWorld) -> None:
    content = structured("category_mapped.csv")
    confirm(
        world,
        content,
        {**ENGLISH_COLUMNS, "cost_category": {"column": "Category"}},
        category_mapping={"Biancheria": "LAUNDRY", "Trasporto": "TRANSPORT"},
    )

    assert world.import_bytes("category_mapped.csv", content).succeeded

    (invoice,) = world.invoices()
    lines = lines_of(world.session, invoice)
    assert [line.cost_category for line in lines] == [
        CostCategory.LAUNDRY,
        CostCategory.TRANSPORT,
        CostCategory.OTHER,  # a canonical name stated by the source: explicit, not a guess
    ]
    assert {line.classification_method for line in lines} == {ClassificationMethod.EXPLICIT_SOURCE}
    assert {line.classification_confidence for line in lines} == {D("100.00")}


def test_structured_08_a_repeated_total_that_conflicts(world: CostWorld) -> None:
    content = structured("conflicting_repeated_total.csv")
    confirm(world, content, {**ENGLISH_COLUMNS, "invoice_gross_amount": {"column": "Gross"}})

    result = world.import_bytes("conflict.csv", content)

    assert result.status == ImportJobStatus.FAILED
    assert result.row_error_summary == {"INVOICE_INCONSISTENT_HEADER": 1}
    assert world.count(Invoice) == world.count(Supplier) == 0  # and no "last row wins"


def test_structured_09_a_duplicate_line_number(world: CostWorld) -> None:
    content = structured("duplicate_line_number.csv")
    confirm(world, content, {**ENGLISH_COLUMNS, "line_number": {"column": "Line"}})

    result = world.import_bytes("dup.csv", content)

    assert result.status == ImportJobStatus.FAILED
    assert result.row_error_summary == {"INVOICE_DUPLICATE_LINE": 2}
    assert world.count(Invoice) == 0


def test_structured_10_extra_pii_columns_are_never_persisted(world: CostWorld) -> None:
    content = structured("pii_unmapped_columns.csv")
    private = [SUPPLIER_EMAIL, SUPPLIER_PHONE, SUPPLIER_STREET, RECIPIENT_NAME]
    assert all(value.encode() in content for value in private)
    confirm(world, content, ENGLISH_COLUMNS)

    assert world.import_bytes("pii.csv", content).succeeded

    assert persisted_hits(world.session, private) == []
    assert world.count(Invoice) == 1


def test_structured_11_a_changed_schema(world: CostWorld) -> None:
    confirm(world, structured("en_comma.csv"), ENGLISH_COLUMNS)

    result = world.import_bytes("changed.csv", structured("changed_schema.csv"))

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.SOURCE_SCHEMA_CHANGED
    assert result.details == {"reason": "mapped_columns_missing", "missing_columns": ["Line Total"]}
    assert world.count(Invoice) == 0


@pytest.mark.parametrize(
    ("name", "reason"),
    [("unsupported.pdf", "pdf_not_supported"), ("unsupported.xml.p7m", "signed_p7m_not_supported")],
)
def test_structured_12_pdf_and_p7m_are_refused_with_a_stable_code(
    world: CostWorld, name: str, reason: str
) -> None:
    result = world.import_bytes(name, structured(name))

    assert result.status == ImportJobStatus.FAILED
    assert (
        result.error_code == Code.UNSUPPORTED_FILE_TYPE
        and Code.UNSUPPORTED_FILE_TYPE.value == "INVOICE_UNSUPPORTED_FILE_TYPE"
    )
    assert result.details["reason"] == reason
    assert world.count(Invoice) == world.count(Supplier) == 0


def test_the_csv_helper_and_the_fixtures_agree_on_the_bytes_of_a_simple_file() -> None:
    """A guard for the fixture folder: the committed CSV is what the test helper would write."""
    rows = [
        ["Supplier", "VAT", "Invoice No", "Invoice Date", "Description", "Line Total"],
        ["Rossi Food S.r.l.", "01234567890", "EN-1", "2026-03-10", "Kitchen supplies", "120.00"],
        ["Rossi Food S.r.l.", "01234567890", "EN-1", "2026-03-10", "Delivery", "20.00"],
        [
            "Bianchi Servizi S.n.c.",
            "09876543210",
            "EN-2",
            "2026-03-11",
            "Maintenance visit",
            "200.00",
        ],
    ]
    assert csv_bytes(rows) == structured("en_comma.csv")
