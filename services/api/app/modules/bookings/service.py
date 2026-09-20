"""BookingImportService: the application service behind a booking file import.

Framework-free (no HTTP, no FastAPI): a future worker or an authenticated API can call it as is.
It is given a Session and a TenantContext, and it OWNS the transaction boundaries:

    T1  create ImportJob (PENDING) + ImportFile metadata, mark RUNNING           commit
    T2  parse -> map -> normalise -> validate -> stage every row                  commit
    T3  (any invalid row) mark the job FAILED                                     commit
    T4  (all valid) lock, upsert bookings, mark rows IMPORTED, job SUCCEEDED      commit / rollback

The job outcome and the staged diagnostics are committed independently of the canonical write,
so a rolled-back canonicalisation still leaves a FAILED job and its staging rows. Canonical
bookings are written in ONE transaction (T4): all or nothing.

Pass a session with no uncommitted work: the service commits (and may roll back) it.
"""

import hashlib
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.errors import BookingErrorCode, BookingImportError, RowIssue
from app.modules.bookings.mapping import (
    DATE_FIELDS,
    DECIMAL_FIELDS,
    CanonicalField,
    FormatOptions,
    MappingConfig,
    check_schema,
    compute_header_signature,
    header_index,
    normalize_header,
)
from app.modules.bookings.models import (
    BookingMappingProfile,
    ImportRowStatus,
)
from app.modules.bookings.normalization import (
    NormalizationContext,
    NormalizedBooking,
    detect_date_order,
    diagnostic_text,
    needs_date_format,
    needs_number_format,
    normalize_row,
    parse_source_record_id,
)
from app.modules.bookings.parsers import Cell, SourceTable, detect_file_type, open_table
from app.modules.bookings.repository import (
    BookingChannelRepository,
    BookingImportRowRepository,
    BookingMappingProfileRepository,
    BookingRepository,
    ImportItem,
    StagedRow,
)
from app.modules.bookings.suggestions import MappingSuggestion, suggest_mapping
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
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository

logger = logging.getLogger(__name__)

F = CanonicalField
_MAX_SUMMARY_MESSAGE = 500


# --- results ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingSuggestionResult:
    """What NINFA proposes for a file. Nothing here is saved or applied."""

    file_type: str | None
    sheet_name: str | None
    headers: list[str]
    suggestions: list[MappingSuggestion]
    # Evidence about day/month order of suggested date columns (a proposal for date_formats).
    date_order_hints: dict[str, str]
    requires_sheet_selection: bool = False
    sheet_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BookingImportResult:
    """Outcome of one import. Machine-readable: branch on `error_code`, never on messages.

    `details` and `row_error_summary` hold field names, codes and counts only.
    """

    import_job_id: UUID
    import_file_id: UUID
    status: ImportJobStatus
    error_code: BookingErrorCode | None
    error_message: str | None
    rows_total: int = 0
    rows_valid: int = 0
    rows_invalid: int = 0
    bookings_created: int = 0
    bookings_updated: int = 0
    bookings_unchanged: int = 0
    row_error_summary: dict[str, int] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    # Informational: this exact file content was already imported successfully by this data
    # source. The import still runs (idempotently); see docs/architecture/booking-data-v1.md.
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
class _RowCounts:
    total: int = 0
    valid: int = 0
    invalid: int = 0


@dataclass(frozen=True)
class _ExtractedRow:
    number: int
    values: dict[CanonicalField, Cell]  # ONLY the mapped columns of the source row


# --- service ----------------------------------------------------------------------------------


