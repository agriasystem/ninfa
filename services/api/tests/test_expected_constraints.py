"""Expected baselines and comparables: what PostgreSQL itself enforces.

Raw Core INSERTs (no repository, no service) so that only the database can say no.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.snapshots.models import BookingSnapshot
from tests.expected_support import (
    ELIGIBLE,
    RECONSTRUCTED,
    TARGET_SNAPSHOT_DAY,
    TARGET_STAY,
    Scenario,
    add_snapshots,
    baseline_values,
    comparable_values,
    insert_baseline,
    insert_comparable,
    insufficient_values,
    snapshot_row,
)
from tests.support import BookingFactory, Rejects, Tenant

FK_PROPERTY = "fk_booking_expected_baselines_workspace_id_properties"
FK_SOURCE = "fk_booking_expected_baselines_workspace_id_data_sources"
FK_TARGET = "fk_booking_expected_baselines_target_snapshot"
FK_COMPARABLE_BASELINE = "fk_booking_expected_comparables_baseline"
FK_COMPARABLE_SNAPSHOT = "fk_booking_expected_comparables_snapshot"
UQ_TARGET_VERSION = "uq_booking_expected_baselines_target_version"


def ck(name: str) -> str:
    return f"ck_booking_expected_baselines_{name}"


@pytest.fixture
def world(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> tuple[Scenario, Scenario]:
    """Tenant A and tenant B, each with an OBSERVED target snapshot."""
    a = Scenario.create(db_session, factory, tenant=two_tenants[0])
    b = Scenario.create(db_session, factory, tenant=two_tenants[1])
    return a, b


# --- A valid baseline and its comparables are accepted ----------------------------------------


def test_a_consistent_ready_baseline_with_comparables_is_accepted(
    db_session: Session, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    history = a.add_history(ELIGIBLE[:2])
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    for rank, snapshot_id in enumerate(history, start=1):
        insert_comparable(
            db_session, comparable_values(a.tenant, baseline_id, snapshot_id, recency_rank=rank)
        )

    assert db_session.scalars(select(BookingExpectedBaseline.status)).one().value == "READY"
    assert len(db_session.scalars(select(BookingExpectedComparable)).all()) == 2


def test_a_consistent_insufficient_baseline_is_accepted(
    db_session: Session, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world

    insert_baseline(db_session, insufficient_values(a.tenant, a.target_id))

    row = db_session.scalars(select(BookingExpectedBaseline)).one()
    assert (row.expected_rooms_on_books, row.confidence_band) == (None, None)
    assert row.confidence_score == Decimal("0.00") and row.sample_size == 4


# --- L. tenant and source integrity of baselines ----------------------------------------------


def test_a_baseline_for_a_property_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, b = world

    with rejects(pg.ForeignKeyViolation, (FK_PROPERTY, FK_SOURCE, FK_TARGET)):
        insert_baseline(
            db_session, baseline_values(a.tenant, a.target_id, property_id=b.tenant.property.id)
        )


def test_a_baseline_for_a_data_source_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, b = world

    with rejects(pg.ForeignKeyViolation, (FK_SOURCE, FK_TARGET)):
        insert_baseline(
            db_session,
            baseline_values(a.tenant, a.target_id, data_source_id=b.tenant.data_source.id),
        )


def test_a_baseline_for_a_data_source_of_another_property_is_rejected(
    db_session: Session, rejects: Rejects, factory: BookingFactory, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    other_property = factory.property(a.tenant.workspace)
    other_source = factory.data_source(other_property)

    with rejects(pg.ForeignKeyViolation, (FK_SOURCE, FK_TARGET)):
        insert_baseline(
            db_session, baseline_values(a.tenant, a.target_id, data_source_id=other_source.id)
        )


def test_a_baseline_whose_target_snapshot_belongs_to_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, b = world

    with rejects(pg.ForeignKeyViolation, FK_TARGET):
        insert_baseline(db_session, baseline_values(a.tenant, b.target_id))


def test_a_baseline_whose_target_snapshot_belongs_to_another_data_source_is_rejected(
    db_session: Session, rejects: Rejects, factory: BookingFactory, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    second_source = factory.data_source(a.tenant.property)
    row = snapshot_row(a.tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, data_source_id=second_source.id)
    add_snapshots(db_session, a.tenant, [row])

    with rejects(pg.ForeignKeyViolation, FK_TARGET):  # same workspace and property, other source
        insert_baseline(db_session, baseline_values(a.tenant, row["id"]))


def test_a_baseline_for_an_unknown_target_snapshot_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world

    with rejects(pg.ForeignKeyViolation, FK_TARGET):
        insert_baseline(db_session, baseline_values(a.tenant, uuid.uuid4()))


def test_a_reconstructed_snapshot_can_never_be_the_target_of_a_baseline(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    stay = TARGET_STAY + timedelta(days=1)
    row = snapshot_row(a.tenant, TARGET_SNAPSHOT_DAY, stay, origin=RECONSTRUCTED)
    add_snapshots(db_session, a.tenant, [row])
    values = baseline_values(
        a.tenant, row["id"], target_stay_date=stay, lead_time_days=lead_of(stay)
    )

    # claiming it is OBSERVED: the composite foreign key finds no OBSERVED snapshot with that id
    with rejects(pg.ForeignKeyViolation, FK_TARGET):
        insert_baseline(db_session, values)
    # admitting it is RECONSTRUCTED: the CHECK refuses the origin itself
    with rejects(pg.CheckViolation, (ck("target_is_observed"), FK_TARGET)):
        insert_baseline(db_session, {**values, "target_origin": "RECONSTRUCTED_APPROXIMATE"})


def lead_of(stay: date) -> int:
    return (stay - TARGET_SNAPSHOT_DAY).days


def test_the_denormalised_lead_time_must_match_the_dates(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world

    with rejects(pg.CheckViolation, ck("lead_time_matches_dates")):
        insert_baseline(db_session, baseline_values(a.tenant, a.target_id, lead_time_days=13))


def test_a_negative_lead_time_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world

    with rejects(pg.CheckViolation, ck("lead_time_non_negative")):
        insert_baseline(
            db_session,
            baseline_values(
                a.tenant,
                a.target_id,
                target_snapshot_local_date=TARGET_STAY + timedelta(days=1),
                lead_time_days=-1,
            ),
        )


# --- G. status coherence ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_rooms_on_books": None},
        {"expected_lower": None},
        {"expected_upper": None},
        {"iqr": None},
        {"confidence_band": None},
        {"sample_size": 4, "observed_sample_size": 4},  # READY needs at least 5 comparables
    ],
)
def test_a_ready_baseline_must_carry_every_statistic_a_band_and_five_comparables(
    db_session: Session,
    rejects: Rejects,
    world: tuple[Scenario, Scenario],
    overrides: dict[str, Any],
) -> None:
    a, _ = world

    with rejects(pg.CheckViolation, (ck("ready_has_statistics"), ck("iqr_is_range_width"))):
        insert_baseline(db_session, baseline_values(a.tenant, a.target_id, **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_rooms_on_books": Decimal("3.00")},
        {"expected_lower": Decimal("1.00")},
        {"expected_upper": Decimal("5.00")},
        {"iqr": Decimal("1.00")},
        {"confidence_score": Decimal("10.00")},  # no fake LOW: an insufficient baseline has 0
        {"confidence_band": "LOW"},
        {"sample_size": 5, "observed_sample_size": 5},  # 5 comparables would be READY
    ],
)
def test_an_insufficient_baseline_carries_no_number_no_score_and_no_band(
    db_session: Session,
    rejects: Rejects,
    world: tuple[Scenario, Scenario],
    overrides: dict[str, Any],
) -> None:
    a, _ = world

    with rejects(pg.CheckViolation, ck("insufficient_has_no_statistics")):
        insert_baseline(db_session, insufficient_values(a.tenant, a.target_id, **overrides))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"sample_size": 7}, "sample_size_is_sum"),
        (
            {"sample_size": 5, "observed_sample_size": 6, "reconstructed_sample_size": -1},
            "sample_counts_non_negative",
        ),
        ({"rejected_uncertain_count": -1}, "sample_counts_non_negative"),
        ({"confidence_score": Decimal("100.01")}, "confidence_score_range"),
        ({"confidence_score": Decimal("-0.01")}, "confidence_score_range"),
        (
            {"expected_lower": Decimal("13.00"), "iqr": Decimal("2.00")},
            "range_ordered",
        ),
        ({"iqr": Decimal("4.00")}, "iqr_is_range_width"),
        (
            {
                "expected_lower": Decimal("-3.00"),
                "expected_rooms_on_books": Decimal("-2.00"),
                "expected_upper": Decimal("-1.00"),
                "iqr": Decimal("2.00"),
            },
            "statistics_non_negative",
        ),
        ({"comparable_fingerprint": "xyz"}, "comparable_fingerprint_format"),
        ({"comparable_fingerprint": "G" * 64}, "comparable_fingerprint_format"),
        ({"method": "  "}, "method_not_blank"),
        ({"calculation_version": ""}, "calculation_version_not_blank"),
    ],
)
def test_inconsistent_baselines_are_rejected(
    db_session: Session,
    rejects: Rejects,
    world: tuple[Scenario, Scenario],
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    a, _ = world

    with rejects(pg.CheckViolation, ck(constraint)):
        insert_baseline(db_session, baseline_values(a.tenant, a.target_id, **overrides))


@pytest.mark.parametrize("bad", ["GUESSED", "high", "EXTREME"])
def test_the_database_refuses_a_band_that_is_not_one_of_the_three(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario], bad: str
) -> None:
    a, _ = world
    values = {"id": uuid.uuid4(), **baseline_values(a.tenant, a.target_id)}
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    with rejects(pg.CheckViolation, ck("confidence_band_valid")):
        db_session.execute(
            text(f"INSERT INTO booking_expected_baselines ({columns}) VALUES ({binds})"),
            {**values, "confidence_band": bad},
        )


def test_a_status_other_than_ready_or_insufficient_is_refused(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    values = {"id": uuid.uuid4(), **baseline_values(a.tenant, a.target_id)}
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    with rejects(pg.CheckViolation, ck("status_valid")):
        db_session.execute(
            text(f"INSERT INTO booking_expected_baselines ({columns}) VALUES ({binds})"),
            {**values, "status": "FORECAST"},
        )


# --- I. one baseline per target and version ---------------------------------------------------


def test_a_second_baseline_for_the_same_target_and_version_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    with rejects(pg.UniqueViolation, UQ_TARGET_VERSION):
        insert_baseline(
            db_session,
            baseline_values(a.tenant, a.target_id, expected_rooms_on_books=Decimal("13.00")),
        )


def test_a_new_calculation_version_may_coexist_with_the_old_one(
    db_session: Session, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world

    insert_baseline(db_session, baseline_values(a.tenant, a.target_id))
    insert_baseline(
        db_session,
        baseline_values(a.tenant, a.target_id, calculation_version="booking-expected-v2"),
    )

    assert len(db_session.scalars(select(BookingExpectedBaseline)).all()) == 2


# --- L. tenant and source integrity of comparables --------------------------------------------


def test_a_comparable_of_a_snapshot_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, b = world
    foreign = b.add_history(ELIGIBLE[:1])[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    with rejects(pg.ForeignKeyViolation, FK_COMPARABLE_SNAPSHOT):
        insert_comparable(db_session, comparable_values(a.tenant, baseline_id, foreign))


def test_a_comparable_of_a_snapshot_of_another_data_source_is_rejected(
    db_session: Session, rejects: Rejects, factory: BookingFactory, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    second_source = factory.data_source(a.tenant.property)
    row = snapshot_row(
        a.tenant,
        ELIGIBLE[0] - timedelta(days=14),
        ELIGIBLE[0],
        data_source_id=second_source.id,
    )
    add_snapshots(db_session, a.tenant, [row])
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    # same workspace and property, but the baseline's data source is another one
    with rejects(pg.ForeignKeyViolation, FK_COMPARABLE_SNAPSHOT):
        insert_comparable(db_session, comparable_values(a.tenant, baseline_id, row["id"]))


def test_a_comparable_pointing_at_a_baseline_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, b = world
    history = a.add_history(ELIGIBLE[:1])[0]
    foreign_baseline = insert_baseline(db_session, baseline_values(b.tenant, b.target_id))

    with rejects(pg.ForeignKeyViolation, FK_COMPARABLE_BASELINE):
        insert_comparable(db_session, comparable_values(a.tenant, foreign_baseline, history))


def test_a_comparable_cannot_claim_another_origin_than_its_snapshot_has(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    observed = a.add_history(ELIGIBLE[:1])[0]  # an OBSERVED snapshot
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    with rejects(pg.ForeignKeyViolation, FK_COMPARABLE_SNAPSHOT):
        insert_comparable(
            db_session,
            comparable_values(a.tenant, baseline_id, observed, origin="RECONSTRUCTED_APPROXIMATE"),
        )


def test_a_reconstructed_comparable_keeps_its_origin(
    db_session: Session, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    reconstructed = a.add_history(ELIGIBLE[:1], origin=RECONSTRUCTED)[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    insert_comparable(
        db_session,
        comparable_values(a.tenant, baseline_id, reconstructed, origin="RECONSTRUCTED_APPROXIMATE"),
    )

    assert db_session.scalars(select(BookingExpectedComparable.origin)).one() == RECONSTRUCTED


def test_a_snapshot_is_a_comparable_of_a_baseline_at_most_once_and_ranks_are_unique(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    first, second = a.add_history(ELIGIBLE[:2])
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))
    insert_comparable(db_session, comparable_values(a.tenant, baseline_id, first, recency_rank=1))

    with rejects(pg.UniqueViolation, "uq_booking_expected_comparables_baseline_snapshot"):
        insert_comparable(
            db_session, comparable_values(a.tenant, baseline_id, first, recency_rank=2)
        )
    with rejects(pg.UniqueViolation, "uq_booking_expected_comparables_baseline_rank"):
        insert_comparable(
            db_session, comparable_values(a.tenant, baseline_id, second, recency_rank=1)
        )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"rooms_on_books": -1}, "rooms_on_books_non_negative"),
        ({"recency_rank": 0}, "recency_rank_positive"),
    ],
)
def test_invalid_comparable_values_are_rejected(
    db_session: Session,
    rejects: Rejects,
    world: tuple[Scenario, Scenario],
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    a, _ = world
    history = a.add_history(ELIGIBLE[:1])[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    with rejects(pg.CheckViolation, f"ck_booking_expected_comparables_{constraint}"):
        insert_comparable(
            db_session, comparable_values(a.tenant, baseline_id, history, **overrides)
        )


def test_zero_rooms_is_a_valid_comparable_value(
    db_session: Session, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    history = a.add_history(ELIGIBLE[:1], rooms=0)[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    insert_comparable(
        db_session, comparable_values(a.tenant, baseline_id, history, rooms_on_books=0)
    )

    assert db_session.scalars(select(BookingExpectedComparable.rooms_on_books)).one() == 0


# --- immutability and delete policy -----------------------------------------------------------


def test_a_stored_baseline_cannot_be_updated(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    insert_baseline(db_session, baseline_values(a.tenant, a.target_id))

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            update(BookingExpectedBaseline).values(expected_rooms_on_books=Decimal("99.00"))
        )
    with rejects(pg.IntegrityConstraintViolation):  # not even a no-op
        db_session.execute(
            update(BookingExpectedBaseline).values(sample_size=BookingExpectedBaseline.sample_size)
        )


def test_a_stored_comparable_cannot_be_updated(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    history = a.add_history(ELIGIBLE[:1])[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))
    insert_comparable(db_session, comparable_values(a.tenant, baseline_id, history))

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(update(BookingExpectedComparable).values(rooms_on_books=99))


def test_referenced_rows_cannot_be_deleted(
    db_session: Session, rejects: Rejects, world: tuple[Scenario, Scenario]
) -> None:
    a, _ = world
    history = a.add_history(ELIGIBLE[:1])[0]
    baseline_id = insert_baseline(db_session, baseline_values(a.tenant, a.target_id))
    insert_comparable(db_session, comparable_values(a.tenant, baseline_id, history))

    with rejects(pg.RestrictViolation, FK_COMPARABLE_BASELINE):
        db_session.execute(delete(BookingExpectedBaseline))
    with rejects(pg.RestrictViolation, (FK_TARGET, FK_COMPARABLE_SNAPSHOT)):
        db_session.execute(delete(BookingSnapshot))


def test_the_triggers_live_on_the_two_expected_tables_only(db_session: Session) -> None:
    triggers = set(
        db_session.execute(
            text(
                "SELECT event_object_table || '.' || trigger_name"
                " FROM information_schema.triggers"
                " WHERE trigger_name LIKE 'trg\\_booking\\_expected%'"
            )
        ).scalars()
    )

    assert triggers == {
        "booking_expected_baselines.trg_booking_expected_baselines_immutable",
        "booking_expected_comparables.trg_booking_expected_comparables_immutable",
    }
