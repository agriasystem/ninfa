"""Golden scenario "MASSERIA NINFA DEMO — COST DATA V1" (Gate 6).

Eight suppliers, 29 invoices and 62 lines over January-June 2026, imported through seven files in
two data sources (five FatturaPA XML files, one Italian CSV, one XLSX). The expected result
(`tests/fixtures/invoices/golden/masseria_ninfa_cost_v1.expected.json`) is written by
`generate_cost_fixtures.py` from the WORLD it designs, with the standard library only: the
application's resolver, normaliser, classifier and rounding are not used to compute it.

The chain verified here is: files -> staging -> supplier resolution -> invoices -> lines ->
categories. It stops there: no cost per occupied room, no expected cost, no anomaly, no decision.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportJobStatus
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import Invoice, InvoiceImportRow, InvoiceLine
from app.modules.invoices.service import InvoiceImportResult
from app.modules.suppliers.models import (
    Supplier,
    SupplierAlias,
    SupplierIdentifier,
    SupplierResolutionReview,
)
from app.modules.suppliers.repository import SupplierRepository
from tests.booking_support import xlsx_bytes
from tests.invoice_support import CostWorld, persisted_hits
from tests.support import BookingFactory

GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "invoices" / "golden"
EXPECTED = json.loads((GOLDEN / "masseria_ninfa_cost_v1.expected.json").read_text("utf-8"))

ITALIAN_COLUMNS: dict[str, dict[str, Any]] = {
    "supplier_name": {"column": "Fornitore"},
    "supplier_vat_number": {"column": "P.IVA"},
    "supplier_tax_code": {"column": "Codice Fiscale"},
    "supplier_iban": {"column": "IBAN"},
    "invoice_number": {"column": "Numero Fattura"},
    "invoice_date": {"column": "Data"},
    "document_type": {"column": "Tipo"},
    "line_description": {"column": "Descrizione"},
    "line_total": {"column": "Importo"},
    "cost_category": {"column": "Categoria"},
    "invoice_net_amount": {"column": "Imponibile"},
}  # "Riferimento cliente" is deliberately not mapped
ITALIAN_FORMAT = {
    "date_formats": {"invoice_date": "%d/%m/%Y"},
    "decimal_separator": ",",
    "thousands_separator": ".",
}
XLSX_COLUMNS: dict[str, dict[str, Any]] = {
    "supplier_name": {"column": "Supplier"},
    "supplier_vat_number": {"column": "VAT"},
    "supplier_tax_code": {"column": "Tax Code"},
    "invoice_number": {"column": "Invoice No"},
    "invoice_date": {"column": "Invoice Date"},
    "line_description": {"column": "Description"},
    "line_total": {"column": "Line Total"},
    "cost_category": {"column": "Category"},
}
COUNT_FIELDS = (
    ("documents", "documents_total"),
    ("rows", "rows_total"),
    ("invoices_created", "invoices_created"),
    ("lines_created", "lines_created"),
    ("suppliers_created", "suppliers_created"),
    ("suppliers_matched", "suppliers_matched"),
    ("identifiers_added", "identifiers_added"),
    ("aliases_added", "aliases_added"),
    ("reviews_created", "reviews_created"),
)


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


class Golden:
    """The golden world: one property, two COSTS data sources, the seven files."""

    def __init__(self, session: Session, factory: BookingFactory) -> None:
        self.session = session
        self.a = CostWorld.create(session, factory)
        self.source_b: DataSource = factory.data_source(
            self.a.tenant.property, DataSourceDomain.COSTS
        )
        self.context = self.a.context
        self.keys = {s["normalized_name"]: s["key"] for s in EXPECTED["suppliers"]}
        self.ids: dict[str, Any] = {}
        self._confirm_mappings()

    def _confirm_mappings(self) -> None:
        service = self.a.service()
        csv_headers = service.describe_file(
            self.a.source.id,
            filename="c.csv",
            content=(GOLDEN / "masseria_ninfa_cost_06_structured.csv").read_bytes(),
        ).headers
        service.save_mapping(
            self.a.source.id,
            headers=csv_headers,
            column_mapping=ITALIAN_COLUMNS,
            category_mapping=EXPECTED["csv_mapping"]["category_mapping"],
            format_options=ITALIAN_FORMAT,
        )
        service.save_mapping(
            self.source_b.id,
            headers=list(XLSX_COLUMNS_HEADERS),
            column_mapping=XLSX_COLUMNS,
            category_mapping={"Consulenza": "PROFESSIONAL_SERVICES"},
        )

    def content(self, step: dict[str, Any]) -> tuple[str, bytes]:
        name = step["file"]
        if step["source"] == "B":  # the XLSX is written here, with typed cells
            return "costi_giugno.xlsx", xlsx_from_rows(GOLDEN / name)
        return name, (GOLDEN / name).read_bytes()

    def run(self, step: dict[str, Any]) -> InvoiceImportResult:
        source = self.source_b if step["source"] == "B" else self.a.source
        name, content = self.content(step)
        return self.a.service().import_file(source.id, filename=name, content=content)

    def refresh_ids(self) -> None:
        for supplier in self.session.scalars(select(Supplier)):
            self.ids[self.keys[supplier.normalized_name]] = supplier.id

    def apply_after(self, step: dict[str, Any]) -> None:
        action = step.get("after", {}).get("set_default")
        if action:
            self.refresh_ids()
            SupplierRepository(self.session, self.context).set_default_cost_category(
                self.ids[action["supplier"]], CostCategory(action["category"])
            )


XLSX_COLUMNS_HEADERS = [
    "Supplier",
    "VAT",
    "Tax Code",
    "Invoice No",
    "Invoice Date",
    "Description",
    "Line Total",
    "Category",
]


def xlsx_from_rows(path: Path) -> bytes:
    """Typed cells: real dates and real numbers, as an accountant's workbook has them."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(path.read_text("utf-8"))))
    typed: list[list[Any]] = [rows[0]]
    for row in rows[1:]:
        cells: list[Any] = list(row)
        cells[4] = datetime.fromisoformat(row[4])
        cells[6] = float(row[6])
        typed.append([None if cell == "" else cell for cell in cells])
    return xlsx_bytes({"Fatture": typed})


