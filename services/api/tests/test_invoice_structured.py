"""Structured CSV/XLSX invoice imports, mapping memory and data minimisation (Gate 6 group H, with
the CSV halves of groups D, F and I). Synthetic data only.
"""

import hashlib
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSourceDomain, ImportJob, ImportJobStatus
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError
from app.modules.invoices.models import (
    DocumentKind,
    Invoice,
    InvoiceImportRow,
    InvoiceMappingProfile,
    SourceFormat,
)
from app.modules.suppliers.models import IdentifierKind, Supplier, SupplierIdentifier
from tests.booking_support import csv_bytes, xlsx_bytes
from tests.invoice_support import (
    IBAN_A,
    MINIMAL_COLUMNS,
    MINIMAL_HEADERS,
    STANDARD_COLUMNS,
    STANDARD_HEADERS,
    Body,
    CostWorld,
    Line,
    Payment,
    fattura_xml,
    job_of,
    lines_of,
    persisted_hits,
    standard_csv,
)
from tests.support import BookingFactory

D = Decimal
Code = InvoiceErrorCode


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    w = CostWorld.create(db_session, factory)
    w.confirm()
    return w


def row(**values: Any) -> dict[str, Any]:
    """A valid one-line invoice row of the STANDARD layout; override any field."""
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


def staged(world: CostWorld, result: Any) -> list[InvoiceImportRow]:
    return list(
        world.session.scalars(
            select(InvoiceImportRow)
            .where(InvoiceImportRow.import_job_id == result.import_job_id)
            .order_by(InvoiceImportRow.row_number)
        )
    )


def nothing_created(world: CostWorld) -> bool:
    return world.count(Invoice) == world.count(Supplier) == world.count(SupplierIdentifier) == 0


# --- file formats -------------------------------------------------------------------------------


def test_an_english_comma_csv_with_iso_dates_is_imported(world: CostWorld) -> None:
    result = world.import_rows(
        [row(), row(invoice_number="2", invoice_date="2026-04-01", line_total="55.50")]
    )

    assert result.succeeded and result.source_format == SourceFormat.CSV
    assert (result.documents_total, result.invoices_created, result.suppliers_created) == (2, 2, 1)
    assert [i.invoice_date for i in world.invoices()] == [date(2026, 3, 10), date(2026, 4, 1)]
    assert world.invoices()[0].source_format == SourceFormat.CSV


def italian_file(delimiter: str = ";", **options: Any) -> bytes:
    rows = [
        ["Fornitore", "P.IVA", "Numero Fattura", "Data", "Descrizione", "Importo"],
        ["Rossi Food S.r.l.", "01234567890", "FA/1", "10/03/2026", "Forniture cucina", "1.234,56"],
        ["Rossi Food S.r.l.", "01234567890", "FA/1", "10/03/2026", "Consegna", "12,00"],
    ]
    return csv_bytes(rows, delimiter=delimiter, **options)


ITALIAN_COLUMNS: dict[str, dict[str, Any]] = {
    "supplier_name": {"column": "Fornitore"},
    "supplier_vat_number": {"column": "P.IVA"},
    "invoice_number": {"column": "Numero Fattura"},
    "invoice_date": {"column": "Data"},
    "line_description": {"column": "Descrizione"},
    "line_total": {"column": "Importo"},
}
ITALIAN_FORMAT: dict[str, Any] = {
    "date_formats": {"invoice_date": "%d/%m/%Y"},
    "decimal_separator": ",",
    "thousands_separator": ".",
}
ITALIAN_HEADERS = [c["column"] for c in ITALIAN_COLUMNS.values()]


def italian_world(db_session: Session, factory: BookingFactory) -> CostWorld:
    w = CostWorld.create(db_session, factory)
    w.confirm(ITALIAN_HEADERS, ITALIAN_COLUMNS, format_options=ITALIAN_FORMAT)
    return w


def test_an_italian_semicolon_csv_with_local_dates_and_numbers_is_imported(
    db_session: Session, factory: BookingFactory
) -> None:
    w = italian_world(db_session, factory)

    result = w.import_bytes("fatture.csv", italian_file())

    assert result.succeeded, result
    (invoice,) = w.invoices()
    assert invoice.invoice_date == date(2026, 3, 10)  # d/m/Y as configured, never guessed
    assert [line.line_total for line in lines_of(db_session, invoice)] == [D("1234.56"), D("12.00")]


