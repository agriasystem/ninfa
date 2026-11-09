"""The history a cost per occupied room needs, rebuilt from the bookings the hotel gave.

A month's cost per occupied room divides its cost by the rooms on the books of EVERY day of that
month, each as the end of that very day saw it (Cost CPOR V1's lead-time-0 snapshot). A property
that began to be analysed on the 9th of November has no such snapshot for October, so the cost of
October stays "month incomplete" however many invoices it has. What can be said about those days
is what the bookings imported today say about them: a RECONSTRUCTION, stored as one
(`RECONSTRUCTED_APPROXIMATE`, never an observation of that day), which the cost engine admits at a
lower quality than an observed day and which tells the two apart in its provenance.

This is the one place that asks for it, and it asks as little as it can:

* only the concluded months the invoices really touch (the months a cost is evaluated for), only
  their lead-time-0 day, never a grid of lead times nobody reads;
* only a night that has a room inventory. A reconstruction copies the capacity of the night when it
  is stored and is never rewritten, so one made before the inventory existed would keep "capacity
  unknown" for good. This is why the inventory comes first, and why saving one with a past "valid
  from" is what makes the history possible;
* only a night the bookings speak about (between the first night and the last night any current
  booking covers). Before the file begins a night is not "zero rooms", it is unknown, and it stays
  unknown;
* never over a snapshot that exists, whatever its origin: an observation wins, and a stored
  reconstruction is history that is not revised. Nothing already analysed changes.

Idempotent: a second call finds every one of those nights stored and writes nothing.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.snapshots.errors import SnapshotError, SnapshotErrorCode
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import (
    BookingSnapshotRepository,
    BookingStayRepository,
    RoomInventoryRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HistoryBackfill:
    """`considered` are the days of the concluded cost months, `rebuilt` the ones stored now."""

    considered: int
    rebuilt: int


_NOTHING = HistoryBackfill(0, 0)


def _days_of(months: tuple[tuple[int, int], ...], local_today: date) -> list[date]:
    days = {
        day
        for year, month in months
        for day in CalendarMonth(year, month).day_list()
        if day < local_today
    }
    return sorted(days)


def backfill_lead_zero_history(
    session: Session,
    tenant: TenantContext,
    *,
    property_id: UUID,
    data_source_id: UUID,
    cost_months: tuple[tuple[int, int], ...],
    local_today: date,
    now: datetime | None = None,
) -> HistoryBackfill:
    """Store the missing lead-time-0 reconstructions of the cost months (see the module doc).

    The caller's session must have no uncommitted work: every night is its own committed
    transaction, like any snapshot run."""
    days = _days_of(cost_months, local_today)
    if not days:
        return _NOTHING
    span = BookingStayRepository(session, tenant).stay_span(property_id, data_source_id)
    if span is None:
        return HistoryBackfill(len(days), 0)
    capacity_known = {
        row.stay_date
        for row in RoomInventoryRepository(session, tenant).list_for_range(
            property_id, days[0], days[-1]
        )
    }
    stored = {
        (row.snapshot_local_date, row.stay_date)
        for row in BookingSnapshotRepository(session, tenant).list_by_keys(
            data_source_id, [(day, day) for day in days]
        )
    }
    wanted = [
        day
        for day in days
        if span[0] <= day <= span[1] and day in capacity_known and (day, day) not in stored
    ]
    instant = datetime.now(UTC) if now is None else now
    service = BookingSnapshotReconstructionService(session, tenant, clock=lambda: instant)
    rebuilt = 0
    for day in wanted:
        try:
            result = service.reconstruct(
                property_id=property_id,
                data_source_id=data_source_id,
                snapshot_date_start=day,
                snapshot_date_end=day,
                stay_date_start=day,
                stay_date_end=day,
            )
        except SnapshotError as error:
            if error.code != SnapshotErrorCode.CONFLICT:
                raise
            # Somebody stored that night between the read and the write: it exists now.
            continue
        rebuilt += result.created
    if rebuilt:
        logger.info(
            "history rebuilt workspace_id=%s property_id=%s data_source_id=%s days=%d",
            tenant.workspace_id,
            property_id,
            data_source_id,
            rebuilt,
        )
    return HistoryBackfill(len(days), rebuilt)


__all__ = ["HistoryBackfill", "backfill_lead_zero_history"]