class BookingImportService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._data_sources = DataSourceRepository(session, tenant)
        self._properties = PropertyRepository(session, tenant)
        self._jobs = ImportJobRepository(session, tenant)
        self._files = ImportFileRepository(session, tenant)
        self._profiles = BookingMappingProfileRepository(session, tenant)
        self._rows = BookingImportRowRepository(session, tenant)
        self._channels = BookingChannelRepository(session, tenant)
        self._bookings = BookingRepository(session, tenant)

    # --- mapping ------------------------------------------------------------------------------

    def suggest_mapping(
        self,
        data_source_id: UUID,
        *,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
        property_id: UUID | None = None,
    ) -> MappingSuggestionResult:
        """Propose a mapping for a file. Read-only: writes nothing, applies nothing."""
        self._load_source(data_source_id, property_id)
        try:
            table = open_table(content, filename, FormatOptions(sheet_name=sheet_name))
        except BookingImportError as error:
            if error.error_code == BookingErrorCode.MAPPING_REQUIRED and error.details:
                return MappingSuggestionResult(
                    file_type="xlsx",
                    sheet_name=None,
                    headers=[],
                    suggestions=[],
                    date_order_hints={},
                    requires_sheet_selection=True,
                    sheet_names=list(error.details.get("sheet_names", [])),
                )
            raise
        suggestions = suggest_mapping(table.headers)
        return MappingSuggestionResult(
            file_type=table.file_type,
            sheet_name=table.sheet_name,
            headers=table.headers,
            suggestions=suggestions,
            date_order_hints=self._date_order_hints(table, suggestions),
        )

    def save_mapping(
        self,
        data_source_id: UUID,
        *,
        headers: list[str],
        column_mapping: dict[str, Any],
        status_mapping: dict[str, str] | None = None,
        channel_mapping: dict[str, Any] | None = None,
        format_options: dict[str, Any] | None = None,
        property_id: UUID | None = None,
    ) -> BookingMappingProfile:
        """Confirm a mapping for the data source (replacing the current one) and remember the
        header signature of the file it was confirmed on.
        """
        data_source, _ = self._load_source(data_source_id, property_id)
        config = MappingConfig.parse(
            {
                "column_mapping": column_mapping,
                "status_mapping": status_mapping or {},
                "channel_mapping": channel_mapping or {},
                "format_options": format_options or {},
            }
        )
        known = header_index(headers)
        unknown = [c for c in config.mapped_columns().values() if normalize_header(c) not in known]
        if unknown:
            raise BookingImportError(
                BookingErrorCode.INVALID_MAPPING,
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
            "booking mapping saved workspace_id=%s property_id=%s data_source_id=%s",
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
    ) -> BookingImportResult:
        """Import one booking file into the canonical model, atomically and idempotently.

        `property_id` is optional: pass it when the caller works on a specific property, and a
        data source of any other property is refused.

        Raises BookingImportError(BOOKING_INVALID_DATA_SOURCE) when the data source cannot be
        used (nothing is created). Every later problem ends as a FAILED ImportJob and a returned
        result with a stable `error_code`.
        """
        data_source, prop = self._load_source(data_source_id, property_id)
        timezone = self._timezone(prop)
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
        self._log("booking import started", ids)

        try:
            result = self._run(ids, filename, content, timezone, duplicate_of)
        except BookingImportError as error:
            result = self._fail(ids, error.error_code, error.message, error.details, duplicate_of)
        except Exception as error:  # a bug or infrastructure problem: never leave the job RUNNING
            logger.error(
                "booking import crashed workspace_id=%s import_job_id=%s error_type=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
            )
            result = self._fail(
                ids,
                BookingErrorCode.INTERNAL_ERROR,
                "The import stopped because of an internal error",
                None,
                duplicate_of,
            )
        self._log(
            f"booking import finished status={result.status.value} "
            f"error_code={result.error_code.value if result.error_code else '-'} "
            f"rows={result.rows_total} invalid={result.rows_invalid} "
            f"created={result.bookings_created} updated={result.bookings_updated} "
            f"unchanged={result.bookings_unchanged}",
            ids,
        )
        return result

    # --- pipeline -----------------------------------------------------------------------------

    def _run(
        self,
        ids: _Ids,
        filename: str,
        content: bytes,
        timezone: ZoneInfo,
        duplicate_of: UUID | None,
    ) -> BookingImportResult:
        detect_file_type(filename, content)  # unsupported types first, before anything else
        profile = self._profiles.get_for_data_source(ids.data_source)
        if profile is None:
            raise BookingImportError(
                BookingErrorCode.MAPPING_REQUIRED,
                "This data source has no confirmed mapping yet: suggest and confirm one first",
                details={"reason": "no_confirmed_mapping"},
            )
        config = MappingConfig.parse(
            {
                "column_mapping": profile.column_mapping,
                "status_mapping": profile.status_mapping,
                "channel_mapping": profile.channel_mapping,
                "format_options": profile.format_options,
            }
        )

        table = open_table(content, filename, config.format_options)
        schema = check_schema(config, profile.header_signature, table.headers)
        if not schema.compatible:
            raise BookingImportError(
                BookingErrorCode.SOURCE_SCHEMA_CHANGED,
                "The file no longer has the columns this data source was mapped on: "
                "review and confirm the mapping again",
                details={
                    "reason": "mapped_columns_missing",
                    "missing_columns": list(schema.missing_columns),
                },
            )

        extracted = self._extract(table, config)
        context = NormalizationContext(timezone, config)
        self._require_explicit_formats(extracted, config, context)

        staged, summary = self._validate(extracted, context)
        invalid = sum(1 for row in staged if row.validation_status == ImportRowStatus.INVALID)
        valid = len(staged) - invalid
        self._rows.add_many(ids.job, ids.file, staged)
        self._session.commit()  # T2: staging and diagnostics are kept whatever happens next

        counts = _RowCounts(len(staged), valid, invalid)
        if invalid:
            return self._fail(
                ids,
                BookingErrorCode.VALIDATION_FAILED,
                f"{invalid} of {len(staged)} rows failed validation: nothing was imported",
                {"schema_signature_matches": schema.signature_matches},
                duplicate_of,
                summary=summary,
                counts=counts,
            )
        return self._canonicalize(ids, timezone, duplicate_of, schema.signature_matches, counts)

    def _extract(self, table: SourceTable, config: MappingConfig) -> list[_ExtractedRow]:
        """Read the file, keeping ONLY the mapped columns of each row.

        This is the data-minimisation boundary: whatever else the row holds (guest names,
        e-mails, phones, notes, ...) is dropped here and never reaches staging, logs or errors.
        """
        index = header_index(table.headers)
        positions = {
            canonical: index[normalize_header(column)]
            for canonical, column in config.mapped_columns().items()
        }
        return [
            _ExtractedRow(row.number, {c: row.cells[i] for c, i in positions.items()})
            for row in table.rows()
        ]

    def _require_explicit_formats(
        self, rows: list[_ExtractedRow], config: MappingConfig, context: NormalizationContext
    ) -> None:
        """Dates such as 01/02/2026 and numbers such as 1,234 mean two things: the profile must
        say which. Detected per column, before any row is judged, so the customer is asked once.
        """
        mapped = config.mapped_columns()
        ambiguous_dates = sorted(
            f.value
            for f in DATE_FIELDS
            if f in mapped and needs_date_format(f, [r.values.get(f) for r in rows], context)
        )
        if ambiguous_dates:
            raise BookingImportError(
                BookingErrorCode.AMBIGUOUS_DATE_FORMAT,
                "Some date columns are written day/month/year or month/day/year: "
                "set the date format in the mapping",
                details={"fields": ambiguous_dates},
            )
        ambiguous_numbers = sorted(
            f.value
            for f in DECIMAL_FIELDS
            if f in mapped and needs_number_format([r.values.get(f) for r in rows], context)
        )
        if ambiguous_numbers:
            raise BookingImportError(
                BookingErrorCode.AMBIGUOUS_NUMBER_FORMAT,
                "Some amount columns use separators that can mean two things: "
                "set the decimal and thousands separators in the mapping",
                details={"fields": ambiguous_numbers},
            )

    def _validate(
        self, rows: list[_ExtractedRow], context: NormalizationContext
    ) -> tuple[list[StagedRow], dict[str, int]]:
        results = [(row, *normalize_row(row.values, context)) for row in rows]

        # The same source record twice in one file is ambiguous: reject both, no "last one wins".
        numbers_by_id: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            source_id = parse_source_record_id(row.values.get(F.SOURCE_RECORD_ID))
            if source_id is not None:
                numbers_by_id[source_id].append(row.number)
        duplicates = {
            number: [n for n in numbers if n != number]
            for numbers in numbers_by_id.values()
            if len(numbers) > 1
            for number in numbers
        }

        summary: Counter[str] = Counter()
        staged: list[StagedRow] = []
        for row, booking, issues in results:
            issues = list(issues)
            if row.number in duplicates:
                others = ", ".join(str(n) for n in duplicates[row.number][:5])
                issues.append(
                    RowIssue(
                        F.SOURCE_RECORD_ID.value,
                        BookingErrorCode.DUPLICATE_SOURCE_ID,
                        f"same source_record_id on row(s) {others}",
                    )
                )
            summary.update(issue.code.value for issue in issues)
            usable = booking if not issues else None
            staged.append(
                StagedRow(
                    row_number=row.number,
                    mapped_payload={
                        f.value: diagnostic_text(v) for f, v in row.values.items() if v is not None
                    },
                    normalized_payload=usable.to_payload() if usable is not None else None,
                    validation_status=(
                        ImportRowStatus.VALID if usable is not None else ImportRowStatus.INVALID
                    ),
                    validation_errors=[issue.to_json() for issue in issues],
                )
            )
        return staged, dict(sorted(summary.items()))

    def _canonicalize(
        self,
        ids: _Ids,
        timezone: ZoneInfo,
        duplicate_of: UUID | None,
        signature_matches: bool,
        counts: _RowCounts,
    ) -> BookingImportResult:
        """T4: every valid row becomes a canonical booking, or none does."""
        try:
            # One canonicalisation per data source at a time: a concurrent import of the same
            # source waits, then sees these bookings and treats them as known.
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
                {"key": str(ids.data_source)},
            )
            staged = self._rows.list_for_job(ids.job, status=ImportRowStatus.VALID)
            bookings = [
                NormalizedBooking.from_payload(row.normalized_payload or {}) for row in staged
            ]

            channel_ids: dict[str, UUID] = {}
            for booking in bookings:
                key = booking.channel.normalized_name
                if key not in channel_ids:
                    channel, _ = self._channels.get_or_create(ids.property, booking.channel)
                    channel_ids[key] = channel.id
            outcome = self._bookings.upsert_from_import(
                property_id=ids.property,
                data_source_id=ids.data_source,
                import_job_id=ids.job,
                items=[
                    ImportItem(b, channel_ids[b.channel.normalized_name], b.fingerprint())
                    for b in bookings
                ],
            )
            self._rows.mark_valid_rows_imported(ids.job)
            self._jobs.succeed(ids.job)
            self._session.commit()
        except Exception as error:
            self._session.rollback()  # nothing of this batch survives
            constraint = _constraint_name(error)
            logger.error(
                "booking canonicalisation rolled back workspace_id=%s import_job_id=%s "
                "error_type=%s constraint=%s",
                self._tenant.workspace_id,
                ids.job,
                type(error).__name__,
                constraint or "-",
            )
            return self._fail(
                ids,
                BookingErrorCode.CANONICALIZATION_FAILED,
                "The database rejected the batch: no booking was imported",
                {"constraint": constraint} if constraint else None,
                duplicate_of,
                counts=counts,
            )
        return BookingImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.SUCCEEDED,
            error_code=None,
            error_message=None,
            bookings_created=outcome.created,
            bookings_updated=outcome.updated,
            bookings_unchanged=outcome.unchanged,
            details={"schema_signature_matches": signature_matches},
            duplicate_of_import_file_id=duplicate_of,
            rows_total=counts.total,
            rows_valid=counts.valid,
            rows_invalid=counts.invalid,
        )

    # --- helpers ------------------------------------------------------------------------------

    def _fail(
        self,
        ids: _Ids,
        code: BookingErrorCode,
        message: str,
        details: dict[str, Any] | None,
        duplicate_of: UUID | None,
        *,
        summary: dict[str, int] | None = None,
        counts: _RowCounts | None = None,
    ) -> BookingImportResult:
        """Record the failure in its own transaction: it survives any data rollback."""
        self._session.rollback()  # drop anything left over from a failed step
        self._jobs.fail(
            ids.job, error_code=code.value, error_message=message[:_MAX_SUMMARY_MESSAGE]
        )
        self._session.commit()
        return BookingImportResult(
            import_job_id=ids.job,
            import_file_id=ids.file,
            status=ImportJobStatus.FAILED,
            error_code=code,
            error_message=message[:_MAX_SUMMARY_MESSAGE],
            rows_total=(counts or _RowCounts()).total,
            rows_valid=(counts or _RowCounts()).valid,
            rows_invalid=(counts or _RowCounts()).invalid,
            row_error_summary=summary or {},
            details=details or {},
            duplicate_of_import_file_id=duplicate_of,
        )

    def _load_source(
        self, data_source_id: UUID, property_id: UUID | None = None
    ) -> tuple[DataSource, Property]:
        """The data source must be an active BOOKINGS/FILE_UPLOAD source of this workspace.

        Unknown ids and ids of another workspace are indistinguishable (same error).
        """
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.BOOKINGS:
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
            raise BookingImportError(
                BookingErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for booking imports",
                details={"reason": reason or "not_found"},
            )
        return data_source, prop

    @staticmethod
    def _timezone(prop: Property) -> ZoneInfo:
        try:
            return ZoneInfo(prop.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise BookingImportError(
                BookingErrorCode.INVALID_DATA_SOURCE,
                "The property has no valid timezone",
                details={"reason": "invalid_property_timezone"},
            ) from error

    @staticmethod
    def _date_order_hints(
        table: SourceTable, suggestions: list[MappingSuggestion]
    ) -> dict[str, str]:
        """For suggested date columns only: what their values prove about day/month order."""
        index = header_index(table.headers)
        wanted = {
            s.canonical_field: index[normalize_header(s.suggested_source_column)]
            for s in suggestions
            if s.suggested_source_column and s.canonical_field in DATE_FIELDS
        }
        if not wanted:
            return {}
        values: dict[CanonicalField, list[str]] = {f: [] for f in wanted}
        for row in table.rows():
            for canonical, position in wanted.items():
                cell = row.cells[position]
                if isinstance(cell, str):
                    values[canonical].append(cell)
        return {f.value: detect_date_order(v).value for f, v in values.items()}

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