@pytest.mark.parametrize(
    ("delimiter", "encoding", "bom"),
    [(";", "utf-8", False), (";", "utf-8", True), (";", "cp1252", False), ("\t", "utf-8", False)],
)
def test_encodings_bom_and_delimiters_are_read(
    db_session: Session, factory: BookingFactory, delimiter: str, encoding: str, bom: bool
) -> None:
    w = italian_world(db_session, factory)
    content = csv_bytes(
        [
            ITALIAN_HEADERS,
            ["Caffè Rossi S.r.l.", "01234567890", "7", "10/03/2026", "Caffè in grani", "10,00"],
        ],
        delimiter=delimiter,
        encoding=encoding,
        bom=bom,
    )

    result = w.import_bytes("f.csv", content)

    assert result.succeeded, result
    supplier = db_session.scalars(select(Supplier)).one()
    assert supplier.legal_name == "Caffè Rossi S.r.l."  # the accent survived every encoding


def test_cp1252_can_be_configured_explicitly(db_session: Session, factory: BookingFactory) -> None:
    w = CostWorld.create(db_session, factory)
    w.confirm(
        ITALIAN_HEADERS,
        ITALIAN_COLUMNS,
        format_options={**ITALIAN_FORMAT, "encoding": "cp1252", "delimiter": ";"},
    )
    content = italian_file(encoding="cp1252")

    assert w.import_bytes("f.csv", content).succeeded


def test_an_xlsx_with_typed_cells_is_imported(world: CostWorld) -> None:
    rows = [
        MINIMAL_HEADERS,
        ["Bar Sport S.n.c.", 1001, datetime(2026, 5, 2), "Caffè e latte", 123.45],
        ["Bar Sport S.n.c.", 1001, datetime(2026, 5, 2), "Zucchero", 6.1],
    ]
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)

    result = world.import_bytes("costi.xlsx", xlsx_bytes({"Fatture": rows}))

    assert result.succeeded and result.source_format == SourceFormat.XLSX
    (invoice,) = world.invoices()
    assert invoice.normalized_invoice_number == "1001" and invoice.invoice_date == date(2026, 5, 2)
    assert [line.line_total for line in lines_of(world.session, invoice)] == [
        D("123.45"),
        D("6.10"),
    ]
    assert invoice.source_format == SourceFormat.XLSX


def test_a_float_cell_becomes_the_exact_decimal_of_what_the_user_typed(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    rows = [
        MINIMAL_HEADERS,
        ["Bar", "1", datetime(2026, 5, 2), "Uno", 0.1],
        ["Bar", "1", datetime(2026, 5, 2), "Due", 0.2],
    ]

    world.import_bytes("c.xlsx", xlsx_bytes({"F": rows}))

    (invoice,) = world.invoices()
    assert sum((line.line_total for line in lines_of(world.session, invoice)), D(0)) == D("0.30")


def test_a_workbook_with_several_sheets_needs_the_sheet_to_be_chosen(world: CostWorld) -> None:
    rows = [MINIMAL_HEADERS, ["Bar", "1", datetime(2026, 5, 2), "Uno", 1.5]]
    content = xlsx_bytes({"Prima": rows, "Seconda": rows})
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)

    description = world.service().describe_file(world.source.id, filename="c.xlsx", content=content)
    ambiguous = world.import_bytes("c.xlsx", content)

    assert description.requires_sheet_selection
    assert description.sheet_names == ["Prima", "Seconda"]
    assert ambiguous.status == ImportJobStatus.FAILED
    assert (
        ambiguous.error_code == Code.MAPPING_REQUIRED
        and Code.MAPPING_REQUIRED.value == "INVOICE_MAPPING_REQUIRED"
    )
    assert nothing_created(world)

    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS, format_options={"sheet_name": "Seconda"})
    assert world.import_bytes("c.xlsx", content).succeeded


def test_describing_a_file_lists_its_headers_and_writes_nothing(world: CostWorld) -> None:
    description = world.service().describe_file(
        world.source.id, filename="f.csv", content=standard_csv([row()])
    )

    assert description.file_type == "csv" and description.headers == STANDARD_HEADERS
    assert world.count(ImportJob) == 1  # only the fixture's job


