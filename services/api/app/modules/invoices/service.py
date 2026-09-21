"""InvoiceImportService: the application service behind an invoice file import.

Framework-free (no HTTP, no FastAPI): a future worker or an authenticated API can call it as is. It
is given a Session and a TenantContext and it OWNS the transaction boundaries:

    T1  create ImportJob (PENDING) + ImportFile metadata, mark RUNNING             commit
    T2  detect type -> parse -> normalise -> group -> validate -> stage each line      commit
    T3  (any invalid row) mark the job FAILED                                    commit
    T4  (all valid) lock, resolve suppliers, write invoices and lines, mark rows
        IMPORTED, job SUCCEEDED                                                  commit / rollback

The job outcome and the staged diagnostics are committed independently of the canonical write, so a
rolled-back canonicalisation still leaves a FAILED job and its staging rows. Canonical data
(new suppliers, identifiers, aliases, reviews, invoices, lines) is written in ONE transaction (T4):
all or nothing. Suppliers are resolved by the separate `SupplierResolver`; classification and
the document sign are canonical-model rules, not import-service rules.

Supported sources: FatturaPA XML 1.2.x (FPR12/FPA12), structured CSV and XLSX. NOT supported: PDF,
scanned documents (OCR) and signed .p7m files.

Pass a session with no uncommitted work: the service commits (and may roll back) it.
"""

import hashlib
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source, lock_supplier_registry
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions
from app.modules.bookings.models import ImportRowStatus
from app.modules.bookings.parsers import open_table
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportJobStatus,
)
from app.modules.ingestion.repository import (
    DataSourceRepository,
    ImportFileRepository,
    ImportJobRepository,
)
from app.modules.ingestion.schemas import ImportFileCreate, ImportJobCreate
from app.modules.invoices.canonical import (
    CanonicalDocument,
    document_from_payloads,
    header_payload,
    line_payload,
)
from app.modules.invoices.classification import classify_line
from app.modules.invoices.documents import ParsedDocument
from app.modules.invoices.errors import InvoiceErrorCode, InvoiceImportError, RowIssue
from app.modules.invoices.fatturapa import parse_fatturapa
from app.modules.invoices.mapping import (
    InvoiceMappingConfig,
    check_schema,
    compute_header_signature,
    header_index,
    normalize_header,
)
from app.modules.invoices.models import InvoiceMappingProfile, ResolutionMethod, SourceFormat
from app.modules.invoices.repository import (
    InvoiceIdentity,
    InvoiceImportRowRepository,
    InvoiceMappingProfileRepository,
    InvoiceRepository,
    StagedRow,
)
from app.modules.invoices.structured import extract, parse_structured, require_explicit_formats
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.suppliers.errors import SupplierError
from app.modules.suppliers.resolution import (
    SupplierEvidence,
    SupplierResolution,
    SupplierResolver,
)

logger = logging.getLogger(__name__)

_MAX_SUMMARY_MESSAGE = 500
SourceKind = Literal["xml", "csv", "xlsx"]

# The Gate 2 readers raise BookingImportError: their codes become the invoice codes.
_READER_CODES = {
    BookingErrorCode.UNSUPPORTED_FILE_TYPE: InvoiceErrorCode.UNSUPPORTED_FILE_TYPE,
    BookingErrorCode.UNREADABLE_FILE: InvoiceErrorCode.UNREADABLE_FILE,
    BookingErrorCode.EMPTY_FILE: InvoiceErrorCode.EMPTY_FILE,
    BookingErrorCode.FILE_LIMIT_EXCEEDED: InvoiceErrorCode.FILE_LIMIT_EXCEEDED,
    BookingErrorCode.DUPLICATE_HEADER: InvoiceErrorCode.DUPLICATE_HEADER,
    BookingErrorCode.MAPPING_REQUIRED: InvoiceErrorCode.MAPPING_REQUIRED,
    BookingErrorCode.SOURCE_SCHEMA_CHANGED: InvoiceErrorCode.SOURCE_SCHEMA_CHANGED,
}


