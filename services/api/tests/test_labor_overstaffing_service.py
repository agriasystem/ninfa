"""LaborDecisionService: read-only, bounded query count, determinism (Gate 8, Parts W/X/Y)."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.labor.types import EvaluationStatus
from app.modules.labor.models import LaborEntry, LaborSnapshot
from app.modules.labor.roles import LaborCategory
from app.modules.snapshots.models import BookingSnapshot
from tests.labor_support import (
    LaborFactory,
    LaborTenant,
    LaborWorld,
    labor_snapshot,
    labor_tenant,
    statements_of,
)

TARGET = date(2026, 6, 15)  # a Monday


def _historical_mondays(n: int) -> list[date]:
    return [TARGET - timedelta(weeks=k) for k in range(1, n + 1)]


def _build_world(db_session: Session, tenant: LaborTenant, n: int = 6) -> LaborWorld:
    world = LaborWorld(db_session, tenant)
    for day in _historical_mondays(n):
        world.booking_day(day, rooms_on_books=30)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="24")
    world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="32")
    return world


def _row_counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(LaborSnapshot)) or 0,
        session.scalar(select(func.count()).select_from(LaborEntry)) or 0,
        session.scalar(select(func.count()).select_from(BookingSnapshot)) or 0,
    )


def test_an_evaluation_writes_nothing(db_session: Session, factory: LaborFactory) -> None:
    tenant = labor_tenant(factory)
    _build_world(db_session, tenant)
    db_session.flush()
    before = _row_counts(db_session)

    service = LaborDecisionService(db_session, tenant.context)
    target = (
        db_session.query(BookingSnapshot)
        .filter_by(stay_date=TARGET, snapshot_local_date=TARGET)
        .one()
    )

    with statements_of(db_session) as statements:
        service.evaluate_overstaffing(
            target_booking_snapshot_id=target.id,
            labor_data_source_id=tenant.labor_data_source.id,
            labor_category=LaborCategory.HOUSEKEEPING,
        )

    kinds = {sql.lstrip().split()[0].upper() for sql, _ in statements}
    assert kinds == {"SELECT"}, kinds  # never an INSERT, UPDATE, DELETE or lock
    assert not any("advisory" in sql.lower() for sql, _ in statements)
    assert _row_counts(db_session) == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_the_query_count_is_bounded_and_does_not_grow_with_comparables(
    db_session: Session, factory: LaborFactory
) -> None:
    small_tenant = labor_tenant(factory)
    _build_world(db_session, small_tenant, n=5)
    db_session.flush()
    small_target = (
        db_session.query(BookingSnapshot)
        .filter_by(
            data_source_id=small_tenant.booking_data_source.id,
            stay_date=TARGET,
            snapshot_local_date=TARGET,
        )
        .one()
    )
    service = LaborDecisionService(db_session, small_tenant.context)
    with statements_of(db_session) as small_statements:
        service.evaluate_overstaffing(
            target_booking_snapshot_id=small_target.id,
            labor_data_source_id=small_tenant.labor_data_source.id,
            labor_category=LaborCategory.HOUSEKEEPING,
        )

    large_tenant = labor_tenant(factory)
    _build_world(db_session, large_tenant, n=20)
    db_session.flush()
    large_target = (
        db_session.query(BookingSnapshot)
        .filter_by(
            data_source_id=large_tenant.booking_data_source.id,
            stay_date=TARGET,
            snapshot_local_date=TARGET,
        )
        .one()
    )
    service = LaborDecisionService(db_session, large_tenant.context)
    with statements_of(db_session) as large_statements:
        service.evaluate_overstaffing(
            target_booking_snapshot_id=large_target.id,
            labor_data_source_id=large_tenant.labor_data_source.id,
            labor_category=LaborCategory.HOUSEKEEPING,
        )

    assert len(small_statements) == len(large_statements)
    assert len(large_statements) <= 12


def test_no_statement_touches_labor_entries_more_than_once(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    _build_world(db_session, tenant, n=15)
    db_session.flush()
    target = (
        db_session.query(BookingSnapshot)
        .filter_by(
            data_source_id=tenant.booking_data_source.id,
            stay_date=TARGET,
            snapshot_local_date=TARGET,
        )
        .one()
    )
    service = LaborDecisionService(db_session, tenant.context)
    with statements_of(db_session) as statements:
        service.evaluate_overstaffing(
            target_booking_snapshot_id=target.id,
            labor_data_source_id=tenant.labor_data_source.id,
            labor_category=LaborCategory.HOUSEKEEPING,
        )
    touching_entries = [sql for sql, _ in statements if "labor_entries" in sql.lower()]
    assert len(touching_entries) == 1


def test_the_fingerprint_is_deterministic_across_two_evaluations(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    _build_world(db_session, tenant)
    target = (
        db_session.query(BookingSnapshot)
        .filter_by(
            data_source_id=tenant.booking_data_source.id,
            stay_date=TARGET,
            snapshot_local_date=TARGET,
        )
        .one()
    )

    service = LaborDecisionService(db_session, tenant.context)
    first = service.evaluate_overstaffing(
        target_booking_snapshot_id=target.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    second = service.evaluate_overstaffing(
        target_booking_snapshot_id=target.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert first.calculation_fingerprint != ""
    assert first.status == second.status == EvaluationStatus.TRIGGERED


def test_a_future_labor_snapshot_after_the_as_of_date_never_leaks_in(
    db_session: Session, factory: LaborFactory
) -> None:
    tenant = labor_tenant(factory)
    _build_world(db_session, tenant)
    target = (
        db_session.query(BookingSnapshot)
        .filter_by(
            data_source_id=tenant.booking_data_source.id,
            stay_date=TARGET,
            snapshot_local_date=TARGET,
        )
        .one()
    )

    service = LaborDecisionService(db_session, tenant.context)
    before = service.evaluate_overstaffing(
        target_booking_snapshot_id=target.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )

    # A LATER labor snapshot (as of AFTER the target's own as-of date) that would change the
    # target's schedule if it leaked in: it must never be read.
    future_as_of = TARGET + timedelta(days=1)
    labor_snapshot(
        factory,
        tenant.labor_data_source,
        tenant.labor_import_job,
        factory.import_file(tenant.labor_import_job),
        snapshot_local_date=future_as_of,
    )
    db_session.flush()

    after = service.evaluate_overstaffing(
        target_booking_snapshot_id=target.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert after.calculation_fingerprint == before.calculation_fingerprint
    assert after.scheduled_hours_exact == before.scheduled_hours_exact