# --- grouping and repeated headers --------------------------------------------------------------


def test_lines_with_the_same_invoice_header_become_one_invoice(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(
                line_number=1,
                line_description="Uno",
                line_total="10.00",
                invoice_gross_amount="61.00",
            ),
            row(
                line_number=2,
                line_description="Due",
                line_total="20.00",
                invoice_gross_amount="61.00",
            ),
            row(
                line_number=3,
                line_description="Tre",
                line_total="30.00",
                invoice_gross_amount="61.00",
            ),
        ]
    )

    assert result.succeeded
    assert (result.documents_total, result.rows_total, result.invoices_created) == (1, 3, 1)
    (invoice,) = world.invoices()
    assert invoice.gross_amount == D("61.00")
    assert [line.source_line_number for line in lines_of(world.session, invoice)] == [1, 2, 3]


def test_interleaved_rows_are_grouped_by_invoice_not_by_position(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(invoice_number="A", line_description="A1"),
            row(invoice_number="B", line_description="B1"),
            row(invoice_number="A", line_description="A2"),
        ]
    )

    assert result.succeeded and result.invoices_created == 2 and result.lines_created == 3
    by_number = {i.normalized_invoice_number: i for i in world.invoices()}
    assert len(lines_of(world.session, by_number["A"])) == 2
    assert len(lines_of(world.session, by_number["B"])) == 1


def test_the_same_number_from_two_suppliers_is_two_documents(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(supplier_name="Uno", supplier_vat_number="01234567890"),
            row(supplier_name="Due", supplier_vat_number="09876543210"),
        ]
    )
    assert result.succeeded and result.invoices_created == 2 and result.suppliers_created == 2


def test_a_header_value_stated_on_one_line_only_is_enough(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(line_number=1, line_total="10.00", invoice_gross_amount="12.20"),
            row(line_number=2, line_total="20.00"),  # the total is not repeated: fine
        ]
    )
    assert result.succeeded
    assert world.invoices()[0].gross_amount == D("12.20")


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        ("invoice_gross_amount", "122.00", "123.00"),
        ("invoice_net_amount", "100.00", "101.00"),
        ("currency", "EUR", "USD"),
        ("supplier_tax_code", "RSSMRA80A01H501U", "BNCLRA85M41H501Z"),
        ("due_date", "2026-04-10", "2026-05-10"),
    ],
)
def test_a_header_field_that_disagrees_across_lines_rejects_the_document(
    world: CostWorld, field: str, first: str, second: str
) -> None:
    result = world.import_rows(
        [
            row(line_number=1, **{field: first}),
            row(line_number=2, line_description="Altra", **{field: second}),
        ]
    )  # no "last row wins"

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.VALIDATION_FAILED
    assert result.row_error_summary == {"INVOICE_INCONSISTENT_HEADER": 1}
    assert nothing_created(world)
    first_row = staged(world, result)[0]
    assert first_row.validation_errors == [{"field": field, "code": "INVOICE_INCONSISTENT_HEADER"}]


def test_two_lines_with_the_same_line_number_are_refused(world: CostWorld) -> None:
    result = world.import_rows(
        [row(line_number=1, line_description="Uno"), row(line_number=1, line_description="Due")]
    )

    assert result.status == ImportJobStatus.FAILED
    assert result.row_error_summary == {"INVOICE_DUPLICATE_LINE": 2}
    assert nothing_created(world)


def test_without_a_line_number_column_the_row_number_identifies_the_line(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    rows = [
        MINIMAL_HEADERS,
        ["Bar", "1", "2026-05-02", "Uno", "1.00"],
        ["Bar", "1", "2026-05-02", "Due", "2.00"],
    ]

    result = world.import_bytes("c.csv", csv_bytes(rows))

    assert result.succeeded
    (invoice,) = world.invoices()
    assert [line.source_line_number for line in lines_of(world.session, invoice)] == [2, 3]


# --- credit notes (D) ---------------------------------------------------------------------------


def test_a_credit_note_written_with_positive_amounts_is_stored_negative(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(
                document_type="TD04",
                invoice_net_amount="100.00",
                invoice_tax_amount="22.00",
                invoice_gross_amount="122.00",
                line_total="100.00",
            )
        ]
    )

    assert result.succeeded
    (invoice,) = world.invoices()
    assert (
        invoice.document_kind == DocumentKind.CREDIT_NOTE and invoice.document_type_code == "TD04"
    )
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (
        D("-100.00"),
        D("-22.00"),
        D("-122.00"),
    )
    assert [line.line_total for line in lines_of(world.session, invoice)] == [D("-100.00")]


