"""Room inventory and booking snapshots: what PostgreSQL itself enforces.

Raw Core INSERTs (no ORM, no repository, no service) so that only the database can say no.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from tests.snapshot_support import insert_inventory, insert_snapshot, snapshot_values
from tests.support import BookingFactory, Rejects, Tenant

FK_INVENTORY_PROPERTY = "fk_room_inventory_daily_workspace_id_properties"
FK_SNAPSHOT_PROPERTY = "fk_booking_snapshots_workspace_id_properties"
FK_SNAPSHOT_SOURCE = "fk_booking_snapshots_workspace_id_data_sources"
UQ_SNAPSHOT_KEY = "uq_booking_snapshots_data_source_snapshot_date_stay_date"


# --- A. room inventory -------------------------------------------------------------------------


def test_inventory_of_a_property_of_the_same_workspace_is_accepted(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_inventory(db_session, tenant, rooms_available=20, rooms_out_of_order=2)

    row = db_session.scalars(select(RoomInventoryDaily)).one()
    assert (row.rooms_available, row.rooms_out_of_order) == (20, 2)


def test_inventory_of_a_property_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_INVENTORY_PROPERTY):
        insert_inventory(db_session, a, property_id=b.property.id)  # workspace A, property of B


@pytest.mark.parametrize("column", ["rooms_available", "rooms_out_of_order"])
def test_negative_inventory_counts_are_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant], column: str
) -> None:
    tenant, _ = two_tenants

    with rejects(pg.CheckViolation, f"ck_room_inventory_daily_{column}_non_negative"):
        insert_inventory(db_session, tenant, **{column: -1})


def test_a_second_inventory_row_for_the_same_property_and_night_is_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    insert_inventory(db_session, tenant)

    with rejects(pg.UniqueViolation, "uq_room_inventory_daily_workspace_id_property_id_stay_date"):
        insert_inventory(db_session, tenant, rooms_available=99)


def test_zero_rooms_available_is_a_valid_closed_night(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_inventory(db_session, tenant, rooms_available=0)

    assert db_session.scalars(select(RoomInventoryDaily.rooms_available)).one() == 0


def test_the_same_night_is_allowed_for_two_properties(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    second = factory.property(a.workspace)

    insert_inventory(db_session, a)
    insert_inventory(db_session, a, property_id=second.id)
    insert_inventory(db_session, b)

    assert len(db_session.scalars(select(RoomInventoryDaily)).all()) == 3


# --- H. tenant integrity of snapshots ----------------------------------------------------------


def test_a_consistent_snapshot_is_accepted(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_snapshot(db_session, tenant)

    assert db_session.scalars(select(BookingSnapshot.origin)).one() == SnapshotOrigin.OBSERVED


def test_a_snapshot_pointing_at_a_property_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    # workspace A + property of B (+ B's data source): neither composite key exists
    with rejects(pg.ForeignKeyViolation, (FK_SNAPSHOT_PROPERTY, FK_SNAPSHOT_SOURCE)):
        insert_snapshot(db_session, a, property_id=b.property.id, data_source_id=b.data_source.id)


def test_a_snapshot_pointing_at_a_data_source_of_another_workspace_is_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_SNAPSHOT_SOURCE):
        insert_snapshot(db_session, a, data_source_id=b.data_source.id)


def test_a_snapshot_pointing_at_a_data_source_of_another_property_is_rejected(
    db_session: Session,
    rejects: Rejects,
    factory: BookingFactory,
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, _ = two_tenants
    other_property = factory.property(a.workspace)
    other_source = factory.data_source(other_property)

    # same workspace, but the data source belongs to a different property
    with rejects(pg.ForeignKeyViolation, FK_SNAPSHOT_SOURCE):
        insert_snapshot(db_session, a, data_source_id=other_source.id)


def test_an_unknown_workspace_is_rejected(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    with rejects(pg.ForeignKeyViolation, (FK_SNAPSHOT_PROPERTY, FK_SNAPSHOT_SOURCE)):
        insert_snapshot(db_session, a, workspace_id=uuid.uuid4())


def test_parents_of_snapshots_and_inventory_cannot_be_deleted(
    db_session: Session,
    rejects: Rejects,
    factory: BookingFactory,
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    tenant, _ = two_tenants
    bare_source = factory.data_source(tenant.property)  # no import job: only snapshots point at it
    bare_property = factory.property(tenant.workspace)  # only inventory points at it
    insert_snapshot(db_session, tenant, data_source_id=bare_source.id)
    insert_inventory(db_session, tenant, property_id=bare_property.id)

    with rejects(pg.RestrictViolation, FK_SNAPSHOT_SOURCE):
        db_session.execute(text("DELETE FROM data_sources WHERE id = :id"), {"id": bare_source.id})
    with rejects(pg.RestrictViolation, FK_INVENTORY_PROPERTY):
        db_session.execute(text("DELETE FROM properties WHERE id = :id"), {"id": bare_property.id})


# --- the shape of a snapshot -------------------------------------------------------------------


RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE


def ck(name: str) -> str:
    return f"ck_booking_snapshots_{name}"


@pytest.mark.parametrize(
    ("overrides", "constraints"),
    [
        ({"booking_count_on_books": -1}, (ck("booking_count_non_negative"),)),
        # Some values break two rules at once: PostgreSQL reports the first one by name.
        (
            {"rooms_on_books": -1},
            (
                ck("rooms_on_books_non_negative"),
                ck("rooms_cover_bookings"),
                ck("adr_defined_with_rooms"),
            ),
        ),
        (
            {"allocated_room_revenue_on_books": Decimal("-0.01")},
            (ck("allocated_revenue_non_negative"),),
        ),
        (
            {"rooms_available": -1},
            (ck("rooms_available_non_negative"), ck("occupancy_defined_with_capacity")),
        ),
        ({"occupancy_on_books": Decimal("-1")}, (ck("occupancy_non_negative"),)),
        ({"adr_on_books": Decimal("-1")}, (ck("adr_non_negative"),)),
        (
            {"origin": RECONSTRUCTED, "uncertain_booking_count": -1},
            (ck("uncertain_count_non_negative"), ck("uncertain_rooms_cover_bookings")),
        ),
        (
            {"origin": RECONSTRUCTED, "uncertain_rooms": -1},
            (ck("uncertain_rooms_non_negative"), ck("uncertain_rooms_cover_bookings")),
        ),
        ({"calculation_version": "  "}, (ck("calculation_version_not_blank"),)),
        ({"content_fingerprint": "abc"}, (ck("content_fingerprint_format"),)),
        ({"content_fingerprint": "G" * 64}, (ck("content_fingerprint_format"),)),
    ],
)
def test_invalid_snapshot_values_are_rejected(
    db_session: Session,
    rejects: Rejects,
    two_tenants: tuple[Tenant, Tenant],
    overrides: dict[str, Any],
    constraints: tuple[str, ...],
) -> None:
    tenant, _ = two_tenants

    with rejects(pg.CheckViolation, constraints):
        insert_snapshot(db_session, tenant, **overrides)


@pytest.mark.parametrize("origin", ["GUESSED", "HISTORICAL_TRUTH", "EXACT", "observed", ""])
def test_the_database_itself_refuses_any_other_origin(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant], origin: str
) -> None:
    """Even raw SQL cannot store an origin that is not one of the two documented values."""
    tenant, _ = two_tenants
    values = snapshot_values(tenant, origin=SnapshotOrigin.OBSERVED)
    values["origin"] = origin
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    with rejects(pg.CheckViolation, ck("origin_valid")):
        db_session.execute(
            text(f"INSERT INTO booking_snapshots ({columns}) VALUES ({binds})"),
            {**values, "origin": origin},
        )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        # a booking has at least one room; no booking means no room
        ({"booking_count_on_books": 4, "rooms_on_books": 3}, "rooms_cover_bookings"),
        (
            {"booking_count_on_books": 0, "rooms_on_books": 2, "adr_on_books": Decimal("10.00")},
            "rooms_cover_bookings",
        ),
        (
            {"origin": RECONSTRUCTED, "uncertain_booking_count": 2, "uncertain_rooms": 1},
            "uncertain_rooms_cover_bookings",
        ),
        (
            {"origin": RECONSTRUCTED, "uncertain_booking_count": 0, "uncertain_rooms": 1},
            "uncertain_rooms_cover_bookings",
        ),
        # ADR exists exactly when there are rooms on the books: never 0 as a stand-in
        ({"adr_on_books": None}, "adr_defined_with_rooms"),
        (
            {
                "booking_count_on_books": 0,
                "rooms_on_books": 0,
                "allocated_room_revenue_on_books": Decimal("0.00"),
                "adr_on_books": Decimal("0.00"),
                "occupancy_on_books": Decimal("0.00"),
            },
            "adr_defined_with_rooms",
        ),
        # occupancy exists exactly when the capacity is known and positive
        ({"rooms_available": None}, "occupancy_defined_with_capacity"),
        ({"rooms_available": 0}, "occupancy_defined_with_capacity"),
        ({"occupancy_on_books": None}, "occupancy_defined_with_capacity"),
        # an observation has no uncertainty
        ({"uncertain_booking_count": 1, "uncertain_rooms": 1}, "observed_has_no_uncertainty"),
    ],
)
def test_inconsistent_snapshots_are_rejected(
    db_session: Session,
    rejects: Rejects,
    two_tenants: tuple[Tenant, Tenant],
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    tenant, _ = two_tenants

    with rejects(pg.CheckViolation, ck(constraint)):
        insert_snapshot(db_session, tenant, **overrides)


def test_a_snapshot_without_bookings_or_inventory_is_valid_with_null_metrics(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_snapshot(
        db_session,
        tenant,
        booking_count_on_books=0,
        rooms_on_books=0,
        allocated_room_revenue_on_books=Decimal("0.00"),
        rooms_available=None,
        occupancy_on_books=None,
        adr_on_books=None,
    )

    row = db_session.scalars(select(BookingSnapshot)).one()
    assert (row.rooms_available, row.occupancy_on_books, row.adr_on_books) == (None, None, None)


def test_a_reconstruction_may_carry_uncertainty(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_snapshot(
        db_session,
        tenant,
        origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
        uncertain_booking_count=1,
        uncertain_rooms=2,
    )

    row = db_session.scalars(select(BookingSnapshot)).one()
    assert (row.origin, row.uncertain_rooms) == (SnapshotOrigin.RECONSTRUCTED_APPROXIMATE, 2)


def test_occupancy_over_one_hundred_percent_is_storable(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants

    insert_snapshot(
        db_session,
        tenant,
        rooms_on_books=45,
        booking_count_on_books=45,
        rooms_available=40,
        occupancy_on_books=Decimal("112.50"),
        adr_on_books=Decimal("100.00"),
        allocated_room_revenue_on_books=Decimal("4500.00"),
    )

    assert db_session.scalars(select(BookingSnapshot.occupancy_on_books)).one() == Decimal("112.50")


# --- the logical key ---------------------------------------------------------------------------


def test_the_key_does_not_contain_the_origin_so_an_observation_and_a_reconstruction_collide(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    insert_snapshot(db_session, tenant, origin=SnapshotOrigin.OBSERVED)

    with rejects(pg.UniqueViolation, UQ_SNAPSHOT_KEY):
        insert_snapshot(db_session, tenant, origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE)
    with rejects(pg.UniqueViolation, UQ_SNAPSHOT_KEY):
        insert_snapshot(db_session, tenant, origin=SnapshotOrigin.OBSERVED)


def test_the_key_allows_other_days_nights_and_data_sources(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    second_source = factory.data_source(tenant.property)

    insert_snapshot(db_session, tenant)
    insert_snapshot(db_session, tenant, snapshot_local_date=date(2026, 3, 16))
    insert_snapshot(db_session, tenant, stay_date=date(2026, 4, 2))
    insert_snapshot(db_session, tenant, data_source_id=second_source.id)  # never merged with it

    assert len(db_session.scalars(select(BookingSnapshot)).all()) == 4


# --- immutability ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"rooms_on_books": 4},
        {"origin": SnapshotOrigin.RECONSTRUCTED_APPROXIMATE},
        {"content_fingerprint": "d" * 64},
        {"rooms_available": None, "occupancy_on_books": None},
    ],
)
def test_a_stored_snapshot_cannot_be_updated(
    db_session: Session,
    rejects: Rejects,
    two_tenants: tuple[Tenant, Tenant],
    change: dict[str, Any],
) -> None:
    tenant, _ = two_tenants
    insert_snapshot(db_session, tenant)

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(update(BookingSnapshot).values(**change))


def test_even_a_no_op_update_of_a_snapshot_is_refused(
    db_session: Session, rejects: Rejects, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    insert_snapshot(db_session, tenant)

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            update(BookingSnapshot).values(rooms_on_books=BookingSnapshot.rooms_on_books)
        )


def test_inventory_stays_editable_because_it_is_configuration_not_evidence(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    tenant, _ = two_tenants
    insert_inventory(db_session, tenant)

    db_session.execute(update(RoomInventoryDaily).values(rooms_available=25))

    assert db_session.scalars(select(RoomInventoryDaily.rooms_available)).one() == 25


def test_the_trigger_lives_on_snapshots_only(db_session: Session) -> None:
    triggers = set(
        db_session.execute(
            text(
                "SELECT event_object_table || '.' || trigger_name"
                " FROM information_schema.triggers"
                " WHERE trigger_name LIKE 'trg\\_booking\\_snapshots%'"
            )
        ).scalars()
    )

    assert triggers == {"booking_snapshots.trg_booking_snapshots_immutable"}
