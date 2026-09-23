"""LaborImportService: the application service behind a labor file import.

Framework-free (no HTTP, no FastAPI): a future worker or an authenticated API can call it as is.
It is given a Session and a TenantContext and it OWNS the transaction boundaries:

    T1  create ImportJob (PENDING) + ImportFile metadata, mark RUNNING             commit
    T2  detect type -> parse -> map -> normalise -> classify -> validate -> stage      commit
    T3  (any invalid row) mark the job FAILED                                    commit
    T4  (all valid) lock, write the LaborSnapshot + its LaborEntry rows (or reuse an
        identical existing snapshot), mark rows IMPORTED, job SUCCEEDED          commit / rollback

The job outcome and the staged diagnostics are committed independently of the canonical write, so
a rolled-back canonicalisation still leaves a FAILED job and its staging rows. `snapshot_local_date`
is always given EXPLICITLY by the caller (never `date.today()`, never a file's mtime): determinism,
replay and backtest all depend on it.

Supported sources: structured CSV and XLSX. NOT supported: PDF, OCR, an HR API, calendar scraping.

Pass a session with no uncommitted work: the service commits (and may roll back) it.
"""

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source
from app.modules.bookings.errors import BookingErrorCode, BookingImportError
from app.modules.bookings.mapping import FormatOptions as BookingFormatOptions
from app.modules.bookings.models import ImportRowStatus
from app.modules.bookings.parsers import SourceTable, open_table
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
from app.modules.labor.canonical import (
    CanonicalEntry,
    entry_from_payload,
    entry_payload,
    snapshot_fingerprint,
)
from app.modules.labor.errors import LaborErrorCode, LaborImportError
from app.modules.labor.mapping import (
    LaborMappingConfig,
    check_schema,
    compute_header_signature,
    header_index,
    normalize_header,
)
from app.modules.labor.models import LaborMappingProfile
from app.modules.labor.repository import (
    LaborEntryRepository,
    LaborImportRowRepository,
    LaborMappingProfileRepository,
    LaborSnapshotRepository,
    StagedRow,
)
from app.modules.labor.structured import (
    ParsedLaborRow,
    extract,
    parse_structured,
    require_explicit_formats,
)
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository

logger = logging.getLogger(__name__)

_MAX_SUMMARY_MESSAGE = 500

# The Gate 2 readers raise BookingImportError: their codes become the labor codes.
_READER_CODES = {
    BookingErrorCode.UNSUPPORTED_FILE_TYPE: LaborErrorCode.UNSUPPORTED_FILE_TYPE,
    BookingErrorCode.UNREADABLE_FILE: LaborErrorCode.UNREADABLE_FILE,
    BookingErrorCode.EMPTY_FILE: LaborErrorCode.EMPTY_FILE,
    BookingErrorCode.FILE_LIMIT_EXCEEDED: LaborErrorCode.FILE_LIMIT_EXCEEDED,
    BookingErrorCode.DUPLICATE_HEADER: LaborErrorCode.DUPLICATE_HEADER,
    BookingErrorCode.MAPPING_REQUIRED: LaborErrorCode.MAPPING_REQUIRED,
    BookingErrorCode.SOURCE_SCHEMA_CHANGED: LaborErrorCode.SOURCE_SCHEMA_CHANGED,
}


# --- results ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LaborFileDescription:
    """What NINFA finds in a structured file, to help a person write a mapping. Nothing is saved."""

    file_type: str | None
    sheet_name: str | None
    headers: list[str]
    requires_sheet_selection: bool = False
    sheet_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LaborImportResult:
    """Outcome of one import. Machine-readable: branch on `error_code`, never on messages."""

    import_job_id: UUID
    import_file_id: UUID
    status: ImportJobStatus
    error_code: LaborErrorCode | str | None
    error_message: str | None
    labor_snapshot_id: UUID | None = None
    snapshot_reused: bool = False
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    entries_created: int = 0
    row_error_summary: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
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
    rows: int = 0
    valid: int = 0
    invalid: int = 0


# --- service ------------------------------------------------------------------------------------


