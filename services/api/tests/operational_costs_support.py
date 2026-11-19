"""Operating costs with no document number (ADR 0057): synthetic files and small helpers.

A register an hotel's own accountant keeps ("Data, Fornitore, Categoria, Descrizione, Imponibile,
IVA, Totale") carries no invoice number at all. Every function here is a free function over the
shared `CostWorld` (the repository's support-module pattern); synthetic data only.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ingestion.models import FileScope
from app.modules.ingestion.scope import NO_SCOPE, ScopePlan
from app.modules.invoices.models import Invoice, InvoiceLine, InvoiceRemoval, is_current_invoice
from app.modules.invoices.service import InvoiceImportResult
from tests.booking_support import csv_bytes
from tests.invoice_support import CostWorld

OPERATIONAL_HEADERS = [
    "Data",
    "Fornitore",
    "Categoria",
    "Descrizione",
    "Imponibile",
    "IVA",
    "Totale",
]
OPERATIONAL_COLUMNS: dict[str, dict[str, Any]] = {
    "invoice_date": {"column": "Data"},
    "supplier_name": {"column": "Fornitore"},
    "cost_category": {"column": "Categoria"},
    "line_description": {"column": "Descrizione"},
    "line_total": {"column": "Imponibile"},
    "invoice_tax_amount": {"column": "IVA"},
    "invoice_gross_amount": {"column": "Totale"},
}
# What a person's "Continua come costi operativi" puts in the mapping.
SYNTHETIC = {"document_identity": "SYNTHETIC_COST_RECORD"}


def cost_row(
    day: str = "2026-10-05",
    supplier: str = "Enel Energia",
    category: str = "UTILITIES",
    description: str = "Energia elettrica ottobre",
    net: str = "100.00",
    tax: str = "22.00",
    gross: str = "122.00",
) -> list[Any]:
    """One cost of the register, in the column order of OPERATIONAL_HEADERS."""
    return [day, supplier, category, description, net, tax, gross]


def operational_csv(rows: Sequence[Sequence[Any]], headers: Sequence[str] | None = None) -> bytes:
    return csv_bytes([list(headers or OPERATIONAL_HEADERS), *[list(row) for row in rows]])


def confirm_operational(world: CostWorld) -> None:
    """The mapping a person confirmed: these are operating costs, there is no document number."""
    world.confirm(
        headers=OPERATIONAL_HEADERS, columns=OPERATIONAL_COLUMNS, format_options=dict(SYNTHETIC)
    )


def import_costs(
    world: CostWorld,
    rows: Sequence[Sequence[Any]],
    *,
    scope: ScopePlan = NO_SCOPE,
    name: str = "costi.csv",
) -> InvoiceImportResult:
    return world.service().import_file(
        world.source.id, filename=name, content=operational_csv(rows), scope=scope
    )


def full(removals: int | None = None) -> ScopePlan:
    """A person said the file holds everything of its period (and was shown `removals` going)."""
    return ScopePlan(FileScope.FULL, None, removals)


def partial() -> ScopePlan:
    return ScopePlan(FileScope.PARTIAL, None, None)


def delta() -> ScopePlan:
    return ScopePlan(FileScope.DELTA, None, None)


def all_records(session: Session, world: CostWorld) -> list[Invoice]:
    """Every row ever written, removed or not, oldest first."""
    return list(
        session.scalars(
            select(Invoice)
            .where(Invoice.workspace_id == world.tenant.workspace.id)
            .order_by(Invoice.created_at, Invoice.source_record_key, Invoice.revision)
        )
    )


def current_records(session: Session, world: CostWorld) -> list[Invoice]:
    """What counts: the newest version of each record that no complete file took away."""
    return list(
        session.scalars(
            select(Invoice)
            .where(Invoice.workspace_id == world.tenant.workspace.id, is_current_invoice())
            .order_by(Invoice.invoice_date, Invoice.source_record_key)
        )
    )


def removals(session: Session, world: CostWorld) -> list[InvoiceRemoval]:
    return list(
        session.scalars(
            select(InvoiceRemoval).where(InvoiceRemoval.workspace_id == world.tenant.workspace.id)
        )
    )


def days(records: Sequence[Invoice]) -> list[date]:
    return sorted(record.invoice_date for record in records)


def stated(session: Session, world: CostWorld) -> dict[str, str]:
    """What counts, as {key of the record: the category it carries}: one entry per current cost."""
    rows = session.execute(
        select(Invoice.source_record_key, InvoiceLine.cost_category)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(Invoice.workspace_id == world.tenant.workspace.id, is_current_invoice())
    )
    return {key: category.value for key, category in rows}
