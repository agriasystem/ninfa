"""How many rooms a property can sell, as the person says it: "24 camere".

There is no second model of the inventory: `room_inventory_daily`, one row per stay night, is what
the observations and the detectors read, and what the operator's `set-room-inventory` command
writes. The person gives one number, and it is written on every night from the property-local today
on:

* a night already gone is never touched, nor is a stored observation (it copied the capacity when it
  was taken, and a run keeps pointing at what it read). A change counts from today;
* the nights are written for `INVENTORY_HORIZON_DAYS` ahead in one go, so no job has to keep
  extending them and nothing can silently stop: the far end is ten years away, and the next save
  moves it;
* the number is never inferred from the bookings, and 0 is not a capacity of a hotel: "closed
  tonight" is a real value of a single night, which this form does not offer.

What the observations say changes only when one is taken: a save that changed something asks for a
refresh of the analysis (the same job as after an import), so the occupancy follows by itself.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.analysis.queue import enqueue_refresh
from app.modules.analysis.refresh import RefreshSkipReason, plan_refresh
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.localtime import local_date_of
from app.modules.snapshots.models import RoomInventoryDaily
from app.modules.snapshots.repository import RoomInventoryRepository

logger = logging.getLogger(__name__)

MIN_ROOMS = 1
MAX_ROOMS = 5000
INVENTORY_HORIZON_DAYS = 3653  # ten years, leap days included


@dataclass(frozen=True, slots=True)
class RoomInventoryState:
    """The capacity from the property-local today on. `rooms_available` is the first known night's;
    `varies` says the coming nights do not all share it (set per period by an operator, or with
    gaps)."""

    configured: bool
    rooms_available: int | None
    varies: bool
    first_night: date | None
    last_night: date | None


@dataclass(frozen=True, slots=True)
class RoomInventorySaved:
    state: RoomInventoryState
    # Nights written or changed: 0 when the number was already that one.
    changed_nights: int
    # A refresh was asked for, so the occupancy follows by itself. False with nothing to analyse
    # yet.
    analysis_requested: bool


class RoomInventoryService:
    """Tenant-scoped. `state` only reads; `save` owns its transaction. The clock can be passed
    in."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    def _property(self, property_id: UUID) -> Property:
        prop = PropertyRepository(self._session, self._tenant).get(property_id)
        if prop is None:
            raise NotFoundError("Property")
        return prop

    def state(self, property_id: UUID, now: datetime | None = None) -> RoomInventoryState:
        now = datetime.now(UTC) if now is None else now
        today = local_date_of(now, ZoneInfo(self._property(property_id).timezone))
        scope = (
            RoomInventoryDaily.workspace_id == self._tenant.workspace_id,
            RoomInventoryDaily.property_id == property_id,
            RoomInventoryDaily.stay_date >= today,
        )
        first, last, nights, numbers = self._session.execute(
            select(
                func.min(RoomInventoryDaily.stay_date),
                func.max(RoomInventoryDaily.stay_date),
                func.count(),
                func.count(RoomInventoryDaily.rooms_available.distinct()),
            ).where(*scope)
        ).one()
        if first is None:
            return RoomInventoryState(False, None, False, None, None)
        rooms = self._session.scalar(
            select(RoomInventoryDaily.rooms_available).where(
                *scope, RoomInventoryDaily.stay_date == first
            )
        )
        gaps = nights != (last - first).days + 1
        return RoomInventoryState(True, rooms, numbers > 1 or gaps, first, last)

    def save(
        self, property_id: UUID, rooms_available: int, now: datetime | None = None
    ) -> RoomInventorySaved:
        """Write the number on every night from today on, then ask for a refresh if that changed
        anything and there is something to analyse. Saved and refused are the only two answers: a
        refresh that cannot be queued is logged, and the day's analysis takes the capacity in
        anyway."""
        now = datetime.now(UTC) if now is None else now
        if not MIN_ROOMS <= rooms_available <= MAX_ROOMS:
            raise ValueError("rooms_available is out of range")
        today = local_date_of(now, ZoneInfo(self._property(property_id).timezone))
        last = today + timedelta(days=INVENTORY_HORIZON_DAYS - 1)
        try:
            changed = RoomInventoryRepository(self._session, self._tenant).set_for_range(
                property_id, today, last, rooms_available=rooms_available
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info(
            "room inventory saved workspace_id=%s property_id=%s rooms_available=%d "
            "changed_nights=%d from=%s",
            self._tenant.workspace_id,
            property_id,
            rooms_available,
            changed,
            today,
        )
        requested = changed > 0 and self._request_refresh(property_id, now)
        return RoomInventorySaved(self.state(property_id, now), changed, requested)

    def _request_refresh(self, property_id: UUID, now: datetime) -> bool:
        if isinstance(
            plan_refresh(self._session, self._tenant, property_id, now), RefreshSkipReason
        ):
            return False  # no bookings yet: the first import brings the occupancy with it
        try:
            enqueue_refresh(self._session, self._tenant, property_id)
            self._session.commit()
        except SQLAlchemyError as error:
            self._session.rollback()
            logger.error(
                "analysis refresh not queued workspace_id=%s property_id=%s error_type=%s",
                self._tenant.workspace_id,
                property_id,
                type(error).__name__,
            )
            return False
        return True


__all__ = [
    "INVENTORY_HORIZON_DAYS",
    "MAX_ROOMS",
    "MIN_ROOMS",
    "RoomInventorySaved",
    "RoomInventoryService",
    "RoomInventoryState",
]
