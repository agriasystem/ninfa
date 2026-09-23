"""LABOR_OVERSTAFFING: exact-Decimal boundary tests for the four trigger conditions and the
confidence gate (Gate 8, Parts F/G). All scenarios use lead_time = 0 (forecast_rooms ==
rooms_on_books, demand_confidence == 100) so only the labor-side thresholds are exercised.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.labor.service import LaborDecisionService
from app.modules.intelligence.labor.types import (
    EvaluationStatus,
    LaborDecisionEvaluation,
    ReasonCode,
)
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from app.modules.snapshots.models import SnapshotOrigin
from tests.labor_support import LaborFactory, LaborWorld, labor_tenant

TARGET = date(2026, 6, 15)  # a Monday


def _historical_mondays(n: int) -> list[date]:
    return [TARGET - timedelta(weeks=k) for k in range(1, n + 1)]


def _build(
    factory: LaborFactory,
    db_session: Session,
    historical_hours: list[str],
    scheduled_hours: str,
    *,
    rooms: int = 30,
) -> LaborDecisionEvaluation:
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    days = _historical_mondays(len(historical_hours))
    for day, hours in zip(days, historical_hours, strict=True):
        world.booking_day(day, rooms_on_books=rooms)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours=hours)
    target_snapshot = world.booking_day(TARGET, rooms_on_books=rooms)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours=scheduled_hours)

    service = LaborDecisionService(db_session, tenant.context)
    return service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )


# 6 identical historical days (IQR = 0, expected = upper_fence = 8h): isolates the EXCESS HOURS
# and RELATIVE conditions from the upper-fence one (they coincide when IQR = 0, so a dedicated
# widened-IQR scenario below isolates the fence condition on its own).
_FLAT_8H = ["8"] * 6


def test_excess_hours_of_exactly_4_reaches_the_threshold(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _build(factory, db_session, _FLAT_8H, "12")  # excess = 4 exact, relative = 50%
    assert evaluation.excess_hours_exact == Decimal(4)
    assert evaluation.excess_hours_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED


def test_excess_hours_of_3_99_does_not_reach_the_threshold(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _build(factory, db_session, _FLAT_8H, "11.98")  # excess = 3.98
    assert evaluation.excess_hours_exact is not None
    assert evaluation.excess_hours_exact < Decimal(4)
    assert evaluation.excess_hours_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)


def test_relative_delta_of_exactly_20_percent_reaches_the_threshold(
    db_session: Session, factory: LaborFactory
) -> None:
    # expected = 24 (flat), scheduled = 28.8 -> delta = 20.00% exact; excess = 4.8 >= 4.
    evaluation = _build(factory, db_session, ["24"] * 6, "28.8")
    assert evaluation.delta_percent_exact == Decimal(20)
    assert evaluation.relative_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED


def test_relative_delta_of_19_99_percent_does_not_reach_the_threshold(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _build(factory, db_session, ["24"] * 6, "28.79")  # delta = 19.9583...%
    assert evaluation.delta_percent_exact is not None
    assert evaluation.delta_percent_exact < Decimal(20)
    assert evaluation.relative_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


def test_all_conditions_must_hold_missing_one_gives_clear(
    db_session: Session, factory: LaborFactory
) -> None:
    # sorted [10,10,10,10,50,90]: median=10, p25=10, p75=40, iqr=30, fence=40+45=85.
    # Large relative delta and excess hours, but the upper fence is far above: the fence
    # condition alone fails, so the whole rule is CLEAR.
    evaluation = _build(factory, db_session, ["10", "10", "10", "10", "50", "90"], "40")
    assert evaluation.above_expected_condition is True
    assert evaluation.relative_condition is True
    assert evaluation.excess_hours_condition is True
    assert evaluation.upper_fence_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


def test_upper_fence_boundary_exact_reaches_triggered(
    db_session: Session, factory: LaborFactory
) -> None:
    # sorted hours [18,20,22,26,28,30]: median=24, p25=20.5, p75=27.5, iqr=7, fence=27.5+10.5=38.
    hours = ["30", "18", "26", "20", "28", "22"]
    evaluation = _build(factory, db_session, hours, "38")
    assert evaluation.expected_labor_hours_exact == Decimal(24)
    assert evaluation.upper_fence_hours_exact == Decimal(38)
    assert evaluation.upper_fence_condition is True
    assert evaluation.status == EvaluationStatus.TRIGGERED


def test_just_below_the_upper_fence_is_clear(db_session: Session, factory: LaborFactory) -> None:
    hours = ["30", "18", "26", "20", "28", "22"]
    evaluation = _build(factory, db_session, hours, "37.99")
    assert evaluation.upper_fence_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


def test_scheduled_not_above_expected_is_clear(db_session: Session, factory: LaborFactory) -> None:
    evaluation = _build(factory, db_session, _FLAT_8H, "8")  # equal, not above
    assert evaluation.above_expected_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


def test_expected_hours_non_positive_is_not_applicable(
    db_session: Session, factory: LaborFactory
) -> None:
    # Zero HOUSEKEEPING hours every historical day, but the day is otherwise staffed normally
    # (a FRONT_OFFICE entry keeps classification coverage well-defined): a real, valid zero.
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    days = _historical_mondays(6)
    for day in days:
        world.booking_day(day, rooms_on_books=30)
        world.labor_day(TARGET, day, LaborCategory.HOUSEKEEPING, actual_hours="0")
        world.labor_day(TARGET, day, LaborCategory.FRONT_OFFICE, actual_hours="8")
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="8")

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.expected_labor_hours_exact == Decimal(0)
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.EXPECTED_LABOR_HOURS_NON_POSITIVE,)


def test_median_of_an_odd_sample_is_the_middle_value(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _build(factory, db_session, ["10", "20", "30", "40", "50"], "60")
    assert evaluation.expected_labor_hours_exact == Decimal(30)


def test_median_of_an_even_sample_is_the_mean_of_the_two_middle_values(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _build(factory, db_session, ["10", "20", "30", "40", "50", "60"], "80")
    assert evaluation.expected_labor_hours_exact == Decimal(35)


def _confidence_gate_scenario(
    factory: LaborFactory, db_session: Session, confidence: str
) -> LaborDecisionEvaluation:
    """5 PLANNED_FALLBACK + RECONSTRUCTED_APPROXIMATE comparables at a tuned classification
    confidence: baseline_confidence lands at exactly 54.99 (confidence="2.72") or 55.00
    (confidence="2.75"), verified against `confidence.baseline_confidence` directly."""
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    for day in _historical_mondays(5):
        world.booking_day(day, rooms_on_books=30, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
        world.labor_day(
            TARGET,
            day,
            LaborCategory.HOUSEKEEPING,
            planned_hours="24",
            method=LaborClassificationMethod.DETERMINISTIC_RULE,
            confidence=confidence,
        )
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="32")

    service = LaborDecisionService(db_session, tenant.context)
    return service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )


def test_confidence_54_99_with_a_numeric_anomaly_is_suppressed(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _confidence_gate_scenario(factory, db_session, "2.72")
    assert evaluation.baseline_confidence == Decimal("54.99")
    assert evaluation.confidence_score == Decimal("54.99")
    assert evaluation.status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.reason_codes == (ReasonCode.LOW_CONFIDENCE,)


def test_confidence_55_00_with_a_numeric_anomaly_triggers(
    db_session: Session, factory: LaborFactory
) -> None:
    evaluation = _confidence_gate_scenario(factory, db_session, "2.75")
    assert evaluation.baseline_confidence == Decimal("55.00")
    assert evaluation.confidence_score == Decimal("55.00")
    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.reason_codes == (ReasonCode.TRIGGER_LABOR_OVERSTAFFING,)


def test_low_confidence_with_no_numeric_anomaly_is_clear_not_suppressed(
    db_session: Session, factory: LaborFactory
) -> None:
    """Low confidence alone never explains a CLEAR: it only ever suppresses a real anomaly."""
    tenant = labor_tenant(factory)
    world = LaborWorld(db_session, tenant)
    for day in _historical_mondays(5):
        world.booking_day(day, rooms_on_books=30, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
        world.labor_day(
            TARGET,
            day,
            LaborCategory.HOUSEKEEPING,
            planned_hours="24",
            confidence="2.72",  # would suppress an anomaly, but there is none here
        )
    target_snapshot = world.booking_day(TARGET, rooms_on_books=30)
    world.labor_day(TARGET, TARGET, LaborCategory.HOUSEKEEPING, planned_hours="24")  # no excess

    service = LaborDecisionService(db_session, tenant.context)
    evaluation = service.evaluate_overstaffing(
        target_booking_snapshot_id=target_snapshot.id,
        labor_data_source_id=tenant.labor_data_source.id,
        labor_category=LaborCategory.HOUSEKEEPING,
    )
    assert evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.reason_codes == (ReasonCode.CLEAR_WITHIN_EXPECTED_RANGE,)
