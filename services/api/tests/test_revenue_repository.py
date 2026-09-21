"""The two read-only repository additions of Gate 5 (set-based reads with no N+1).

`BookingSnapshotRepository.list_by_ids` / ADR on `SnapshotHistoryRow`, and
`ExpectedRepository.list_comparables_for_baselines`. Both carry the TenantContext workspace and
neither writes.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.revenue_support import (
    ELIGIBLE,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    RevenueWorld,
    snap,
    statements_of,
)
from tests.support import BookingFactory

STAYS = ELIGIBLE[2:10]


def build(session: Session, factory: BookingFactory) -> RevenueWorld:
    world = RevenueWorld.create(session, factory, target_rooms=20, available=40)
    world.curves(STAYS, prior=16, anchor=26, final=34)
    world.calculate()
    return world


# --- BookingSnapshotRepository.list_by_ids ---------------------------------------------------


def test_list_by_ids_returns_the_requested_snapshots_with_their_adr(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build(db_session, factory)
    rows = [
        snap(
            world.tenant,
            TARGET_SNAPSHOT_DAY - timedelta(days=30),
            STAYS[0],
            4,
            adr=Decimal("87.50"),
        ),
        snap(world.tenant, TARGET_SNAPSHOT_DAY - timedelta(days=31), STAYS[0], 0),
    ]
    world.add(*rows)
    repository = BookingSnapshotRepository(db_session, world.tenant.context)

    found = repository.list_by_ids(world.tenant.data_source.id, [r["id"] for r in rows])

    by_id = {row.snapshot_id: row for row in found}
    assert set(by_id) == {r["id"] for r in rows}
    assert by_id[rows[0]["id"]].adr_on_books == Decimal("87.50")
    assert by_id[rows[0]["id"]].rooms_on_books == 4
    assert by_id[rows[1]["id"]].adr_on_books is None  # no rooms, no ADR (never 0 as a stand-in)
    assert by_id[rows[0]["id"]].stay_date == STAYS[0]


def test_list_by_ids_with_no_ids_reads_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build(db_session, factory)
    repository = BookingSnapshotRepository(db_session, world.tenant.context)
    with statements_of(db_session) as statements:
        assert repository.list_by_ids(world.tenant.data_source.id, []) == []
    assert statements == []


def test_list_by_ids_is_one_statement_however_many_ids(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build(db_session, factory)
    ids = [row["id"] for row in world.rows]
    repository = BookingSnapshotRepository(db_session, world.tenant.context)
    with statements_of(db_session) as statements:
        found = repository.list_by_ids(world.tenant.data_source.id, ids)
    assert len(found) == len(ids)
    assert len(statements) == 1


def test_list_by_ids_never_crosses_a_data_source_or_a_workspace(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build(db_session, factory)
    other = build(db_session, factory)
    ids = [row["id"] for row in world.rows]
    mine = BookingSnapshotRepository(db_session, world.tenant.context)
    theirs = BookingSnapshotRepository(db_session, other.tenant.context)

    assert mine.list_by_ids(other.tenant.data_source.id, ids) == []  # another data source
    assert theirs.list_by_ids(other.tenant.data_source.id, ids) == []  # another workspace
    assert theirs.list_by_ids(world.tenant.data_source.id, ids) == []  # even with the right source
    assert mine.list_by_ids(world.tenant.data_source.id, [uuid.uuid4()]) == []


def test_the_keyed_read_also_carries_the_adr(db_session: Session, factory: BookingFactory) -> None:
    world = build(db_session, factory)
    repository = BookingSnapshotRepository(db_session, world.tenant.context)
    key = (STAYS[0] - timedelta(days=14), STAYS[0])
    (row,) = repository.list_by_keys(world.tenant.data_source.id, [key])
    assert row.adr_on_books == Decimal("100.00")
    assert row.rooms_on_books == 26


# --- ExpectedRepository.list_comparables_for_baselines ---------------------------------------


def test_the_comparables_of_many_baselines_come_in_one_statement_in_rank_order(
    db_session: Session, factory: BookingFactory
) -> None:
    world = build(db_session, factory)  # target: the Saturday, seen 14 days before
    # a second target: the Sunday after, seen 15 days before
    sunday = TARGET_STAY + timedelta(days=1)
    second = snap(world.tenant, TARGET_SNAPSHOT_DAY, sunday, 20, available=40)
    world.add(second)
    world.curves(
        [stay + timedelta(days=1) for stay in STAYS], prior=16, anchor=26, final=34, lead=15
    )
    world.calculate(second["id"])
    baselines = [world.baseline(), world.baseline(second["id"])]
    repository = ExpectedRepository(db_session, world.tenant.context)

    with statements_of(db_session) as statements:
        grouped = repository.list_comparables_for_baselines([b.id for b in baselines])

    assert len(statements) == 1
    assert set(grouped) == {b.id for b in baselines}
    for baseline in baselines:
        ranks = [c.recency_rank for c in grouped[baseline.id]]
        assert ranks == sorted(ranks) == list(range(1, len(STAYS) + 1))
        single = list(repository.list_comparables(baseline.id))
        assert [c.id for c in grouped[baseline.id]] == [c.id for c in single]


def test_comparables_of_another_workspace_are_never_returned(
    db_session: Session, factory: BookingFactory
) -> None:
    mine = build(db_session, factory)
    theirs = build(db_session, factory)
    repository = ExpectedRepository(db_session, mine.tenant.context)

    grouped = repository.list_comparables_for_baselines([mine.baseline().id, theirs.baseline().id])

    assert set(grouped) == {mine.baseline().id}


def test_no_baseline_ids_read_nothing(db_session: Session, factory: BookingFactory) -> None:
    world = build(db_session, factory)
    repository = ExpectedRepository(db_session, world.tenant.context)
    with statements_of(db_session) as statements:
        assert repository.list_comparables_for_baselines([]) == {}
    assert statements == []


def test_an_insufficient_baseline_keeps_its_comparables_for_the_adr_fallback(
    db_session: Session, factory: BookingFactory
) -> None:
    thin = RevenueWorld.create(db_session, factory, target_rooms=20, available=40)
    thin.curves(STAYS[:3], prior=16, anchor=26, final=34)
    thin.calculate()
    repository = ExpectedRepository(db_session, thin.tenant.context)

    grouped = repository.list_comparables_for_baselines([thin.baseline().id])

    assert thin.baseline().status.value == "INSUFFICIENT_DATA"
    assert len(grouped[thin.baseline().id]) == 3
