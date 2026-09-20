"""Tenant scoping and semantics of the bookings repositories (two real tenants, real PostgreSQL)."""

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.modules.bookings.channels import ChannelOverride, resolve_channel
from app.modules.bookings.models import BookingStatus, ChannelType, ImportRowStatus
from app.modules.bookings.normalization import NormalizedBooking
from app.modules.bookings.repository import (
    BookingChannelRepository,
    BookingImportRowRepository,
    BookingMappingProfileRepository,
    BookingRepository,
    ImportItem,
    StagedRow,
)
from tests.support import BookingFactory, Tenant

UTC = dt.UTC


def make_booking(source_record_id: str = "BK-1", **overrides: object) -> NormalizedBooking:
    values: dict[str, object] = {
        "source_record_id": source_record_id,
        "booked_at": dt.datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
        "check_in": dt.date(2026, 3, 10),
        "check_out": dt.date(2026, 3, 13),
        "status": BookingStatus.CONFIRMED,
        "rooms": 1,
        "guests": None,
        "room_revenue": Decimal("450.00"),
        "total_revenue": None,
        "channel": resolve_channel("Booking.com", {}),
        "commission_amount": None,
        "commission_rate": None,
        "cancelled_at": None,
        "room_type": None,
        "rate_plan": None,
    }
    values.update(overrides)
    return NormalizedBooking(**values)  # type: ignore[arg-type]


def item(booking: NormalizedBooking, channel_id: object) -> ImportItem:
    return ImportItem(booking, channel_id, booking.fingerprint())  # type: ignore[arg-type]


# --- BookingRepository ------------------------------------------------------------------------