# --- results ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class InvoiceFileDescription:
    """What NINFA finds in a structured file, to help a person write a mapping. Nothing is saved."""

    file_type: str | None
    sheet_name: str | None
    headers: list[str]
    requires_sheet_selection: bool = False
    sheet_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InvoiceImportResult:
    """Outcome of one import. Machine-readable: branch on `error_code`, never on messages.

    `details` and `row_error_summary` hold field names, codes and counts only.
    """

    import_job_id: UUID
    import_file_id: UUID
    status: ImportJobStatus
    error_code: InvoiceErrorCode | str | None
    error_message: str | None
    source_format: SourceFormat | None = None
    documents_total: int = 0
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    invoices_created: int = 0
    invoices_unchanged: int = 0
    lines_created: int = 0
    suppliers_created: int = 0
    suppliers_matched: int = 0
    identifiers_added: int = 0
    aliases_added: int = 0
    reviews_created: int = 0
    row_error_summary: dict[str, int] = field(default_factory=dict)
    warning_summary: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    # Informational: this exact file content was already imported successfully by this data
    # source. The import still runs (idempotently).
    duplicate_of_import_file_id: UUID | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == ImportJobStatus.SUCCEEDED


@dataclass(frozen=True)
class _Ids:
    """Plain ids, captured up front: safe to use after a rollback expired the ORM objects."""

    job: UUID
    file: UUID
    data_source: UUID
    property: UUID


@dataclass(frozen=True)
class _Counts:
    documents: int = 0
    rows: int = 0
    valid: int = 0
    invalid: int = 0


# --- service ----------------------------------------------------------------------------------