@pytest.fixture
def golden(db_session: Session, factory: BookingFactory) -> Golden:
    return Golden(db_session, factory)


def run_all(golden: Golden) -> list[InvoiceImportResult]:
    results = []
    for step in EXPECTED["steps"]:
        results.append(golden.run(step))
        golden.apply_after(step)
    golden.refresh_ids()
    return results


# --- the canonical result, read back from the database ----------------------------------------


def canonical_invoices(golden: Golden) -> list[dict[str, Any]]:
    session = golden.session
    found = []
    for invoice in session.scalars(select(Invoice)):
        supplier = session.get(Supplier, invoice.supplier_id)
        assert supplier is not None
        lines = session.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice.id)
            .order_by(InvoiceLine.source_line_number)
        ).all()
        found.append(
            {
                "supplier": golden.keys[supplier.normalized_name],
                "number": invoice.invoice_number,
                "normalized_number": invoice.normalized_invoice_number,
                "date": invoice.invoice_date.isoformat(),
                "kind": invoice.document_kind.value,
                "type_code": invoice.document_type_code,
                "source_format": invoice.source_format.value,
                "resolution_method": invoice.supplier_resolution_method.value,
                "due_date": None if invoice.due_date is None else invoice.due_date.isoformat(),
                "net": money(invoice.net_amount),
                "tax": money(invoice.tax_amount),
                "gross": money(invoice.gross_amount),
                "lines": [
                    {
                        "n": line.source_line_number,
                        "description": line.description_raw,
                        "total": money(line.line_total),
                        "category": line.cost_category.value,
                        "method": line.classification_method.value,
                        "confidence": money(line.classification_confidence),
                    }
                    for line in lines
                ],
            }
        )
    return found


def order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["date"], item["number"], item["supplier"]))


def grouped(session: Session, expression: str) -> dict[str, str]:
    rows = session.execute(
        text(
            f"SELECT {expression} AS k, sum(l.line_total) FROM invoice_lines l"  # noqa: S608
            " JOIN invoices i ON i.id = l.invoice_id AND i.workspace_id = l.workspace_id"
            " GROUP BY 1 ORDER BY 1"
        )
    ).all()
    return {key: f"{total:.2f}" for key, total in rows}


# --- the tests --------------------------------------------------------------------------------


