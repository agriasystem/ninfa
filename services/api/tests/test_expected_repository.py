"""Tenant-scoped repositories of Gate 4, and the snapshot reads they rely on."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.intelligence.expected.calculator import (
    comparable_fingerprint,
    compute_expected,
)
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.expected.repository import ExpectedRepository, NewBaseline
from app.modules.intelligence.expected.selection import Candidate, HistoricalTarget
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotHistoryRow
from tests.expected_support import (
    ELIGIBLE,
    LEAD,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    Scenario,
    add_snapshots,
    snapshot_row,
)
from tests.support import BookingFactory, Tenant


def new_baseline(scenario: Scenario, stay_dates: int = 6) -> NewBaseline:
    target = HistoricalTarget(TARGET_STAY, LEAD)
    ids = scenario.add_history(ELIGIBLE[:stay_dates], rooms=list(range(10, 10 + stay_dates)))
    candidates = [
        Candidate(sid, stay - timedelta(days=LEAD), stay, SnapshotOrigin.OBSERVED, rooms, 0)
        for sid, stay, rooms in zip(ids, ELIGIBLE, range(10, 10 + stay_dates), strict=False)
    ]
    computation = compute_expected(target, candidates)
    return NewBaseline(
        id=uuid.uuid4(),
        property_id=scenario.tenant.property.id,
        data_source_id=scenario.tenant.data_source.id,
        target_snapshot_id=scenario.target_id,
        target=target,
        computation=computation,
        comparable_fingerprint=comparable_fingerprint(
            data_source_id=scenario.tenant.data_source.id,
            target_snapshot_id=scenario.target_id,
            target=target,
            computation=computation,
        ),
    )


@pytest.fixture
def two(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> tuple[Scenario, Scenario]:
    return (
        Scenario.create(db_session, factory, tenant=two_tenants[0]),
        Scenario.create(db_session, factory, tenant=two_tenants[1]),
    )


# --- writes and reads -------------------------------------------------------------------------


def test_inserted_baselines_and_comparables_are_read_back(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    item = new_baseline(a)
    repository = ExpectedRepository(db_session, a.tenant.context)

    repository.insert_baselines([item])
    repository.insert_comparables([item])

    stored = repository.get_for_target_snapshot(a.target_id)
    assert stored is not None and stored.id == item.id
    assert stored.comparable_fingerprint == item.comparable_fingerprint
    comparables = repository.list_comparables(item.id)
    assert [c.recency_rank for c in comparables] == [1, 2, 3, 4, 5, 6]
    assert [c.rooms_on_books for c in comparables] == [10, 11, 12, 13, 14, 15]


def test_comparables_come_back_in_recency_order(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    item = new_baseline(a, stay_dates=7)
    repository = ExpectedRepository(db_session, a.tenant.context)
    repository.insert_baselines([item])
    repository.insert_comparables([item])

    ranks = [c.recency_rank for c in repository.list_comparables(item.id)]

    assert ranks == sorted(ranks) == list(range(1, 8))


def test_the_baseline_of_an_unknown_target_or_another_version_is_none(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    item = new_baseline(a)
    repository = ExpectedRepository(db_session, a.tenant.context)
    repository.insert_baselines([item])

    assert repository.get_for_target_snapshot(uuid.uuid4()) is None
    assert repository.get_for_target_snapshot(a.target_id, "booking-expected-v2") is None
    assert repository.existing_for_targets([]) == {}
    assert set(repository.existing_for_targets([a.target_id, uuid.uuid4()])) == {a.target_id}


def test_baselines_of_a_snapshot_day_are_listed_by_stay_date(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    item = new_baseline(a)
    repository = ExpectedRepository(db_session, a.tenant.context)
    repository.insert_baselines([item])

    listed = repository.list_for_snapshot_date(a.tenant.data_source.id, TARGET_SNAPSHOT_DAY)

    assert [b.id for b in listed] == [item.id]
    assert (
        repository.list_for_snapshot_date(
            a.tenant.data_source.id, TARGET_SNAPSHOT_DAY - timedelta(days=1)
        )
        == []
    )


# --- L. the repositories are tenant scoped ----------------------------------------------------


def test_another_workspace_sees_none_of_a_baseline_or_its_comparables(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, b = two
    item = new_baseline(a)
    ExpectedRepository(db_session, a.tenant.context).insert_baselines([item])
    ExpectedRepository(db_session, a.tenant.context).insert_comparables([item])
    other = ExpectedRepository(db_session, b.tenant.context)

    assert other.get_for_target_snapshot(a.target_id) is None
    assert other.existing_for_targets([a.target_id]) == {}
    assert other.list_for_snapshot_date(a.tenant.data_source.id, TARGET_SNAPSHOT_DAY) == []
    assert other.list_comparables(item.id) == []


def test_a_repository_needs_a_tenant_context(db_session: Session) -> None:
    with pytest.raises(TypeError):
        ExpectedRepository(db_session)  # type: ignore[call-arg]


def test_a_baseline_written_through_the_wrong_tenant_is_refused_by_the_database(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    """The repository stamps its own workspace on every row: a foreign target cannot slip in."""
    a, b = two
    item = new_baseline(a)
    wrong = ExpectedRepository(db_session, b.tenant.context)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        wrong.insert_baselines([item])


# --- the snapshot reads used by the engine ----------------------------------------------------


def test_a_snapshot_is_read_by_id_only_inside_its_workspace(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, b = two

    assert (
        BookingSnapshotRepository(db_session, a.tenant.context).get_by_id(a.target_id) is not None
    )
    assert BookingSnapshotRepository(db_session, b.tenant.context).get_by_id(a.target_id) is None


def test_keys_fetch_exactly_the_requested_snapshots_of_one_data_source(
    db_session: Session, factory: BookingFactory, two: tuple[Scenario, Scenario]
) -> None:
    a, b = two
    a.add_history(ELIGIBLE[:6], rooms=[1, 2, 3, 4, 5, 6])
    other_source = factory.data_source(a.tenant.property)
    add_snapshots(
        db_session,
        a.tenant,
        [
            snapshot_row(
                a.tenant,
                ELIGIBLE[0] - timedelta(days=LEAD),
                ELIGIBLE[0],
                rooms=99,
                data_source_id=other_source.id,
            )
        ],
    )
    b.add_history(ELIGIBLE[:6], rooms=50)
    repository = BookingSnapshotRepository(db_session, a.tenant.context)
    keys = {(stay - timedelta(days=LEAD), stay) for stay in ELIGIBLE[:4]}
    keys.add((date(2020, 1, 1), date(2020, 1, 15)))  # a key with no snapshot

    rows = repository.list_by_keys(a.tenant.data_source.id, keys)

    assert isinstance(rows[0], SnapshotHistoryRow)
    assert sorted(r.stay_date for r in rows) == sorted(ELIGIBLE[:4])
    assert sorted(r.rooms_on_books for r in rows) == [1, 2, 3, 4]  # not 99, not tenant B's 50
    assert repository.list_by_keys(a.tenant.data_source.id, set()) == []
    assert repository.list_by_keys(other_source.id, keys)[0].rooms_on_books == 99


def test_a_key_lookup_is_exact_on_both_dates(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    a.add_history([ELIGIBLE[0]], lead=14)
    a.add_history([ELIGIBLE[0]], lead=13)
    repository = BookingSnapshotRepository(db_session, a.tenant.context)

    at_14 = repository.list_by_keys(
        a.tenant.data_source.id, {(ELIGIBLE[0] - timedelta(days=14), ELIGIBLE[0])}
    )

    assert len(at_14) == 1 and at_14[0].snapshot_local_date == ELIGIBLE[0] - timedelta(days=14)


def test_a_large_key_list_is_fetched_in_blocks(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    a.add_history(ELIGIBLE[:3])
    keys = {
        (date(1990, 1, 1) + timedelta(days=i), date(1990, 1, 15) + timedelta(days=i))
        for i in range(6000)
    }
    keys |= {(stay - timedelta(days=LEAD), stay) for stay in ELIGIBLE[:3]}  # 6003 keys: two blocks

    rows = BookingSnapshotRepository(db_session, a.tenant.context).list_by_keys(
        a.tenant.data_source.id, keys
    )

    assert len(rows) == 3


def test_snapshots_of_a_day_can_be_filtered_by_origin(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    a, _ = two
    add_snapshots(
        db_session,
        a.tenant,
        [
            snapshot_row(
                a.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY + timedelta(days=1), origin=RECONSTRUCTED
            ),
        ],
    )
    repository = BookingSnapshotRepository(db_session, a.tenant.context)

    everything = repository.list_for_snapshot_date(a.tenant.data_source.id, TARGET_SNAPSHOT_DAY)
    observed = repository.list_for_snapshot_date(
        a.tenant.data_source.id, TARGET_SNAPSHOT_DAY, origin=SnapshotOrigin.OBSERVED
    )

    assert len(everything) == 2 and len(observed) == 1
    assert observed[0].id == a.target_id


def test_baselines_are_never_updated_by_the_repository(
    db_session: Session, two: tuple[Scenario, Scenario]
) -> None:
    """The repository has no update or delete: there is nothing that could rewrite a record."""
    public = {name for name in dir(ExpectedRepository) if not name.startswith("_")}

    assert public == {
        "get_for_target_snapshot",
        "existing_for_targets",
        "list_for_snapshot_date",
        "list_comparables",
        "insert_baselines",
        "insert_comparables",
    }
    assert BookingExpectedBaseline.__tablename__ == "booking_expected_baselines"
