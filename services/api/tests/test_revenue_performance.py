"""No N+1: evaluating many targets reads a small, fixed number of statements (Gate 5, group R).

A batch of 60 observed targets (leads 0..59 of one snapshot day), each with up to 24 comparable
stay dates that carry their own prior and final snapshots, is evaluated with the same bounded
number of statements as a batch of 3 targets. No timing is measured. The two new set-based
statements are also checked against the real query plan.
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import EvaluationStatus, ReasonCode, RevenueSignals
from tests.expected_support import add_snapshots
from tests.revenue_support import (
    OBSERVED,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    snap,
    statements_of,
)
from tests.support import BookingFactory, Tenant


def build_batch(session: Session, factory: BookingFactory, targets: int) -> Tenant:
    """`targets` observed targets on one snapshot day, each with its exact-lead history, and the
    REAL Gate 4 baselines calculated for all of them."""
    tenant = factory.tenant()
    rows: dict[tuple[date, date], dict[str, Any]] = {}

    def put(row: dict[str, Any]) -> None:
        rows.setdefault((row["snapshot_local_date"], row["stay_date"]), row)

    for k in range(targets):
        stay = TARGET_SNAPSHOT_DAY + timedelta(days=k)  # lead time k
        put(snap(tenant, TARGET_SNAPSHOT_DAY, stay, 12, available=40))
        put(snap(tenant, TARGET_SNAPSHOT_DAY - timedelta(days=7), stay, 6))
        for position, past in enumerate(eligible_stay_dates(stay)):
            origin = OBSERVED if position < 9 else RECONSTRUCTED
            put(
                snap(tenant, past - timedelta(days=k), past, (position * 7 + k) % 23, origin=origin)
            )
            put(
                snap(
                    tenant,
                    past - timedelta(days=k + 7),
                    past,
                    (position * 3 + k) % 17,
                    origin=origin,
                )
            )
            put(snap(tenant, past, past, (position * 7 + k) % 23 + 5, origin=origin))
    add_snapshots(session, tenant, list(rows.values()))
    session.commit()
    BookingExpectedService(session, tenant.context).calculate_for_snapshot_date(
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=TARGET_SNAPSHOT_DAY,
        stay_date_end=TARGET_SNAPSHOT_DAY + timedelta(days=targets - 1),
    )
    return tenant


def evaluate_batch(session: Session, tenant: Tenant, targets: int) -> tuple[RevenueSignals, ...]:
    return RevenueDecisionService(session, tenant.context).evaluate_snapshot_date(
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=TARGET_SNAPSHOT_DAY,
        stay_date_end=TARGET_SNAPSHOT_DAY + timedelta(days=targets - 1),
    )


def test_a_batch_of_60_targets_uses_a_bounded_number_of_statements(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = build_batch(db_session, factory, 60)

    with statements_of(db_session) as statements:
        batch = evaluate_batch(db_session, tenant, 60)

    assert len(batch) == 60
    assert len(statements) <= 10, [s for s, _ in statements]  # not 60 x 24 x 3 queries
    for sql, _ in statements:
        assert sql.lstrip().upper().startswith("SELECT"), sql


def test_the_statement_count_does_not_depend_on_the_number_of_targets(
    db_session: Session, factory: BookingFactory
) -> None:
    small = build_batch(db_session, factory, 3)
    with statements_of(db_session) as few:
        evaluate_batch(db_session, small, 3)
    big = build_batch(db_session, factory, 60)
    with statements_of(db_session) as many:
        evaluate_batch(db_session, big, 60)

    assert len(many) == len(few), ([s for s, _ in few], [s for s, _ in many])


def test_a_single_target_costs_no_more_than_a_batch(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = build_batch(db_session, factory, 8)
    batch = evaluate_batch(db_session, tenant, 8)
    target_id = batch[3].pickup_low.target_snapshot_id
    service = RevenueDecisionService(db_session, tenant.context)

    with statements_of(db_session) as pickup_only:
        service.evaluate_pickup_low(target_id)
    with statements_of(db_session) as both:
        single = service.evaluate_revenue_signals(target_id)

    assert len(pickup_only) <= 10
    assert len(both) <= 10
    assert single == batch[3]


def test_the_batch_results_are_the_same_as_evaluating_one_by_one(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = build_batch(db_session, factory, 12)
    batch = evaluate_batch(db_session, tenant, 12)
    service = RevenueDecisionService(db_session, tenant.context)
    for signals in batch:
        assert service.evaluate_revenue_signals(signals.pickup_low.target_snapshot_id) == signals


def test_a_realistic_batch_mixes_statuses_without_failing(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = build_batch(db_session, factory, 60)
    batch = evaluate_batch(db_session, tenant, 60)
    statuses = {s.pickup_low.status for s in batch} | {s.occupancy_risk.status for s in batch}
    assert statuses <= set(EvaluationStatus)
    assert len(statuses) >= 2
    for signals in batch:
        for evaluation in (signals.pickup_low, signals.occupancy_risk):
            assert evaluation.rules_version == "revenue-decisions-v1"
            assert len(evaluation.calculation_fingerprint) == 64
            if evaluation.status == EvaluationStatus.INSUFFICIENT_DATA:
                assert evaluation.reason_codes[0] in {
                    ReasonCode.EXPECTED_BASELINE_INSUFFICIENT,
                    ReasonCode.PAIR_SAMPLE_INSUFFICIENT,
                    ReasonCode.PICKUP_PRIOR_OBSERVATION_MISSING,
                }


def _plan(session: Session, sql: str, params: Any) -> str:
    connection = session.connection()
    connection.exec_driver_sql("SET LOCAL enable_seqscan = off")  # tiny test tables: force indexes
    return "\n".join(row[0] for row in connection.exec_driver_sql("EXPLAIN " + sql, params))


def test_the_set_based_statements_are_served_by_indexes(
    db_session: Session, factory: BookingFactory
) -> None:
    tenant = build_batch(db_session, factory, 10)
    with statements_of(db_session) as statements:
        evaluate_batch(db_session, tenant, 10)

    by_ids = next(
        (sql, params)
        for sql, params in statements
        if "FROM booking_snapshots" in sql
        and "booking_snapshots.id IN" in sql
        and "wanted" not in sql
    )
    keyed = next((sql, params) for sql, params in statements if "wanted" in sql)
    comparables = next(
        (sql, params) for sql, params in statements if "FROM booking_expected_comparables" in sql
    )
    for sql, params in (by_ids, keyed, comparables):
        assert "Seq Scan" not in _plan(db_session, sql, params), sql