def test_the_world_is_as_large_as_the_specification_asks() -> None:
    aggregates = EXPECTED["aggregates"]
    assert aggregates["supplier_count"] >= 8
    assert aggregates["invoice_count"] >= 20 and aggregates["line_count"] >= 60
    assert len(aggregates["by_month"]) >= 3
    assert len({c for c in aggregates["by_category"]}) >= 5
    assert aggregates["credit_note_count"] >= 1 and aggregates["other_lines"] >= 1
    assert {
        "CREATED_NEW",
        "VAT_NUMBER",
        "TAX_CODE",
        "IBAN_SHA256",
        "EXACT_ALIAS",
        "EXACT_NAME",
    } <= set(aggregates["invoices_by_resolution_method"])
    assert len(EXPECTED["reviews"]) == 1
    assert set(aggregates["invoices_by_format"]) == {"FATTURAPA_XML", "CSV", "XLSX"}


def test_every_import_step_reports_the_expected_counts(golden: Golden) -> None:
    for step in EXPECTED["steps"]:
        result = golden.run(step)

        assert result.succeeded, (step["step"], result.error_code, result.details)
        for expected_key, result_field in COUNT_FIELDS:
            assert getattr(result, result_field) == step[expected_key], (step["step"], expected_key)
        assert result.warning_summary == step["warnings"], step["step"]
        assert result.invoices_unchanged == 0
        golden.apply_after(step)


def test_the_suppliers_aliases_and_identifiers_are_the_ones_of_the_world(golden: Golden) -> None:
    run_all(golden)
    session = golden.session

    found = []
    for supplier in session.scalars(select(Supplier)):
        identifiers = sorted(
            [i.kind.value, i.normalized_value]
            for i in session.scalars(
                select(SupplierIdentifier).where(SupplierIdentifier.supplier_id == supplier.id)
            )
        )
        aliases = sorted(
            a.normalized_name
            for a in session.scalars(
                select(SupplierAlias).where(SupplierAlias.supplier_id == supplier.id)
            )
        )
        found.append(
            {
                "key": golden.keys[supplier.normalized_name],
                "legal_name": supplier.legal_name,
                "normalized_name": supplier.normalized_name,
                "country": supplier.country,
                "identifiers": identifiers,
                "aliases": aliases,
                "default_cost_category": (
                    None
                    if supplier.default_cost_category is None
                    else supplier.default_cost_category.value
                ),
                "is_verified": supplier.is_verified,
            }
        )

    assert sorted(found, key=lambda s: s["key"]) == sorted(
        EXPECTED["suppliers"], key=lambda s: s["key"]
    )


def key_of(golden: Golden, supplier_id: Any) -> str:
    supplier = golden.session.get(Supplier, supplier_id)
    assert supplier is not None
    return str(golden.keys[supplier.normalized_name])


def test_the_one_near_duplicate_is_a_pending_review_and_nothing_is_merged(golden: Golden) -> None:
    run_all(golden)

    reviews = [
        {
            "provisional": key_of(golden, r.provisional_supplier_id),
            "candidate": key_of(golden, r.candidate_supplier_id),
            "reason": r.reason.value,
            "similarity": f"{r.similarity_score:.4f}",
            "status": r.status.value,
        }
        for r in golden.session.scalars(select(SupplierResolutionReview))
    ]
    assert reviews == EXPECTED["reviews"]
    # the invoice of the provisional supplier stays on it, never on the candidate
    provisional = golden.ids["S7"]
    assert {
        i.supplier_id
        for i in golden.session.scalars(select(Invoice))
        if i.invoice_number == "AMS/2026/1"
    } == {provisional}


def test_every_invoice_and_line_matches_the_independent_expectation(golden: Golden) -> None:
    run_all(golden)

    found = order(canonical_invoices(golden))

    assert len(found) == EXPECTED["aggregates"]["invoice_count"]
    for got, want in zip(found, order(EXPECTED["invoices"]), strict=True):
        assert got == want, (want["supplier"], want["number"])


