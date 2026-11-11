"""Tenant-scoped repositories of the bookings module (explicit, no generic base class).

Every class takes a TenantContext and puts its workspace_id in every query. Repositories
`flush()` but never `commit()`: transaction boundaries belong to BookingImportService.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.bookings.channels import ChannelSpec
from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    BookingStatus,
    ImportRowStatus,
    is_current_booking,
)
from app.modules.bookings.normalization import NormalizedBooking
from app.modules.ingestion.models import DataSource, ImportJob, ImportJobStatus

_CHUNK = 1000
CHANNEL_UNIQUE = "uq_booking_channels_workspace_id_property_id_normalized_name"


# --- channels --------------------------------------------------------------------------------


class BookingChannelRepository:
    """Channels of ONE workspace (each belongs to one property of it)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_by_normalized_name(
        self, property_id: UUID, normalized_name: str
    ) -> BookingChannel | None:
        return self._session.scalar(
            select(BookingChannel).where(
                BookingChannel.workspace_id == self._tenant.workspace_id,
                BookingChannel.property_id == property_id,
                BookingChannel.normalized_name == normalized_name,
            )
        )

    def get_or_create(self, property_id: UUID, spec: ChannelSpec) -> tuple[BookingChannel, bool]:
        """The channel of the property with this normalised name; created (unverified OTHER
        unless the spec says otherwise) when it does not exist yet. An existing channel is
        reused untouched: a later profile never silently reclassifies it.
        """
        existing = self.get_by_normalized_name(property_id, spec.normalized_name)
        if existing is not None:
            return existing, False
        # ON CONFLICT DO NOTHING: two imports creating the same channel concurrently both end up
        # with the one row instead of one of them failing.
        inserted = self._session.execute(
            pg_insert(BookingChannel)
            .values(
                workspace_id=self._tenant.workspace_id,
                property_id=property_id,
                name=spec.name,
                normalized_name=spec.normalized_name,
                channel_type=spec.channel_type,
                is_verified=spec.is_verified,
            )
            .on_conflict_do_nothing(constraint=CHANNEL_UNIQUE)
            .returning(BookingChannel.id)
        ).scalar_one_or_none()
        channel = self.get_by_normalized_name(property_id, spec.normalized_name)
        if channel is None:  # pragma: no cover - the property does not exist for this tenant
            raise NotFoundError("Property")
        return channel, inserted is not None

    def list_for_property(self, property_id: UUID) -> Sequence[BookingChannel]:
        return self._session.scalars(
            select(BookingChannel)
            .where(
                BookingChannel.workspace_id == self._tenant.workspace_id,
                BookingChannel.property_id == property_id,
            )
            .order_by(BookingChannel.normalized_name)
        ).all()


# --- mapping profiles ------------------------------------------------------------------------


