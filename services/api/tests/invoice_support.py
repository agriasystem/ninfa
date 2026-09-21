"""Helpers shared by the Gate 6 (invoices and suppliers) tests. Synthetic data only.

`fattura_xml` builds a FatturaPA document (FPR12/FPA12) with the recipient, address, phone, e-mail,
PEC and attachment blocks that a real one has, so tests can prove they never reach the database.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportJob
from app.modules.invoices.models import Invoice, InvoiceLine
from app.modules.invoices.service import InvoiceImportResult, InvoiceImportService
from tests.booking_support import csv_bytes
from tests.support import BookingFactory, Tenant

NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"

# Fictional but structurally valid IBANs (the checksum is right, the accounts do not exist).
IBAN_A = "IT60X0542811101000000123456"
IBAN_B = "GB82WEST12345698765432"
IBAN_C = "DE89370400440532013000"
# The PII that a source carries and NINFA must never store.
RECIPIENT_NAME = "Masseria Cliente Fittizia S.r.l."
RECIPIENT_TAX_CODE = "99999999999"
SUPPLIER_EMAIL = "amministrazione@fornitore-fittizio.example"
SUPPLIER_PHONE = "+39 000 5550101"
SUPPLIER_STREET = "Via Inventata 12"


@dataclass
class Line:
    number: int
    description: str
    total: str
    quantity: str | None = None
    unit: str | None = None
    unit_price: str | None = None
    vat: str | None = "22.00"


@dataclass
class Payment:
    due: str | None = None
    iban: str | None = None
    beneficiary: str | None = None


@dataclass
class Body:
    number: str = "1"
    date: str = "2026-03-10"
    type_code: str = "TD01"
    currency: str = "EUR"
    lines: list[Line] = field(default_factory=lambda: [Line(1, "Servizio generico", "100.00")])
    total: str | None = None
    summaries: list[tuple[str, str, str]] | None = None  # (vat rate, taxable, tax)
    payments: list[Payment] = field(default_factory=list)


@dataclass
class Cedente:
    name: str | None = "Fornitore Fittizio S.r.l."
    vat: str | None = "01234567890"
    country: str = "IT"
    tax_code: str | None = None
    first_name: str | None = None
    last_name: str | None = None


def _opt(tag: str, value: str | None) -> str:
    return "" if value is None else f"<{tag}>{escape(value)}</{tag}>"


def fattura_xml(
    bodies: list[Body] | None = None,
    *,
    cedente: Cedente | None = None,
    prefix: str = "",
    version: str = "FPR12",
    root: str = "FatturaElettronica",
    namespace: bool = True,
    doctype: str = "",
) -> bytes:
    """A FatturaPA document. `prefix` ("p:") exercises namespace-prefix independence."""
    cedente = cedente or Cedente()
    bodies = bodies or [Body()]
    p = prefix
    ns = f' xmlns{":" + p[:-1] if p else ""}="{NS}"' if namespace else ""

    def t(tag: str, inner: str) -> str:
        return f"<{p}{tag}>{inner}</{p}{tag}>"

    def o(tag: str, value: str | None) -> str:
        return "" if value is None else t(tag, escape(value))

    if cedente.name is not None:
        anagrafica = t("Denominazione", escape(cedente.name))
    else:
        anagrafica = o("Nome", cedente.first_name) + o("Cognome", cedente.last_name)
    vat = (
        t("IdFiscaleIVA", o("IdPaese", cedente.country) + o("IdCodice", cedente.vat))
        if cedente.vat is not None
        else ""
    )
    header = t(
        "FatturaElettronicaHeader",
        t(
            "DatiTrasmissione",
            t("IdTrasmittente", o("IdPaese", "IT") + o("IdCodice", "00000000001"))
            + o("ProgressivoInvio", "00001")
            + o("FormatoTrasmissione", version)
            + o("CodiceDestinatario", "ABCDEFG")
            + o("PECDestinatario", "cliente-pec@example.com"),
        )
        + t(
            "CedentePrestatore",
            t(
                "DatiAnagrafici",
                vat
                + o("CodiceFiscale", cedente.tax_code)
                + t("Anagrafica", anagrafica)
                + o("RegimeFiscale", "RF01"),
            )
            + t(
                "Sede",
                o("Indirizzo", SUPPLIER_STREET)
                + o("CAP", "06121")
                + o("Comune", "Perugia")
                + o("Provincia", "PG")
                + o("Nazione", cedente.country),
            )
            + t("Contatti", o("Telefono", SUPPLIER_PHONE) + o("Email", SUPPLIER_EMAIL)),
        )
        + t(
            "CessionarioCommittente",
            t(
                "DatiAnagrafici",
                o("CodiceFiscale", RECIPIENT_TAX_CODE)
                + t("Anagrafica", o("Denominazione", RECIPIENT_NAME)),
            )
            + t(
                "Sede", o("Indirizzo", "Via del Cliente 1") + o("CAP", "00100") + o("Nazione", "IT")
            ),
        ),
    )

    def body_xml(body: Body) -> str:
        lines = "".join(
            t(
                "DettaglioLinee",
                o("NumeroLinea", str(line.number))
                + o("Descrizione", line.description)
                + o("Quantita", line.quantity)
                + o("UnitaMisura", line.unit)
                + o("PrezzoUnitario", line.unit_price)
                + o("PrezzoTotale", line.total)
                + o("AliquotaIVA", line.vat),
            )
            for line in body.lines
        )
        summaries = body.summaries
        if summaries is None:
            taxable = sum((Decimal(line.total) for line in body.lines), Decimal(0))
            summaries = [("22.00", f"{taxable:.2f}", f"{taxable * Decimal('0.22'):.2f}")]
        summary_xml = "".join(
            t(
                "DatiRiepilogo",
                o("AliquotaIVA", rate) + o("ImponibileImporto", taxable) + o("Imposta", tax),
            )
            for rate, taxable, tax in summaries
        )
        payments = ""
        if body.payments:
            details = "".join(
                t(
                    "DettaglioPagamento",
                    o("Beneficiario", pay.beneficiary)
                    + o("ModalitaPagamento", "MP05")
                    + o("DataScadenzaPagamento", pay.due)
                    + o("ImportoPagamento", "100.00")
                    + o("IBAN", pay.iban),
                )
                for pay in body.payments
            )
            payments = t("DatiPagamento", o("CondizioniPagamento", "TP02") + details)
        return t(
            "FatturaElettronicaBody",
            t(
                "DatiGenerali",
                t(
                    "DatiGeneraliDocumento",
                    o("TipoDocumento", body.type_code)
                    + o("Divisa", body.currency)
                    + o("Data", body.date)
                    + o("Numero", body.number)
                    + o("ImportoTotaleDocumento", body.total),
                ),
            )
            + t("DatiBeniServizi", lines + summary_xml)
            + payments
            + t(
                "Allegati",
                o("NomeAttachment", "copia.pdf") + o("Attachment", "JVBERi0xLjQKJSVFT0Y="),
            ),
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        + doctype
        + f'<{p}{root}{ns} versione="{version}">'
        + header
        + "".join(body_xml(body) for body in bodies)
        + f"</{p}{root}>"
    )
    return xml.encode("utf-8")


# --- database worlds ----------------------------------------------------------------------------


def costs_source(factory: BookingFactory, tenant: Tenant) -> DataSource:
    """A COSTS / FILE_UPLOAD data source of the tenant's property."""
    return factory.data_source(tenant.property, DataSourceDomain.COSTS)