class InvoiceImportService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._data_sources = DataSourceRepository(session, tenant)
        self._properties = PropertyRepository(session, tenant)
        self._jobs = ImportJobRepository(session, tenant)
        self._files = ImportFileRepository(session, tenant)
        self._profiles = InvoiceMappingProfileRepository(session, tenant)
        self._rows = InvoiceImportRowRepository(session, tenant)
        self._invoices = InvoiceRepository(session, tenant)
        self._resolver = SupplierResolver(session, tenant)

    # --- mapping ------------------------------------------------------------------------------

    def describe_file(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
        property_id: UUID | None = None,
    ) -> InvoiceFileDescription:
        """The headers (and sheets) of a structured file. Read-only: writes nothing."""
        self._load_source(data_source_id, property_id)
        try:
            table = self._open_table(content, filename, FormatOptions(sheet_name=sheet_name))
        except InvoiceImportError as error:
            if error.error_code == InvoiceErrorCode.MAPPING_REQUIRED and error.details:
                return InvoiceFileDescription(
                    file_type="xlsx",
                    sheet_name=None,
                    headers=[],
                    requires_sheet_selection=True,
                    sheet_names=list(error.details.get("sheet_names", [])),
                )
            raise
        return InvoiceFileDescription(table.file_type, table.sheet_name, table.headers)

    def save_mapping(
        self,
        data_source_id: UUID,
        *,
        headers: list[str],
        column_mapping: dict[str, Any],
        category_mapping: dict[str, str] | None = None,
        format_options: dict[str, Any] | None = None,
        property_id: UUID | None = None,
    ) -> InvoiceMappingProfile:
        """Confirm a mapping for the data source (replacing the current one) and remember the
        header signature of the file it was confirmed on."""
        data_source, _ = self._load_source(data_source_id, property_id)
        config = InvoiceMappingConfig.parse(
            {
                "column_mapping": column_mapping,
                "category_mapping": category_mapping or {},
                "format_options": format_options or {},
            }
        )
        known = header_index(headers)
        unknown = [c for c in config.mapped_columns().values() if normalize_header(c) not in known]
        if unknown:
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_MAPPING,
                "The mapping refers to columns that are not in the file",
                details={"unknown_columns": unknown},
            )
        profile = self._profiles.upsert(
            data_source,
            stored=config.to_stored(),
            header_signature=compute_header_signature(headers),
        )
        self._session.commit()
        logger.info(
            "invoice mapping saved workspace_id=%s property_id=%s data_source_id=%s",
            self._tenant.workspace_id,
            data_source.property_id,
            data_source.id,
        )
        return profile

    # --- import -------------------------------------------------------------------------------

    def import_file(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        property_id: UUID | None = None,
    ) -> InvoiceImportResult:
        """Import one invoice file into the canonical model, atomically and idempotently.

        Raises InvoiceImportError(INVOICE_INVALID_DATA_SOURCE) when the data source cannot be used
        (nothing is created). Every later problem ends as a FAILED ImportJob and a returned result
        with a stable `error_code`.
        """
        data_source, prop = self._load_source(data_source_id, property_id)
        sha256 = hashlib.sha256(content).hexdigest()
        previous = self._files.find_successful_for_data_source(data_source.id, sha256)

        # T1: the attempt is recorded before anything can go wrong.
        job = self._jobs.add(ImportJobCreate(data_source_id=data_source.id))
        import_file = self._files.add(
            job.id,
            ImportFileCreate(
                original_filename=_safe_filename(filename),
                mime_type=mime_type,
                size_bytes=len(content),
                sha256=sha256,
            ),
        )
        self._jobs.start(job.id)
        ids = _Ids(job.id, import_file.id, data_source.id, data_source.property_id)
        duplicate_of = previous.id if previous is not None else None
        currency = prop.currency
        self._session.commit()
        self._log("invoice import started", ids)

        try:
            result = self._run(ids, filename, content, currency, duplicate_of)
        except (InvoiceImportError, SupplierError) as error:
            result = self._fail(ids, error.code, error.message, _details(error), duplicate_of)
        except Exception as error:  # a bug or infrastructure problem: never leave the job RUNNING
            logger.error(
                "invoice import crashed workspace_id=%s import_job_id=%s error_type=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
            )
            result = self._fail(
                ids,
                InvoiceErrorCode.INTERNAL_ERROR,
                "The import stopped because of an internal error",
                None,
                duplicate_of,
            )
        self._log(
            f"invoice import finished status={result.status.value} "
            f"error_code={_code(result.error_code)} documents={result.documents_total} "
            f"rows={result.rows_total} invalid={result.rows_invalid} "
            f"invoices_created={result.invoices_created} unchanged={result.invoices_unchanged} "
            f"suppliers_created={result.suppliers_created} reviews={result.reviews_created}",
            ids,
        )
        return result

    # --- pipeline -----------------------------------------------------------------------------

    def _run(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        currency: str,
        duplicate_of: UUID | None,
    ) -> InvoiceImportResult:
        kind = detect_source(filename, content)
        source_format = {
            "xml": SourceFormat.FATTURAPA_XML,
            "csv": SourceFormat.CSV,
            "xlsx": SourceFormat.XLSX,
        }[kind]
        if kind == "xml":
            documents = parse_fatturapa(content, data_source_id=ids.data_source)
        else:
            documents = self._parse_structured(ids, filename, content, currency, source_format)
        if not documents:
            raise InvoiceImportError(
                InvoiceErrorCode.EMPTY_FILE, "The file has a header but no invoice rows"
            )

        staged, summary, warnings = _stage(documents)
        invalid = sum(1 for row in staged if row.validation_status == ImportRowStatus.INVALID)
        self._rows.add_many(ids.job, ids.file, staged)
        self._session.commit()  # T2: staging and diagnostics are kept whatever happens next

        counts = _Counts(len(documents), len(staged), len(staged) - invalid, invalid)
        if invalid:
            return self._fail(
                ids,
                InvoiceErrorCode.VALIDATION_FAILED,
                f"{invalid} of {len(staged)} rows failed validation: nothing was imported",
                None,
                duplicate_of,
                summary=summary,
                counts=counts,
                warnings=warnings,
                source_format=source_format,
            )
        return self._canonicalize(ids, duplicate_of, counts, warnings, source_format)

    def _parse_structured(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        currency: str,
        source_format: SourceFormat,
    ) -> list[ParsedDocument]:
        profile = self._profiles.get_for_data_source(ids.data_source)
        if profile is None:
            raise InvoiceImportError(
                InvoiceErrorCode.MAPPING_REQUIRED,
                "This data source has no confirmed mapping yet: describe the file and confirm one",
                details={"reason": "no_confirmed_mapping"},
            )
        config = InvoiceMappingConfig.parse(
            {
                "column_mapping": profile.column_mapping,
                "category_mapping": profile.category_mapping,
                "format_options": profile.format_options,
            }
        )
        options = config.format_options
        table = self._open_table(
            content,
            filename,
            FormatOptions(
                sheet_name=options.sheet_name,
                delimiter=options.delimiter,
                encoding=options.encoding,
            ),
        )
        schema = check_schema(config, profile.header_signature, table.headers)
        if not schema.compatible:
            raise InvoiceImportError(
                InvoiceErrorCode.SOURCE_SCHEMA_CHANGED,
                "The file no longer has the columns this data source was mapped on: "
                "review and confirm the mapping again",
                details={
                    "reason": "mapped_columns_missing",
                    "missing_columns": list(schema.missing_columns),
                },
            )
        rows = extract(table, config)
        require_explicit_formats(rows, config)
        return parse_structured(
            rows,
            config,
            property_currency=currency,
            data_source_id=ids.data_source,
            source_format=source_format,
        )

    @staticmethod
    def _open_table(content: bytes, filename: str, options: FormatOptions) -> Any:
        try:
            return open_table(content, filename, options)
        except BookingImportError as error:
            code = _READER_CODES.get(error.error_code, InvoiceErrorCode.UNREADABLE_FILE)
            raise InvoiceImportError(code, error.message, details=error.details) from None

    # --- canonicalisation (T4) ------------------------------------------------------------------

    def _canonicalize(
        self,
        ids: _Ids,
        duplicate_of: UUID | None,
        counts: _Counts,
        warnings: dict[str, int],
        source_format: SourceFormat,
    ) -> InvoiceImportResult:
        """Every valid document becomes a canonical invoice (with its supplier), or none does."""
        try:
            # One canonicalisation per data source at a time, and one supplier registry writer per
            # workspace at a time, always in this order (no lock cycle is possible).
            lock_data_source(self._session, ids.data_source)
            lock_supplier_registry(self._session, self._tenant.workspace_id)

            documents = self._load_documents(ids)
            plan = self._resolver.plan([document.supplier for document in documents])
            self._resolver.apply(plan)
            # A supplier created by this import tells ONE story to all its documents: a sibling
            # document that merely matched it (say, one without the IBAN) was not resolved
            # "by VAT number" in any sense a person would care about.
            created_by = {r.supplier_id: r for r in plan.resolutions.values() if r.created}

            resolved = [
                (document, plan.resolutions[document.supplier.key]) for document in documents
            ]
            identities: dict[InvoiceIdentity, CanonicalDocument] = {}
            keyed: list[tuple[InvoiceIdentity, CanonicalDocument, SupplierResolution]] = []
            duplicated: list[int] = []
            for document, resolution in resolved:
                identity = (
                    resolution.supplier_id,
                    document.normalized_invoice_number,
                    document.invoice_date,
                    document.document_kind,
                )
                if identity in identities:  # the same document twice in one import
                    duplicated.append(document.source_document_index)
                identities[identity] = document
                keyed.append((identity, document, resolution))
            if duplicated:
                raise InvoiceImportError(
                    InvoiceErrorCode.DOCUMENT_CONFLICT,
                    "The same invoice appears more than once in the import",
                    details={"reason": "duplicate_in_import", "documents": duplicated[:50]},
                )

            existing = self._invoices.find_by_identities(ids.property, list(identities))
            conflicts: list[int] = []
            new_invoices: list[dict[str, Any]] = []
            new_lines: list[dict[str, Any]] = []
            unchanged = 0
            for identity, document, resolution in keyed:
                fingerprint = document.fingerprint(str(resolution.supplier_id))
                stored = existing.get(identity)
                if stored is not None:
                    if stored.source_fingerprint == fingerprint:
                        unchanged += 1
                    else:
                        conflicts.append(document.source_document_index)
                    continue
                invoice_id = uuid4()
                new_invoices.append(
                    self._invoice_row(
                        ids,
                        invoice_id,
                        document,
                        resolution,
                        fingerprint,
                        _resolution_story(resolution, created_by),
                    )
                )
                new_lines.extend(self._line_rows(invoice_id, document, resolution))
            if conflicts:
                raise InvoiceImportError(
                    InvoiceErrorCode.DOCUMENT_CONFLICT,
                    "An invoice with this identity already exists with a different content: "
                    "it is never updated silently",
                    details={"reason": "different_content", "documents": conflicts[:50]},
                )

            self._invoices.insert_invoices(new_invoices)
            self._invoices.insert_lines(new_lines)
            self._rows.mark_valid_rows_imported(ids.job)
            self._jobs.succeed(ids.job)
            self._session.commit()
        except (InvoiceImportError, SupplierError):
            raise  # rolled back and recorded as FAILED by import_file
        except Exception as error:
            self._session.rollback()  # nothing of this batch survives
            constraint = _constraint_name(error)
            logger.error(
                "invoice canonicalisation rolled back workspace_id=%s import_job_id=%s "
                "error_type=%s constraint=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
                constraint or "-",
            )
            return self._fail(
                ids,
                InvoiceErrorCode.CANONICALIZATION_FAILED,
                "The database rejected the batch: no invoice was imported",
                {"constraint": constraint} if constraint else None,
                duplicate_of,
                counts=counts,
                warnings=warnings,
                source_format=source_format,
            )
        created_suppliers = list(created_by.values())
        matched_suppliers = {
            r.supplier_id
            for r in plan.resolutions.values()
            if not r.created and r.supplier_id not in created_by
        }
        return InvoiceImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.SUCCEEDED,
            error_code=None,
            error_message=None,
            source_format=source_format,
            documents_total=counts.documents,
            rows_total=counts.rows,
            rows_valid=counts.valid,
            rows_invalid=counts.invalid,
            invoices_created=len(new_invoices),
            invoices_unchanged=unchanged,
            lines_created=len(new_lines),
            suppliers_created=len(created_suppliers),
            suppliers_matched=len(matched_suppliers),
            identifiers_added=len(plan.identifiers) - _identifiers_of_new(plan),
            aliases_added=len(plan.aliases) - len(created_suppliers),
            reviews_created=len(plan.reviews),
            warning_summary=warnings,
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_documents(self, ids: _Ids) -> list[CanonicalDocument]:
        """The canonical documents of the staged VALID rows, in file order."""
        rows = self._rows.list_for_job(ids.job, status=ImportRowStatus.VALID)
        headers: dict[int, dict[str, Any]] = {}
        lines: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            payload = row.normalized_payload or {}
            if "header" in payload:
                headers[row.source_document_index] = payload["header"]
            lines[row.source_document_index].append(payload["line"])
        return [
            document_from_payloads(headers[index], lines[index], ids.data_source)
            for index in sorted(headers)
        ]

    def _invoice_row(
        self,
        ids: _Ids,
        invoice_id: UUID,
        document: CanonicalDocument,
        resolution: SupplierResolution,
        fingerprint: str,
        method: ResolutionMethod,
    ) -> dict[str, Any]:
        return {
            "id": invoice_id,
            "workspace_id": self._tenant.workspace_id,
            "property_id": ids.property,
            "data_source_id": ids.data_source,
            "supplier_id": resolution.supplier_id,
            "invoice_number": document.invoice_number,
            "normalized_invoice_number": document.normalized_invoice_number,
            "invoice_date": document.invoice_date,
            "due_date": document.due_date,
            "document_type_code": document.document_type_code,
            "document_kind": document.document_kind,
            "currency": document.currency,
            "net_amount": document.net_amount,
            "tax_amount": document.tax_amount,
            "gross_amount": document.gross_amount,
            "source_format": document.source_format,
            "source_import_job_id": ids.job,
            "source_import_file_id": ids.file,
            "source_fingerprint": fingerprint,
            "supplier_resolution_method": method,
        }

    def _line_rows(
        self, invoice_id: UUID, document: CanonicalDocument, resolution: SupplierResolution
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line in document.lines:
            classification = classify_line(
                line.description_normalized,
                explicit=line.explicit_category,
                supplier_default=resolution.default_cost_category,
            )
            rows.append(
                {
                    "workspace_id": self._tenant.workspace_id,
                    "invoice_id": invoice_id,
                    "source_line_number": line.source_line_number,
                    "description_raw": line.description_raw,
                    "description_normalized": line.description_normalized,
                    "quantity": line.quantity,
                    "unit": line.unit,
                    "unit_price": line.unit_price,
                    "line_total": line.line_total,
                    "vat_rate": line.vat_rate,
                    "cost_category": classification.category,
                    "classification_confidence": classification.confidence,
                    "classification_method": classification.method,
                }
            )
        return rows

    # --- helpers ------------------------------------------------------------------------------

    def _fail(
        self,
        ids: _Ids,
        code: InvoiceErrorCode | str,
        message: str,
        details: dict[str, Any] | None,
        duplicate_of: UUID | None,
        *,
        summary: dict[str, int] | None = None,
        counts: _Counts | None = None,
        warnings: dict[str, int] | None = None,
        source_format: SourceFormat | None = None,
    ) -> InvoiceImportResult:
        """Record the failure in its own transaction: it survives any data rollback."""
        self._session.rollback()  # drop anything left over from a failed step
        code_text = code.value if isinstance(code, InvoiceErrorCode) else str(code)
        self._jobs.fail(ids.job, error_code=code_text, error_message=message[:_MAX_SUMMARY_MESSAGE])
        self._session.commit()
        counted = counts or _Counts()
        return InvoiceImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.FAILED,
            error_code=code,
            error_message=message[:_MAX_SUMMARY_MESSAGE],
            source_format=source_format,
            documents_total=counted.documents,
            rows_total=counted.rows,
            rows_valid=counted.valid,
            rows_invalid=counted.invalid,
            row_error_summary=summary or {},
            warning_summary=warnings or {},
            details=details or {},
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_source(
        self, data_source_id: UUID, property_id: UUID | None = None
    ) -> tuple[DataSource, Property]:
        """The data source must be an active COSTS/FILE_UPLOAD source of this workspace.

        Unknown ids and ids of another workspace are indistinguishable (same error).
        """
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.COSTS:
            reason = "wrong_domain"
        elif data_source.source_type != DataSourceType.FILE_UPLOAD:
            reason = "wrong_source_type"
        elif not data_source.is_active:
            reason = "inactive"
        elif property_id is not None and data_source.property_id != property_id:
            reason = "property_mismatch"
        prop = self._properties.get(data_source.property_id) if data_source is not None else None
        if reason is None and (prop is None or prop.archived_at is not None):
            reason = "property_unavailable"
        if reason is not None or data_source is None or prop is None:
            raise InvoiceImportError(
                InvoiceErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for invoice imports",
                details={"reason": reason or "not_found"},
            )
        return data_source, prop

    def _log(self, message: str, ids: _Ids) -> None:
        logger.info(
            "%s workspace_id=%s property_id=%s data_source_id=%s "
            "import_job_id=%s import_file_id=%s",
            message,
            self._tenant.workspace_id,
            ids.property,
            ids.data_source,
            ids.job,
            ids.file,
        )


# --- module functions ---------------------------------------------------------------------------


def detect_source(filename: str, content: bytes) -> SourceKind:
    """`.xml` (FatturaPA), `.csv` and `.xlsx` only. PDF, scans and signed `.p7m` are refused."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".xml":
        return "xml"
    if suffix in {".csv", ".xlsx"}:
        return "xlsx" if suffix == ".xlsx" else "csv"
    reason = {".p7m": "signed_p7m_not_supported", ".pdf": "pdf_not_supported"}.get(
        suffix, "unsupported_extension"
    )
    raise InvoiceImportError(
        InvoiceErrorCode.UNSUPPORTED_FILE_TYPE,
        f"Unsupported file type '{suffix or 'none'}': only FatturaPA .xml, .csv and .xlsx are "
        "supported (no PDF, no OCR, no signed .p7m)",
        details={"reason": reason, "supported": [".xml", ".csv", ".xlsx"]},
    )


def _stage(
    documents: list[ParsedDocument],
) -> tuple[list[StagedRow], dict[str, int], dict[str, int]]:
    """One staging row per source line (a document header rides on its first line)."""
    rows: list[StagedRow] = []
    summary: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    for document in documents:
        warnings.update(w.code.value for w in document.warnings)
        canonical = document.canonical if document.valid else None
        located = document.located_issues()
        if not document.lines:  # a document with no line still needs a row to carry its issues
            issues = [item.issue for item in located]
            summary.update(issue.code.value for issue in issues)
            rows.append(
                StagedRow(
                    row_number=len(rows) + 1,
                    source_document_index=document.index,
                    source_line_number=None,
                    mapped_payload=dict(document.mapped_header),
                    normalized_payload=None,
                    validation_status=ImportRowStatus.INVALID,
                    validation_errors=[issue.to_json() for issue in issues],
                    validation_warnings=[w.to_json() for w in document.warnings],
                )
            )
            continue
        for position, line in enumerate(document.lines):
            first = position == 0
            issues = [item.issue for item in located if item.line_index == position]
            if first:
                issues = [item.issue for item in located if item.line_index is None] + issues
            summary.update(issue.code.value for issue in issues)
            if not issues and canonical is None:
                issues = [
                    RowIssue(
                        "document",
                        InvoiceErrorCode.VALIDATION_FAILED,
                        "another line or the document header is invalid",
                    )
                ]
            mapped = dict(document.mapped_header) if first else {}
            mapped.update(line.mapped)
            normalized: dict[str, Any] | None = None
            if canonical is not None and not issues:
                normalized = {"line": line_payload(canonical.lines[position])}
                if first:
                    normalized["header"] = header_payload(canonical)
            rows.append(
                StagedRow(
                    row_number=len(rows) + 1,
                    source_document_index=document.index,
                    source_line_number=line.source_line_number,
                    mapped_payload=mapped,
                    normalized_payload=normalized,
                    validation_status=(
                        ImportRowStatus.INVALID if issues else ImportRowStatus.VALID
                    ),
                    validation_errors=[issue.to_json() for issue in issues],
                    validation_warnings=([w.to_json() for w in document.warnings] if first else []),
                )
            )
    return rows, dict(sorted(summary.items())), dict(sorted(warnings.items()))


def _resolution_story(
    resolution: SupplierResolution, created_by: dict[UUID, SupplierResolution]
) -> ResolutionMethod:
    """How a document's supplier was resolved: the creation story when this import created it."""
    origin = created_by.get(resolution.supplier_id)
    return origin.method if origin is not None else resolution.method


def _identifiers_of_new(plan: Any) -> int:
    """Identifiers written for suppliers created in this import (not counted as 'added')."""
    created = {item.id for item in plan.suppliers}
    return sum(1 for item in plan.identifiers if item.supplier_id in created)


def _details(error: InvoiceImportError | SupplierError) -> dict[str, Any] | None:
    details = error.details
    return details if isinstance(details, dict) else None


def _code(code: InvoiceErrorCode | str | None) -> str:
    if code is None:
        return "-"
    return code.value if isinstance(code, InvoiceErrorCode) else str(code)


def _safe_filename(filename: str) -> str:
    """Base name only (no client path), bounded, never empty."""
    name = PurePath(filename.replace("\\", "/")).name.strip()
    return (name or "upload")[:255]


def _constraint_name(error: Exception) -> str | None:
    """The violated constraint of a database error: a schema name, never row data."""
    if isinstance(error, DBAPIError):
        diag = getattr(error.orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
        return name if isinstance(name, str) else None
    return None


__all__ = [
    "InvoiceFileDescription",
    "InvoiceImportResult",
    "InvoiceImportService",
    "SupplierEvidence",
    "detect_source",
]