def test_a_credit_note_already_written_negative_is_not_negated_twice(world: CostWorld) -> None:
    result = world.import_rows(
        [
            row(
                document_type="Nota di credito",
                invoice_net_amount="-100.00",
                invoice_tax_amount="-22.00",
                invoice_gross_amount="-122.00",
                line_total="-100.00",
            )
        ]
    )

    assert result.succeeded
    (invoice,) = world.invoices()
    assert invoice.document_kind == DocumentKind.CREDIT_NOTE
    assert invoice.gross_amount == D("-122.00")
    assert [line.line_total for line in lines_of(world.session, invoice)] == [D("-100.00")]


def test_a_positive_invoice_stays_positive(world: CostWorld) -> None:
    result = world.import_rows(
        [row(document_type="Fattura", invoice_gross_amount="122.00", line_total="100.00")]
    )

    assert result.succeeded
    (invoice,) = world.invoices()
    assert invoice.document_kind == DocumentKind.INVOICE and invoice.gross_amount == D("122.00")
    assert [line.line_total for line in lines_of(world.session, invoice)] == [D("100.00")]


def test_an_unknown_document_type_is_a_row_error(world: CostWorld) -> None:
    result = world.import_rows([row(document_type="Preventivo")])
    assert result.row_error_summary == {"INVOICE_UNKNOWN_DOCUMENT_TYPE": 1}
    assert nothing_created(world)


def test_a_constant_document_type_makes_every_document_a_credit_note(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)
    columns = {**MINIMAL_COLUMNS, "document_type": {"constant": "TD04"}}
    w.confirm(MINIMAL_HEADERS, columns)

    result = w.import_bytes(
        "c.csv", csv_bytes([MINIMAL_HEADERS, ["Bar", "1", "2026-05-02", "Storno", "10.00"]])
    )

    assert result.succeeded
    assert w.invoices()[0].document_kind == DocumentKind.CREDIT_NOTE


# --- categories (F) -----------------------------------------------------------------------------


def test_an_explicit_source_category_is_mapped_and_kept_with_full_confidence(
    world: CostWorld,
) -> None:
    world.confirm(category_mapping={"Biancheria": "LAUNDRY", "Cibo e bevande": "FOOD"})

    result = world.import_rows(
        [
            row(line_number=1, line_description="Cose", cost_category="Biancheria"),
            row(line_number=2, line_description="Altre cose", cost_category="cibo e bevande"),
            row(line_number=3, line_description="Ancora", cost_category="SOFTWARE"),
        ]
    )

    assert result.succeeded
    lines = lines_of(world.session, world.invoices()[0])
    assert [line.cost_category for line in lines] == [
        CostCategory.LAUNDRY,
        CostCategory.FOOD,
        CostCategory.SOFTWARE,  # a canonical category name needs no mapping
    ]
    assert {line.classification_method for line in lines} == {ClassificationMethod.EXPLICIT_SOURCE}
    assert {line.classification_confidence for line in lines} == {D("100.00")}


def test_an_unknown_category_label_is_refused_not_guessed(world: CostWorld) -> None:
    result = world.import_rows([row(cost_category="Roba varia")])

    assert result.status == ImportJobStatus.FAILED
    assert result.row_error_summary == {"INVOICE_UNKNOWN_CATEGORY": 1}
    (only_row,) = staged(world, result)
    assert only_row.validation_errors == [
        {"field": "cost_category", "code": "INVOICE_UNKNOWN_CATEGORY", "value": "Roba varia"}
    ]
    assert nothing_created(world)


def test_an_explicit_category_wins_over_the_supplier_default_and_the_rules(
    world: CostWorld,
) -> None:
    world.import_rows([row(invoice_number="0")])
    supplier = world.session.scalars(select(Supplier)).one()
    supplier.default_cost_category = CostCategory.MAINTENANCE
    world.session.flush()

    world.import_rows([row(line_description="Servizio lavanderia", cost_category="MARKETING")])

    invoice = next(i for i in world.invoices() if i.normalized_invoice_number == "1")
    (line,) = lines_of(world.session, invoice)
    assert line.cost_category == CostCategory.MARKETING
    assert line.classification_method == ClassificationMethod.EXPLICIT_SOURCE


