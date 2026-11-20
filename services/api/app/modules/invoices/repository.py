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

from sqlalchemy import (
    Date,
    String,
    Uuid,
    and_,
    any_,
    bindparam,
    column,
    func,
    insert,
    select,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.models import ImportRowStatus
from app.modules.ingestion.models import DataSource
from app.modules.invoices.cost_categories import ClassificationMethod, CostCategory
from app.modules.invoices.models import (
    DocumentKind,
    IdentityOrigin,
    Invoice,
    InvoiceImportRow,
    InvoiceLine,
    InvoiceMappingProfile,
    InvoiceRemoval,
    SourceFormat,
    is_current_invoice,
    is_latest_revision,
    is_removed,
)

_CHUNK = 1000
_KEYS_PER_QUERY = 2000

# (supplier_id, source record key, invoice date, document kind): the identity of a cost record
# inside one property. The key is the normalised invoice number of a real document, or the
# content-derived key of an operating cost that has no number (ADR 0057).
InvoiceIdentity = tuple[UUID, str, date, DocumentKind]


@dataclass(frozen=True, slots=True)
class ExistingInvoice:
    id: UUID
    source_fingerprint: str
    revision: int = 1
    source_format: SourceFormat = SourceFormat.FATTURAPA_XML
    # A synthetic record a person's word took away (never true of a record with a number).
    removed: bool = False


@dataclass(frozen=True, slots=True)
class ExistingRecord:
    """A SYNTHETIC cost record already in a data source (ADR 0057): which of its identical siblings
    it is (`occurrence`), which version it is, whether a person's word took it away, and the
    category the SOURCE stated for it (None: the source stated none, and whatever NINFA derived is
    not a statement of the source and never a reason to change anything)."""

    id: UUID
    key: str
    occurrence: int
    revision: int
    removed: bool
    category: CostCategory | None


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
            .order_by(Invoice.invoice_date, Invoice.source_record_key, Invoice.id)
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
        """The LATEST version of the records of the property at these identities (one statement per
        block, a join with a VALUES list served by the unique identity key), whether or not it still
        counts: `removed` says a person's word took it away, and a record that comes back is then
        the next revision, never a row that already exists. The data source is NOT part of the
        identity of a real document: the same invoice from another source is the same invoice."""
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
                    Invoice.source_record_key,
                    Invoice.invoice_date,
                    Invoice.document_kind,
                    Invoice.source_fingerprint,
                    Invoice.revision,
                    Invoice.source_format,
                    is_removed().label("removed"),
                )
                .join(
                    wanted,
                    (Invoice.supplier_id == wanted.c.supplier_id)
                    & (Invoice.source_record_key == wanted.c.number)
                    & (Invoice.invoice_date == wanted.c.invoice_date)
                    & (Invoice.document_kind == wanted.c.kind),
                )
                .where(
                    Invoice.workspace_id == self._tenant.workspace_id,
                    Invoice.property_id == property_id,
                    is_latest_revision(),
                )
            )
            for row in rows:
                found[
                    (
                        row.supplier_id,
                        row.source_record_key,
                        row.invoice_date,
                        row.document_kind,
                    )
                ] = ExistingInvoice(
                    row.id,
                    row.source_fingerprint,
                    row.revision,
                    row.source_format,
                    bool(row.removed),
                )
        return found

    def synthetic_records_of(
        self,
        property_id: UUID,
        data_source_id: UUID,
        fingerprints: Sequence[str],
        dates: Sequence[date],
    ) -> dict[str, list[ExistingRecord]]:
        """The latest version of every SYNTHETIC record of this data source that has one of these
        content fingerprints (the date narrows the search to what the file can hold), by
        fingerprint, whether or not it still counts. A record's category is the one its source
        STATED (`EXPLICIT_SOURCE`), never one NINFA derived."""
        found: dict[str, list[ExistingRecord]] = {}
        ordered = sorted(set(fingerprints))
        for start in range(0, len(ordered), _KEYS_PER_QUERY):
            block = ordered[start : start + _KEYS_PER_QUERY]
            rows = self._session.execute(
                select(
                    Invoice.id,
                    Invoice.source_record_key,
                    Invoice.revision,
                    Invoice.source_fingerprint,
                    is_removed().label("removed"),
                    InvoiceLine.cost_category,
                    InvoiceLine.classification_method,
                )
                .join(
                    InvoiceLine,
                    and_(
                        InvoiceLine.workspace_id == Invoice.workspace_id,
                        InvoiceLine.invoice_id == Invoice.id,
                    ),
                    isouter=True,
                )
                .where(
                    Invoice.workspace_id == self._tenant.workspace_id,
                    Invoice.property_id == property_id,
                    Invoice.data_source_id == data_source_id,
                    Invoice.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD,
                    Invoice.invoice_date.in_(sorted(set(dates))),
                    Invoice.source_fingerprint.in_(block),
                    is_latest_revision(),
                )
            )
            for row in rows:
                stated = (
                    row.cost_category
                    if row.classification_method == ClassificationMethod.EXPLICIT_SOURCE
                    else None
                )
                found.setdefault(row.source_fingerprint, []).append(
                    ExistingRecord(
                        row.id,
                        row.source_record_key,
                        int(row.source_record_key.rsplit("#", 1)[1]),
                        row.revision,
                        bool(row.removed),
                        stated,
                    )
                )
        for records in found.values():
            records.sort(key=lambda record: record.occurrence)
        return found

    # --- operating costs with no document number: what a complete file takes away --------------

    def _synthetic_absent_from(
        self,
        data_source_id: UUID,
        register: str,
        held_keys: Sequence[str],
        first: date,
        last: date,
    ) -> Any:
        """The SYNTHETIC records of this data source WRITTEN BY THIS REGISTER that count, are dated
        within the file's own period and are not among the keys the file holds. Real documents, and
        what another register of the same property wrote, are never in it."""
        held = bindparam("held_keys", list(held_keys), type_=ARRAY(String))
        return select(Invoice.id, Invoice.property_id).where(
            Invoice.workspace_id == self._tenant.workspace_id,
            Invoice.data_source_id == data_source_id,
            Invoice.identity_origin == IdentityOrigin.SYNTHETIC_COST_RECORD,
            Invoice.cost_register_key == register,
            Invoice.invoice_date >= first,
            Invoice.invoice_date <= last,
            ~(Invoice.source_record_key == any_(held)),
            is_current_invoice(),
        )

    def count_synthetic_absent_from(
        self,
        data_source_id: UUID,
        register: str,
        held_keys: Sequence[str],
        first: date,
        last: date,
    ) -> int:
        """How many records of this source would stop counting if the file holds everything of the
        period it covers (first to last date of its own rows). Read-only."""
        absent = self._synthetic_absent_from(
            data_source_id, register, held_keys, first, last
        ).subquery()
        return int(self._session.scalar(select(func.count()).select_from(absent)) or 0)

    def remove_synthetic_absent_from(
        self,
        data_source_id: UUID,
        register: str,
        import_job_id: UUID,
        held_keys: Sequence[str],
        first: date,
        last: date,
    ) -> int:
        """Take those records away: a removal row each, written with the import that did it. The
        invoices themselves are immutable and stay."""
        absent = self._synthetic_absent_from(
            data_source_id, register, held_keys, first, last
        ).subquery()
        # (RETURNING, not `rowcount`: an INSERT ... SELECT does not report how many rows it wrote)
        removed = self._session.scalars(
            insert(InvoiceRemoval)
            .from_select(
                [
                    "workspace_id",
                    "property_id",
                    "data_source_id",
                    "invoice_id",
                    "identity_origin",
                    "removed_by_import_job_id",
                ],
                select(
                    bindparam("workspace_id", self._tenant.workspace_id, type_=Uuid),
                    absent.c.property_id,
                    bindparam("data_source_id", data_source_id, type_=Uuid),
                    absent.c.id,
                    bindparam(
                        "identity_origin",
                        IdentityOrigin.SYNTHETIC_COST_RECORD.value,
                        type_=String,
                    ),
                    bindparam("job_id", import_job_id, type_=Uuid),
                ),
                # (the id is PostgreSQL's gen_random_uuid(), one per row: the ORM's Python default
                # would be evaluated ONCE and repeated on every row of an INSERT ... SELECT, so a
                # complete file taking away two records or more would break the primary key)
                include_defaults=False,
            )
            .returning(InvoiceRemoval.id)
        ).all()
        return len(removed)

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

    def delete_for_data_source(self, data_source_id: UUID) -> bool:
        """Forget the confirmed mapping (configuration only: no imported data is touched)."""
        profile = self.get_for_data_source(data_source_id)
        if profile is None:
            return False
        self._session.delete(profile)
        self._session.flush()
        return True

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
