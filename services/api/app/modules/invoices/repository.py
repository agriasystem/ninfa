"""Tenant-scoped repositories of the invoices module (explicit, no generic base class).

Every class takes a TenantContext and puts its workspace_id in every query. Repositories `flush()`
but never `commit()`: transaction boundaries belong to InvoiceImportService. Writes are bulk (one
statement per kind of row) so an import does not grow with its number of invoices.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Date, String, Uuid, column, func, insert, select, update, values
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSource
from app.modules.invoices.models import (
    DocumentKind,
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    InvoiceMappingProfile,
)

_CHUNK = 1000
_KEYS_PER_QUERY = 2000

# (supplier_id, normalised invoice number, invoice date, document kind): the identity of a document
# inside one property.
InvoiceIdentity = tuple[UUID, str, date, DocumentKind]


@dataclass(frozen=True, slots=True)
class ExistingInvoice:
    id: UUID
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class StagedRow:
    row_number: int
    source_document_index: int
    source_line_number: int | None
    mapped_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    validation_status: ImportRowStatus
    validation_errors: list[dict[str, str]]
    validation_warnings: list[dict[str, str]]


class InvoiceRepository:
    """Invoices and lines of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get(self, invoice_id: UUID) -> Invoice | None:
        return self._session.scalar(
            select(Invoice).where(
                Invoice.workspace_id == self._tenant.workspace_id, Invoice.id == invoice_id
            )
        )

    def list_for_property(self, property_id: UUID) -> Sequence[Invoice]:
        return self._session.scalars(
            select(Invoice)
            .where(
                Invoice.workspace_id == self._tenant.workspace_id,
                Invoice.property_id == property_id,
            )
            .order_by(Invoice.invoice_date, Invoice.normalized_invoice_number, Invoice.id)
        ).all()

    def lines_of(self, invoice_id: UUID) -> Sequence[InvoiceLine]:
        return self._session.scalars(
            select(InvoiceLine)
            .where(
                InvoiceLine.workspace_id == self._tenant.workspace_id,
                InvoiceLine.invoice_id == invoice_id,
            )
            .order_by(InvoiceLine.source_line_number)
        ).all()

    def find_by_identities(
        self, property_id: UUID, identities: Sequence[InvoiceIdentity]
    ) -> dict[InvoiceIdentity, ExistingInvoice]:
        """The stored invoices of the property at these identities (one statement per block, a
        join with a VALUES list served by the unique identity key). The data source is NOT part of
        the identity: the same invoice from another source is the same invoice."""
        found: dict[InvoiceIdentity, ExistingInvoice] = {}
        ordered = sorted(identities, key=lambda i: (str(i[0]), i[1], i[2], i[3].value))
        for start in range(0, len(ordered), _KEYS_PER_QUERY):
            block = ordered[start : start + _KEYS_PER_QUERY]
            wanted = values(
                column("supplier_id", Uuid),
                column("number", String),
                column("invoice_date", Date),
                column("kind", String),
                name="wanted",
            ).data([(s, n, d, k.value) for s, n, d, k in block])
            rows = self._session.execute(
                select(
                    Invoice.id,
                    Invoice.supplier_id,
                    Invoice.normalized_invoice_number,
                    Invoice.invoice_date,
                    Invoice.document_kind,
                    Invoice.source_fingerprint,
                )
                .join(
                    wanted,
                    (Invoice.supplier_id == wanted.c.supplier_id)
                    & (Invoice.normalized_invoice_number == wanted.c.number)
                    & (Invoice.invoice_date == wanted.c.invoice_date)
                    & (Invoice.document_kind == wanted.c.kind),
                )
                .where(
                    Invoice.workspace_id == self._tenant.workspace_id,
                    Invoice.property_id == property_id,
                )
            )
            for row in rows:
                found[
                    (
                        row.supplier_id,
                        row.normalized_invoice_number,
                        row.invoice_date,
                        row.document_kind,
                    )
                ] = ExistingInvoice(row.id, row.source_fingerprint)
        return found

    def insert_invoices(self, rows: Sequence[dict[str, Any]]) -> None:
        for start in range(0, len(rows), _CHUNK):
            self._session.execute(insert(Invoice), list(rows[start : start + _CHUNK]))

    def insert_lines(self, rows: Sequence[dict[str, Any]]) -> None:
        for start in range(0, len(rows), _CHUNK):
            self._session.execute(insert(InvoiceLine), list(rows[start : start + _CHUNK]))