def test_a_booking_repository_only_sees_its_own_workspace(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    booking_a = factory.booking(
        a.data_source, factory.channel(a.property), a.import_job, source_record_id="SAME"
    )
    booking_b = factory.booking(
        b.data_source, factory.channel(b.property), b.import_job, source_record_id="SAME"
    )
    repo_a, repo_b = (BookingRepository(db_session, t.context) for t in (a, b))

    assert repo_a.get_by_id(booking_a.id) == booking_a and repo_a.get_by_id(booking_b.id) is None
    assert repo_b.get_by_id(booking_a.id) is None
    assert repo_a.get_by_source_record_id(a.data_source.id, "SAME") == booking_a
    assert repo_a.get_by_source_record_id(b.data_source.id, "SAME") is None  # B's source, from A
    assert [x.id for x in repo_a.list_for_property(a.property.id)] == [booking_a.id]
    assert repo_a.list_for_property(b.property.id) == []  # asking for B's property leaks nothing
    assert list(repo_a.existing_by_source_record_ids(b.data_source.id, ["SAME"])) == []


def test_bookings_can_be_listed_by_status_and_stay_date(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    channel = factory.channel(a.property)
    for index, (check_in, status) in enumerate(
        [
            (dt.date(2026, 3, 10), BookingStatus.CONFIRMED),
            (dt.date(2026, 4, 10), BookingStatus.CANCELLED),
            (dt.date(2026, 5, 10), BookingStatus.CONFIRMED),
        ]
    ):
        factory.booking(
            a.data_source,
            channel,
            a.import_job,
            source_record_id=f"B{index}",
            status=status,
            check_in=check_in,
            check_out=check_in + dt.timedelta(days=2),
        )
    repo = BookingRepository(db_session, a.context)

    assert [x.source_record_id for x in repo.list_for_property(a.property.id)] == ["B0", "B1", "B2"]
    assert [
        x.source_record_id
        for x in repo.list_for_property(a.property.id, status=BookingStatus.CANCELLED)
    ] == ["B1"]
    assert [
        x.source_record_id
        for x in repo.list_for_property(
            a.property.id, check_in_from=dt.date(2026, 4, 1), check_in_until=dt.date(2026, 4, 30)
        )
    ] == ["B1"]


def test_upsert_creates_updates_and_leaves_identical_bookings_alone(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    channel = factory.channel(a.property)
    later_job = factory.import_job(a.data_source)
    repo = BookingRepository(db_session, a.context)
    args = {"property_id": a.property.id, "data_source_id": a.data_source.id}

    first = repo.upsert_from_import(
        **args,
        import_job_id=a.import_job.id,
        items=[item(make_booking("K1"), channel.id), item(make_booking("K2"), channel.id)],
    )
    second = repo.upsert_from_import(
        **args,
        import_job_id=later_job.id,
        items=[
            item(make_booking("K1"), channel.id),  # identical
            item(make_booking("K2", status=BookingStatus.CANCELLED), channel.id),  # changed
            item(make_booking("K3"), channel.id),  # new
        ],
    )

    assert (first.created, first.updated, first.unchanged) == (2, 0, 0)
    assert (second.created, second.updated, second.unchanged) == (1, 1, 1)
    by_id = {x.source_record_id: x for x in repo.list_for_property(a.property.id)}
    assert (by_id["K1"].first_import_job_id, by_id["K1"].last_import_job_id) == (
        a.import_job.id,
        a.import_job.id,
    )
    assert (by_id["K2"].first_import_job_id, by_id["K2"].last_import_job_id) == (
        a.import_job.id,
        later_job.id,
    )
    assert by_id["K2"].status == BookingStatus.CANCELLED
    assert (by_id["K3"].first_import_job_id, by_id["K3"].last_import_job_id) == (
        later_job.id,
        later_job.id,
    )


def test_an_upsert_batch_cannot_contain_the_same_source_record_twice(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    channel = factory.channel(a.property)

    with pytest.raises(ValueError, match="duplicate source_record_id"):
        BookingRepository(db_session, a.context).upsert_from_import(
            property_id=a.property.id,
            data_source_id=a.data_source.id,
            import_job_id=a.import_job.id,
            items=[item(make_booking("X"), channel.id), item(make_booking("X"), channel.id)],
        )


def test_an_upsert_cannot_write_into_another_workspaces_data_source(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    """The repository takes the tenant from its context; the database refuses the rest."""
    a, b = two_tenants
    channel_b = factory.channel(b.property)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        BookingRepository(db_session, a.context).upsert_from_import(
            property_id=b.property.id,
            data_source_id=b.data_source.id,
            import_job_id=b.import_job.id,
            items=[item(make_booking("LEAK"), channel_b.id)],
        )


# --- BookingChannelRepository -----------------------------------------------------------------


def test_channels_are_created_once_and_reused(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = BookingChannelRepository(db_session, a.context)

    first, created_first = repo.get_or_create(a.property.id, resolve_channel("Booking.com", {}))
    again, created_again = repo.get_or_create(a.property.id, resolve_channel("BOOKING.COM", {}))
    other, created_other = repo.get_or_create(a.property.id, resolve_channel("Portale X", {}))

    assert (created_first, created_again, created_other) == (True, False, True)
    assert first.id == again.id != other.id
    assert (first.channel_type, first.is_verified) == (ChannelType.OTA, False)
    assert [c.normalized_name for c in repo.list_for_property(a.property.id)] == [
        "booking com",
        "portale x",
    ]


def test_an_existing_channel_is_never_reclassified_by_a_later_spec(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = BookingChannelRepository(db_session, a.context)
    repo.get_or_create(a.property.id, resolve_channel("Acme", {}))

    override = {"acme": ChannelOverride(channel_type=ChannelType.CORPORATE)}

    channel, created = repo.get_or_create(a.property.id, resolve_channel("acme", override))

    assert (created, channel.channel_type, channel.is_verified) == (False, ChannelType.OTHER, False)


def test_channels_are_scoped_to_the_workspace_and_its_properties(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    second_property = factory.property(a.workspace)
    repo_a, repo_b = (BookingChannelRepository(db_session, t.context) for t in (a, b))

    in_a, _ = repo_a.get_or_create(a.property.id, resolve_channel("Booking.com", {}))
    in_a2, _ = repo_a.get_or_create(second_property.id, resolve_channel("Booking.com", {}))
    in_b, _ = repo_b.get_or_create(b.property.id, resolve_channel("Booking.com", {}))

    assert len({in_a.id, in_a2.id, in_b.id}) == 3
    assert repo_a.get_by_normalized_name(a.property.id, "booking com") == in_a
    assert repo_a.get_by_normalized_name(b.property.id, "booking com") is None
    assert repo_a.list_for_property(b.property.id) == []


def test_a_channel_cannot_be_created_for_another_workspaces_property(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with pytest.raises(IntegrityError), db_session.begin_nested():
        BookingChannelRepository(db_session, a.context).get_or_create(
            b.property.id, resolve_channel("Sneaky", {})
        )


# --- BookingMappingProfileRepository ----------------------------------------------------------

STORED = {
    "column_mapping": {"check_in": {"column": "Check-in"}},
    "status_mapping": {},
    "channel_mapping": {},
    "format_options": {},
}


def test_profiles_are_scoped_and_replaced_not_duplicated(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo_a, repo_b = (BookingMappingProfileRepository(db_session, t.context) for t in (a, b))

    created = repo_a.upsert(a.data_source, stored=STORED, header_signature="a" * 64)
    replaced = repo_a.upsert(
        a.data_source,
        stored={**STORED, "status_mapping": {"x": "CONFIRMED"}},
        header_signature="c" * 64,
    )

    assert created.id == replaced.id and replaced.header_signature == "c" * 64
    assert repo_a.get_for_data_source(a.data_source.id) == replaced
    assert repo_b.get_for_data_source(a.data_source.id) is None  # B cannot read A's mapping
    assert repo_a.get_for_data_source(b.data_source.id) is None


def test_a_profile_cannot_be_written_for_another_workspaces_data_source(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with pytest.raises(NotFoundError):
        BookingMappingProfileRepository(db_session, a.context).upsert(
            b.data_source, stored=STORED, header_signature="a" * 64
        )


# --- BookingImportRowRepository ---------------------------------------------------------------


def staged(number: int, status: ImportRowStatus = ImportRowStatus.VALID) -> StagedRow:
    invalid = status == ImportRowStatus.INVALID
    return StagedRow(
        row_number=number,
        mapped_payload={"check_in": "2026-03-10"},
        normalized_payload=None if invalid else {"check_in": "2026-03-10"},
        validation_status=status,
        validation_errors=[{"field": "check_in", "code": "BOOKING_INVALID_DATE"}]
        if invalid
        else [],
    )


def test_staging_rows_are_scoped_and_status_changes_touch_only_valid_rows_of_the_job(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    file_a, file_b = factory.import_file(a.import_job), factory.import_file(b.import_job)
    repo_a, repo_b = (BookingImportRowRepository(db_session, t.context) for t in (a, b))
    repo_a.add_many(
        a.import_job.id, file_a.id, [staged(2), staged(3, ImportRowStatus.INVALID), staged(4)]
    )
    repo_b.add_many(b.import_job.id, file_b.id, [staged(2)])

    assert [r.row_number for r in repo_a.list_for_job(a.import_job.id)] == [2, 3, 4]
    assert repo_a.list_for_job(b.import_job.id) == []  # B's job id, asked by A
    assert repo_a.count_by_status(a.import_job.id) == {
        ImportRowStatus.VALID: 2,
        ImportRowStatus.INVALID: 1,
    }
    assert repo_a.mark_valid_rows_imported(a.import_job.id) == 2
    assert repo_a.mark_valid_rows_imported(b.import_job.id) == 0  # cannot touch B's rows
    assert repo_a.count_by_status(a.import_job.id) == {
        ImportRowStatus.IMPORTED: 2,
        ImportRowStatus.INVALID: 1,
    }
    assert repo_b.count_by_status(b.import_job.id) == {ImportRowStatus.VALID: 1}


def test_staging_rows_cannot_be_added_to_another_workspaces_job(
    db_session: Session, factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    file_b = factory.import_file(b.import_job)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        BookingImportRowRepository(db_session, a.context).add_many(
            b.import_job.id, file_b.id, [staged(2)]
        )


def test_unknown_ids_are_simply_absent(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    assert BookingRepository(db_session, a.context).get_by_id(uuid4()) is None
    assert BookingImportRowRepository(db_session, a.context).list_for_job(uuid4()) == []


# --- read schemas -----------------------------------------------------------------------------


def test_read_schemas_serialise_the_orm_rows(
    factory: BookingFactory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    from app.modules.bookings.schemas import (
        BookingChannelRead,
        BookingImportRowRead,
        BookingMappingProfileRead,
        BookingRead,
    )

    a, _ = two_tenants
    channel = factory.channel(a.property)
    booking = factory.booking(a.data_source, channel, a.import_job, room_revenue=Decimal("450.00"))
    profile = factory.profile(a.data_source)
    row = factory.import_row(a.import_job, factory.import_file(a.import_job))

    assert BookingRead.model_validate(booking).room_revenue == Decimal("450.00")
    assert BookingChannelRead.model_validate(channel).normalized_name == "booking com"
    assert BookingMappingProfileRead.model_validate(profile).header_signature == "b" * 64
    assert BookingImportRowRead.model_validate(row).validation_status == ImportRowStatus.VALID
