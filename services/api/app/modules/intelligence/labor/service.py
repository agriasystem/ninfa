"""LaborDecisionService: evaluates LABOR_OVERSTAFFING for one target booking snapshot / category.

    validate -> demand forecast (Gate 5's own machinery) -> load the target's labor plan and the
    historical comparable days (set-based) -> evaluate in memory

The service is READ-ONLY: it writes nothing, never commits or rolls back, takes no advisory lock
and reads no clock (the target is always an already-stored booking snapshot; the "as of" date is
its own `snapshot_local_date`, never `date.today()`). It persists no Decision: an evaluation is a
value returned to the caller. The database work is a fixed handful of statements whatever the
number of historical candidate days: the target snapshot, the booking/labor data sources, the
property, the demand forecast's own bounded reads, ONE labor-entries read of every work date
involved and ONE booking-snapshot read of every historical lead-time-0 key.

Everything is read through the repositories of the TenantContext: a target, source or entry of
another workspace simply does not exist for this service, and an unknown id and a foreign id
raise the same error.
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.demand.service import (
    DemandForecastError,
    DemandForecastErrorCode,
    DemandForecastService,
)
from app.modules.intelligence.labor.aggregation import (
    LaborEntryRow,
    build_target_plan,
    latest_snapshot_rows_by_work_date,
)
from app.modules.intelligence.labor.cost_proxy import TargetCategoryCost
from app.modules.intelligence.labor.detector import evaluate_labor_overstaffing
from app.modules.intelligence.labor.errors import LaborDecisionError, LaborDecisionErrorCode
from app.modules.intelligence.labor.precision import exact_sum
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.intelligence.labor.selection import (
    OccupancyLeadZeroRow,
    candidate_work_dates,
    select_comparables,
)
from app.modules.intelligence.labor.types import LaborDecisionEvaluation
from app.modules.labor.roles import LaborCategory
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.repository import BookingSnapshotRepository

logger = logging.getLogger(__name__)

_DEMAND_ERROR_CODES = {
    DemandForecastErrorCode.TARGET_NOT_FOUND: LaborDecisionErrorCode.TARGET_NOT_FOUND,
    DemandForecastErrorCode.TARGET_NOT_OBSERVED: LaborDecisionErrorCode.TARGET_NOT_OBSERVED,
    DemandForecastErrorCode.INVALID_TARGET: LaborDecisionErrorCode.INVALID_TARGET,
}


def _target_cost(
    day_rows: list[LaborEntryRow] | None, category: LaborCategory
) -> TargetCategoryCost:
    if not day_rows:
        return TargetCategoryCost(None, None)
    category_rows = [row for row in day_rows if row.labor_category == category]
    costs = [row.planned_cost for row in category_rows if row.planned_cost is not None]
    currencies = {row.currency for row in category_rows if row.planned_cost is not None}
    if costs and len(currencies) == 1:
        return TargetCategoryCost(exact_sum(costs), next(iter(currencies)))
    return TargetCategoryCost(None, None)


class LaborDecisionService:
    """Read-only. Pass any session: the service neither commits nor rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Labor Decision service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._labor = LaborEvaluationRepository(session, tenant)
        self._demand = DemandForecastService(session, tenant)

    def evaluate_overstaffing(
        self,
        *,
        target_booking_snapshot_id: UUID,
        labor_data_source_id: UUID,
        labor_category: LaborCategory,
    ) -> LaborDecisionEvaluation:
        if not isinstance(labor_category, LaborCategory):
            raise LaborDecisionError(
                LaborDecisionErrorCode.INVALID_CATEGORY,
                "The labor category must be a LaborCategory",
            )

        try:
            demand = self._demand.forecast_for_target(target_booking_snapshot_id)
        except DemandForecastError as error:
            code = _DEMAND_ERROR_CODES.get(
                error.error_code, LaborDecisionErrorCode.TARGET_NOT_FOUND
            )
            raise LaborDecisionError(code, error.message) from error

        self._validate_booking_source(demand.booking_data_source_id, demand.property_id)
        self._validate_labor_source(labor_data_source_id, demand.property_id)

        target_as_of_date = demand.snapshot_local_date
        target_work_date = demand.stay_date

        candidates = candidate_work_dates(target_work_date, target_as_of_date)
        wanted_dates = {target_work_date, *candidates}
        raw_rows = self._labor.entries_as_of(labor_data_source_id, target_as_of_date, wanted_dates)
        by_date = latest_snapshot_rows_by_work_date(raw_rows)

        target_labor_snapshot_id: UUID | None = None
        target_day_rows: list[LaborEntryRow] | None = None
        found = by_date.get(target_work_date)
        if found is not None:
            target_labor_snapshot_id, target_day_rows = found
        target_plan = (
            None if target_day_rows is None else build_target_plan(target_day_rows, labor_category)
        )
        target_cost = _target_cost(target_day_rows, labor_category)

        keys = {(day, day) for day in candidates}
        booking_rows = self._snapshots.list_by_keys(demand.booking_data_source_id, keys)
        occupancy_by_date = {
            row.stay_date: OccupancyLeadZeroRow(
                booking_snapshot_id=row.snapshot_id,
                rooms_on_books=row.rooms_on_books,
                uncertain_rooms=row.uncertain_rooms,
                origin=row.origin,
            )
            for row in booking_rows
        }

        def occupancy_of(day):  # type: ignore[no-untyped-def]
            return occupancy_by_date.get(day)

        def labor_of(day):  # type: ignore[no-untyped-def]
            return by_date.get(day)

        def select(forecast_rooms):  # type: ignore[no-untyped-def]
            return select_comparables(
                target_work_date,
                target_as_of_date,
                forecast_rooms,
                labor_category,
                occupancy_of=occupancy_of,
                labor_of=labor_of,
            )

        evaluation = evaluate_labor_overstaffing(
            workspace_id=self._tenant.workspace_id,
            property_id=demand.property_id,
            booking_data_source_id=demand.booking_data_source_id,
            labor_data_source_id=labor_data_source_id,
            target_booking_snapshot_id=target_booking_snapshot_id,
            target_as_of_date=target_as_of_date,
            target_work_date=target_work_date,
            labor_category=labor_category,
            demand=demand,
            target_labor_snapshot_id=target_labor_snapshot_id,
            target_plan=target_plan,
            target_cost=target_cost,
            select=select,
        )
        logger.info(
            "labor overstaffing evaluated workspace_id=%s property_id=%s "
            "target_booking_snapshot_id=%s labor_category=%s status=%s",
            self._tenant.workspace_id,
            demand.property_id,
            target_booking_snapshot_id,
            labor_category.value,
            evaluation.status.value,
        )
        return evaluation

    # --- validation ---------------------------------------------------------------------------

    def _validate_booking_source(self, data_source_id: UUID, property_id: UUID) -> None:
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise LaborDecisionError(
                LaborDecisionErrorCode.INVALID_PROPERTY,
                "The property cannot be used for Labor Decision Detection",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        source = self._data_sources.get(data_source_id)
        reason = None
        if source is None:
            reason = "not_found"
        elif source.domain != DataSourceDomain.BOOKINGS:
            reason = "wrong_domain"
        elif not source.is_active:
            reason = "inactive"
        elif source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise LaborDecisionError(
                LaborDecisionErrorCode.BOOKING_DATA_SOURCE_INVALID,
                "The booking data source cannot be used as the demand denominator",
                details={"reason": reason},
            )

    def _validate_labor_source(self, data_source_id: UUID, property_id: UUID) -> None:
        source = self._data_sources.get(data_source_id)
        reason = None
        if source is None:
            reason = "not_found"
        elif source.domain != DataSourceDomain.LABOR:
            reason = "wrong_domain"
        elif not source.is_active:
            reason = "inactive"
        elif source.property_id != property_id:
            reason = "property_mismatch"
        if reason is not None:
            raise LaborDecisionError(
                LaborDecisionErrorCode.LABOR_DATA_SOURCE_INVALID,
                "The labor data source cannot be used for Labor Decision Detection",
                details={"reason": reason},
            )
