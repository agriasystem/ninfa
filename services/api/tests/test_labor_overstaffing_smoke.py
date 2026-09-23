"""Smoke tests for LaborDecisionService.evaluate_overstaffing (lead_time = 0 scenarios)."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.labor.types import EvaluationStatus, ReasonCode
from app.modules.labor.roles import LaborCategory
from tests.labor_support import LaborFactory, LaborWorld, labor_tenant

TARGET = date(2026, 6, 15)  # a Monday


def _historical_mondays(n: int) -> list[date]:
    return [TARGET - timedelta(weeks=k) for k in range(1, n + 1)]


def test_a_clear_overstaffing_pattern_triggers(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)

    for day in _historical_mondays(6):
        world.booking_day(day, rooms_on_books=30)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="24")

    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="32")

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )

    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_LABOR_OVERSTAFFING,)
    assert evaluation.scheduled_hours_exact == Decimal(32)
    assert evaluation.expected_labor_hours_exact == Decimal(24)
    assert evaluation.excess_hours_exact == Decimal(8)
    assert evaluation.delta_percent_display == Decimal("33.33")
    assert evaluation.sample_count == 6
    assert evaluation.fully_observed_count == 6
    assert evaluation.confidence_score >= Decimal(55)
    assert evaluation.calculation_fingerprint != ""


def test_a_normal_schedule_is_clear(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    for day in _historical_mondays(6):
        world.booking_day(day, rooms_on_books=30)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="24")
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="24.5")

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)


def test_other_category_is_not_applicable(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.OTHER,
    )
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.LABOR_CATEGORY_OTHER_NOT_ACTIONABLE,)


def test_category_not_scheduled_is_not_applicable(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="10")

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.KITCHEN,  # not scheduled that day
    )
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.LABOR_CATEGORY_NOT_SCHEDULED,)


def test_no_labor_plan_at_all_is_insufficient_data(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.LABOR_PLAN_MISSING,)


def test_fewer_than_5_comparables_is_insufficient_data(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    for day in _historical_mondays(3):  # fewer than 5
        world.booking_day(day, rooms_on_books=30)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="24")
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="32")

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.LABOR_COMPARABLE_SAMPLE_INSUFFICIENT,)
