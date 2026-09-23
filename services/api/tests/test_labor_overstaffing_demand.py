"""LABOR_OVERSTAFFING with a real lead_time > 0 demand forecast, reusing the REAL Gate 4/5
machinery (BookingExpectedService + DemandForecastService) end to end.

Lead time is kept small (1 day) so that, within the fixed 42-day seasonal window Gate 4/5 both
use, there is room for several same-weekday historical Saturdays that are ALSO strictly before
the target's own as-of date (the anti-leakage rule both the Expected baseline and the
remaining-pickup pairs enforce): with a 14-day lead (the Gate 4/5 test suites' own default target)
that window leaves only 4 candidates, one short of both MIN_PAIRS and Labor's MIN_COMPARABLES.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.demand.service import DemandForecastService, DemandForecastStatus
from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.labor.types import EvaluationStatus, ReasonCode
from app.modules.labor.roles import LaborCategory
from tests.expected_support import add_snapshots
from tests.labor_support import LaborFactory, LaborTenant, LaborWorld, labor_data_source
from tests.revenue_support import RevenueWorld, snap
from tests.support import Tenant

TARGET_STAY = date(2026, 8, 15)  # a Saturday
LEAD = 1
TARGET_AS_OF = TARGET_STAY - timedelta(days=LEAD)


def _historical_saturdays(n: int) -> list[date]:
    return [TARGET_STAY - timedelta(weeks=k) for k in range(1, n + 1)]


def _build_target(session: Session, tenant: Tenant, rooms: int) -> RevenueWorld:
    row = snap(tenant, TARGET_AS_OF, TARGET_STAY, rooms)
    add_snapshots(session, tenant, [row])
    return RevenueWorld(session, tenant, row["id"], [row])


def test_demand_forecast_reuses_gate5_pairing_for_a_future_target(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = factory.tenant()  # a plain BOOKINGS tenant
    world = _build_target(db_session, tenant, rooms=20)
    for stay in _historical_saturdays(6):
        world.curve(stay, prior=None, anchor=20, final=30, lead=LEAD)
    world.calculate()

    demand = DemandForecastService(db_session, tenant.context).forecast_for_target(world.target_id)
    assert demand.status == DemandForecastStatus.READY
    assert demand.forecast_rooms_exact == Decimal(30)  # 20 rooms + median remaining pickup (10)
    assert demand.demand_confidence is not None and demand.demand_confidence > 0
    assert demand.lead_time_days == LEAD


def test_labor_overstaffing_evaluates_end_to_end_for_a_future_target(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = factory.tenant()
    labor_source = labor_data_source(factory, tenant.property)
    labor_job = factory.import_job(labor_source)
    labor_tenant = LaborTenant(
        workspace=tenant.workspace,
        property=tenant.property,
        booking_data_source=tenant.data_source,
        labor_data_source=labor_source,
        booking_import_job=tenant.import_job,
        labor_import_job=labor_job,
    )

    world = _build_target(db_session, tenant, rooms=20)
    historical_saturdays = _historical_saturdays(6)
    for stay in historical_saturdays:
        world.curve(stay, prior=None, anchor=20, final=30, lead=LEAD)
    world.calculate()

    labor_world = LaborWorld(db_session, labor_tenant)
    for stay in historical_saturdays:
        labor_world.labor_day(TARGET_AS_OF, stay, LaborCategory.HOUSEKEEPING, actual_hours="24")
    labor_world.labor_day(TARGET_AS_OF, TARGET_STAY, LaborCategory.HOUSEKEEPING, planned_hours="32")

    service = LaborDecisionService(db_session, labor_tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=world.target_id,
        labor_data_source_id=labor_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )

    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_LABOR_OVERSTAFFING,)
    assert evaluation.forecast_rooms_exact == Decimal(30)
    assert evaluation.scheduled_hours_exact == Decimal(32)
    assert evaluation.expected_labor_hours_exact == Decimal(24)
    assert evaluation.target_work_date == TARGET_STAY
    assert evaluation.target_as_of_date == TARGET_AS_OF


def test_insufficient_gate4_baseline_makes_labor_demand_insufficient(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = factory.tenant()
    labor_source = labor_data_source(factory, tenant.property)
    labor_job = factory.import_job(labor_source)
    world = _build_target(db_session, tenant, rooms=20)
    # Fewer than 5 comparables: Gate 4's baseline is INSUFFICIENT_DATA.
    for stay in _historical_saturdays(2):
        world.curve(stay, prior=None, anchor=20, final=30, lead=LEAD)
    world.calculate()

    labor_tenant = LaborTenant(
        workspace=tenant.workspace,
        property=tenant.property,
        booking_data_source=tenant.data_source,
        labor_data_source=labor_source,
        booking_import_job=tenant.import_job,
        labor_import_job=labor_job,
    )
    service = LaborDecisionService(db_session, labor_tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=world.target_id,
        labor_data_source_id=labor_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.LABOR_DEMAND_FORECAST_INSUFFICIENT,)
