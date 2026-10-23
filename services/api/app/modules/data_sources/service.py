"""The data sources of ONE property: what is configured, what was last received, and how a file gets
in.

Everything here reuses what already exists: `DataSource` / `ImportJob` rows for the state and the
last update (no new table), the three import services for the import itself, the pilot's canonical
CSV convention (`app.modules.ingestion.canonical_csv`) for the mapping. Nothing is parsed or
validated here and no integration is simulated: see `app.modules.data_sources.types`.

Tenant isolation: every read and write goes through the repositories of the request's
`TenantContext`, and a source is only reachable through the property it belongs to - another
property's source answers the same `DataSourceNotFoundError` as an id that does not exist.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.models import ChannelType
from app.modules.bookings.repository import BookingChannelRepository
from app.modules.bookings.service import BookingImportService
from app.modules.data_sources.errors import (
    AmbiguousSourceError,
    DataSourceNotFoundError,
    FileTooLargeError,
    InvalidSnapshotDateError,
)
from app.modules.data_sources.files import (
    MAX_FILE_BYTES,
    ImportPreview,
    ImportProblem,
    preview_csv,
    preview_invoices,
    problem_of_code,
)
from app.modules.data_sources.types import (
    DOMAIN_METHOD,
    DOMAIN_SOURCE_NAME,
    DerivedFrom,
    SourceCapability,
    SourceCard,
    SourceCardState,
    SourcesOverview,
    SourceState,
)
from app.modules.ingestion.canonical_csv import (
    booking_format_options,
    identity_column_mapping,
    labor_format_options,
    read_headers,
)
from app.modules.ingestion.models import DataSource, DataSourceDomain
from app.modules.ingestion.repository import (
    DataSourceRepository,
    ImportFileRepository,
    ImportJobRepository,
)
from app.modules.ingestion.schemas import DataSourceCreate
from app.modules.invoices.service import InvoiceImportService, detect_source
from app.modules.labor.mapping import LaborField
from app.modules.labor.service import LaborImportService

logger = logging.getLogger(__name__)

_MAX_CHANNELS_SHOWN = 8


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    succeeded: bool
    problem: ImportProblem | None
    rows_total: int = 0
    rows_invalid: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    # This exact file had already been imported by this source: the import is idempotent, nothing
    # doubles.
    already_imported: bool = False


class DataSourcesService:
    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant
        self._sources = DataSourceRepository(session, tenant)
        self._jobs = ImportJobRepository(session, tenant)
        self._files = ImportFileRepository(session, tenant)
        self._channels = BookingChannelRepository(session, tenant)

    # --- reading ------------------------------------------------------------------------------

    def overview(self, property_id: UUID) -> SourcesOverview:
        active = self._sources.list_all(property_id=property_id)
        by_domain = {
            domain: [source for source in active if source.domain == domain]
            for domain in DataSourceDomain
        }
        bookings = by_domain[DataSourceDomain.BOOKINGS]
        bookings_received = any(self._last_update(source) is not None for source in bookings)

        pms = self._file_card(SourceCard.PMS, DataSourceDomain.BOOKINGS, bookings)
        if bookings_received:
            channel_manager = SourceCardState(
                card=SourceCard.CHANNEL_MANAGER,
                state=SourceState.DERIVED,
                derived_from=DerivedFrom.BOOKINGS_FILE,
            )
            ota = SourceCardState(
                card=SourceCard.OTA,
                state=SourceState.DERIVED,
                derived_from=DerivedFrom.BOOKINGS_FILE,
                channels=self._ota_channels(property_id),
            )
        else:
            channel_manager = SourceCardState(
                SourceCard.CHANNEL_MANAGER, SourceState.NOT_CONFIGURED
            )
            ota = SourceCardState(SourceCard.OTA, SourceState.NOT_CONFIGURED)

        cards = (
            pms,
            channel_manager,
            ota,
            self._file_card(
                SourceCard.ACCOUNTING, DataSourceDomain.COSTS, by_domain[DataSourceDomain.COSTS]
            ),
            self._file_card(
                SourceCard.STAFF, DataSourceDomain.LABOR, by_domain[DataSourceDomain.LABOR]
            ),
        )
        capabilities = tuple(
            SourceCapability(domain, (method,)) for domain, method in DOMAIN_METHOD.items()
        )
        return SourcesOverview(property_id=property_id, cards=cards, capabilities=capabilities)

    def _file_card(
        self, card: SourceCard, domain: DataSourceDomain, sources: list[DataSource]
    ) -> SourceCardState:
        """A source is CONFIGURED for the hotelier only once it has delivered: a source that never
        completed a valid import (a leftover of an abandoned flow, or one an operator created and
        never fed) reads "Non configurato", exactly like no source at all."""
        method = DOMAIN_METHOD[domain]
        if not sources:
            return SourceCardState(card, SourceState.NOT_CONFIGURED, domain=domain)
        if len(sources) > 1:
            # Created outside this API: NINFA does not pick one (the analysis would not either).
            return SourceCardState(
                card,
                SourceState.CONFIGURED_FILE,
                domain=domain,
                method=method,
                several_sources=True,
            )
        source = sources[0]
        last_update = self._last_update(source)
        if last_update is None:
            return SourceCardState(card, SourceState.NOT_CONFIGURED, domain=domain)
        return SourceCardState(
            card,
            SourceState.CONFIGURED_FILE,
            domain=domain,
            data_source_id=source.id,
            method=method,
            last_update_at=last_update,
        )

    def _last_update(self, source: DataSource) -> datetime | None:
        job = self._jobs.latest_succeeded_for_data_source(source.id)
        if job is None or job.finished_at is None:
            return None
        return job.finished_at

    def _ota_channels(self, property_id: UUID) -> tuple[str, ...]:
        names = sorted(
            channel.name
            for channel in self._channels.list_for_property(property_id)
            if channel.channel_type == ChannelType.OTA
        )
        return tuple(names[:_MAX_CHANNELS_SHOWN])

    # --- removing -------------------------------------------------------------------------------

    def deactivate(self, property_id: UUID, data_source_id: UUID) -> None:
        """Switch the source off. Its imported data are NOT touched: removing a source stops new
        data from arriving, it never deletes what NINFA already received."""
        source = self._load(property_id, data_source_id)
        self._switch_off(source.id)
        logger.info(
            "data source removed workspace_id=%s property_id=%s data_source_id=%s",
            self._tenant.workspace_id,
            property_id,
            source.id,
        )

    # --- files ----------------------------------------------------------------------------------

    def preview(self, property_id: UUID, domain: DataSourceDomain, content: bytes) -> ImportPreview:
        """Look at a file. Read-only: it writes NOTHING - no source, no job, no row - so opening a
        dialog and choosing a file can never configure anything."""
        self._check_size(content)
        digest = hashlib.sha256(content).hexdigest()
        # "Already imported" is a fact about the property's own sources of this kind, removed ones
        # included (a source that was switched off keeps its history).
        already = any(
            self._files.find_successful_for_data_source(source.id, digest) is not None
            for source in self._sources_of(property_id, domain, include_inactive=True)
        )
        if domain == DataSourceDomain.COSTS:
            return preview_invoices(content, already_imported=already)
        return preview_csv(domain, content, already_imported=already)

    def import_file(
        self,
        property_id: UUID,
        domain: DataSourceDomain,
        *,
        filename: str,
        content: bytes,
        snapshot_local_date: date | None = None,
    ) -> ImportOutcome:
        """Import one file through the SAME service the pilot CLI uses. Nothing is re-implemented:
        parsing, validation, idempotency and all-or-nothing are the import service's.

        THIS call is the only way a source comes to exist, and it exists only if the import
        succeeds: the source is created (or switched back on, with its history) when the user
        confirms the import, and switched off again if the import does not succeed. A flow that is
        abandoned, or a file that fails, therefore never leaves a "configured" source behind (the
        failed attempt stays as a FAILED job, like every other operational record).
        """
        self._check_size(content)
        if domain == DataSourceDomain.LABOR and snapshot_local_date is None:
            # The day the file is dated as of is never guessed (the labor service insists) - and a
            # request that cannot be imported must not even switch a source on.
            raise InvalidSnapshotDateError()
        source, switched_on = self._source_for_import(property_id, domain)
        source_id = source.id
        try:
            outcome = self._run_import(source, property_id, filename, content, snapshot_local_date)
        except Exception:
            if switched_on:
                # An unexpected failure may leave the transaction unusable: start clean, then undo
                # what THIS call switched on.
                self._session.rollback()
                self._switch_off(source_id)
            raise
        if switched_on and not outcome.succeeded:
            self._switch_off(source_id)
        return outcome

    def _sources_of(
        self, property_id: UUID, domain: DataSourceDomain, *, include_inactive: bool = False
    ) -> list[DataSource]:
        return [
            source
            for source in self._sources.list_all(
                property_id=property_id, include_inactive=include_inactive
            )
            if source.domain == domain
        ]

    def _source_for_import(
        self, property_id: UUID, domain: DataSourceDomain
    ) -> tuple[DataSource, bool]:
        """The source this import goes into, and whether THIS call switched it on.

        The active source when there is one (several active ones are refused: NINFA does not pick);
        otherwise the one that was removed before (so its history stays attached - a second, empty
        source would be read by the analysis instead of the imported data); otherwise a new one.
        """
        existing = self._sources_of(property_id, domain, include_inactive=True)
        active = [source for source in existing if source.is_active]
        if len(active) > 1:
            raise AmbiguousSourceError()
        if active:
            return active[0], False
        if existing:
            source = max(existing, key=lambda item: (item.updated_at, str(item.id)))
            self._sources.reactivate(source.id)
            verb = "reactivated"
        else:
            source = self._sources.add(
                DataSourceCreate(
                    property_id=property_id, name=DOMAIN_SOURCE_NAME[domain], domain=domain
                )
            )
            verb = "created"
        self._session.commit()
        logger.info(
            "data source %s for an import workspace_id=%s property_id=%s "
            "data_source_id=%s domain=%s",
            verb,
            self._tenant.workspace_id,
            property_id,
            source.id,
            domain.value,
        )
        return source, True

    def _switch_off(self, data_source_id: UUID) -> None:
        self._sources.deactivate(data_source_id)
        self._session.commit()

    def _run_import(
        self,
        source: DataSource,
        property_id: UUID,
        filename: str,
        content: bytes,
        snapshot_local_date: date | None,
    ) -> ImportOutcome:
        try:
            if source.domain == DataSourceDomain.BOOKINGS:
                return self._import_bookings(source, property_id, filename, content)
            if source.domain == DataSourceDomain.LABOR and snapshot_local_date is not None:
                return self._import_labor(
                    source, property_id, filename, content, snapshot_local_date
                )
            return self._import_invoices(source, property_id, filename, content)
        except UnicodeDecodeError:
            return ImportOutcome(False, ImportProblem.UNREADABLE_FILE)
        except (AppError, ValueError) as error:
            # A refusal BEFORE a job exists (an unusable mapping, a source that cannot be used).
            code = getattr(error, "error_code", None) or getattr(error, "code", None)
            logger.info(
                "data source import refused workspace_id=%s property_id=%s "
                "data_source_id=%s code=%s",
                self._tenant.workspace_id,
                property_id,
                source.id,
                code,
            )
            return ImportOutcome(
                False, problem_of_code(code) if code else ImportProblem.MISSING_COLUMNS
            )

    def _import_bookings(
        self, source: DataSource, property_id: UUID, filename: str, content: bytes
    ) -> ImportOutcome:
        service = BookingImportService(self._session, self._tenant)
        headers = read_headers(content)
        service.save_mapping(
            source.id,
            headers=headers,
            column_mapping=identity_column_mapping(headers, CanonicalField),
            format_options=booking_format_options(),
            property_id=property_id,
        )
        result = service.import_file(
            source.id, filename=filename, content=content, property_id=property_id
        )
        return ImportOutcome(
            succeeded=result.succeeded,
            problem=None if result.succeeded else problem_of_code(result.error_code),
            rows_total=result.rows_total,
            rows_invalid=result.rows_invalid,
            created=result.bookings_created,
            updated=result.bookings_updated,
            unchanged=result.bookings_unchanged,
            already_imported=result.duplicate_of_import_file_id is not None,
        )

    def _import_labor(
        self,
        source: DataSource,
        property_id: UUID,
        filename: str,
        content: bytes,
        snapshot_local_date: date,
    ) -> ImportOutcome:
        service = LaborImportService(self._session, self._tenant)
        headers = read_headers(content)
        service.save_mapping(
            source.id,
            headers=headers,
            column_mapping=identity_column_mapping(headers, LaborField),
            format_options=labor_format_options(),
            property_id=property_id,
        )
        result = service.import_file(
            source.id,
            filename=filename,
            content=content,
            snapshot_local_date=snapshot_local_date,
            property_id=property_id,
        )
        return ImportOutcome(
            succeeded=result.succeeded,
            problem=None if result.succeeded else problem_of_code(result.error_code),
            rows_total=result.rows_total,
            rows_invalid=result.rows_invalid,
            created=result.entries_created,
            already_imported=result.duplicate_of_import_file_id is not None,
        )

    def _import_invoices(
        self, source: DataSource, property_id: UUID, filename: str, content: bytes
    ) -> ImportOutcome:
        # Costs arrive as FatturaPA XML only: a CSV or XLSX would need a column mapping NINFA does
        # not offer yet (Smart Import V2), so it is refused here instead of being half-understood.
        if detect_source(filename, content) != "xml":
            return ImportOutcome(False, ImportProblem.UNSUPPORTED_FILE)
        result = InvoiceImportService(self._session, self._tenant).import_file(
            source.id, filename=filename, content=content, property_id=property_id
        )
        return ImportOutcome(
            succeeded=result.succeeded,
            problem=None if result.succeeded else problem_of_code(result.error_code),
            rows_total=result.rows_total,
            rows_invalid=result.rows_invalid,
            created=result.invoices_created,
            unchanged=result.invoices_unchanged,
            already_imported=result.duplicate_of_import_file_id is not None,
        )

    # --- helpers --------------------------------------------------------------------------------

    def _load(self, property_id: UUID, data_source_id: UUID) -> DataSource:
        source = self._sources.get(data_source_id)
        if source is None or source.property_id != property_id or not source.is_active:
            raise DataSourceNotFoundError()
        return source

    @staticmethod
    def _check_size(content: bytes) -> None:
        if len(content) > MAX_FILE_BYTES:
            raise FileTooLargeError(MAX_FILE_BYTES)


__all__ = ["DataSourcesService", "ImportOutcome"]
