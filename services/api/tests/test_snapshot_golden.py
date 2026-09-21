"""Golden snapshots: "MASSERIA NINFA DEMO".

The Gate 2 golden world (16 bookings imported through the real import service) plus a small
synthetic addendum, a declared room inventory, one OBSERVED run and one RECONSTRUCTION run.
The expected result (`masseria_ninfa_snapshots_v1.expected.json`) was computed independently of
the application code (tests/fixtures/snapshots/generate_masseria_snapshots_expected.py, standard
library only). It is BOOKINGS + INVENTORY -> SNAPSHOTS: no expected value, alert, impact,
priority, recommendation or decision is derived from it.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg.errors as pg
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.bookings.service import BookingImportService
from app.modules.bookings.suggestions import SuggestionConfidence
from app.modules.ingestion.models import DataSource, ImportJobStatus
from app.modules.properties.models import Property
from app.modules.snapshots.calculation import stay_nights, to_cents
from app.modules.snapshots.common import SnapshotRunResult
from app.modules.snapshots.models import BookingSnapshot, RoomInventoryDaily, SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import BookingSnapshotRepository, RoomInventoryRepository
from tests.booking_support import FIXTURES
from tests.snapshot_support import FixedClock
from tests.support import BookingFactory, Rejects, make_rejects

SNAPSHOT_FIXTURES = FIXTURES.parent / "snapshots"
GOLDEN_CSV = FIXTURES / "masseria_ninfa_bookings_v1.csv"
ADDENDUM_CSV = SNAPSHOT_FIXTURES / "masseria_ninfa_bookings_addendum_v1.csv"
EXPECTED = json.loads(
    (SNAPSHOT_FIXTURES / "masseria_ninfa_snapshots_v1.expected.json").read_text("utf-8")
)
ITALIAN_FORMAT: dict[str, Any] = {
    "date_formats": {
        "booked_at": "%d/%m/%Y %H:%M",
        "check_in": "%d/%m/%Y",
        "check_out": "%d/%m/%Y",
        "cancelled_at": "%d/%m/%Y %H:%M",
    },
    "decimal_separator": ",",
    "thousands_separator": ".",
}
OBSERVED_AT = datetime.fromisoformat(EXPECTED["observed_at"])
RECONSTRUCTED_AT = datetime.fromisoformat(EXPECTED["reconstructed_at"])
STAY_FIRST = date.fromisoformat(EXPECTED["stay_dates"]["first"])
STAY_LAST = date.fromisoformat(EXPECTED["stay_dates"]["last"])
SNAPSHOT_FIRST = date.fromisoformat(EXPECTED["reconstruction_snapshot_dates"]["first"])
SNAPSHOT_LAST = date.fromisoformat(EXPECTED["reconstruction_snapshot_dates"]["last"])


@dataclass
class Golden:
    session: Session
    context: TenantContext
    prop: Property
    source: DataSource
    observed: SnapshotRunResult
    reconstructed: SnapshotRunResult

    def snapshots(self) -> BookingSnapshotRepository:
        return BookingSnapshotRepository(self.session, self.context)


def import_world(session: Session, factory: BookingFactory) -> tuple[TenantContext, Any, Any]:
    workspace = factory.workspace()
    prop = factory.property(workspace, "masseria-ninfa")
    source = factory.data_source(prop)
    context = TenantContext(workspace.id)
    service = BookingImportService(session, context)

    golden = GOLDEN_CSV.read_bytes()
    suggestion = service.suggest_mapping(source.id, filename=GOLDEN_CSV.name, content=golden)
    service.save_mapping(
        source.id,
        headers=suggestion.headers,
        column_mapping={
            s.canonical_field.value: {"column": s.suggested_source_column}
            for s in suggestion.suggestions
            if s.suggested_source_column and s.confidence == SuggestionConfidence.HIGH
        },
        format_options=ITALIAN_FORMAT,
    )
    for path, expected_rows in ((GOLDEN_CSV, 16), (ADDENDUM_CSV, 7)):
        result = service.import_file(source.id, filename=path.name, content=path.read_bytes())
        assert (result.status, result.rows_valid, result.rows_invalid) == (
            ImportJobStatus.SUCCEEDED,
            expected_rows,
            0,
        ), path.name
    return context, prop, source


def declare_inventory(session: Session, context: TenantContext, prop: Property) -> None:
    repository = RoomInventoryRepository(session, context)
    for block in EXPECTED["inventory"]:
        day = date.fromisoformat(block["first"])
        last = date.fromisoformat(block["last"])
        while day <= last:
            repository.set_for_date(
                prop.id,
                day,
                rooms_available=block["rooms_available"],
                rooms_out_of_order=block["rooms_out_of_order"],
            )
            day = date.fromordinal(day.toordinal() + 1)
    session.commit()


def build(session: Session, factory: BookingFactory) -> Golden:
    context, prop, source = import_world(session, factory)
    declare_inventory(session, context, prop)

    observed = ObservedSnapshotService(
        session, context, clock=FixedClock(OBSERVED_AT)
    ).take_snapshot(
        property_id=prop.id,
        data_source_id=source.id,
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )
    reconstructed = BookingSnapshotReconstructionService(
        session, context, clock=FixedClock(RECONSTRUCTED_AT)
    ).reconstruct(
        property_id=prop.id,
        data_source_id=source.id,
        snapshot_date_start=SNAPSHOT_FIRST,
        snapshot_date_end=SNAPSHOT_LAST,
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )
    return Golden(session, context, prop, source, observed, reconstructed)


def text(value: object) -> str:
    return "-" if value is None else str(value)


def money(value: Decimal | None) -> str | None:
    return None if value is None else format(value, ".2f")


def as_expected(row: BookingSnapshot) -> dict[str, object]:
    """A stored row in the shape of the expected file (no shared code with the generator)."""
    return {
        "snapshot_date": row.snapshot_local_date.isoformat(),
        "stay_date": row.stay_date.isoformat(),
        "origin": row.origin.value,
        "booking_count_on_books": row.booking_count_on_books,
        "rooms_on_books": row.rooms_on_books,
        "allocated_room_revenue_on_books": money(row.allocated_room_revenue_on_books),
        "rooms_available": row.rooms_available,
        "occupancy_on_books": money(row.occupancy_on_books),
        "adr_on_books": money(row.adr_on_books),
        "uncertain_booking_count": row.uncertain_booking_count,
        "uncertain_rooms": row.uncertain_rooms,
    }


def all_rows(session: Session) -> list[BookingSnapshot]:
    return list(session.scalars(select(BookingSnapshot)))


def count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- the golden world covers what it must ------------------------------------------------------


def test_the_golden_world_contains_every_situation_the_snapshots_must_handle(
    db_session: Session, factory: BookingFactory
) -> None:
    _, _, source = import_world(db_session, factory)

    bookings = list(db_session.scalars(select(Booking).where(Booking.data_source_id == source.id)))

    assert len(bookings) == 16 + 7
    cancelled = [b for b in bookings if b.status == BookingStatus.CANCELLED]
    assert any(b.cancelled_at is not None for b in cancelled)  # a cancellation with a date
    assert any(b.cancelled_at is None for b in cancelled)  # and one without
    assert any(b.rooms >= 3 for b in bookings)  # multi-room
    assert any((b.check_out - b.check_in).days >= 3 for b in bookings)  # multi-night
    assert any(
        to_cents(b.room_revenue) % stay_nights(b.check_in, b.check_out) != 0 for b in bookings
    )  # revenue that no whole number of cents per night can split evenly
    assert {b.status for b in bookings} == set(BookingStatus)  # every status is present
    inventory_days = sum(
        (date.fromisoformat(b["last"]) - date.fromisoformat(b["first"])).days + 1
        for b in EXPECTED["inventory"]
    )
    assert inventory_days < EXPECTED["counts"]["stay_nights"]  # some nights have NO inventory row


# --- observed and reconstructed values ---------------------------------------------------------


def test_the_snapshots_match_the_independently_computed_expected_result(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    counts = EXPECTED["counts"]
    assert (golden.observed.created, golden.observed.unchanged) == (counts["observed"], 0)
    assert golden.observed.snapshot_date_first == date(2026, 7, 25)
    assert (
        golden.reconstructed.created,
        golden.reconstructed.unchanged,
        golden.reconstructed.skipped_observed,
    ) == (counts["reconstructed_created"], 0, counts["reconstructed_skipped_observed"])

    # 1. every hand-checked probe
    for probe in EXPECTED["probes"]:
        row = golden.snapshots().get_for_stay_date(
            golden.source.id,
            date.fromisoformat(probe["snapshot_date"]),
            date.fromisoformat(probe["stay_date"]),
        )
        assert row is not None, probe
        expected = {k: v for k, v in probe.items() if k != "note"}
        assert as_expected(row) == expected, probe["note"]

    # 2. the whole grid, cell by cell, as one checksum
    rows = all_rows(db_session)
    assert len(rows) == counts["observed"] + counts["reconstructed_created"]
    lines = sorted("|".join(text(v) for v in as_expected(row).values()) for row in rows)
    assert hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest() == EXPECTED["grid_sha256"]


def test_observed_rows_are_the_only_observed_ones_and_carry_the_observation_instant(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    observed = [r for r in all_rows(db_session) if r.origin == SnapshotOrigin.OBSERVED]
    reconstructed = [r for r in all_rows(db_session) if r.origin != SnapshotOrigin.OBSERVED]

    assert len(observed) == EXPECTED["counts"]["stay_nights"]
    assert {r.snapshot_local_date for r in observed} == {date(2026, 7, 25)}
    assert {r.as_of_at for r in observed} == {OBSERVED_AT}
    assert all(r.uncertain_rooms == 0 for r in observed)
    assert {r.origin for r in reconstructed} == {SnapshotOrigin.RECONSTRUCTED_APPROXIMATE}
    # the reconstruction of the observed day was skipped, so that day still has ONE row per night
    on_observed_day = [
        r for r in all_rows(db_session) if r.snapshot_local_date == date(2026, 7, 25)
    ]
    assert len(on_observed_day) == golden.observed.created
    assert {r.calculation_version for r in all_rows(db_session)} == {"booking-snapshot-v1"}
    # uncertainty exists only where the canonical table cannot tell (reconstructed rows)
    assert any(r.uncertain_rooms > 0 for r in reconstructed)


def test_the_curve_of_a_night_shows_bookings_arriving_cancelling_and_the_observation(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    curve = golden.snapshots().list_curve_for_stay_date(golden.source.id, date(2026, 4, 10))

    assert len(curve) == 207 and curve[0].snapshot_local_date == SNAPSHOT_FIRST
    rooms = {p.snapshot_local_date: p.rooms_on_books for p in curve}
    assert rooms[date(2026, 1, 19)] == 0  # MN-0003 not yet made
    assert rooms[date(2026, 1, 20)] == 1  # made on the 20th
    assert rooms[date(2026, 2, 14)] == 1
    assert rooms[date(2026, 2, 15)] == 0  # cancelled on the 15th
    assert rooms[date(2026, 3, 5)] == 1  # MN-0102 made on the 5th
    assert curve[-2].origin == SnapshotOrigin.OBSERVED and curve[-2].snapshot_local_date == date(
        2026, 7, 25
    )
    assert curve[-1].origin == SnapshotOrigin.RECONSTRUCTED_APPROXIMATE


# --- scope: bookings + inventory -> snapshots, nothing else ------------------------------------


def test_the_snapshot_runs_write_snapshots_and_nothing_else(
    db_session: Session, factory: BookingFactory
) -> None:
    context, prop, source = import_world(db_session, factory)
    declare_inventory(db_session, context, prop)
    tables = {
        mapper.class_.__tablename__: mapper.class_
        for mapper in Base.registry.mappers
        if mapper.class_ is not BookingSnapshot
    }
    snapshot_before = {name: count(db_session, model) for name, model in tables.items()}

    ObservedSnapshotService(db_session, context, clock=FixedClock(OBSERVED_AT)).take_snapshot(
        property_id=prop.id,
        data_source_id=source.id,
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )
    BookingSnapshotReconstructionService(
        db_session, context, clock=FixedClock(RECONSTRUCTED_AT)
    ).reconstruct(
        property_id=prop.id,
        data_source_id=source.id,
        snapshot_date_start=date(2026, 7, 1),
        snapshot_date_end=date(2026, 7, 10),
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )

    assert {name: count(db_session, model) for name, model in tables.items()} == snapshot_before
    assert count(db_session, BookingSnapshot) == 124 + 10 * 124
    assert count(db_session, RoomInventoryDaily) == sum(
        (date.fromisoformat(b["last"]) - date.fromisoformat(b["first"])).days + 1
        for b in EXPECTED["inventory"]
    )


def test_guest_data_of_the_source_files_never_reaches_a_snapshot(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    dump = json.dumps([as_expected(r) for r in all_rows(db_session)])

    assert golden.prop.slug == "masseria-ninfa"
    for guest in ("Anna Bianchi", "Sofia Ambra", "+39 000 0000101", "Camera Doppia"):
        assert guest not in dump


# --- reproducibility and immutability ----------------------------------------------------------


def test_running_the_whole_golden_scenario_again_changes_nothing(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    before = sorted(
        (r.snapshot_local_date, r.stay_date, r.content_fingerprint, r.id)
        for r in all_rows(db_session)
    )

    observed = ObservedSnapshotService(
        db_session, golden.context, clock=FixedClock(OBSERVED_AT)
    ).take_snapshot(
        property_id=golden.prop.id,
        data_source_id=golden.source.id,
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )
    reconstructed = BookingSnapshotReconstructionService(
        db_session, golden.context, clock=FixedClock(RECONSTRUCTED_AT)
    ).reconstruct(
        property_id=golden.prop.id,
        data_source_id=golden.source.id,
        snapshot_date_start=SNAPSHOT_FIRST,
        snapshot_date_end=SNAPSHOT_LAST,
        stay_date_start=STAY_FIRST,
        stay_date_end=STAY_LAST,
    )

    assert (observed.created, observed.unchanged) == (0, 124)
    assert (reconstructed.created, reconstructed.unchanged, reconstructed.skipped_observed) == (
        0,
        EXPECTED["counts"]["reconstructed_created"],
        124,
    )
    after = sorted(
        (r.snapshot_local_date, r.stay_date, r.content_fingerprint, r.id)
        for r in all_rows(db_session)
    )
    assert after == before  # same rows, same ids, same fingerprints


def test_a_golden_snapshot_cannot_be_edited(db_session: Session, factory: BookingFactory) -> None:
    golden = build(db_session, factory)
    rejects: Rejects = make_rejects(db_session)

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            update(BookingSnapshot)
            .where(
                BookingSnapshot.data_source_id == golden.source.id,
                BookingSnapshot.snapshot_local_date == date(2026, 7, 25),
                BookingSnapshot.stay_date == date(2026, 3, 20),
            )
            .values(rooms_on_books=99)
        )


def test_the_clock_constants_of_the_scenario_are_what_the_fixture_says() -> None:
    assert datetime(2026, 7, 25, 10, 0, tzinfo=UTC) == OBSERVED_AT
    assert datetime(2026, 7, 27, 10, 0, tzinfo=UTC) == RECONSTRUCTED_AT
