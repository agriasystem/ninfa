"""Tenant-scoped, READ-ONLY access to the canonical cost lines (Gate 6) for Cost CPOR V1.

One statement returns the whole history a target needs: the canonical invoice lines of ONE
property between two dates, summed by (month of the invoice date, currency, category). The sums
are done by PostgreSQL on exact NUMERIC values, so no float and no per-invoice or per-line read
exists. It reads `invoices` and `invoice_lines` only: never the staging rows, never a file, never
the data source of an invoice (the Gate 6 identity is cross-source: a document counts ONCE).

Every query carries the workspace_id of the TenantContext. The repository never writes.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.costs.types import MonthlyCostAggregate
from app.modules.invoices.models import DocumentKind, Invoice, InvoiceLine


class CostLineRepository:
    """The canonical invoice lines of ONE workspace, aggregated for the cost detector."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def monthly_aggregates(
        self, property_id: UUID, first: date, last: date
    ) -> list[MonthlyCostAggregate]:
        """The lines of the invoices dated `first..last` (both included) of one property.

        `first` should be the first day of a month and `last` the last day of one, so that no
        month is cut. One row per (month, currency, category) that has at least one line.
        """
        month = cast(func.date_trunc("month", Invoice.invoice_date), Date)
        absolute = func.abs(InvoiceLine.line_total)
        credit = Invoice.document_kind == DocumentKind.CREDIT_NOTE
        rows = self._session.execute(
            select(
                month.label("month"),
                Invoice.currency,
                InvoiceLine.cost_category,
                func.sum(InvoiceLine.line_total),
                func.sum(absolute),
                func.sum(absolute * InvoiceLine.classification_confidence),
                func.count(func.distinct(Invoice.id)),
                func.count(),
                func.count().filter(credit),
                func.coalesce(func.sum(InvoiceLine.line_total).filter(credit), Decimal(0)),
            )
            .select_from(InvoiceLine)
            .join(
                Invoice,
                and_(
                    Invoice.workspace_id == InvoiceLine.workspace_id,
                    Invoice.id == InvoiceLine.invoice_id,
                ),
            )
            .where(
                Invoice.workspace_id == self._tenant.workspace_id,
                Invoice.property_id == property_id,
                Invoice.invoice_date >= first,
                Invoice.invoice_date <= last,
            )
            .group_by(month, Invoice.currency, InvoiceLine.cost_category)
            .order_by(month, Invoice.currency, InvoiceLine.cost_category)
        ).all()
        return [MonthlyCostAggregate(*row) for row in rows]
