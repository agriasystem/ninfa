"""Invoice, supplier and staging invariants enforced by PostgreSQL (Gate 6 groups C, M, N).

Rows are written with bare ORM objects and Core statements and no application safeguard: the
database must refuse what is wrong, whatever the code above it does.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportFile, ImportJob
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.models import (
    DocumentKind,
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    InvoiceMappingProfile,
    ResolutionMethod,
    SourceFormat,
)
from app.modules.properties.models import Property
from app.modules.suppliers.models import (
    IdentifierKind,
    ReviewReason,
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from app.modules.tenancy.models import Workspace
from tests.support import BookingFactory, Rejects

FP = "a" * 64
SIG = "b" * 64


@dataclass
class Costs:
    """A tenant with everything an invoice hangs on."""

    workspace: Workspace
    property: Property
    source: DataSource
    job: ImportJob
    file: ImportFile
    supplier: Supplier


def costs(factory: BookingFactory) -> Costs:
    workspace = factory.workspace()
    prop = factory.property(workspace)
    source = factory.data_source(prop, DataSourceDomain.COSTS)
    job = factory.import_job(source)
    file = factory.import_file(job)
    supplier = supplier_of(factory, workspace)
    return Costs(workspace, prop, source, job, file, supplier)


def supplier_of(factory: BookingFactory, workspace: Workspace, name: str = "Fornitore") -> Supplier:
    supplier = Supplier(workspace_id=workspace.id, legal_name=name, normalized_name=name.lower())
    factory.session.add(supplier)
    factory.session.flush()
    return supplier


def invoice_values(c: Costs, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": c.workspace.id,
        "property_id": c.property.id,
        "data_source_id": c.source.id,
        "supplier_id": c.supplier.id,
        "invoice_number": "FA/1",
        "normalized_invoice_number": "FA/1",
        "invoice_date": date(2026, 3, 10),
        "due_date": None,
        "document_type_code": "TD01",
        "document_kind": DocumentKind.INVOICE,
        "currency": "EUR",
        "net_amount": Decimal("100.00"),
        "tax_amount": Decimal("22.00"),
        "gross_amount": Decimal("122.00"),
        "source_format": SourceFormat.FATTURAPA_XML,
        "source_import_job_id": c.job.id,
        "source_import_file_id": c.file.id,
        "source_fingerprint": FP,
        "supplier_resolution_method": ResolutionMethod.CREATED_NEW,
    }
    values.update(overrides)
    return values


def make_invoice(session: Session, c: Costs, **overrides: Any) -> Invoice:
    invoice = Invoice(**invoice_values(c, **overrides))
    session.add(invoice)
    session.flush()
    return invoice


def line_values(invoice: Invoice, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": invoice.workspace_id,
        "invoice_id": invoice.id,
        "source_line_number": 1,
        "description_raw": "Servizio",
        "description_normalized": "servizio",
        "quantity": None,
        "unit": None,
        "unit_price": None,
        "line_total": Decimal("100.00"),
        "vat_rate": Decimal("22.00"),
        "cost_category": CostCategory.OTHER,
        "classification_confidence": Decimal("0.00"),
        "classification_method": ClassificationMethod.UNCLASSIFIED,
    }
    values.update(overrides)
    return values


def make_line(session: Session, invoice: Invoice, **overrides: Any) -> InvoiceLine:
    line = InvoiceLine(**line_values(invoice, **overrides))
    session.add(line)
    session.flush()
    return line


@pytest.fixture
def a(factory: BookingFactory) -> Costs:
    return costs(factory)


@pytest.fixture
def b(factory: BookingFactory) -> Costs:
    return costs(factory)


# --- C. invoice identity ------------------------------------------------------------------------


def test_a_valid_invoice_and_line_are_accepted(db_session: Session, a: Costs) -> None:
    invoice = make_invoice(db_session, a)
    line = make_line(db_session, invoice)
    assert invoice.created_at is not None and line.created_at is not None


def test_the_identity_has_no_data_source_in_it(db_session: Session) -> None:
    columns = db_session.execute(
        text(
            "SELECT a.attname FROM pg_constraint c JOIN pg_attribute a"
            " ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)"
            " WHERE c.conname = 'uq_invoices_identity' ORDER BY a.attname"
        )
    ).scalars()
    assert sorted(columns) == [
        "document_kind",
        "invoice_date",
        "normalized_invoice_number",
        "property_id",
        "supplier_id",
        "workspace_id",
    ]


def test_the_same_identity_from_another_data_source_is_refused_by_the_database(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs
) -> None:
    make_invoice(db_session, a)
    other = factory.data_source(a.property, DataSourceDomain.COSTS)
    job = factory.import_job(other)
    file = factory.import_file(job)

    with rejects(pg.UniqueViolation, "uq_invoices_identity"):
        db_session.add(
            Invoice(
                **invoice_values(
                    a,
                    data_source_id=other.id,
                    source_import_job_id=job.id,
                    source_import_file_id=file.id,
                )
            )
        )


@pytest.mark.parametrize(
    "change",
    [
        {"normalized_invoice_number": "FA/2"},
        {"invoice_date": date(2026, 3, 11)},
        {
            "document_kind": DocumentKind.CREDIT_NOTE,
            "net_amount": None,
            "tax_amount": None,
            "gross_amount": None,
        },
    ],
)
def test_a_different_number_date_or_kind_is_a_different_invoice(
    db_session: Session, a: Costs, change: dict[str, Any]
) -> None:
    make_invoice(db_session, a)
    make_invoice(db_session, a, **change)


def test_the_same_number_of_another_supplier_is_a_different_invoice(
    db_session: Session, factory: BookingFactory, a: Costs
) -> None:
    make_invoice(db_session, a)
    other = supplier_of(factory, a.workspace, "Altro")
    make_invoice(db_session, a, supplier_id=other.id)


def test_the_same_supplier_can_have_invoices_for_two_properties_of_the_workspace(
    db_session: Session, factory: BookingFactory, a: Costs
) -> None:
    second_property = factory.property(a.workspace)
    source = factory.data_source(second_property, DataSourceDomain.COSTS)
    job = factory.import_job(source)
    file = factory.import_file(job)

    first = make_invoice(db_session, a)
    second = make_invoice(
        db_session,
        a,
        property_id=second_property.id,
        data_source_id=source.id,
        source_import_job_id=job.id,
        source_import_file_id=file.id,
    )

    assert first.supplier_id == second.supplier_id
    assert first.property_id != second.property_id  # the supplier is workspace-wide


def test_a_supplier_has_no_property_but_an_invoice_has_exactly_one() -> None:
    assert "property_id" not in Supplier.__table__.columns
    assert Invoice.__table__.columns["property_id"].nullable is False


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("invoice_number", " ", "ck_invoices_invoice_number_not_blank"),
        ("normalized_invoice_number", "", "ck_invoices_normalized_invoice_number_not_blank"),
        ("currency", "eur", "ck_invoices_currency_format"),
        ("source_fingerprint", "xyz", "ck_invoices_source_fingerprint_format"),
        ("document_type_code", " ", "ck_invoices_document_type_code_not_blank"),
    ],
)
def test_invoice_values_are_checked_by_the_database(
    db_session: Session, rejects: Rejects, a: Costs, column: str, value: Any, constraint: str
) -> None:
    with rejects(pg.CheckViolation, constraint):
        db_session.add(Invoice(**invoice_values(a, **{column: value})))


@pytest.mark.parametrize(
    ("column", "value"),
    [("document_kind", "MEMO"), ("source_format", "PDF"), ("supplier_resolution_method", "GUESS")],
)
def test_closed_sets_are_stored_as_text_with_a_check(
    db_session: Session, rejects: Rejects, a: Costs, column: str, value: str
) -> None:
    values = invoice_values(a)
    values[column] = "X"
    with rejects(pg.CheckViolation):
        db_session.execute(
            text(
                "INSERT INTO invoices (id, workspace_id, property_id, data_source_id, supplier_id,"
                " invoice_number, normalized_invoice_number, invoice_date, document_kind, currency,"
                " source_format, source_import_job_id, source_import_file_id, source_fingerprint,"
                " supplier_resolution_method) VALUES (gen_random_uuid(), :w, :p, :d, :s, 'N', 'N',"
                " '2026-01-01', :kind, 'EUR', :fmt, :j, :f, :fp, :res)"
            ),
            {
                "w": a.workspace.id,
                "p": a.property.id,
                "d": a.source.id,
                "s": a.supplier.id,
                "j": a.job.id,
                "f": a.file.id,
                "fp": FP,
                "kind": value if column == "document_kind" else "INVOICE",
                "fmt": value if column == "source_format" else "CSV",
                "res": value if column == "supplier_resolution_method" else "CREATED_NEW",
            },
        )


def test_a_credit_note_cannot_carry_positive_header_amounts(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    for amounts in (
        {"net_amount": Decimal("1.00")},
        {"tax_amount": Decimal("1.00")},
        {"gross_amount": Decimal("1.00")},
    ):
        values = invoice_values(
            a,
            document_kind=DocumentKind.CREDIT_NOTE,
            net_amount=None,
            tax_amount=None,
            gross_amount=None,
        )
        values.update(amounts)
        with rejects(pg.CheckViolation, "ck_invoices_credit_note_amounts_not_positive"):
            db_session.add(Invoice(**values))
    make_invoice(  # negative or absent amounts are fine
        db_session,
        a,
        document_kind=DocumentKind.CREDIT_NOTE,
        net_amount=Decimal("-100.00"),
        tax_amount=Decimal("-22.00"),
        gross_amount=None,
    )


def test_money_is_exact_decimal_numeric_never_float(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name || '.' || column_name, data_type || COALESCE('(' ||"
            " numeric_precision || ',' || numeric_scale || ')', '')"
            " FROM information_schema.columns WHERE table_name IN ('invoices', 'invoice_lines')"
            " AND column_name IN ('net_amount', 'tax_amount', 'gross_amount', 'line_total',"
            " 'quantity', 'unit_price', 'vat_rate', 'classification_confidence')"
        )
    ).all()
    types: dict[str, str] = {str(row[0]): str(row[1]) for row in rows}
    assert set(types.values()) == {
        "numeric(14,2)",
        "numeric(18,8)",
        "numeric(6,2)",
        "numeric(5,2)",
    }
    assert not [t for t in types.values() if "double" in t or "real" in t]


def test_lines_are_checked_by_the_database(db_session: Session, rejects: Rejects, a: Costs) -> None:
    invoice = make_invoice(db_session, a)
    make_line(db_session, invoice)

    with rejects(pg.UniqueViolation):
        db_session.add(InvoiceLine(**line_values(invoice)))  # the same line number twice
    for column, value, constraint in (
        ("source_line_number", 0, "ck_invoice_lines_source_line_number_positive"),
        ("description_raw", " ", "ck_invoice_lines_description_raw_not_blank"),
        ("vat_rate", Decimal("101"), "ck_invoice_lines_vat_rate_range"),
        (
            "classification_confidence",
            Decimal("100.01"),
            "ck_invoice_lines_classification_confidence_range",
        ),
    ):
        with rejects(pg.CheckViolation, constraint):
            db_session.add(
                InvoiceLine(**line_values(invoice, **{"source_line_number": 9, column: value}))
            )


def test_a_classification_is_consistent_with_its_confidence(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    invoice = make_invoice(db_session, a)

    # UNCLASSIFIED means confidence 0 and OTHER, and nothing else does
    cases: tuple[dict[str, Any], ...] = (
        {"classification_confidence": Decimal("50.00")},
        {"cost_category": CostCategory.FOOD},
        {
            "classification_method": ClassificationMethod.DETERMINISTIC_RULE,
            "classification_confidence": Decimal("0.00"),
            "cost_category": CostCategory.FOOD,
        },
    )
    for number, changes in enumerate(cases, start=2):
        with rejects(pg.CheckViolation, "ck_invoice_lines_classification_consistent"):
            db_session.add(
                InvoiceLine(**line_values(invoice, **{"source_line_number": number, **changes}))
            )
    make_line(
        db_session,
        invoice,
        source_line_number=10,
        classification_method=ClassificationMethod.DETERMINISTIC_RULE,
        classification_confidence=Decimal("80.00"),
        cost_category=CostCategory.FOOD,
    )


def test_categories_and_methods_are_closed_sets_stored_as_text(db_session: Session) -> None:
    checks = set(
        db_session.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid IN ('invoice_lines'::regclass,"
                " 'suppliers'::regclass) AND contype = 'c'"
            )
        ).scalars()
    )
    assert {
        "ck_invoice_lines_cost_category_valid",
        "ck_invoice_lines_classification_method_valid",
        "ck_suppliers_default_cost_category_valid",
    } <= checks
    enums = db_session.scalar(
        text("SELECT count(*) FROM pg_type WHERE typtype = 'e' AND typname LIKE '%cost%'")
    )
    assert enums == 0  # VARCHAR + CHECK, not a PostgreSQL ENUM


# --- M. tenant integrity: raw rows crossing tenants are refused ---------------------------------


def test_an_identifier_cannot_point_at_a_supplier_of_another_workspace(
    db_session: Session, rejects: Rejects, a: Costs, b: Costs
) -> None:
    with rejects(pg.ForeignKeyViolation, "fk_supplier_identifiers_workspace_id_suppliers"):
        db_session.add(
            SupplierIdentifier(
                workspace_id=a.workspace.id,
                supplier_id=b.supplier.id,
                kind=IdentifierKind.VAT_NUMBER,
                normalized_value="IT01234567890",
            )
        )


def test_an_alias_cannot_point_at_a_supplier_or_a_data_source_of_another_workspace(
    db_session: Session, rejects: Rejects, a: Costs, b: Costs
) -> None:
    with rejects(pg.ForeignKeyViolation, "fk_supplier_aliases_workspace_id_suppliers"):
        db_session.add(
            SupplierAlias(
                workspace_id=a.workspace.id, supplier_id=b.supplier.id, normalized_name="x"
            )
        )
    with rejects(pg.ForeignKeyViolation, "fk_supplier_aliases_workspace_id_data_sources"):
        db_session.add(
            SupplierAlias(
                workspace_id=a.workspace.id,
                supplier_id=a.supplier.id,
                normalized_name="x",
                data_source_id=b.source.id,
            )
        )


def test_a_review_cannot_cross_workspaces(
    db_session: Session, rejects: Rejects, a: Costs, b: Costs
) -> None:
    def review(provisional: Supplier, candidate: Supplier) -> SupplierResolutionReview:
        return SupplierResolutionReview(
            workspace_id=a.workspace.id,
            provisional_supplier_id=provisional.id,
            candidate_supplier_id=candidate.id,
            reason=ReviewReason.FUZZY_NAME_SIMILARITY,
            similarity_score=Decimal("0.9000"),
        )

    other = supplier_of(BookingFactory(db_session), a.workspace, "Altro")
    with rejects(pg.ForeignKeyViolation, "fk_supplier_reviews_workspace_id_provisional_supplier"):
        db_session.add(review(b.supplier, other))
    with rejects(pg.ForeignKeyViolation, "fk_supplier_reviews_workspace_id_candidate_supplier"):
        db_session.add(review(other, b.supplier))


@pytest.mark.parametrize(
    ("override", "constraint"),
    [
        ("property", "fk_invoices_workspace_id_properties"),
        ("data_source", "fk_invoices_workspace_id_data_sources"),
        ("supplier", "fk_invoices_workspace_id_suppliers"),
        ("import_job", "fk_invoices_source_import_job"),
        ("import_file", "fk_invoices_source_import_file"),
    ],
)
def test_an_invoice_cannot_reference_another_workspaces_parents(
    db_session: Session, rejects: Rejects, a: Costs, b: Costs, override: str, constraint: str
) -> None:
    foreign = {
        "property": {"property_id": b.property.id},
        "data_source": {"data_source_id": b.source.id},
        "supplier": {"supplier_id": b.supplier.id},
        "import_job": {"source_import_job_id": b.job.id},
        "import_file": {"source_import_file_id": b.file.id},
    }[override]
    allowed = (
        (constraint, "fk_invoices_workspace_id_data_sources")
        if override == "property"
        else constraint
    )
    with rejects(pg.ForeignKeyViolation, allowed):
        db_session.add(Invoice(**invoice_values(a, **foreign)))


def test_an_invoice_data_source_must_belong_to_the_invoices_property(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs
) -> None:
    other_property = factory.property(a.workspace)
    elsewhere = factory.data_source(other_property, DataSourceDomain.COSTS)

    with rejects(pg.ForeignKeyViolation, "fk_invoices_workspace_id_data_sources"):
        db_session.add(Invoice(**invoice_values(a, data_source_id=elsewhere.id)))


def test_an_invoice_import_job_must_belong_to_the_invoices_data_source(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs
) -> None:
    other_source = factory.data_source(a.property, DataSourceDomain.COSTS)
    other_job = factory.import_job(other_source)
    other_file = factory.import_file(other_job)

    with rejects(pg.ForeignKeyViolation, "fk_invoices_source_import_job"):
        db_session.add(
            Invoice(
                **invoice_values(
                    a, source_import_job_id=other_job.id, source_import_file_id=other_file.id
                )
            )
        )


def test_an_invoice_file_must_belong_to_the_invoices_job(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs
) -> None:
    other_job = factory.import_job(a.source)
    other_file = factory.import_file(other_job)  # same data source, another job

    with rejects(pg.ForeignKeyViolation, "fk_invoices_source_import_file"):
        db_session.add(Invoice(**invoice_values(a, source_import_file_id=other_file.id)))


def test_a_line_cannot_reference_an_invoice_of_another_workspace(
    db_session: Session, rejects: Rejects, a: Costs, b: Costs
) -> None:
    foreign_invoice = make_invoice(db_session, b)

    with rejects(pg.ForeignKeyViolation, "fk_invoice_lines_workspace_id_invoices"):
        db_session.add(InvoiceLine(**line_values(foreign_invoice, workspace_id=a.workspace.id)))


def test_a_mapping_profile_must_match_its_property_and_data_source(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs, b: Costs
) -> None:
    def profile(**overrides: Any) -> InvoiceMappingProfile:
        values: dict[str, Any] = {
            "workspace_id": a.workspace.id,
            "property_id": a.property.id,
            "data_source_id": a.source.id,
            "column_mapping": {},
            "header_signature": SIG,
        }
        values.update(overrides)
        return InvoiceMappingProfile(**values)

    other_property = factory.property(a.workspace)
    with rejects(pg.ForeignKeyViolation, "fk_invoice_mapping_profiles_workspace_id_data_sources"):
        db_session.add(profile(data_source_id=b.source.id))
    with rejects(pg.ForeignKeyViolation, "fk_invoice_mapping_profiles_workspace_id_data_sources"):
        db_session.add(profile(property_id=other_property.id))
    db_session.add(profile())
    db_session.flush()
    with rejects(pg.UniqueViolation, "uq_invoice_mapping_profiles_workspace_id_data_source_id"):
        db_session.add(profile())  # one profile per data source


def test_a_staging_row_must_match_its_job_and_file(
    db_session: Session, factory: BookingFactory, rejects: Rejects, a: Costs, b: Costs
) -> None:
    def staged(**overrides: Any) -> InvoiceImportRow:
        values: dict[str, Any] = {
            "workspace_id": a.workspace.id,
            "import_job_id": a.job.id,
            "import_file_id": a.file.id,
            "row_number": 1,
            "source_document_index": 1,
            "source_line_number": 1,
            "mapped_payload": {},
            "normalized_payload": {},
            "validation_status": ImportRowStatus.VALID,
            "validation_errors": [],
        }
        values.update(overrides)
        return InvoiceImportRow(**values)

    other_job = factory.import_job(a.source)
    with rejects(pg.ForeignKeyViolation, "fk_invoice_import_rows_workspace_id_import_files"):
        db_session.add(staged(import_job_id=b.job.id, import_file_id=b.file.id))
    with rejects(pg.ForeignKeyViolation, "fk_invoice_import_rows_workspace_id_import_files"):
        db_session.add(staged(import_job_id=other_job.id))  # a file of another job
    db_session.add(staged())
    db_session.flush()
    with rejects(pg.UniqueViolation):
        db_session.add(staged())  # the same row number of the file


def test_staging_status_must_agree_with_errors_and_payload(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    def staged(**overrides: Any) -> InvoiceImportRow:
        values: dict[str, Any] = {
            "workspace_id": a.workspace.id,
            "import_job_id": a.job.id,
            "import_file_id": a.file.id,
            "row_number": 1,
            "source_document_index": 1,
            "mapped_payload": {},
            "normalized_payload": {},
            "validation_status": ImportRowStatus.VALID,
            "validation_errors": [],
        }
        values.update(overrides)
        return InvoiceImportRow(**values)

    with rejects(pg.CheckViolation, "ck_invoice_import_rows_status_consistent"):
        db_session.add(staged(validation_status=ImportRowStatus.INVALID))  # invalid, no errors
    with rejects(pg.CheckViolation, "ck_invoice_import_rows_status_consistent"):
        db_session.add(staged(validation_errors=[{"field": "x", "code": "Y"}]))  # valid + errors
    with rejects(pg.CheckViolation, "ck_invoice_import_rows_status_consistent"):
        db_session.add(staged(normalized_payload=None))  # valid without a normalised payload


def test_deleting_a_supplier_with_invoices_is_restricted(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    make_invoice(db_session, a)
    with rejects(pg.RestrictViolation, "fk_invoices_workspace_id_suppliers"):
        db_session.execute(delete(Supplier).where(Supplier.id == a.supplier.id))


# --- N. immutability ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"net_amount": Decimal("1.00")},
        {"invoice_number": "OTHER"},
        {"supplier_id": None},
        {"source_fingerprint": "c" * 64},
        {"due_date": date(2027, 1, 1)},
    ],
)
def test_a_stored_invoice_cannot_be_updated(
    db_session: Session, rejects: Rejects, a: Costs, change: dict[str, Any]
) -> None:
    make_invoice(db_session, a)
    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(update(Invoice).values(**change))


def test_a_stored_invoice_line_cannot_be_updated(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    make_line(db_session, make_invoice(db_session, a))
    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(update(InvoiceLine).values(line_total=Decimal("1.00")))
    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            update(InvoiceLine).values(cost_category=CostCategory.FOOD)  # not even the category
        )


def test_even_a_no_op_update_of_an_invoice_is_refused(
    db_session: Session, rejects: Rejects, a: Costs
) -> None:
    make_invoice(db_session, a)
    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(update(Invoice).values(net_amount=Invoice.net_amount))


def test_the_orm_cannot_edit_an_invoice_either(db_session: Session, a: Costs) -> None:
    from sqlalchemy.exc import IntegrityError

    invoice = make_invoice(db_session, a)
    invoice.net_amount = Decimal("5.00")
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.flush()
    db_session.expire_all()


def test_a_supplier_can_evolve_but_an_invoice_and_its_lines_cannot(
    db_session: Session, a: Costs
) -> None:
    supplier = a.supplier
    supplier.is_verified = True
    supplier.default_cost_category = CostCategory.FOOD
    supplier.legal_name = "Fornitore Rinominato"
    db_session.flush()
    db_session.add(
        SupplierIdentifier(
            workspace_id=a.workspace.id,
            supplier_id=supplier.id,
            kind=IdentifierKind.TAX_CODE,
            normalized_value="RSSMRA80A01H501U",
        )
    )
    db_session.add(
        SupplierAlias(workspace_id=a.workspace.id, supplier_id=supplier.id, normalized_name="x")
    )
    db_session.flush()

    assert db_session.get(Supplier, supplier.id).is_verified is True  # type: ignore[union-attr]


def test_the_triggers_live_on_invoices_and_lines_only(db_session: Session) -> None:
    triggers = set(
        db_session.execute(
            text(
                "SELECT event_object_table || '.' || trigger_name"
                " FROM information_schema.triggers WHERE trigger_name LIKE 'trg\\_invoice%'"
            )
        ).scalars()
    )
    assert triggers == {
        "invoices.trg_invoices_immutable",
        "invoice_lines.trg_invoice_lines_immutable",
    }
    assert not db_session.scalar(
        text(
            "SELECT count(*) FROM information_schema.triggers"
            " WHERE event_object_table IN ('suppliers', 'supplier_identifiers', 'supplier_aliases',"
            " 'invoice_import_rows', 'invoice_mapping_profiles')"
        )
    )


def test_staging_rows_can_be_marked_imported_because_they_are_not_evidence(
    db_session: Session, a: Costs
) -> None:
    db_session.execute(
        insert(InvoiceImportRow).values(
            workspace_id=a.workspace.id,
            import_job_id=a.job.id,
            import_file_id=a.file.id,
            row_number=1,
            source_document_index=1,
            mapped_payload={},
            normalized_payload={},
            validation_status=ImportRowStatus.VALID,
            validation_errors=[],
        )
    )

    db_session.execute(update(InvoiceImportRow).values(validation_status=ImportRowStatus.IMPORTED))

    assert db_session.scalars(select(InvoiceImportRow.validation_status)).one() == (
        ImportRowStatus.IMPORTED
    )