@dataclass
class CostWorld:
    """One tenant with a COSTS data source, and the import service bound to it."""

    session: Session
    tenant: Tenant
    source: DataSource

    @classmethod
    def create(cls, session: Session, factory: BookingFactory) -> "CostWorld":
        tenant = factory.tenant()
        return cls(session, tenant, costs_source(factory, tenant))

    @property
    def context(self) -> TenantContext:
        return self.tenant.context

    def service(self) -> InvoiceImportService:
        return InvoiceImportService(self.session, self.context)

    def import_xml(self, content: bytes, name: str = "fattura.xml") -> InvoiceImportResult:
        return self.service().import_file(self.source.id, filename=name, content=content)

    def import_bytes(self, name: str, content: bytes) -> InvoiceImportResult:
        return self.service().import_file(self.source.id, filename=name, content=content)

    def confirm(
        self,
        headers: list[str] | None = None,
        columns: dict[str, dict[str, Any]] | None = None,
        **sections: Any,
    ) -> None:
        """Confirm the mapping of the data source (the STANDARD layout by default)."""
        self.service().save_mapping(
            self.source.id,
            headers=headers or STANDARD_HEADERS,
            column_mapping=columns or STANDARD_COLUMNS,
            **sections,
        )

    def import_rows(
        self, rows: Sequence[dict[str, Any]], name: str = "costs.csv"
    ) -> InvoiceImportResult:
        return self.import_bytes(name, standard_csv(rows))

    def count(self, model: type[Any]) -> int:
        return count(self.session, model, self.tenant.workspace.id)

    def invoices(self) -> list[Invoice]:
        return all_invoices(self.session, self.tenant.workspace.id)