class LaborImportService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Labor Import service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._data_sources = DataSourceRepository(session, tenant)
        self._properties = PropertyRepository(session, tenant)
        self._jobs = ImportJobRepository(session, tenant)
        self._files = ImportFileRepository(session, tenant)
        self._profiles = LaborMappingProfileRepository(session, tenant)
        self._rows = LaborImportRowRepository(session, tenant)
        self._snapshots = LaborSnapshotRepository(session, tenant)
        self._entries = LaborEntryRepository(session, tenant)

    # --- mapping ------------------------------------------------------------------------------

    def describe_file(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
        property_id: UUID | None = None,
    ) -> LaborFileDescription:
        """The headers (and sheets) of a structured file. Read-only: writes nothing."""
        self._load_source(data_source_id, property_id)
        try:
            table = self._open_table(content, filename, sheet_name)
        except LaborImportError as error:
            if error.error_code == LaborErrorCode.MAPPING_REQUIRED and error.details:
                return LaborFileDescription(
                    file_type="xlsx",
                    sheet_name=None,
                    headers=[],
                    requires_sheet_selection=True,
                    sheet_names=list(error.details.get("sheet_names", [])),
                )
            raise
        return LaborFileDescription(table.file_type, table.sheet_name, table.headers)

    def save_mapping(
        self,
        data_source_id: UUID,
        *,
        headers: list[str],
        column_mapping: dict[str, Any],
        role_mapping: dict[str, str] | None = None,
        format_options: dict[str, Any] | None = None,
        property_id: UUID | None = None,
    ) -> LaborMappingProfile:
        """Confirm a mapping for the data source (replacing the current one)."""
        data_source, _ = self._load_source(data_source_id, property_id)
        config = LaborMappingConfig.parse(
            {
                "column_mapping": column_mapping,
                "role_mapping": role_mapping or {},
                "format_options": format_options or {},
            }
        )
        known = header_index(headers)
        unknown = [c for c in config.mapped_columns().values() if normalize_header(c) not in known]
        if unknown:
            raise LaborImportError(
                LaborErrorCode.INVALID_MAPPING,
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
            "labor mapping saved workspace_id=%s property_id=%s data_source_id=%s",
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
        snapshot_local_date: date,
        mime_type: str | None = None,
        property_id: UUID | None = None,
    ) -> LaborImportResult:
        """Import one labor file into the canonical model, atomically and idempotently.

        `snapshot_local_date` must be an explicit `date` (never a `datetime`, never inferred):
        it is the local day NINFA's knowledge is dated as of.
        """
        if type(snapshot_local_date) is not date:
            raise LaborImportError(
                LaborErrorCode.SNAPSHOT_DATE_REQUIRED,
                "snapshot_local_date must be given explicitly as a date",
                details={"reason": "missing_or_not_a_date"},
            )
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
        self._session.commit()
        self._log("labor import started", ids)

        try:
            result = self._run(ids, filename, content, snapshot_local_date, duplicate_of, prop)
        except LaborImportError as error:
            result = self._fail(ids, error.error_code, error.message, _details(error), duplicate_of)
        except Exception as error:  # a bug or infrastructure problem: never leave the job RUNNING
            logger.error(
                "labor import crashed workspace_id=%s import_job_id=%s error_type=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
            )
            result = self._fail(
                ids,
                LaborErrorCode.INTERNAL_ERROR,
                "The import stopped because of an internal error",
                None,
                duplicate_of,
            )
        self._log(
            f"labor import finished status={result.status.value} "
            f"error_code={_code(result.error_code)} rows={result.rows_total} "
            f"invalid={result.rows_invalid} entries_created={result.entries_created} "
            f"snapshot_reused={result.snapshot_reused}",
            ids,
        )
        return result

    # --- pipeline -----------------------------------------------------------------------------

    def _run(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        snapshot_local_date: date,
        duplicate_of: UUID | None,
        prop: Property,
    ) -> LaborImportResult:
        profile = self._profiles.get_for_data_source(ids.data_source)
        if profile is None:
            raise LaborImportError(
                LaborErrorCode.MAPPING_REQUIRED,
                "This data source has no confirmed mapping yet: describe the file and confirm one",
                details={"reason": "no_confirmed_mapping"},
            )
        config = LaborMappingConfig.parse(
            {
                "column_mapping": profile.column_mapping,
                "role_mapping": profile.role_mapping,
                "format_options": profile.format_options,
            }
        )
        options = config.format_options
        table = self._open_table(content, filename, options.sheet_name, options=options)
        schema = check_schema(config, profile.header_signature, table.headers)
        if not schema.compatible:
            raise LaborImportError(
                LaborErrorCode.SOURCE_SCHEMA_CHANGED,
                "The file no longer has the columns this data source was mapped on: "
                "review and confirm the mapping again",
                details={
                    "reason": "mapped_columns_missing",
                    "missing_columns": list(schema.missing_columns),
                },
            )
        raw_rows = extract(table, config)
        if not raw_rows:
            raise LaborImportError(LaborErrorCode.EMPTY_FILE, "The file has a header but no rows")
        require_explicit_formats(raw_rows, config)
        parsed = parse_structured(raw_rows, config)

        staged, summary = _stage(parsed)
        invalid = sum(1 for row in staged if row.validation_status == ImportRowStatus.INVALID)
        self._rows.add_many(ids.job, ids.file, staged)
        self._session.commit()  # T2: staging and diagnostics are kept whatever happens next

        counts = _Counts(len(staged), len(staged) - invalid, invalid)
        if invalid:
            return self._fail(
                ids,
                LaborErrorCode.VALIDATION_FAILED,
                f"{invalid} of {len(staged)} rows failed validation: nothing was imported",
                None,
                duplicate_of,
                summary=summary,
                counts=counts,
            )
        return self._canonicalize(ids, snapshot_local_date, duplicate_of, counts, prop)

    def _open_table(
        self,
        content: bytes,
        filename: str,
        sheet_name: str | None,
        *,
        options: Any = None,
    ) -> SourceTable:
        booking_options = BookingFormatOptions(
            sheet_name=sheet_name,
            delimiter=None if options is None else options.delimiter,
            encoding=None if options is None else options.encoding,
        )
        try:
            return open_table(content, filename, booking_options)
        except BookingImportError as error:
            code = _READER_CODES.get(error.error_code, LaborErrorCode.UNREADABLE_FILE)
            raise LaborImportError(code, error.message, details=error.details) from None

    # --- canonicalisation (T4) ------------------------------------------------------------------

    def _canonicalize(
        self,
        ids: _Ids,
        snapshot_local_date: date,
        duplicate_of: UUID | None,
        counts: _Counts,
        prop: Property,
    ) -> LaborImportResult:
        """Every valid row becomes a canonical entry of ONE labor snapshot, or none does."""
        try:
            lock_data_source(self._session, ids.data_source)  # one canonicalisation per source

            entries = self._load_entries(ids)
            fingerprint = snapshot_fingerprint(
                snapshot_local_date=snapshot_local_date,
                property_id=str(ids.property),
                data_source_id=str(ids.data_source),
                entries=entries,
            )
            existing = self._snapshots.get_by_identity(ids.data_source, snapshot_local_date)
            if existing is not None:
                if existing.source_fingerprint != fingerprint:
                    raise LaborImportError(
                        LaborErrorCode.SNAPSHOT_CONFLICT,
                        "A labor snapshot already exists for this date with different content: "
                        "a revision must arrive as a new snapshot date",
                        details={"reason": "different_content"},
                    )
                snapshot_id = existing.id
                created = 0
                reused = True
            else:
                snapshot = self._snapshots.insert(
                    {
                        "id": uuid4(),
                        "workspace_id": self._tenant.workspace_id,
                        "property_id": ids.property,
                        "data_source_id": ids.data_source,
                        "snapshot_local_date": snapshot_local_date,
                        "source_import_job_id": ids.job,
                        "source_import_file_id": ids.file,
                        "source_fingerprint": fingerprint,
                    }
                )
                self._entries.insert_many(
                    [self._entry_row(snapshot.id, entry) for entry in entries]
                )
                snapshot_id = snapshot.id
                created = len(entries)
                reused = False

            self._rows.mark_valid_rows_imported(ids.job)
            self._jobs.succeed(ids.job)
            self._session.commit()
        except LaborImportError:
            raise  # rolled back and recorded as FAILED by import_file
        except Exception as error:
            self._session.rollback()  # nothing of this batch survives
            constraint = _constraint_name(error)
            logger.error(
                "labor canonicalisation rolled back workspace_id=%s import_job_id=%s "
                "error_type=%s constraint=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
                constraint or "-",
            )
            return self._fail(
                ids,
                LaborErrorCode.CANONICALIZATION_FAILED,
                "The database rejected the batch: no labor snapshot was imported",
                {"constraint": constraint} if constraint else None,
                duplicate_of,
                counts=counts,
            )
        return LaborImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.SUCCEEDED,
            error_code=None,
            error_message=None,
            labor_snapshot_id=snapshot_id,
            snapshot_reused=reused,
            rows_total=counts.rows,
            rows_valid=counts.valid,
            rows_invalid=counts.invalid,
            entries_created=created,
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_entries(self, ids: _Ids) -> list[CanonicalEntry]:
        """The canonical entries of the staged VALID rows, in file order."""
        rows = self._rows.list_for_job(ids.job, status=ImportRowStatus.VALID)
        return [
            entry_from_payload(row.normalized_payload) for row in rows if row.normalized_payload
        ]

    def _entry_row(self, snapshot_id: UUID, entry: CanonicalEntry) -> dict[str, Any]:
        return {
            "workspace_id": self._tenant.workspace_id,
            "labor_snapshot_id": snapshot_id,
            "source_row_number": entry.source_row_number,
            "work_date": entry.work_date,
            "role_raw": entry.role_raw,
            "role_normalized": entry.role_normalized,
            "labor_category": entry.labor_category,
            "planned_minutes": entry.planned_minutes,
            "actual_minutes": entry.actual_minutes,
            "planned_cost": entry.planned_cost,
            "actual_cost": entry.actual_cost,
            "currency": entry.currency,
            "classification_method": entry.classification_method,
            "classification_confidence": entry.classification_confidence,
        }

    # --- helpers ------------------------------------------------------------------------------

    def _fail(
        self,
        ids: _Ids,
        code: LaborErrorCode | str,
        message: str,
        details: dict[str, Any] | None,
        duplicate_of: UUID | None,
        *,
        summary: dict[str, int] | None = None,
        counts: _Counts | None = None,
    ) -> LaborImportResult:
        """Record the failure in its own transaction: it survives any data rollback."""
        self._session.rollback()  # drop anything left over from a failed step
        code_text = code.value if isinstance(code, LaborErrorCode) else str(code)
        self._jobs.fail(ids.job, error_code=code_text, error_message=message[:_MAX_SUMMARY_MESSAGE])
        self._session.commit()
        counted = counts or _Counts()
        return LaborImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.FAILED,
            error_code=code,
            error_message=message[:_MAX_SUMMARY_MESSAGE],
            rows_total=counted.rows,
            rows_valid=counted.valid,
            rows_invalid=counted.invalid,
            row_error_summary=summary or {},
            details=details or {},
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_source(
        self, data_source_id: UUID, property_id: UUID | None = None
    ) -> tuple[DataSource, Property]:
        """The data source must be an active LABOR/FILE_UPLOAD source of this workspace.

        Unknown ids and ids of another workspace are indistinguishable (same error).
        """
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.LABOR:
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
            raise LaborImportError(
                LaborErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for labor imports",
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


# --- module functions -----------------------------------------------------------------------------


def _stage(rows: list[ParsedLaborRow]) -> tuple[list[StagedRow], dict[str, int]]:
    """One staging row per source row (a labor file has no header/lines nesting)."""
    staged: list[StagedRow] = []
    summary: Counter[str] = Counter()
    for row in rows:
        entry = row.to_entry()
        summary.update(issue.code.value for issue in row.issues)
        staged.append(
            StagedRow(
                source_row_number=row.number,
                mapped_payload=dict(row.mapped),
                normalized_payload=None if entry is None else entry_payload(entry),
                validation_status=(
                    ImportRowStatus.INVALID if row.issues else ImportRowStatus.VALID
                ),
                validation_errors=[issue.to_json() for issue in row.issues],
                validation_warnings=[],
            )
        )
    return staged, dict(sorted(summary.items()))


def _details(error: LaborImportError) -> dict[str, Any] | None:
    details = error.details
    return details if isinstance(details, dict) else None


def _code(code: LaborErrorCode | str | None) -> str:
    if code is None:
        return "-"
    return code.value if isinstance(code, LaborErrorCode) else str(code)


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


__all__ = ["LaborFileDescription", "LaborImportResult", "LaborImportService"]