def test_the_canonical_content_has_the_expected_checksum(golden: Golden) -> None:
    run_all(golden)

    canonical = json.dumps(
        order(canonical_invoices(golden)), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == EXPECTED["invoices_sha256"]


def test_the_aggregates_match_the_independent_computation(golden: Golden) -> None:
    run_all(golden)
    session = golden.session
    want = EXPECTED["aggregates"]

    assert session.scalar(select(func.count()).select_from(Invoice)) == want["invoice_count"]
    assert session.scalar(select(func.count()).select_from(InvoiceLine)) == want["line_count"]
    assert session.scalar(select(func.count()).select_from(Supplier)) == want["supplier_count"]
    assert (
        f"{session.scalar(select(func.sum(InvoiceLine.line_total))):.2f}" == want["line_total_sum"]
    )
    assert grouped(session, "to_char(i.invoice_date, 'YYYY-MM')") == want["by_month"]
    assert grouped(session, "l.cost_category") == want["by_category"]
    assert grouped(session, "l.classification_method") == want["by_method"]
    credit = session.scalar(
        text(
            "SELECT sum(l.line_total) FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id"
            " WHERE i.document_kind = 'CREDIT_NOTE'"
        )
    )
    assert f"{credit:.2f}" == want["credit_note_line_total_sum"]
    by_supplier = {
        golden.keys[name]: f"{total:.2f}"
        for name, total in session.execute(
            text(
                "SELECT s.normalized_name, sum(l.line_total) FROM invoice_lines l"
                " JOIN invoices i ON i.id = l.invoice_id JOIN suppliers s ON s.id = i.supplier_id"
                " GROUP BY 1"
            )
        )
    }
    assert dict(sorted(by_supplier.items())) == want["by_supplier"]


def test_one_supplier_of_the_workspace_has_invoices_from_three_source_formats(
    golden: Golden,
) -> None:
    run_all(golden)

    formats = {
        i.source_format.value
        for i in golden.session.scalars(select(Invoice))
        if i.supplier_id == golden.ids["S1"]
    }
    assert formats == {"FATTURAPA_XML", "XLSX"}  # the same laundry, through two data sources
    assert (
        golden.session.scalar(
            select(func.count(func.distinct(Invoice.data_source_id))).where(
                Invoice.supplier_id == golden.ids["S1"]
            )
        )
        == 2
    )


def test_staging_keeps_every_line_and_all_are_imported(golden: Golden) -> None:
    run_all(golden)

    rows = golden.session.scalars(select(InvoiceImportRow)).all()

    assert len(rows) == sum(step["rows"] for step in EXPECTED["steps"])
    assert {row.validation_status for row in rows} == {ImportRowStatus.IMPORTED}


def test_no_raw_iban_and_no_private_value_reaches_any_table(golden: Golden) -> None:
    run_all(golden)
    session = golden.session

    assert persisted_hits(session, EXPECTED["raw_ibans_never_stored"]) == []
    assert persisted_hits(session, EXPECTED["private_values_never_stored"]) == []
    # control: the authorised data, and the hash of the bank account, are stored
    assert persisted_hits(session, ["Lavanderia Salentina S.r.l."])
    hashes = list(EXPECTED["iban_sha256"].values())
    assert {value for _, value in persisted_hits(session, hashes)} == set(hashes)


def test_importing_the_whole_world_again_creates_nothing(golden: Golden) -> None:
    run_all(golden)
    before = canonical_invoices(golden)
    counts = {
        model.__tablename__: golden.session.scalar(select(func.count()).select_from(model))
        for model in (
            Supplier,
            SupplierIdentifier,
            SupplierAlias,
            SupplierResolutionReview,
            Invoice,
            InvoiceLine,
        )
    }

    for step in EXPECTED["steps"]:
        again = golden.run(step)

        assert again.status == ImportJobStatus.SUCCEEDED, (step["step"], again.error_code)
        assert (again.invoices_created, again.lines_created) == (0, 0)
        assert again.invoices_unchanged == step["invoices_created"]
        assert (again.suppliers_created, again.identifiers_added, again.reviews_created) == (
            0,
            0,
            0,
        )

    assert order(canonical_invoices(golden)) == order(before)
    assert counts == {
        model.__tablename__: golden.session.scalar(select(func.count()).select_from(model))
        for model in (
            Supplier,
            SupplierIdentifier,
            SupplierAlias,
            SupplierResolutionReview,
            Invoice,
            InvoiceLine,
        )
    }


def test_the_golden_files_are_reproducible_from_the_generator() -> None:
    """Running the generator changes no committed byte (it is deterministic)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cost_generator", GOLDEN.parent / "generate_cost_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.build_world()
    result = module.expected()
    assert result["invoices_sha256"] == EXPECTED["invoices_sha256"]
    for name, content in module.golden_files().items():
        assert (GOLDEN / name).read_bytes() == content.encode("utf-8"), name
    for name, content in module.xml_fixtures().items():
        assert (GOLDEN.parent / "xml" / name).read_bytes() == content.encode("utf-8"), name
    for name, data in module.structured_fixtures().items():
        assert (GOLDEN.parent / "structured" / name).read_bytes() == data, name