def money(value: str) -> Decimal:
    return Decimal(value)


def iso(value: date) -> str:
    return value.isoformat()


# --- structured files ---------------------------------------------------------------------------

STANDARD_HEADERS = [
    "Supplier",
    "VAT",
    "Tax Code",
    "IBAN",
    "Invoice No",
    "Invoice Date",
    "Due Date",
    "Type",
    "Currency",
    "Net",
    "Tax",
    "Gross",
    "Line",
    "Description",
    "Qty",
    "Unit",
    "Unit Price",
    "Line Total",
    "VAT Rate",
    "Category",
]
STANDARD_COLUMNS: dict[str, dict[str, Any]] = {
    "supplier_name": {"column": "Supplier"},
    "supplier_vat_number": {"column": "VAT"},
    "supplier_tax_code": {"column": "Tax Code"},
    "supplier_iban": {"column": "IBAN"},
    "invoice_number": {"column": "Invoice No"},
    "invoice_date": {"column": "Invoice Date"},
    "due_date": {"column": "Due Date"},
    "document_type": {"column": "Type"},
    "currency": {"column": "Currency"},
    "invoice_net_amount": {"column": "Net"},
    "invoice_tax_amount": {"column": "Tax"},
    "invoice_gross_amount": {"column": "Gross"},
    "line_number": {"column": "Line"},
    "line_description": {"column": "Description"},
    "quantity": {"column": "Qty"},
    "unit": {"column": "Unit"},
    "unit_price": {"column": "Unit Price"},
    "line_total": {"column": "Line Total"},
    "vat_rate": {"column": "VAT Rate"},
    "cost_category": {"column": "Category"},
}
# The minimum a file needs (everything else is optional).
MINIMAL_COLUMNS: dict[str, dict[str, Any]] = {
    key: STANDARD_COLUMNS[key]
    for key in (
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "line_description",
        "line_total",
    )
}
MINIMAL_HEADERS = [column["column"] for column in MINIMAL_COLUMNS.values()]


def structured_row(**values: Any) -> list[Any]:
    """A row of the STANDARD layout: pass columns by their canonical field name."""
    keys = list(STANDARD_COLUMNS)
    unknown = set(values) - set(keys)
    assert not unknown, unknown
    return [values.get(key) for key in keys]


def standard_csv(rows: Sequence[dict[str, Any]], **options: Any) -> bytes:
    return csv_bytes([STANDARD_HEADERS, *[structured_row(**row) for row in rows]], **options)


def as_dict(**values: Any) -> dict[str, Any]:
    return dict(values)


# --- inspection ---------------------------------------------------------------------------------


def count(session: Session, model: type[Any], workspace_id: Any = None) -> int:
    query = select(func.count()).select_from(model)
    if workspace_id is not None:
        query = query.where(model.workspace_id == workspace_id)
    return int(session.scalar(query) or 0)


def all_invoices(session: Session, workspace_id: Any = None) -> list[Invoice]:
    query = select(Invoice).order_by(Invoice.invoice_date, Invoice.normalized_invoice_number)
    if workspace_id is not None:
        query = query.where(Invoice.workspace_id == workspace_id)
    return list(session.scalars(query))


def lines_of(session: Session, invoice: Invoice) -> list[InvoiceLine]:
    return list(
        session.scalars(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice.id)
            .order_by(InvoiceLine.source_line_number)
        )
    )


def job_of(session: Session, result: InvoiceImportResult) -> ImportJob:
    job = session.get(ImportJob, result.import_job_id)
    assert job is not None
    return job


def persisted_hits(session: Session, needles: Sequence[str]) -> list[tuple[str, str]]:
    """Every (table, needle) pair where the needle appears anywhere in any persisted row.

    Scans EVERY table of the schema as text, so a value cannot hide in a table the test forgot.
    """
    tables = (
        session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )
    hits: list[tuple[str, str]] = []
    for table in tables:
        for needle in needles:
            found = session.execute(
                text(f'SELECT count(*) FROM "{table}" t WHERE CAST(t AS text) ILIKE :pattern'),
                {"pattern": f"%{needle}%"},
            ).scalar_one()
            if found:
                hits.append((table, needle))
    return hits


@contextmanager
def sql_log(session: Session) -> Iterator[list[str]]:
    """Every SQL statement the body sends (statement text, no parameters)."""
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(bind, "before_cursor_execute", record)
