"""BookingSnapshotReconstructionService: what can be INFERRED today about an earlier day.

This is NOT an observation and never becomes one. The canonical booking table keeps only the
CURRENT state of each booking: its dates, rooms, revenue, channel and status may have changed
since the day being reconstructed, and the room inventory is today's inventory. Every row it
produces is therefore `RECONSTRUCTED_APPROXIMATE`, even when nothing is uncertain.

Cutoff of a snapshot day = the start of the NEXT property-local day (half-open, see
`localtime`). A booking counts when it was made before the cutoff; the rules for cancellations
and no-shows live in `aggregate.aggregate_reconstruction`. What cannot be known is reported as
`uncertain_*`, never guessed. An existing observation of the same key is left untouched.

Transaction and consistency: identical to the observed service (one transaction, the same
per-data-source advisory lock).
"""

import logging
from datetime import date
from uuid import UUID

from app.modules.snapshots.aggregate import aggregate_reconstruction
from app.modules.snapshots.calculation import build_content, date_range
from app.modules.snapshots.common import (
    MAX_RECONSTRUCTED_ROWS,
    SnapshotRunResult,
    SnapshotServiceBase,
)
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.localtime import end_of_local_day
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import NewSnapshot

logger = logging.getLogger(__name__)


class BookingSnapshotReconstructionService(SnapshotServiceBase):
    def reconstruct(
        self,
        *,
        property_id: UUID,
        data_source_id: UUID,
        snapshot_date_start: date,
        snapshot_date_end: date,
        stay_date_start: date,
        stay_date_end: date,
    ) -> SnapshotRunResult:
        """Reconstruct, for every property-local snapshot day in `snapshot_date_start..end` and
        every stay night in `stay_date_start..end` (all inclusive), the on-books state of one
        data source.

        Only COMPLETED local days can be reconstructed: a day whose end is still in the future
        would be a prediction dressed as history. `as_of_at` of each row is that day's exclusive
        cutoff instant (UTC). Existing observations are skipped (OBSERVED wins); an existing
        reconstruction with different content raises `BOOKING_SNAPSHOT_CONFLICT`.
        """
        self._validate_range(snapshot_date_start, snapshot_date_end, "snapshot_date")
        self._validate_range(stay_date_start, stay_date_end, "stay_date")
        snapshot_days = date_range(snapshot_date_start, snapshot_date_end)
        stay_days = date_range(stay_date_start, stay_date_end)
        if len(snapshot_days) * len(stay_days) > MAX_RECONSTRUCTED_ROWS:
            raise SnapshotError(
                SnapshotErrorCode.INVALID_RANGE,
                "The reconstruction would store too many rows",
                details={"reason": "too_many_rows", "max_rows": MAX_RECONSTRUCTED_ROWS},
            )

        def run() -> SnapshotRunResult:
            source = self._load_source(property_id, data_source_id)
            cutoffs = [end_of_local_day(day, source.timezone) for day in snapshot_days]
            now = self._begin(source)
            if cutoffs[-1] > now:
                raise SnapshotError(
                    SnapshotErrorCode.INVALID_RANGE,
                    "A snapshot day that has not ended yet cannot be reconstructed",
                    details={"reason": "snapshot_date_not_completed"},
                )
            stays = self._stays.list_stays(
                source.property_id, source.data_source_id, stay_date_start, stay_date_end
            )
            capacity = {
                row.stay_date: row.rooms_available
                for row in self._inventory.list_for_range(
                    source.property_id, stay_date_start, stay_date_end
                )
            }
            grid = aggregate_reconstruction(
                stays, snapshot_days, cutoffs, stay_date_start, stay_date_end
            )
            calculated = [
                NewSnapshot.of(
                    build_content(
                        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
                        snapshot_local_date=snapshot_day,
                        stay_date=stay_day,
                        data_source_id=source.data_source_id,
                        totals=grid[k][j],
                        rooms_available=capacity.get(stay_day),
                    ),
                    cutoffs[k],
                )
                for k, snapshot_day in enumerate(snapshot_days)
                for j, stay_day in enumerate(stay_days)
            ]
            existing = self._snapshots.existing_in_range(
                source.data_source_id,
                snapshot_date_start,
                snapshot_date_end,
                stay_date_start,
                stay_date_end,
            )
            created, unchanged, skipped = self._store(
                source, calculated, existing, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
            )
            logger.info(
                "reconstructed snapshots stored workspace_id=%s property_id=%s data_source_id=%s "
                "created=%d unchanged=%d skipped_observed=%d",
                self._tenant.workspace_id,
                source.property_id,
                source.data_source_id,
                created,
                unchanged,
                skipped,
            )
            return SnapshotRunResult(
                origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
                property_id=source.property_id,
                data_source_id=source.data_source_id,
                snapshot_date_first=snapshot_date_start,
                snapshot_date_last=snapshot_date_end,
                stay_date_first=stay_date_start,
                stay_date_last=stay_date_end,
                created=created,
                unchanged=unchanged,
                skipped_observed=skipped,
            )

        return self._finish(run)