def test_a_constant_category_classifies_every_line_explicitly(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)
    w.confirm(MINIMAL_HEADERS, {**MINIMAL_COLUMNS, "cost_category": {"constant": "SOFTWARE"}})

    result = w.import_bytes(
        "c.csv", csv_bytes([MINIMAL_HEADERS, ["Saas", "1", "2026-05-02", "Abbonamento", "10.00"]])
    )

    assert result.succeeded
    (line,) = lines_of(db_session, w.invoices()[0])
    assert (line.cost_category, line.classification_method) == (
        CostCategory.SOFTWARE,
        ClassificationMethod.EXPLICIT_SOURCE,
    )


# --- mapping memory -----------------------------------------------------------------------------


def test_an_import_without_a_confirmed_mapping_asks_for_one(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)

    result = w.import_rows([row()])

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.MAPPING_REQUIRED
    assert result.details == {"reason": "no_confirmed_mapping"}
    assert nothing_created(w)


def test_a_required_field_that_is_not_mapped_is_an_invalid_mapping(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)
    columns = {k: v for k, v in MINIMAL_COLUMNS.items() if k != "invoice_date"}

    with pytest.raises(InvoiceImportError) as error:
        w.confirm(MINIMAL_HEADERS, columns)

    assert error.value.error_code == Code.INVALID_MAPPING
    assert w.count(InvoiceMappingProfile) == 0


@pytest.mark.parametrize(
    "field", ["invoice_number", "invoice_date", "supplier_name", "line_description", "line_total"]
)
def test_only_currency_document_type_and_category_may_be_constants(
    db_session: Session, factory: BookingFactory, field: str
) -> None:
    w = CostWorld.create(db_session, factory)
    columns = {**MINIMAL_COLUMNS, field: {"constant": "X"}}

    with pytest.raises(InvoiceImportError) as error:
        w.confirm(MINIMAL_HEADERS, columns)

    assert error.value.error_code == Code.INVALID_MAPPING
    assert "cannot be a constant" in repr(error.value.details)


def test_a_mapping_that_names_a_column_the_file_lacks_is_refused(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)

    with pytest.raises(InvoiceImportError) as error:
        w.confirm(["Supplier"], MINIMAL_COLUMNS)

    assert error.value.error_code == Code.INVALID_MAPPING
    assert (
        error.value.details is not None and "Invoice No" in error.value.details["unknown_columns"]
    )


def test_a_data_source_has_one_mapping_profile_and_saving_again_replaces_it(
    world: CostWorld,
) -> None:
    assert world.count(InvoiceMappingProfile) == 1

    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)

    assert world.count(InvoiceMappingProfile) == 1
    profile = world.session.scalars(select(InvoiceMappingProfile)).one()
    assert set(profile.column_mapping) == set(MINIMAL_COLUMNS)
    assert (
        profile.header_signature
        == hashlib.sha256(
            "\n".join(sorted(h.lower() for h in MINIMAL_HEADERS)).encode()
        ).hexdigest()
        or len(profile.header_signature) == 64
    )


def test_the_mapping_is_per_data_source(world: CostWorld, factory: BookingFactory) -> None:
    other = factory.data_source(world.tenant.property, DataSourceDomain.COSTS)

    result = world.service().import_file(other.id, filename="f.csv", content=standard_csv([row()]))

    assert result.error_code == Code.MAPPING_REQUIRED  # the other source has no confirmed mapping


def test_the_mapping_of_a_bookings_source_cannot_be_saved(
    world: CostWorld, factory: BookingFactory
) -> None:
    bookings = factory.data_source(world.tenant.property, DataSourceDomain.BOOKINGS)
    with pytest.raises(InvoiceImportError) as error:
        world.service().save_mapping(
            bookings.id, headers=MINIMAL_HEADERS, column_mapping=MINIMAL_COLUMNS
        )
    assert error.value.error_code == Code.INVALID_DATA_SOURCE


