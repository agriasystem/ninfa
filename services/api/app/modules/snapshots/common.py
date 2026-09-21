"""What the two snapshot services share: validation, the clock, the lock and the storing rules.

The services themselves stay separate (`ObservedSnapshotService`, `BookingSnapshotReconstruction
Service`): an observation and a reconstruction must never be produced by the same code path.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http import HTTPStatus
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source
from app.modules.ingestion.models import DataSourceDomain, DataSourceType
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.calculation import CALCULATION_VERSION
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import (
    BookingSnapshotRepository,
    BookingStayRepository,
    NewSnapshot,
    RoomInventoryRepository,
    SnapshotKey,
    StoredSnapshotRef,
)

logger = logging.getLogger(__name__)

# A run covers at most two years of stay nights (and of snapshot days), and a reconstruction at
# most this many stored rows: an upper bound, not a target.
MAX_DATE_SPAN_DAYS = 731
MAX_RECONSTRUCTED_ROWS = 200_000
_MAX_REPORTED_CONFLICTS = 20

# The only source of "now". Injected so that tests (and later a scheduler) control it; callers
# of the services cannot pass an `as_of_at`, so a past state can never be faked.
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SnapshotSource:
    """The validated scope of a run: one property, one of its data sources, its time zone."""

    property_id: UUID
    data_source_id: UUID
    timezone: ZoneInfo


@dataclass(frozen=True, slots=True)
class SnapshotRunResult:
    """Outcome of a run. Counts only: the snapshots themselves are read back through the
    repository. `skipped_observed` is only ever non-zero for a reconstruction (an existing
    observation is left alone)."""

    origin: SnapshotOrigin
    property_id: UUID
    data_source_id: UUID
    snapshot_date_first: date
    snapshot_date_last: date
    stay_date_first: date
    stay_date_last: date
    created: int
    unchanged: int
    skipped_observed: int
    calculation_version: str = CALCULATION_VERSION

    @property
    def total(self) -> int:
        return self.created + self.unchanged + self.skipped_observed


class SnapshotServiceBase:
    """Shared plumbing. Pass a session with no uncommitted work: the service commits it (and
    rolls it back on failure), exactly like the booking import."""

    def __init__(self, session: Session, tenant: TenantContext, *, clock: Clock = utc_now) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("a snapshot service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._clock = clock
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._stays = BookingStayRepository(session, tenant)
        self._inventory = RoomInventoryRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)

    # --- inputs -------------------------------------------------------------------------------

    @staticmethod
    def _require_date(value: date, name: str) -> None:
        # datetime is a subclass of date: refuse it, its time part would be silently ignored.
        if isinstance(value, datetime) or not isinstance(value, date):
            raise TypeError(f"{name} must be a date")

    def _validate_range(self, first: date, last: date, name: str) -> None:
        self._require_date(first, f"{name}_start")
        self._require_date(last, f"{name}_end")
        if first > last:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_RANGE,
                f"The {name} range ends before it starts",
                details={"range": name, "reason": "start_after_end"},
            )
        if (last - first).days + 1 > MAX_DATE_SPAN_DAYS:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_RANGE,
                f"The {name} range is longer than {MAX_DATE_SPAN_DAYS} days",
                details={"range": name, "reason": "too_long", "max_days": MAX_DATE_SPAN_DAYS},
            )

    def _load_source(self, property_id: UUID, data_source_id: UUID) -> SnapshotSource:
        """The property and the data source must be usable and belong to this workspace.

        Unknown ids and ids of another workspace are indistinguishable (same error).
        """
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_PROPERTY,
                "The property cannot be used for booking snapshots",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        try:
            timezone = ZoneInfo(prop.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_PROPERTY,
                "The property has no valid timezone",
                details={"reason": "invalid_timezone"},
            ) from error

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
        elif data_source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for booking snapshots",
                details={"reason": reason},
            )
        return SnapshotSource(prop.id, data_source_id, timezone)

    # --- the one transaction ------------------------------------------------------------------

    def _begin(self, source: SnapshotSource) -> datetime:
        """Take the per-data-source lock and read the clock (always in this order).

        The lock serialises this run with the canonical writes of the same source (the booking
        import) and with any other snapshot run of it. Reading `now` only afterwards means that
        every import committed before the lock is older than `as_of_at`, and none can commit
        between the lock and the reads that follow.
        """
        lock_data_source(self._session, source.data_source_id)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("the clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _finish(self, run: Callable[[], SnapshotRunResult]) -> SnapshotRunResult:
        """Run the calculation inside one transaction: commit it whole or roll it back whole."""
        try:
            result = run()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return result

    # --- storing ------------------------------------------------------------------------------

    def _store(
        self,
        source: SnapshotSource,
        calculated: Sequence[NewSnapshot],
        existing: dict[SnapshotKey, StoredSnapshotRef],
        *,
        origin: SnapshotOrigin,
    ) -> tuple[int, int, int]:
        """Insert what is new; compare what exists. Returns (created, unchanged, skipped).

        Rules, identical for both origins except the first one:

        * an existing OBSERVED row is never touched by a RECONSTRUCTION (skipped: OBSERVED wins);
        * the same fingerprint (same origin, same content) is an idempotent no-op;
        * anything else on the same key is a conflict. Nothing is updated and, as the caller
          rolls back, nothing of this run is stored.
        """
        to_insert: list[NewSnapshot] = []
        unchanged = skipped = 0
        conflicts: list[dict[str, str]] = []
        for snapshot in calculated:
            current = existing.get(snapshot.key)
            if current is None:
                to_insert.append(snapshot)
            elif current.origin == SnapshotOrigin.OBSERVED and origin != SnapshotOrigin.OBSERVED:
                skipped += 1
            elif (current.origin, current.content_fingerprint) == (
                origin,
                snapshot.content_fingerprint,
            ):
                unchanged += 1
            else:
                conflicts.append(
                    {
                        "snapshot_local_date": snapshot.key[0].isoformat(),
                        "stay_date": snapshot.key[1].isoformat(),
                        "existing_origin": current.origin.value,
                    }
                )
        if conflicts:
            raise self._conflict(len(conflicts), conflicts)
        inserted = self._snapshots.insert_if_absent(source.property_id, to_insert)
        if inserted != {snapshot.key for snapshot in to_insert}:
            # Somebody wrote a key between our read and our insert (a writer that bypassed the
            # lock). Treated as a conflict: the caller rolls the whole run back.
            raise self._conflict(len(to_insert) - len(inserted), [])
        return len(inserted), unchanged, skipped

    @staticmethod
    def _conflict(count: int, conflicts: list[dict[str, str]]) -> SnapshotError:
        return SnapshotError(
            SnapshotErrorCode.CONFLICT,
            "A stored snapshot with different content exists for the same key; it is never updated",
            details={"conflict_count": count, "conflicts": conflicts[:_MAX_REPORTED_CONFLICTS]},
            status_code=HTTPStatus.CONFLICT,
        )
