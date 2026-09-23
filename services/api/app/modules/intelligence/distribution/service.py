"""OtaDependencyService: evaluates REV_OTA_DEPENDENCY for one property / booking source / as-of.

    validate -> load the target's 30-snapshot window (set-based) -> if it is fit to be judged,
    reconstruct its channel mix and the historical comparables' (set-based) -> evaluate in memory

The service is READ-ONLY: it writes nothing, never commits or rolls back, takes no advisory lock
and reads no clock (`as_of_local_date` is always given explicitly by the caller; there is no
`date.today()` anywhere in this module or below it). It persists no Decision: an evaluation is a
value returned to the caller. The database work is a fixed handful of statements whatever the
number of historical comparable periods: the property/data source, ONE batched snapshot read of
every (as-of, stay date) key a run needs, and - only when the target's own window is usable - ONE
channel read and ONE booking read covering every window (the target's and every candidate's).

Everything is read through the repositories of the TenantContext: a property, data source or
booking of another workspace simply does not exist for this service, and an unknown id and a
foreign id raise the same error.
"""

import logging
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain, DataSourceType
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.distribution.channels import ChannelClassification, classify_channels
from app.modules.intelligence.distribution.detector import evaluate_ota_dependency
from app.modules.intelligence.distribution.errors import OtaDependencyError, OtaDependencyErrorCode
from app.modules.intelligence.distribution.metrics import (
    build_target_facts,
    reconstruct_channel_mix,
)
from app.modules.intelligence.distribution.repository import DistributionRepository
from app.modules.intelligence.distribution.selection import (
    candidate_as_of_dates,
    select_comparable_periods,
)
from app.modules.intelligence.distribution.temporal import StayRecord
from app.modules.intelligence.distribution.types import (
    FORWARD_STAY_WINDOW_DAYS,
    LOOKBACK_DAYS,
    SEASONAL_WINDOW_DAYS,
    OtaDependencyEvaluation,
)
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.localtime import end_of_local_day

logger = logging.getLogger(__name__)


class OtaDependencyService:
    """Read-only. Pass any session: the service neither commits nor rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the OTA Dependency service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._repo = DistributionRepository(session, tenant)

    def evaluate(
        self,
        *,
        property_id: UUID,
        booking_data_source_id: UUID,
        as_of_local_date: date,
    ) -> OtaDependencyEvaluation:
        # datetime is a subclass of date: refuse it, its time part would be silently ignored.
        if isinstance(as_of_local_date, datetime) or not isinstance(as_of_local_date, date):
            raise OtaDependencyError(
                OtaDependencyErrorCode.INVALID_AS_OF_DATE,
                "as_of_local_date must be an explicit date, never a datetime or date.today()",
            )

        timezone = self._validate_booking_source(property_id, booking_data_source_id)

        window_start = as_of_local_date
        window_end = as_of_local_date + timedelta(days=FORWARD_STAY_WINDOW_DAYS - 1)
        candidates = candidate_as_of_dates(
            as_of_local_date, lookback_days=LOOKBACK_DAYS, seasonal_window_days=SEASONAL_WINDOW_DAYS
        )

        snapshot_rows_by_as_of = self._repo.snapshot_rows_by_as_of(
            booking_data_source_id, [as_of_local_date, *candidates], FORWARD_STAY_WINDOW_DAYS
        )
        target_rows = snapshot_rows_by_as_of[as_of_local_date]
        target_window_complete = len(target_rows) == FORWARD_STAY_WINDOW_DAYS
        target_any_uncertain = target_window_complete and any(
            row.uncertain_rooms > 0 for row in target_rows
        )

        target_facts = None
        stays: list[tuple[StayRecord, UUID]] = []
        classifications: dict[UUID, ChannelClassification] = {}
        if target_window_complete and not target_any_uncertain:
            classifications = classify_channels(self._repo.list_channels(property_id))
            first_night = min([window_start, *candidates])
            last_night = max(
                window_end, *(c + timedelta(days=FORWARD_STAY_WINDOW_DAYS - 1) for c in candidates)
            )
            stays = self._repo.list_stays_with_channel(
                property_id, booking_data_source_id, first_night, last_night
            )
            cutoff = end_of_local_day(as_of_local_date, timezone)
            mix = reconstruct_channel_mix(
                stays,
                classifications,
                as_of_local_date=as_of_local_date,
                cutoff=cutoff,
                window_start=window_start,
                window_end=window_end,
            )
            target_facts = build_target_facts(target_rows, mix)

        def select():  # type: ignore[no-untyped-def]
            return select_comparable_periods(
                as_of_local_date,
                snapshot_rows_of=lambda h: snapshot_rows_by_as_of.get(h),
                stays=stays,
                classifications=classifications,
                timezone=timezone,
            )

        evaluation = evaluate_ota_dependency(
            workspace_id=self._tenant.workspace_id,
            property_id=property_id,
            booking_data_source_id=booking_data_source_id,
            as_of_local_date=as_of_local_date,
            window_start=window_start,
            window_end=window_end,
            target_window_complete=target_window_complete,
            target_any_uncertain=target_any_uncertain,
            target_facts=target_facts,
            select=select,
        )
        logger.info(
            "ota dependency evaluated workspace_id=%s property_id=%s "
            "booking_data_source_id=%s as_of_local_date=%s status=%s",
            self._tenant.workspace_id,
            property_id,
            booking_data_source_id,
            as_of_local_date.isoformat(),
            evaluation.status.value,
        )
        return evaluation

    # --- validation ---------------------------------------------------------------------------

    def _validate_booking_source(self, property_id: UUID, data_source_id: UUID) -> ZoneInfo:
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise OtaDependencyError(
                OtaDependencyErrorCode.INVALID_PROPERTY,
                "The property cannot be used for OTA Dependency Detection",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        source = self._data_sources.get(data_source_id)
        reason = None
        if source is None:
            reason = "not_found"
        elif source.domain != DataSourceDomain.BOOKINGS:
            reason = "wrong_domain"
        elif source.source_type != DataSourceType.FILE_UPLOAD:
            reason = "wrong_source_type"
        elif not source.is_active:
            reason = "inactive"
        elif source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise OtaDependencyError(
                OtaDependencyErrorCode.BOOKING_DATA_SOURCE_INVALID,
                "The booking data source cannot be used for OTA Dependency Detection",
                details={"reason": reason},
            )
        try:
            return ZoneInfo(prop.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise OtaDependencyError(
                OtaDependencyErrorCode.INVALID_PROPERTY,
                "The property has no valid timezone",
                details={"reason": "invalid_timezone"},
            ) from error
