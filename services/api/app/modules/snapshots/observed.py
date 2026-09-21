"""ObservedSnapshotService: what the canonical bookings say RIGHT NOW.

An observation is evidence: it records what NINFA saw at `as_of_at`, computed from the bookings
as they are at that instant. It is not the history of the bookings and it is never rewritten.

    one transaction:  validate -> lock the data source -> read the clock -> read bookings and
                      inventory -> calculate one row per stay night -> store or compare -> commit

Consistency choice (see docs/architecture/booking-snapshots-v1.md):

* The per-data-source advisory lock (shared with the booking import) makes the read set
  coherent: the import is the only writer of canonical bookings and it holds the same lock, so
  the bookings read here are never half of an import. It also serialises concurrent runs, so
  the outcome (create / idempotent no-op / conflict) is deterministic instead of a race won by
  the unique constraint.
* REPEATABLE READ was evaluated and NOT used: the service works inside the caller's
  transaction, where the isolation level can no longer be changed, and the lock already gives
  the guarantee that matters. Bookings are read in one statement and inventory in one statement.
"""

import logging
from datetime import date
from uuid import UUID

from app.modules.snapshots.aggregate import aggregate_observed
from app.modules.snapshots.calculation import (
    OBSERVED_STATUSES,
    build_content,
    date_range,
)
from app.modules.snapshots.common import SnapshotRunResult, SnapshotServiceBase
from app.modules.snapshots.localtime import local_date_of
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import NewSnapshot

logger = logging.getLogger(__name__)


class ObservedSnapshotService(SnapshotServiceBase):
    def take_snapshot(
        self,
        *,
        property_id: UUID,
        data_source_id: UUID,
        stay_date_start: date,
        stay_date_end: date,
    ) -> SnapshotRunResult:
        """Record today's observation for every stay night of `stay_date_start..stay_date_end`
        (both included) of one data source.

        `as_of_at` is the injected clock's now (UTC); the snapshot day is that instant's date in
        the property's time zone. There is deliberately no way to pass either of them in.

        Same key + same content -> idempotent no-op. Same key + different content -> raises
        `BOOKING_SNAPSHOT_CONFLICT` and stores nothing: an observation is never updated (one
        observation per data source, snapshot day and stay night).
        """
        self._validate_range(stay_date_start, stay_date_end, "stay_date")

        def run() -> SnapshotRunResult:
            source = self._load_source(property_id, data_source_id)
            as_of_at = self._begin(source)
            snapshot_date = local_date_of(as_of_at, source.timezone)

            stays = self._stays.list_stays(
                source.property_id,
                source.data_source_id,
                stay_date_start,
                stay_date_end,
                statuses=OBSERVED_STATUSES,
            )
            capacity = {
                row.stay_date: row.rooms_available
                for row in self._inventory.list_for_range(
                    source.property_id, stay_date_start, stay_date_end
                )
            }
            totals = aggregate_observed(stays, stay_date_start, stay_date_end)
            calculated = [
                NewSnapshot.of(
                    build_content(
                        origin=SnapshotOrigin.OBSERVED,
                        snapshot_local_date=snapshot_date,
                        stay_date=stay_date,
                        data_source_id=source.data_source_id,
                        totals=totals[stay_date],
                        rooms_available=capacity.get(stay_date),
                    ),
                    as_of_at,
                )
                for stay_date in date_range(stay_date_start, stay_date_end)
            ]
            existing = self._snapshots.existing_in_range(
                source.data_source_id, snapshot_date, snapshot_date, stay_date_start, stay_date_end
            )
            created, unchanged, skipped = self._store(
                source, calculated, existing, origin=SnapshotOrigin.OBSERVED
            )
            logger.info(
                "observed snapshots stored workspace_id=%s property_id=%s data_source_id=%s "
                "snapshot_date=%s created=%d unchanged=%d",
                self._tenant.workspace_id,
                source.property_id,
                source.data_source_id,
                snapshot_date,
                created,
                unchanged,
            )
            return SnapshotRunResult(
                origin=SnapshotOrigin.OBSERVED,
                property_id=source.property_id,
                data_source_id=source.data_source_id,
                snapshot_date_first=snapshot_date,
                snapshot_date_last=snapshot_date,
                stay_date_first=stay_date_start,
                stay_date_last=stay_date_end,
                created=created,
                unchanged=unchanged,
                skipped_observed=skipped,
            )

        return self._finish(run)