def test_extra_columns_in_a_later_file_are_harmless(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    headers = [*MINIMAL_HEADERS, "Note interne", "Nuova colonna"]
    content = csv_bytes([headers, ["Bar", "1", "2026-05-02", "Uno", "1.00", "x", "y"]])

    assert world.import_bytes("c.csv", content).succeeded


def test_a_column_that_disappeared_is_a_changed_schema(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    headers = ["Supplier", "Invoice No", "Invoice Date", "Description"]  # "Line Total" is gone
    content = csv_bytes([headers, ["Bar", "1", "2026-05-02", "Uno"]])

    result = world.import_bytes("c.csv", content)

    assert result.status == ImportJobStatus.FAILED
    assert (
        result.error_code == Code.SOURCE_SCHEMA_CHANGED
        and Code.SOURCE_SCHEMA_CHANGED.value == "INVOICE_SOURCE_SCHEMA_CHANGED"
    )
    assert result.details == {"reason": "mapped_columns_missing", "missing_columns": ["Line Total"]}
    assert nothing_created(world)


def test_a_renamed_column_is_a_changed_schema(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    headers = ["Supplier", "Invoice No", "Invoice Date", "Description", "Amount"]
    content = csv_bytes([headers, ["Bar", "1", "2026-05-02", "Uno", "1.00"]])

    assert world.import_bytes("c.csv", content).error_code == Code.SOURCE_SCHEMA_CHANGED


def test_duplicate_headers_are_rejected(world: CostWorld) -> None:
    world.confirm(MINIMAL_HEADERS, MINIMAL_COLUMNS)
    headers = [*MINIMAL_HEADERS, "Line Total"]
    content = csv_bytes([headers, ["Bar", "1", "2026-05-02", "Uno", "1.00", "9.00"]])

    result = world.import_bytes("c.csv", content)

    assert (
        result.error_code == Code.DUPLICATE_HEADER
        and Code.DUPLICATE_HEADER.value == "INVOICE_DUPLICATE_HEADER"
    )
    assert nothing_created(world)


def test_the_mapping_is_a_separate_thing_from_the_booking_mapping() -> None:
    from app.modules.bookings.models import BookingMappingProfile

    assert InvoiceMappingProfile.__tablename__ != BookingMappingProfile.__tablename__
    assert "channel_mapping" not in {c.name for c in InvoiceMappingProfile.__table__.columns}
    assert "category_mapping" in {c.name for c in InvoiceMappingProfile.__table__.columns}


# --- formats that need to be stated -------------------------------------------------------------


def test_a_slashed_date_without_a_stated_format_is_ambiguous(world: CostWorld) -> None:
    result = world.import_rows([row(invoice_date="01/02/2026")])

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.AMBIGUOUS_DATE_FORMAT
    assert result.details == {"fields": ["invoice_date"]}
    assert nothing_created(world)


def test_an_amount_with_a_comma_and_no_stated_separators_is_ambiguous(world: CostWorld) -> None:
    result = world.import_rows([row(line_total="1,234")])

    assert result.error_code == Code.AMBIGUOUS_NUMBER_FORMAT
    assert result.details == {"fields": ["line_total"]}


def test_stated_formats_read_the_same_text_the_stated_way(
    db_session: Session, factory: BookingFactory
) -> None:
    w = CostWorld.create(db_session, factory)
    w.confirm(
        MINIMAL_HEADERS,
        MINIMAL_COLUMNS,
        format_options={"date_formats": {"invoice_date": "%m/%d/%Y"}, "decimal_separator": "."},
    )
    content = csv_bytes([MINIMAL_HEADERS, ["Bar", "1", "01/02/2026", "Uno", "1,234.50"]])

    # a thousands separator is not stated: 1,234.50 is not a valid number in this profile
    assert w.import_bytes("c.csv", content).row_error_summary == {"INVOICE_INVALID_NUMBER": 1}
    w.confirm(
        MINIMAL_HEADERS,
        MINIMAL_COLUMNS,
        format_options={
            "date_formats": {"invoice_date": "%m/%d/%Y"},
            "decimal_separator": ".",
            "thousands_separator": ",",
        },
    )
    assert w.import_bytes("c.csv", content).succeeded
    assert w.invoices()[0].invoice_date == date(2026, 1, 2)  # month first, as stated


# --- row validation (atomic: one bad row rejects the file) ---------------------------------------


def test_row_level_problems_are_reported_by_field_and_code_and_nothing_is_imported(
    world: CostWorld,
) -> None:
    result = world.import_rows(
        [
            row(invoice_number="1"),
            row(invoice_number="2", supplier_name=None),
            row(invoice_number="3", invoice_date="not a date"),
            row(invoice_number="4", line_total="abc"),
            row(invoice_number="5", supplier_vat_number="12"),
            row(invoice_number="6", line_description=None),
            row(invoice_number="7", currency="EURO"),
            row(invoice_number="8", vat_rate="150"),
        ]
    )

    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.VALIDATION_FAILED
    assert (result.rows_total, result.rows_valid, result.rows_invalid) == (8, 1, 7)
    assert result.row_error_summary == {
        "INVOICE_INVALID_CURRENCY": 1,
        "INVOICE_INVALID_DATE": 1,
        "INVOICE_INVALID_NUMBER": 1,
        "INVOICE_INVALID_VAT_NUMBER": 1,
        "INVOICE_OUT_OF_RANGE": 1,
        "INVOICE_REQUIRED_VALUE_MISSING": 2,
    }
    assert nothing_created(world)
    assert [r.validation_status for r in staged(world, result)][0] == ImportRowStatus.VALID
    assert job_of(world.session, result).status == ImportJobStatus.FAILED


def test_an_amount_with_more_than_eight_decimals_is_refused_not_rounded(world: CostWorld) -> None:
    result = world.import_rows([row(line_total="1.123456789")])
    assert result.row_error_summary == {"INVOICE_AMOUNT_PRECISION": 1}


def test_a_file_with_only_a_header_is_refused_without_creating_anything(world: CostWorld) -> None:
    result = world.import_bytes("c.csv", csv_bytes([STANDARD_HEADERS]))
    assert result.status == ImportJobStatus.FAILED
    assert result.error_code == Code.EMPTY_FILE and nothing_created(world)


def test_a_workbook_disguised_as_csv_is_refused(world: CostWorld) -> None:
    content = xlsx_bytes({"F": [MINIMAL_HEADERS]})
    assert world.import_bytes("c.csv", content).status == ImportJobStatus.FAILED


# --- the two source formats state the same invoice ----------------------------------------------


def test_the_same_invoice_from_xml_and_from_csv_is_one_invoice(world: CostWorld) -> None:
    xml = fattura_xml(
        [
            Body(
                number="FA/1",
                date="2026-03-10",
                lines=[Line(1, "Servizio di lavanderia", "100.00", vat="22.00")],
                summaries=[("22.00", "100.00", "22.00")],
            )
        ]
    )
    first = world.import_xml(xml)
    csv_content = standard_csv(
        [
            row(
                supplier_name="Fornitore Fittizio S.r.l.",
                supplier_vat_number="IT01234567890",
                invoice_number="fa/1",
                invoice_date="2026-03-10",
                line_number=1,
                line_description="Servizio di lavanderia",
                line_total="100.00",
                vat_rate="22",
                invoice_net_amount="100.00",
                invoice_tax_amount="22.00",
            )
        ]
    )

    second = world.import_bytes("stesso.csv", csv_content)

    assert first.succeeded and second.succeeded, second
    assert (second.invoices_created, second.invoices_unchanged) == (0, 1)  # same fingerprint
    assert world.count(Invoice) == 1
    assert world.invoices()[0].source_format == SourceFormat.FATTURAPA_XML  # the first stays


def test_a_csv_that_states_a_different_amount_for_a_known_invoice_conflicts(
    world: CostWorld,
) -> None:
    world.import_rows([row(line_total="100.00")])

    result = world.import_bytes("b.csv", standard_csv([row(line_total="101.00")]))

    assert result.error_code == Code.DOCUMENT_CONFLICT
    assert world.count(Invoice) == 1


def test_a_structured_import_is_idempotent(world: CostWorld) -> None:
    content = standard_csv([row(), row(invoice_number="2")])
    world.import_bytes("c.csv", content)

    again = world.import_bytes("c.csv", content)

    assert again.succeeded and (again.invoices_created, again.invoices_unchanged) == (0, 2)
    assert world.count(Invoice) == 2 and world.count(Supplier) == 1


# --- data minimisation (I) ----------------------------------------------------------------------

PII_ROW = {
    "Email": "amministrazione@fornitore-fittizio.example",
    "Telefono": "+39 000 5550199",
    "Indirizzo": "Via Inventata 99, Perugia",
    "Cliente": "Masseria Cliente Fittizia",
    "Note": "pagamento urgente cliente vip",
}


def pii_file() -> tuple[list[str], bytes]:
    headers = [*MINIMAL_HEADERS, *PII_ROW]
    body = ["Bar Sport", "1", "2026-05-02", "Caffè", "10.00", *PII_ROW.values()]
    return headers, csv_bytes([headers, body])


def test_unmapped_pii_columns_are_never_persisted_or_logged(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    headers, content = pii_file()
    world.confirm(headers, MINIMAL_COLUMNS)

    result = world.import_bytes("c.csv", content)

    assert result.succeeded
    assert persisted_hits(world.session, list(PII_ROW.values())) == []
    assert not [value for value in PII_ROW.values() if value in caplog.text]
    for stored in staged(world, result):
        assert set(stored.mapped_payload) <= set(STANDARD_COLUMNS) | {"supplier_iban_sha256"}


def test_control_a_column_that_is_explicitly_mapped_is_stored(world: CostWorld) -> None:
    """Proves the leak detector works: data IS persisted exactly where the customer mapped it."""
    headers, content = pii_file()
    world.confirm(headers, {**MINIMAL_COLUMNS, "unit": {"column": "Telefono"}})

    assert world.import_bytes("c.csv", content).succeeded

    assert ("invoice_lines", "+39 000 5550199") in persisted_hits(
        world.session, ["+39 000 5550199"]
    )
    assert persisted_hits(world.session, ["fornitore-fittizio.example", "Via Inventata"]) == []


def test_pii_columns_do_not_leak_through_failures_either(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    headers = [*MINIMAL_HEADERS, *PII_ROW]
    bad = ["Bar Sport", "1", "not a date", "Caffè", "10.00", *PII_ROW.values()]
    world.confirm(headers, MINIMAL_COLUMNS)

    result = world.import_bytes("c.csv", csv_bytes([headers, bad]))

    assert result.status == ImportJobStatus.FAILED
    surfaces = [repr(result), caplog.text, str(job_of(world.session, result).error_message)]
    surfaces += [str(r.validation_errors) + str(r.mapped_payload) for r in staged(world, result)]
    joined = "\n".join(surfaces)
    assert not [value for value in PII_ROW.values() if value in joined]
    assert persisted_hits(world.session, list(PII_ROW.values())) == []


def test_a_raw_iban_column_is_hashed_and_the_raw_value_persisted_nowhere(
    world: CostWorld, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    digest = hashlib.sha256(IBAN_A.encode()).hexdigest()

    result = world.import_rows([row(supplier_iban="it60 x054 2811 1010 0000 0123 456")])

    assert result.succeeded
    stored = world.session.scalars(
        select(SupplierIdentifier).where(SupplierIdentifier.kind == IdentifierKind.IBAN_SHA256)
    ).all()
    assert [i.normalized_value for i in stored] == [digest]
    assert persisted_hits(world.session, [IBAN_A, "0542811101", "X054"]) == []  # no raw form
    assert persisted_hits(world.session, [digest]) != []  # the hash IS where it belongs
    assert IBAN_A not in caplog.text and IBAN_A not in repr(result)
    assert [r.mapped_payload.get("supplier_iban_sha256") for r in staged(world, result)] == [digest]


def test_an_invalid_iban_is_ignored_with_a_warning_and_not_echoed(world: CostWorld) -> None:
    bad = "IT00X0542811101000000123456"

    result = world.import_rows([row(supplier_iban=bad)])

    assert result.succeeded and result.warning_summary == {"INVALID_IBAN_IGNORED": 1}
    assert persisted_hits(world.session, [bad]) == []
    assert (
        world.session.scalars(
            select(SupplierIdentifier).where(SupplierIdentifier.kind == IdentifierKind.IBAN_SHA256)
        ).all()
        == []
    )


def test_the_iban_of_an_xml_payment_block_is_hashed_the_same_way(world: CostWorld) -> None:
    digest = hashlib.sha256(IBAN_A.encode()).hexdigest()

    result = world.import_xml(fattura_xml([Body(payments=[Payment(iban=IBAN_A)])]))

    assert result.succeeded
    assert persisted_hits(world.session, [IBAN_A]) == []
    assert persisted_hits(world.session, [digest]) != []