class BookingMappingProfileRepository:
    """The confirmed mapping of each data source of ONE workspace (at most one per source)."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_for_data_source(self, data_source_id: UUID) -> BookingMappingProfile | None:
        return self._session.scalar(
            select(BookingMappingProfile).where(
                BookingMappingProfile.workspace_id == self._tenant.workspace_id,
                BookingMappingProfile.data_source_id == data_source_id,
            )
        )

    def upsert(
        self,
        data_source: DataSource,
        *,
        stored: dict[str, dict[str, Any]],
        header_signature: str,
    ) -> BookingMappingProfile:
        """Replace the current profile of the data source (no history in V1)."""
        if data_source.workspace_id != self._tenant.workspace_id:
            raise NotFoundError("Data source")
        profile = self.get_for_data_source(data_source.id)
        if profile is None:
            profile = BookingMappingProfile(
                workspace_id=self._tenant.workspace_id,
                property_id=data_source.property_id,
                data_source_id=data_source.id,
                **stored,
                header_signature=header_signature,
            )
            self._session.add(profile)
        else:
            profile.column_mapping = stored["column_mapping"]
            profile.status_mapping = stored["status_mapping"]
            profile.channel_mapping = stored["channel_mapping"]
            profile.format_options = stored["format_options"]
            profile.header_signature = header_signature
        self._session.flush()
        return profile

    def delete_for_data_source(self, data_source_id: UUID) -> bool:
        """Forget the confirmed mapping (configuration only: no imported data is touched)."""
        profile = self.get_for_data_source(data_source_id)
        if profile is None:
            return False
        self._session.delete(profile)
        self._session.flush()
        return True


# --- staging ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class StagedRow:
    row_number: int
    mapped_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    validation_status: ImportRowStatus
    validation_errors: list[dict[str, str]]


class BookingImportRowRepository:
    """Staging rows of ONE workspace's imports."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def add_many(
        self, import_job_id: UUID, import_file_id: UUID, rows: Sequence[StagedRow]
    ) -> None:
        for start in range(0, len(rows), _CHUNK):
            chunk = rows[start : start + _CHUNK]
            self._session.execute(
                pg_insert(BookingImportRow),
                [
                    {
                        "workspace_id": self._tenant.workspace_id,
                        "import_job_id": import_job_id,
                        "import_file_id": import_file_id,
                        "row_number": row.row_number,
                        "mapped_payload": row.mapped_payload,
                        "normalized_payload": row.normalized_payload,
                        "validation_status": row.validation_status,
                        "validation_errors": row.validation_errors,
                    }
                    for row in chunk
                ],
            )
        self._session.flush()

    def list_for_job(
        self, import_job_id: UUID, *, status: ImportRowStatus | None = None
    ) -> Sequence[BookingImportRow]:
        query = select(BookingImportRow).where(
            BookingImportRow.workspace_id == self._tenant.workspace_id,
            BookingImportRow.import_job_id == import_job_id,
        )
        if status is not None:
            query = query.where(BookingImportRow.validation_status == status)
        return self._session.scalars(query.order_by(BookingImportRow.row_number)).all()

    def count_by_status(self, import_job_id: UUID) -> dict[ImportRowStatus, int]:
        counts = self._session.execute(
            select(BookingImportRow.validation_status, func.count())
            .where(
                BookingImportRow.workspace_id == self._tenant.workspace_id,
                BookingImportRow.import_job_id == import_job_id,
            )
            .group_by(BookingImportRow.validation_status)
        )
        return {status: total for status, total in counts}

    def mark_valid_rows_imported(self, import_job_id: UUID) -> int:
        result = self._session.execute(
            update(BookingImportRow)
            .where(
                BookingImportRow.workspace_id == self._tenant.workspace_id,
                BookingImportRow.import_job_id == import_job_id,
                BookingImportRow.validation_status == ImportRowStatus.VALID,
            )
            .values(validation_status=ImportRowStatus.IMPORTED)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


# --- bookings --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportItem:
    """One validated booking, ready to be written: its channel already resolved."""

    booking: NormalizedBooking
    channel_id: UUID
    fingerprint: str


@dataclass(frozen=True)
class UpsertResult:
    created: int
    updated: int
    unchanged: int


# The statuses that are on the books in some form: a booking already cancelled or a no-show that an
# export leaves out has nothing left to lose, so its absence neither asks nor removes anything.
_NOT_ON_THE_BOOKS = (BookingStatus.CANCELLED, BookingStatus.NO_SHOW)


class BookingRepository:
    """Bookings of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def get_by_id(self, booking_id: UUID) -> Booking | None:
        return self._session.scalar(
            select(Booking).where(
                Booking.workspace_id == self._tenant.workspace_id, Booking.id == booking_id
            )
        )

    def get_by_source_record_id(
        self, data_source_id: UUID, source_record_id: str
    ) -> Booking | None:
        return self._session.scalar(
            select(Booking).where(
                Booking.workspace_id == self._tenant.workspace_id,
                Booking.data_source_id == data_source_id,
                Booking.source_record_id == source_record_id,
            )
        )

    def list_for_property(
        self,
        property_id: UUID,
        *,
        status: BookingStatus | None = None,
        check_in_from: date | None = None,
        check_in_until: date | None = None,
    ) -> Sequence[Booking]:
        query = select(Booking).where(
            Booking.workspace_id == self._tenant.workspace_id,
            Booking.property_id == property_id,
            is_current_booking(),
        )
        if status is not None:
            query = query.where(Booking.status == status)
        if check_in_from is not None:
            query = query.where(Booking.check_in >= check_in_from)
        if check_in_until is not None:
            query = query.where(Booking.check_in <= check_in_until)
        return self._session.scalars(
            query.order_by(Booking.check_in, Booking.source_record_id)
        ).all()

    def existing_by_source_record_ids(
        self, data_source_id: UUID, source_record_ids: Sequence[str]
    ) -> dict[str, Booking]:
        found: dict[str, Booking] = {}
        for start in range(0, len(source_record_ids), _CHUNK):
            chunk = source_record_ids[start : start + _CHUNK]
            for booking in self._session.scalars(
                select(Booking).where(
                    Booking.workspace_id == self._tenant.workspace_id,
                    Booking.data_source_id == data_source_id,
                    Booking.source_record_id.in_(chunk),
                )
            ):
                found[booking.source_record_id] = booking
        return found

    def upsert_from_import(
        self,
        *,
        property_id: UUID,
        data_source_id: UUID,
        import_job_id: UUID,
        items: Sequence[ImportItem],
    ) -> UpsertResult:
        """Create unknown bookings, update changed ones, leave identical ones completely alone.

        A booking is identified by (data source, source_record_id). Equal fingerprint = no-op
        (nothing is written, not even updated_at/last_import_job_id); a different fingerprint
        updates the same row and its last_import_job_id, never first_import_job_id. A booking a
        complete file had taken away and this file holds again is back: that is a change too.
        """
        ids = [item.booking.source_record_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source_record_id in one upsert batch")
        existing = self.existing_by_source_record_ids(data_source_id, ids)

        created = updated = unchanged = 0
        for item in items:
            booking = item.booking
            current = existing.get(booking.source_record_id)
            if current is None:
                self._session.add(
                    Booking(
                        workspace_id=self._tenant.workspace_id,
                        property_id=property_id,
                        data_source_id=data_source_id,
                        source_record_id=booking.source_record_id,
                        **_business_columns(item),
                        first_import_job_id=import_job_id,
                        last_import_job_id=import_job_id,
                    )
                )
                created += 1
            elif current.source_fingerprint == item.fingerprint and current.removed_at is None:
                unchanged += 1
            else:
                for column, value in _business_columns(item).items():
                    setattr(current, column, value)
                current.last_import_job_id = import_job_id
                current.removed_by_import_job_id = None
                current.removed_at = None
                current.last_seen_import_job_id = None
                updated += 1
        self._session.flush()
        return UpsertResult(created, updated, unchanged)

    def _on_the_books_between(
        self, data_source_id: UUID, first_check_in: date, last_check_in: date
    ) -> Sequence[Booking]:
        return self._session.scalars(
            select(Booking).where(
                Booking.workspace_id == self._tenant.workspace_id,
                Booking.data_source_id == data_source_id,
                Booking.check_in >= first_check_in,
                Booking.check_in <= last_check_in,
                Booking.status.not_in(_NOT_ON_THE_BOOKS),
                is_current_booking(),
            )
        ).all()

    def count_absent_from(
        self,
        data_source_id: UUID,
        source_record_ids: Collection[str],
        first_check_in: date,
        last_check_in: date,
    ) -> int:
        """How many bookings on the books in this period a file holding these ids does not hold."""
        held = set(source_record_ids)
        return sum(
            booking.source_record_id not in held
            for booking in self._on_the_books_between(data_source_id, first_check_in, last_check_in)
        )

    def remove_absent_from(
        self,
        data_source_id: UUID,
        import_job_id: UUID,
        source_record_ids: Collection[str],
        first_check_in: date,
        last_check_in: date,
    ) -> int:
        """A complete file: the bookings of its period it no longer holds are no longer current.
        Marked, never deleted, with the import that held each of them last. Returns how many."""
        held = set(source_record_ids)
        absent = [
            booking
            for booking in self._on_the_books_between(data_source_id, first_check_in, last_check_in)
            if booking.source_record_id not in held
        ]
        if not absent:
            return 0
        last_seen = self._last_imports_holding(
            data_source_id, [booking.source_record_id for booking in absent]
        )
        now = datetime.now(UTC)
        for booking in absent:
            booking.removed_by_import_job_id = import_job_id
            booking.removed_at = now
            booking.last_seen_import_job_id = last_seen.get(
                booking.source_record_id, booking.last_import_job_id
            )
        self._session.flush()
        return len(absent)

    def _last_imports_holding(
        self, data_source_id: UUID, source_record_ids: Sequence[str]
    ) -> dict[str, UUID]:
        """The latest SUCCEEDED import of this source that held each booking, from its own staged
        rows: an import that changed nothing about a booking did not write on the booking itself."""
        record = BookingImportRow.normalized_payload["source_record_id"].astext
        found: dict[str, UUID] = {}
        for start in range(0, len(source_record_ids), _CHUNK):
            chunk = source_record_ids[start : start + _CHUNK]
            rows = self._session.execute(
                select(record, ImportJob.id)
                .join(
                    ImportJob,
                    (ImportJob.workspace_id == BookingImportRow.workspace_id)
                    & (ImportJob.id == BookingImportRow.import_job_id),
                )
                .where(
                    BookingImportRow.workspace_id == self._tenant.workspace_id,
                    ImportJob.data_source_id == data_source_id,
                    ImportJob.status == ImportJobStatus.SUCCEEDED,
                    record.in_(chunk),
                )
                .distinct(record)
                .order_by(record, ImportJob.finished_at.desc(), ImportJob.id.desc())
            )
            found.update({str(row[0]): row[1] for row in rows})
        return found


def _business_columns(item: ImportItem) -> dict[str, Any]:
    booking = item.booking
    return {
        "booked_at": booking.booked_at,
        "check_in": booking.check_in,
        "check_out": booking.check_out,
        "status": booking.status,
        "rooms": booking.rooms,
        "guests": booking.guests,
        "room_revenue": booking.room_revenue,
        "total_revenue": booking.total_revenue,
        "channel_id": item.channel_id,
        "commission_amount": booking.commission_amount,
        "commission_rate": booking.commission_rate,
        "cancelled_at": booking.cancelled_at,
        "room_type": booking.room_type,
        "rate_plan": booking.rate_plan,
        "source_fingerprint": item.fingerprint,
    }