class InvoiceMappingProfileRepository:
    """The confirmed mapping of each COSTS data source of ONE workspace (at most one each)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_for_data_source(self, data_source_id: UUID) -> InvoiceMappingProfile | None:
        return self._session.scalar(
            select(InvoiceMappingProfile).where(
                InvoiceMappingProfile.workspace_id == self._tenant.workspace_id,
                InvoiceMappingProfile.data_source_id == data_source_id,
            )
        )

    def upsert(
        self,
        data_source: DataSource,
        *,
        stored: dict[str, dict[str, Any]],
        header_signature: str,
    ) -> InvoiceMappingProfile:
        """Replace the current profile of the data source (no history in V1)."""
        statement = (
            pg_insert(InvoiceMappingProfile)
            .values(
                workspace_id=self._tenant.workspace_id,
                property_id=data_source.property_id,
                data_source_id=data_source.id,
                column_mapping=stored["column_mapping"],
                category_mapping=stored["category_mapping"],
                format_options=stored["format_options"],
                header_signature=header_signature,
            )
            .on_conflict_do_update(
                constraint="uq_invoice_mapping_profiles_workspace_id_data_source_id",
                set_={
                    "column_mapping": stored["column_mapping"],
                    "category_mapping": stored["category_mapping"],
                    "format_options": stored["format_options"],
                    "header_signature": header_signature,
                    "updated_at": func.now(),
                },
            )
            .returning(InvoiceMappingProfile)
        )
        profile = self._session.scalars(
            statement, execution_options={"populate_existing": True}
        ).one()
        self._session.flush()
        return profile


class InvoiceImportRowRepository:
    """Staging rows of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add_many(
        self, import_job_id: UUID, import_file_id: UUID, rows: Sequence[StagedRow]
    ) -> None:
        payload = [
            {
                "workspace_id": self._tenant.workspace_id,
                "import_job_id": import_job_id,
                "import_file_id": import_file_id,
                "row_number": row.row_number,
                "source_document_index": row.source_document_index,
                "source_line_number": row.source_line_number,
                "mapped_payload": row.mapped_payload,
                "normalized_payload": row.normalized_payload,
                "validation_status": row.validation_status,
                "validation_errors": row.validation_errors,
                "validation_warnings": row.validation_warnings,
            }
            for row in rows
        ]
        for start in range(0, len(payload), _CHUNK):
            self._session.execute(insert(InvoiceImportRow), payload[start : start + _CHUNK])

    def list_for_job(
        self, import_job_id: UUID, *, status: ImportRowStatus | None = None
    ) -> Sequence[InvoiceImportRow]:
        query = select(InvoiceImportRow).where(
            InvoiceImportRow.workspace_id == self._tenant.workspace_id,
            InvoiceImportRow.import_job_id == import_job_id,
        )
        if status is not None:
            query = query.where(InvoiceImportRow.validation_status == status)
        return self._session.scalars(query.order_by(InvoiceImportRow.row_number)).all()

    def mark_valid_rows_imported(self, import_job_id: UUID) -> int:
        result = self._session.execute(
            update(InvoiceImportRow)
            .where(
                InvoiceImportRow.workspace_id == self._tenant.workspace_id,
                InvoiceImportRow.import_job_id == import_job_id,
                InvoiceImportRow.validation_status == ImportRowStatus.VALID,
            )
            .values(validation_status=ImportRowStatus.IMPORTED)
        )
        return int(getattr(result, "rowcount", 0) or 0)
