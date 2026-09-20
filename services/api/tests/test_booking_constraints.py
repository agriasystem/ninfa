"""Booking, channel, mapping-profile and staging invariants enforced by PostgreSQL.

Rows are written with Core INSERTs/bare ORM objects and no application safeguard: the database
must refuse what is wrong, whatever the code above it does.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    BookingStatus,
    ChannelType,
    ImportRowStatus,
)
from tests.support import (
    VALID_FINGERPRINT,
    VALID_SIGNATURE,
    BookingFactory,
    Rejects,
    Tenant,
    booking_values,
    insert_core,
)

FK_DS = "fk_bookings_workspace_id_data_sources"
FK_CHANNEL = "fk_bookings_workspace_id_booking_channels"
FK_FIRST = "fk_bookings_first_import_job"
FK_LAST = "fk_bookings_last_import_job"
UQ_SOURCE_ID = "uq_bookings_workspace_id_data_source_id_source_record_id"
ANY_BOOKING_FK = (FK_DS, FK_CHANNEL, FK_FIRST, FK_LAST)


@pytest.fixture
def a(two_tenants: tuple[Tenant, Tenant]) -> Tenant:
    return two_tenants[0]


@pytest.fixture
def b(two_tenants: tuple[Tenant, Tenant]) -> Tenant:
    return two_tenants[1]


# --- A. bookings: tenant integrity (tests 1-4) ------------------------------------------------


def test_a_booking_whose_parents_share_its_workspace_and_property_is_accepted(
    factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property)

    booking = factory.booking(a.data_source, channel, a.import_job)

    assert booking.id.version == 4
    assert isinstance(booking.room_revenue, Decimal)


def test_a_booking_cannot_point_at_a_property_of_another_workspace(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    channel_a = factory.channel(a.property)

    with rejects(pg.ForeignKeyViolation, ANY_BOOKING_FK):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel_a, a.import_job, property_id=b.property.id),
        )
    with rejects(pg.ForeignKeyViolation, ANY_BOOKING_FK):
        insert_core(
            db_session,
            Booking,
            **booking_values(
                b.data_source,
                factory.channel(b.property),
                b.import_job,
                workspace_id=a.workspace.id,
            ),
        )


def test_a_booking_cannot_point_at_a_data_source_of_another_workspace(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    channel_a = factory.channel(a.property)

    with rejects(pg.ForeignKeyViolation, ANY_BOOKING_FK):
        insert_core(
            db_session,
            Booking,
            **booking_values(
                a.data_source, channel_a, a.import_job, data_source_id=b.data_source.id
            ),
        )


def test_a_booking_cannot_use_a_channel_of_another_workspace(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    channel_b = factory.channel(b.property)

    with rejects(pg.ForeignKeyViolation, FK_CHANNEL):
        insert_core(db_session, Booking, **booking_values(a.data_source, channel_b, a.import_job))


def test_a_booking_cannot_use_a_channel_of_another_property_of_the_same_workspace(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    other_property = factory.property(a.workspace)
    other_channel = factory.channel(other_property)

    with rejects(pg.ForeignKeyViolation, FK_CHANNEL):
        insert_core(
            db_session, Booking, **booking_values(a.data_source, other_channel, a.import_job)
        )


def test_import_jobs_of_a_booking_must_belong_to_its_own_data_source(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    same_property_other_source = factory.data_source(a.property)
    job_of_other_source = factory.import_job(same_property_other_source)

    for column, constraint in (("first_import_job_id", FK_FIRST), ("last_import_job_id", FK_LAST)):
        with rejects(pg.ForeignKeyViolation, constraint):
            insert_core(
                db_session,
                Booking,
                **booking_values(
                    a.data_source, channel, a.import_job, **{column: job_of_other_source.id}
                ),
            )
        with rejects(pg.ForeignKeyViolation, constraint):  # and never a job of another workspace
            insert_core(
                db_session,
                Booking,
                **booking_values(a.data_source, channel, a.import_job, **{column: b.import_job.id}),
            )


def test_a_booking_needs_existing_parents(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    from uuid import uuid4

    with rejects(pg.ForeignKeyViolation, FK_CHANNEL):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel, a.import_job, channel_id=uuid4()),
        )


# --- A. bookings: identity and value constraints (tests 5-10) --------------------------------


def test_source_record_id_is_unique_per_data_source(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    factory.booking(a.data_source, channel, a.import_job, source_record_id="SAME")

    with rejects(pg.UniqueViolation, UQ_SOURCE_ID):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel, a.import_job, source_record_id="SAME"),
        )


def test_the_same_source_record_id_is_allowed_in_another_data_source(
    factory: BookingFactory, a: Tenant, b: Tenant
) -> None:
    second_source_same_property = factory.data_source(a.property)
    job_2 = factory.import_job(second_source_same_property)
    channel = factory.channel(a.property)

    first = factory.booking(a.data_source, channel, a.import_job, source_record_id="SAME")
    second = factory.booking(second_source_same_property, channel, job_2, source_record_id="SAME")
    other_workspace = factory.booking(
        b.data_source, factory.channel(b.property), b.import_job, source_record_id="SAME"
    )

    assert len({first.id, second.id, other_workspace.id}) == 3


@pytest.mark.parametrize("check_out", [date(2026, 3, 10), date(2026, 3, 9)])
def test_check_out_must_be_after_check_in(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects, check_out: date
) -> None:
    channel = factory.channel(a.property)

    with rejects(pg.CheckViolation, "ck_bookings_check_out_after_check_in"):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel, a.import_job, check_out=check_out),
        )


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("rooms", 0, "ck_bookings_rooms_positive"),
        ("rooms", -1, "ck_bookings_rooms_positive"),
        ("guests", 0, "ck_bookings_guests_positive"),
        ("guests", -2, "ck_bookings_guests_positive"),
        ("commission_rate", Decimal("-0.01"), "ck_bookings_commission_rate_range"),
        ("commission_rate", Decimal("100.01"), "ck_bookings_commission_rate_range"),
        ("room_revenue", Decimal("-0.01"), "ck_bookings_room_revenue_non_negative"),
        ("total_revenue", Decimal("-1"), "ck_bookings_total_revenue_non_negative"),
        ("commission_amount", Decimal("-1"), "ck_bookings_commission_amount_non_negative"),
        ("source_record_id", "   ", "ck_bookings_source_record_id_not_blank"),
        ("room_type", " ", "ck_bookings_room_type_not_blank"),
        ("rate_plan", "", "ck_bookings_rate_plan_not_blank"),
        ("source_fingerprint", "F" * 64, "ck_bookings_source_fingerprint_format"),
        ("source_fingerprint", "a" * 63, "ck_bookings_source_fingerprint_format"),
    ],
)
def test_value_constraints(
    db_session: Session,
    factory: BookingFactory,
    a: Tenant,
    rejects: Rejects,
    column: str,
    value: Any,
    constraint: str,
) -> None:
    channel = factory.channel(a.property)

    with rejects(pg.CheckViolation, constraint):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel, a.import_job, **{column: value}),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"guests": 1},
        {"commission_rate": Decimal("0")},
        {"commission_rate": Decimal("100")},
        {"commission_rate": Decimal("17.5000")},
        {"room_revenue": Decimal("0.00")},
        {"total_revenue": Decimal("0.00")},
        {"total_revenue": Decimal("1.00")},  # deliberately below room_revenue: allowed
        {"commission_amount": Decimal("0.00")},
    ],
)
def test_boundary_values_are_accepted(
    factory: BookingFactory, a: Tenant, overrides: dict[str, Any]
) -> None:
    channel = factory.channel(a.property)

    assert factory.booking(a.data_source, channel, a.import_job, **overrides)


def test_cancelled_at_requires_a_cancelled_status_but_not_the_other_way_round(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    when = datetime(2026, 2, 1, 8, 0, tzinfo=UTC)

    with rejects(pg.CheckViolation, "ck_bookings_cancelled_at_requires_cancelled"):
        insert_core(
            db_session,
            Booking,
            **booking_values(a.data_source, channel, a.import_job, cancelled_at=when),
        )
    assert factory.booking(
        a.data_source,
        channel,
        a.import_job,
        source_record_id="C1",
        status=BookingStatus.CANCELLED,
        cancelled_at=when,
    )
    assert factory.booking(  # many PMS do not export the cancellation date
        a.data_source, channel, a.import_job, source_record_id="C2", status=BookingStatus.CANCELLED
    )


def test_status_is_a_closed_set_stored_as_text(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    with rejects(pg.CheckViolation, "ck_bookings_status_valid"):
        db_session.execute(
            text(
                "INSERT INTO bookings (workspace_id, property_id, data_source_id, source_record_id,"
                " booked_at, check_in, check_out, status, rooms, room_revenue, channel_id,"
                " source_fingerprint, first_import_job_id, last_import_job_id)"
                " VALUES (:w, :p, :d, 'X', now(), '2026-03-10', '2026-03-13', 'PENDING', 1, 1, :c,"
                " :f, :j, :j)"
            ),
            {
                "w": a.workspace.id,
                "p": a.property.id,
                "d": a.data_source.id,
                "c": channel.id,
                "f": VALID_FINGERPRINT,
                "j": a.import_job.id,
            },
        )
    stored = factory.booking(a.data_source, channel, a.import_job, source_record_id="OK")
    assert (
        db_session.execute(
            text("SELECT status FROM bookings WHERE id = :id"), {"id": stored.id}
        ).scalar_one()
        == "CONFIRMED"
    )


def test_money_is_stored_as_numeric_and_returned_as_decimal(
    db_session: Session, factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property)
    booking = factory.booking(
        a.data_source,
        channel,
        a.import_job,
        room_revenue=Decimal("1234567.89"),
        total_revenue=Decimal("0.10"),
        commission_rate=Decimal("12.3456"),
    )
    db_session.expire(booking)

    assert (booking.room_revenue, booking.total_revenue, booking.commission_rate) == (
        Decimal("1234567.89"),
        Decimal("0.10"),
        Decimal("12.3456"),
    )
    rows = db_session.execute(
        text(
            "SELECT column_name, data_type || ':' || coalesce(numeric_scale::text, '-')"
            " FROM information_schema.columns WHERE table_name = 'bookings'"
            " AND column_name IN ('room_revenue', 'commission_rate', 'booked_at', 'check_in')"
        )
    )
    types: dict[str, str] = {row[0]: row[1] for row in rows}
    assert types == {
        "room_revenue": "numeric:2",
        "commission_rate": "numeric:4",
        "booked_at": "timestamp with time zone:-",
        "check_in": "date:-",
    }


def test_booked_at_is_timezone_aware_utc(
    db_session: Session, factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property)
    booking = factory.booking(a.data_source, channel, a.import_job)
    db_session.expire(booking)

    assert booking.booked_at.utcoffset() == timedelta(0)
    assert booking.booked_at == datetime(2026, 1, 15, 9, 30, tzinfo=UTC)


# --- identity is immutable; delete policy -----------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "id",
        "workspace_id",
        "property_id",
        "data_source_id",
        "source_record_id",
        "first_import_job_id",
        "created_at",
    ],
)
def test_the_identity_of_a_booking_cannot_change(
    db_session: Session,
    factory: BookingFactory,
    a: Tenant,
    b: Tenant,
    rejects: Rejects,
    column: str,
) -> None:
    channel = factory.channel(a.property)
    booking = factory.booking(a.data_source, channel, a.import_job)
    new_value = {
        "id": "gen_random_uuid()",
        "workspace_id": f"'{b.workspace.id}'",
        "property_id": f"'{b.property.id}'",
        "data_source_id": f"'{b.data_source.id}'",
        "source_record_id": "'CHANGED'",
        "first_import_job_id": f"'{factory.import_job(a.data_source).id}'",
        "created_at": "now() + interval '1 day'",
    }[column]

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            text(f"UPDATE bookings SET {column} = {new_value} WHERE id = :id"), {"id": booking.id}
        )


def test_the_mutable_columns_of_a_booking_can_change(
    db_session: Session, factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property)
    booking = factory.booking(a.data_source, channel, a.import_job)
    later_job = factory.import_job(a.data_source)

    booking.status = BookingStatus.CANCELLED
    booking.room_revenue = Decimal("500.00")
    booking.last_import_job_id = later_job.id
    booking.source_fingerprint = "c" * 64
    db_session.flush()

    assert (booking.status, booking.last_import_job_id) == (BookingStatus.CANCELLED, later_job.id)
    assert booking.first_import_job_id == a.import_job.id


def test_records_that_bookings_depend_on_cannot_be_deleted(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    channel = factory.channel(a.property)
    factory.booking(a.data_source, channel, a.import_job)

    for table, key, constraint in (
        ("booking_channels", channel.id, FK_CHANNEL),
        ("import_jobs", a.import_job.id, (FK_FIRST, FK_LAST)),
        ("data_sources", a.data_source.id, (FK_DS, "fk_import_jobs_workspace_id_data_sources")),
    ):
        with rejects(pg.RestrictViolation, constraint):
            db_session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": key})
    assert db_session.query(Booking).count() == 1


def test_a_booking_can_be_deleted_by_itself(
    db_session: Session, factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property)
    booking = factory.booking(a.data_source, channel, a.import_job)

    db_session.execute(text("DELETE FROM bookings WHERE id = :id"), {"id": booking.id})

    assert db_session.query(Booking).count() == 0


# --- B. booking channels (tests 11, 14 at DB level) -------------------------------------------


def test_channel_names_are_unique_per_property_by_normalised_name(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    factory.channel(a.property, "Booking.com")

    with rejects(
        pg.UniqueViolation, "uq_booking_channels_workspace_id_property_id_normalized_name"
    ):
        insert_core(
            db_session,
            BookingChannel,
            workspace_id=a.workspace.id,
            property_id=a.property.id,
            name="BOOKING.COM",
            normalized_name="booking com",
        )


def test_the_same_channel_is_allowed_in_different_properties(
    factory: BookingFactory, a: Tenant, b: Tenant
) -> None:
    second_property = factory.property(a.workspace)

    channels = [
        factory.channel(a.property, "Booking.com"),
        factory.channel(second_property, "Booking.com"),
        factory.channel(b.property, "Booking.com"),
    ]

    assert len({c.id for c in channels}) == 3
    assert {c.normalized_name for c in channels} == {"booking com"}


def test_channels_default_to_other_and_unverified(
    db_session: Session, factory: BookingFactory, a: Tenant
) -> None:
    channel = factory.channel(a.property, "Portale Sconosciuto")
    db_session.expire(channel)

    assert (channel.channel_type, channel.is_verified) == (ChannelType.OTHER, False)
    assert channel.default_commission_rate is None


def test_a_channel_cannot_belong_to_a_property_of_another_workspace(
    db_session: Session, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    with rejects(pg.ForeignKeyViolation, "fk_booking_channels_workspace_id_properties"):
        insert_core(
            db_session,
            BookingChannel,
            workspace_id=a.workspace.id,
            property_id=b.property.id,
            name="X",
            normalized_name="x",
        )


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"channel_type": "PORTAL"}, "ck_booking_channels_channel_type_valid"),
        (
            {"default_commission_rate": Decimal("100.5")},
            "ck_booking_channels_default_commission_rate_range",
        ),
        (
            {"default_commission_rate": Decimal("-1")},
            "ck_booking_channels_default_commission_rate_range",
        ),
        ({"name": "  "}, "ck_booking_channels_name_not_blank"),
        ({"normalized_name": ""}, "ck_booking_channels_normalized_name_not_blank"),
    ],
)
def test_channel_value_constraints(
    db_session: Session, a: Tenant, rejects: Rejects, columns: dict[str, Any], constraint: str
) -> None:
    values: dict[str, Any] = {
        "workspace_id": a.workspace.id,
        "property_id": a.property.id,
        "name": "X",
        "normalized_name": "x",
        **columns,
    }
    with rejects(pg.CheckViolation, constraint):
        db_session.execute(
            text(
                "INSERT INTO booking_channels (workspace_id, property_id, name,"
                " normalized_name, channel_type, default_commission_rate)"
                " VALUES (:workspace_id, :property_id, :name, :normalized_name,"
                " coalesce(:channel_type, 'OTHER'), :default_commission_rate)"
            ),
            {"channel_type": None, "default_commission_rate": None, **values},
        )


def test_every_channel_type_is_accepted(factory: BookingFactory, a: Tenant) -> None:
    for index, channel_type in enumerate(ChannelType):
        assert factory.channel(a.property, f"Channel {index}", channel_type=channel_type)


# --- C. mapping profiles (test 55) -----------------------------------------------------------


def test_one_mapping_profile_per_data_source(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    factory.profile(a.data_source)

    with rejects(pg.UniqueViolation, "uq_booking_mapping_profiles_workspace_id_data_source_id"):
        insert_core(
            db_session,
            BookingMappingProfile,
            workspace_id=a.workspace.id,
            property_id=a.property.id,
            data_source_id=a.data_source.id,
            column_mapping={},
            header_signature=VALID_SIGNATURE,
        )


def test_a_mapping_profile_cannot_cross_tenants(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    fk = "fk_booking_mapping_profiles_workspace_id_data_sources"
    base: dict[str, Any] = {"column_mapping": {}, "header_signature": VALID_SIGNATURE}

    with rejects(pg.ForeignKeyViolation, fk):  # A's workspace, B's data source
        insert_core(
            db_session,
            BookingMappingProfile,
            workspace_id=a.workspace.id,
            property_id=b.property.id,
            data_source_id=b.data_source.id,
            **base,
        )
    with rejects(pg.ForeignKeyViolation, fk):  # B's data source claimed by A with A's property
        insert_core(
            db_session,
            BookingMappingProfile,
            workspace_id=a.workspace.id,
            property_id=a.property.id,
            data_source_id=b.data_source.id,
            **base,
        )
    other_property = factory.property(a.workspace)
    with rejects(pg.ForeignKeyViolation, fk):  # right workspace, wrong property for that source
        insert_core(
            db_session,
            BookingMappingProfile,
            workspace_id=a.workspace.id,
            property_id=other_property.id,
            data_source_id=a.data_source.id,
            **base,
        )


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"column_mapping": []}, "ck_booking_mapping_profiles_json_shapes"),
        ({"status_mapping": "x"}, "ck_booking_mapping_profiles_json_shapes"),
        ({"format_options": [1]}, "ck_booking_mapping_profiles_json_shapes"),
        ({"header_signature": "ABC"}, "ck_booking_mapping_profiles_header_signature_format"),
    ],
)
def test_mapping_profile_shape_constraints(
    db_session: Session, a: Tenant, rejects: Rejects, columns: dict[str, Any], constraint: str
) -> None:
    values: dict[str, Any] = {
        "workspace_id": a.workspace.id,
        "property_id": a.property.id,
        "data_source_id": a.data_source.id,
        "column_mapping": {},
        "status_mapping": {},
        "channel_mapping": {},
        "format_options": {},
        "header_signature": VALID_SIGNATURE,
        **columns,
    }
    with rejects(pg.CheckViolation, constraint):
        insert_core(db_session, BookingMappingProfile, **values)


# --- D. staging rows (test 56) ---------------------------------------------------------------


def test_a_staging_row_of_a_file_and_job_in_the_same_workspace_is_accepted(
    factory: BookingFactory, a: Tenant
) -> None:
    import_file = factory.import_file(a.import_job)

    row = factory.import_row(a.import_job, import_file)

    assert row.validation_status == ImportRowStatus.VALID


def test_staging_rows_cannot_cross_tenants_or_jobs(
    db_session: Session, factory: BookingFactory, a: Tenant, b: Tenant, rejects: Rejects
) -> None:
    file_a, file_b = factory.import_file(a.import_job), factory.import_file(b.import_job)
    fk = "fk_booking_import_rows_workspace_id_import_files"
    base: dict[str, Any] = {
        "row_number": 1,
        "mapped_payload": {},
        "normalized_payload": {},
        "validation_status": ImportRowStatus.VALID,
    }
    from app.modules.bookings.models import BookingImportRow as Row

    cases = [
        {
            "workspace_id": a.workspace.id,
            "import_job_id": b.import_job.id,
            "import_file_id": file_b.id,
        },
        {
            "workspace_id": b.workspace.id,
            "import_job_id": a.import_job.id,
            "import_file_id": file_a.id,
        },
        {
            "workspace_id": a.workspace.id,
            "import_job_id": a.import_job.id,
            "import_file_id": file_b.id,
        },
        {
            "workspace_id": a.workspace.id,
            "import_job_id": b.import_job.id,
            "import_file_id": file_a.id,
        },
    ]
    for case in cases:
        with rejects(pg.ForeignKeyViolation, fk):
            insert_core(db_session, Row, **case, **base)


def test_a_file_must_belong_to_the_job_of_its_staging_row(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    other_job = factory.import_job(a.data_source)  # same workspace, same data source
    file_of_other_job = factory.import_file(other_job)

    with rejects(pg.ForeignKeyViolation, "fk_booking_import_rows_workspace_id_import_files"):
        factory.import_row(a.import_job, file_of_other_job)


def test_row_numbers_are_unique_per_file(
    db_session: Session, factory: BookingFactory, a: Tenant, rejects: Rejects
) -> None:
    import_file = factory.import_file(a.import_job)
    factory.import_row(a.import_job, import_file, row_number=2)

    with rejects(
        pg.UniqueViolation, "uq_booking_import_rows_workspace_id_import_file_id_row_number"
    ):
        factory.import_row(a.import_job, import_file, row_number=2)
    assert factory.import_row(a.import_job, import_file, row_number=3)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"row_number": 0}, "ck_booking_import_rows_row_number_positive"),
        (
            {"validation_status": ImportRowStatus.INVALID, "validation_errors": []},
            "ck_booking_import_rows_status_consistent",
        ),
        (
            {
                "validation_status": ImportRowStatus.VALID,
                "validation_errors": [{"field": "x", "code": "y"}],
            },
            "ck_booking_import_rows_status_consistent",
        ),
        (
            {"validation_status": ImportRowStatus.VALID, "normalized_payload": None},
            "ck_booking_import_rows_status_consistent",
        ),
        (
            {"validation_status": ImportRowStatus.IMPORTED, "normalized_payload": None},
            "ck_booking_import_rows_status_consistent",
        ),
        ({"mapped_payload": ["not", "an", "object"]}, "ck_booking_import_rows_payload_shapes"),
        ({"validation_errors": {"not": "an array"}}, "ck_booking_import_rows_payload_shapes"),
        ({"normalized_payload": [1]}, "ck_booking_import_rows_payload_shapes"),
    ],
)
def test_staging_row_constraints(
    db_session: Session,
    factory: BookingFactory,
    a: Tenant,
    rejects: Rejects,
    columns: dict[str, Any],
    constraint: str,
) -> None:
    import_file = factory.import_file(a.import_job)
    values: dict[str, Any] = {
        "workspace_id": a.workspace.id,
        "import_job_id": a.import_job.id,
        "import_file_id": import_file.id,
        "row_number": 1,
        "mapped_payload": {},
        "normalized_payload": {},
        "validation_status": ImportRowStatus.VALID,
        "validation_errors": [],
        **columns,
    }
    with rejects(pg.CheckViolation, constraint):
        insert_core(db_session, BookingImportRow, **values)


def test_an_invalid_row_needs_diagnostics_and_may_have_no_normalised_payload(
    factory: BookingFactory, a: Tenant
) -> None:
    import_file = factory.import_file(a.import_job)

    row = factory.import_row(
        a.import_job,
        import_file,
        validation_status=ImportRowStatus.INVALID,
        normalized_payload=None,
        validation_errors=[{"field": "check_in", "code": "BOOKING_INVALID_DATE"}],
    )

    assert row.normalized_payload is None
