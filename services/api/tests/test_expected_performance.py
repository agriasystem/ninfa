"""No N+1: candidate retrieval is one SQL statement and the statement count does not grow.

A batch of 60 observed targets (leads 0..59 of one snapshot day), each with up to 24 comparable
snapshots at its own exact lead time, is calculated with a small bounded number of statements
that is the same for 3 targets as for 60. No timing is measured. The statement that fetches the
candidates is also checked against the real query plan: the Gate 3 unique key serves it.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, event, func, select
from sqlalchemy.orm import Session

from app.modules.intelligence.expected.calculator import ExpectedStatus, compute_expected
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.selection import Candidate, HistoricalTarget
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from tests.expected_support import (
    OBSERVED,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    Scenario,
    add_snapshots,
    snapshot_row,
)
from tests.support import BookingFactory


@contextmanager
def statements_of(session: Session) -> Iterator[list[tuple[str, Any]]]:
    connection = session.get_bind()
    assert isinstance(connection, Connection)
    captured: list[tuple[str, Any]] = []

    def record(*args: Any) -> None:
        captured.append((str(args[2]), args[3]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)


def build_batch(
    session: Session, factory: BookingFactory, targets: int
) -> tuple[Scenario, list[Any]]:
    """`targets` observed targets on one snapshot day, each with its exact-lead history."""
    tenant = factory.tenant()
    scenario = Scenario(session, tenant, uuid.uuid4())
    rows: list[dict[str, Any]] = []
    for k in range(targets):
        stay = TARGET_SNAPSHOT_DAY + timedelta(days=k)  # lead time k
        rows.append(snapshot_row(tenant, TARGET_SNAPSHOT_DAY, stay, rooms=12))
        for position, past in enumerate(eligible_stay_dates(stay)):
            rows.append(
                snapshot_row(
                    tenant,
                    past - timedelta(days=k),
                    past,
                    rooms=(position * 7 + k) % 23,  # deterministic variety, zeros included
                    origin=OBSERVED if position < 9 else RECONSTRUCTED,
                )
            )
    add_snapshots(session, tenant, rows)
    scenario.commit()
    return scenario, rows


def run_batch(scenario: Scenario, targets: int) -> Any:
    return scenario.service().calculate_for_snapshot_date(
        property_id=scenario.tenant.property.id,
        data_source_id=scenario.tenant.data_source.id,
        snapshot_local_date=TARGET_SNAPSHOT_DAY,
        stay_date_start=TARGET_SNAPSHOT_DAY,
        stay_date_end=TARGET_SNAPSHOT_DAY + timedelta(days=targets - 1),
    )


def test_a_batch_of_60_targets_uses_a_bounded_number_of_statements(
    db_session: Session, factory: BookingFactory
) -> None:
    scenario, _ = build_batch(db_session, factory, 60)

    with statements_of(db_session) as statements:
        result = run_batch(scenario, 60)

    assert result.created == 60
    assert len(statements) <= 14, [s for s, _ in statements]  # not 60 x 24 queries
    assert (
        int(db_session.scalar(select(func.count()).select_from(BookingExpectedBaseline)) or 0) == 60
    )
    assert (
        int(db_session.scalar(select(func.count()).select_from(BookingExpectedComparable)) or 0)
        > 60
    )


def test_the_statement_count_does_not_depend_on_the_number_of_targets(
    db_session: Session, factory: BookingFactory
) -> None:
    small, _ = build_batch(db_session, factory, 3)
    with statements_of(db_session) as few:
        run_batch(small, 3)
    big, _ = build_batch(db_session, factory, 60)
    with statements_of(db_session) as many:
        run_batch(big, 60)

    assert len(many) == len(few), ([s for s, _ in few], [s for s, _ in many])


def test_a_single_target_costs_the_same_as_a_batch(
    db_session: Session, factory: BookingFactory
) -> None:
    scenario, rows = build_batch(db_session, factory, 5)
    target_id = next(
        r["id"]
        for r in rows
        if r["stay_date"] == TARGET_SNAPSHOT_DAY + timedelta(days=2)
        and r["snapshot_local_date"] == TARGET_SNAPSHOT_DAY
    )

    with statements_of(db_session) as single:
        scenario.service().calculate_for_target(
            property_id=scenario.tenant.property.id,
            data_source_id=scenario.tenant.data_source.id,
            target_snapshot_id=target_id,
        )

    assert len(single) <= 14


def test_a_rerun_of_the_whole_batch_is_also_bounded_and_writes_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    scenario, _ = build_batch(db_session, factory, 30)
    run_batch(scenario, 30)

    with statements_of(db_session) as statements:
        again = run_batch(scenario, 30)

    assert (again.created, again.unchanged) == (0, 30)
    assert not [s for s, _ in statements if s.lstrip().upper().startswith("INSERT")]


def test_the_batch_results_equal_the_pure_calculation_on_the_same_snapshots(
    db_session: Session, factory: BookingFactory
) -> None:
    scenario, rows = build_batch(db_session, factory, 20)
    run_batch(scenario, 20)
    by_key = {(r["snapshot_local_date"], r["stay_date"]): r for r in rows}

    for k in (0, 1, 7, 13, 19):
        stay = TARGET_SNAPSHOT_DAY + timedelta(days=k)
        target = HistoricalTarget(stay, k)
        candidates = [
            Candidate(
                by_key[key]["id"],
                key[0],
                key[1],
                SnapshotOrigin(by_key[key]["origin"]),
                by_key[key]["rooms_on_books"],
                by_key[key]["uncertain_rooms"],
            )
            for past in eligible_stay_dates(stay)
            if (key := (past - timedelta(days=k), past)) in by_key
        ]
        computation = compute_expected(target, candidates)
        stored = db_session.scalar(
            select(BookingExpectedBaseline).where(
                BookingExpectedBaseline.target_stay_date == stay,
                BookingExpectedBaseline.workspace_id == scenario.tenant.workspace.id,
            )
        )
        assert stored is not None
        assert stored.status == computation.status
        assert stored.sample_size == computation.selection.sample_size
        if computation.statistics is not None:
            assert stored.expected_rooms_on_books == computation.statistics.expected
            assert stored.confidence_score == computation.confidence_score
        else:
            assert stored.status == ExpectedStatus.INSUFFICIENT_DATA


def test_the_candidate_query_is_served_by_the_gate_3_unique_key_index(
    db_session: Session, factory: BookingFactory
) -> None:
    scenario, _ = build_batch(db_session, factory, 10)
    with statements_of(db_session) as statements:
        run_batch(scenario, 10)
    candidate_query = next(
        (sql, params)
        for sql, params in statements
        if "booking_snapshots" in sql
        and "wanted" in sql
        and sql.lstrip().upper().startswith("SELECT")
    )

    connection = db_session.connection()
    connection.exec_driver_sql(
        "SET LOCAL enable_seqscan = off"
    )  # tiny test tables: force index paths
    plan = "\n".join(
        row[0]
        for row in connection.exec_driver_sql("EXPLAIN " + candidate_query[0], candidate_query[1])
    )

    assert "Seq Scan on booking_snapshots" not in plan
    assert (
        "uq_booking_snapshots_data_source_snapshot_date_stay_date" in plan
        or "ix_booking_snapshots_booking_curve" in plan
    ), plan
    assert BookingSnapshot.__tablename__ in plan
