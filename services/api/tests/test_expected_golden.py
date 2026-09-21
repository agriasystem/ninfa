"""Golden Expected baselines: "MASSERIA NINFA DEMO".

The full chain, end to end, through the real services:

    BOOKINGS (golden + addendum + a synthetic history, imported by the import service)
      -> SNAPSHOTS (observed and reconstructed by the snapshot services)
      -> EXPECTED BASELINES (the Expected service)      STOP: no alert, no decision.

The expected result (`masseria_ninfa_expected_v1.expected.json`) was computed independently of
the application code (tests/fixtures/expected/generate_masseria_expected_expected.py, standard
library only, exact fractions), including the snapshot values themselves.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg.errors as pg
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.bookings.service import BookingImportService
from app.modules.bookings.suggestions import SuggestionConfidence
from app.modules.ingestion.models import DataSource, ImportJobStatus
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.expected.service import BookingExpectedService
from app.modules.properties.models import Property
from app.modules.snapshots.models import BookingSnapshot
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import BookingSnapshotRepository
from tests.booking_support import FIXTURES
from tests.snapshot_support import FixedClock
from tests.support import BookingFactory, Rejects, make_rejects

FIXTURE_DIR = FIXTURES.parent / "expected"
EXPECTED = json.loads((FIXTURE_DIR / "masseria_ninfa_expected_v1.expected.json").read_text("utf-8"))
BOOKING_FILES = [
    (FIXTURES / "masseria_ninfa_bookings_v1.csv", 16),
    (FIXTURES.parent / "snapshots" / "masseria_ninfa_bookings_addendum_v1.csv", 7),
    (
        FIXTURE_DIR / "masseria_ninfa_bookings_history_v1.csv",
        EXPECTED["counts"]["history_bookings"],
    ),
]
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
RECONSTRUCTION_CLOCK = datetime.fromisoformat(EXPECTED["reconstruction_clock"])


@dataclass
class Golden:
    session: Session
    context: TenantContext
    prop: Property
    source: DataSource

    def snapshots(self) -> BookingSnapshotRepository:
        return BookingSnapshotRepository(self.session, self.context)

    def expected(self) -> ExpectedRepository:
        return ExpectedRepository(self.session, self.context)

    def service(self) -> BookingExpectedService:
        return BookingExpectedService(self.session, self.context)


def import_bookings(session: Session, factory: BookingFactory) -> Golden:
    workspace = factory.workspace()
    prop = factory.property(workspace, "masseria-ninfa")
    source = factory.data_source(prop)
    context = TenantContext(workspace.id)
    service = BookingImportService(session, context)

    first = BOOKING_FILES[0][0]
    suggestion = service.suggest_mapping(source.id, filename=first.name, content=first.read_bytes())
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
    for path, rows in BOOKING_FILES:
        result = service.import_file(source.id, filename=path.name, content=path.read_bytes())
        assert (result.status, result.rows_valid, result.rows_invalid) == (
            ImportJobStatus.SUCCEEDED,
            rows,
            0,
        ), path.name
    return Golden(session, context, prop, source)


def materialise_snapshots(golden: Golden) -> None:
    """One snapshot per spec, through the real observed / reconstruction services."""
    for spec in EXPECTED["snapshots"]:
        snapshot_day = date.fromisoformat(spec["snapshot_date"])
        stay_day = date.fromisoformat(spec["stay_date"])
        if spec["kind"] == "OBSERVED":
            clock = FixedClock(
                datetime.combine(snapshot_day, datetime.min.time(), tzinfo=UTC).replace(hour=10)
            )
            ObservedSnapshotService(golden.session, golden.context, clock=clock).take_snapshot(
                property_id=golden.prop.id,
                data_source_id=golden.source.id,
                stay_date_start=stay_day,
                stay_date_end=stay_day,
            )
        else:
            BookingSnapshotReconstructionService(
                golden.session, golden.context, clock=FixedClock(RECONSTRUCTION_CLOCK)
            ).reconstruct(
                property_id=golden.prop.id,
                data_source_id=golden.source.id,
                snapshot_date_start=snapshot_day,
                snapshot_date_end=snapshot_day,
                stay_date_start=stay_day,
                stay_date_end=stay_day,
            )


def build(session: Session, factory: BookingFactory) -> Golden:
    golden = import_bookings(session, factory)
    materialise_snapshots(golden)
    return golden


def target_snapshot(golden: Golden, target: dict[str, Any]) -> BookingSnapshot:
    row = golden.snapshots().get_for_stay_date(
        golden.source.id,
        date.fromisoformat(target["snapshot_date"]),
        date.fromisoformat(target["stay_date"]),
    )
    assert row is not None, target["name"]
    return row


def calculate_all(golden: Golden) -> dict[str, BookingExpectedBaseline]:
    baselines: dict[str, BookingExpectedBaseline] = {}
    for target in EXPECTED["targets"]:
        snapshot = target_snapshot(golden, target)
        golden.service().calculate_for_target(
            property_id=golden.prop.id,
            data_source_id=golden.source.id,
            target_snapshot_id=snapshot.id,
        )
        stored = golden.expected().get_for_target_snapshot(snapshot.id)
        assert stored is not None
        baselines[target["name"]] = stored
    return baselines


def text(value: object) -> str | None:
    return None if value is None else format(value, ".2f")


def count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- the golden world contains what it must ---------------------------------------------------


def test_the_snapshots_of_the_golden_world_match_the_independent_calculation(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    counts = EXPECTED["counts"]
    stored = list(db_session.scalars(select(BookingSnapshot)))
    assert len(stored) == counts["snapshots"]
    assert sum(s.origin.value == "OBSERVED" for s in stored) == counts["observed_snapshots"]
    lines = sorted(
        f"{s.snapshot_local_date}|{s.stay_date}|{s.origin.value}|{s.rooms_on_books}|{s.uncertain_rooms}"
        for s in stored
    )
    assert (
        hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()
        == EXPECTED["snapshot_grid_sha256"]
    )
    assert golden.prop.slug == "masseria-ninfa"


# --- the expected baselines -------------------------------------------------------------------


def test_every_baseline_matches_the_independently_computed_expected_result(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    baselines = calculate_all(golden)

    for target in EXPECTED["targets"]:
        name = target["name"]
        baseline = baselines[name]
        assert baseline.status.value == target["status"], name
        assert text(baseline.expected_rooms_on_books) == target["expected"], name
        assert text(baseline.expected_lower) == target["lower"], name
        assert text(baseline.expected_upper) == target["upper"], name
        assert text(baseline.iqr) == target["iqr"], name
        assert (
            baseline.sample_size,
            baseline.observed_sample_size,
            baseline.reconstructed_sample_size,
            baseline.rejected_uncertain_count,
        ) == (
            target["sample_size"],
            target["observed_sample_size"],
            target["reconstructed_sample_size"],
            target["rejected_uncertain_count"],
        ), name
        assert text(baseline.confidence_score) == target["confidence_score"], name
        assert (baseline.confidence_band.value if baseline.confidence_band else None) == target[
            "confidence_band"
        ], name
        assert (baseline.target_snapshot_local_date.isoformat(), baseline.lead_time_days) == (
            target["snapshot_date"],
            target["lead_time_days"],
        ), name
        assert baseline.target_stay_date.isoformat() == target["stay_date"], name
        assert baseline.calculation_version == EXPECTED["calculation_version"], name
        assert baseline.method == EXPECTED["method"], name


def test_the_comparables_used_are_exactly_the_expected_ones_in_recency_order(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    baselines = calculate_all(golden)
    snapshots = {s.id: s for s in db_session.scalars(select(BookingSnapshot))}

    for target in EXPECTED["targets"]:
        stored = golden.expected().list_comparables(baselines[target["name"]].id)
        actual = [
            {
                "rank": c.recency_rank,
                "stay_date": snapshots[c.snapshot_id].stay_date.isoformat(),
                "snapshot_date": snapshots[c.snapshot_id].snapshot_local_date.isoformat(),
                "origin": c.origin.value,
                "rooms_on_books": c.rooms_on_books,
            }
            for c in stored
        ]
        assert actual == target["comparables"], target["name"]
        for comparable in stored:  # the copy in the comparable is the snapshot's own value
            snapshot = snapshots[comparable.snapshot_id]
            assert (comparable.rooms_on_books, comparable.origin) == (
                snapshot.rooms_on_books,
                snapshot.origin,
            )


def test_the_golden_world_covers_every_required_situation(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    baselines = calculate_all(golden)
    by_name = {t["name"]: t for t in EXPECTED["targets"]}

    # 1 observed only, 2 observed + reconstructed, 3 insufficient data
    a, c, d = by_name["A"], by_name["C"], by_name["D"]
    assert (a["status"], a["observed_sample_size"], a["reconstructed_sample_size"]) == (
        "READY",
        6,
        0,
    )
    assert c["observed_sample_size"] > 0 and c["reconstructed_sample_size"] > 0
    assert d["status"] == "INSUFFICIENT_DATA" and d["expected"] is None and d["sample_size"] == 4
    # 4 low dispersion, 5 high dispersion
    assert float(a["iqr"]) / float(a["expected"]) < 0.2
    assert float(by_name["B"]["iqr"]) / float(by_name["B"]["expected"]) > 1.5
    assert by_name["B"]["confidence_band"] == "LOW" and a["confidence_band"] == "MEDIUM"
    # 6 zero-room historical values in the sample (12 of 24), with a fractional median
    e = by_name["E"]
    e_rooms = [x["rooms_on_books"] for x in e["comparables"]]
    assert (len(e_rooms), e_rooms.count(0)) == (24, 12)  # 12 zeros among 24 comparables
    assert sorted(e_rooms) == [0] * 12 + [1] * 8 + [2, 2, 3, 6]
    assert (e["expected"], e["lower"], e["upper"], e["iqr"]) == (
        "0.50",  # (x12 + x13) / 2 = (0 + 1) / 2
        "0.00",  # position 5.75 between two zeros
        "1.00",  # position 17.25 between two ones
        "1.00",
    )
    # 7 a reconstruction rejected for uncertainty (and not used)
    assert c["rejected_uncertain_count"] == 2
    used = {x["snapshot_date"] + x["stay_date"] for x in c["comparables"]}
    uncertain = [s for s in db_session.scalars(select(BookingSnapshot)) if s.uncertain_rooms > 0]
    assert len(uncertain) >= 2
    assert not used & {str(s.snapshot_local_date) + str(s.stay_date) for s in uncertain}
    # 8 same weekday but out of season, 9 same season but wrong weekday, 10 wrong lead time:
    # all exist in the database and none of them is used by target A
    a_stay, a_lead = date.fromisoformat(a["stay_date"]), a["lead_time_days"]
    a_used = {(x["snapshot_date"], x["stay_date"]) for x in a["comparables"]}
    stored = list(db_session.scalars(select(BookingSnapshot)))
    out_of_season = [
        s
        for s in stored
        if s.stay_date.weekday() == a_stay.weekday()
        and (s.stay_date - s.snapshot_local_date).days == a_lead
        and s.stay_date.month in (11, 12, 1, 2)
    ]
    wrong_weekday = [
        s
        for s in stored
        if s.stay_date.weekday() == 4
        and s.stay_date.month in (7, 8)
        and (s.stay_date - s.snapshot_local_date).days == a_lead
    ]
    wrong_lead = [s for s in stored if (s.stay_date - s.snapshot_local_date).days in (13, 15)]
    assert out_of_season and wrong_weekday and wrong_lead
    for group in (out_of_season, wrong_weekday, wrong_lead):
        assert not {(str(s.snapshot_local_date), str(s.stay_date)) for s in group} & a_used
    # confidence: the caps, on real numbers
    assert (
        text(baselines["F"].confidence_score) == "65.00"
        and baselines["F"].observed_sample_size == 0
    )
    assert text(baselines["C"].confidence_score) == "85.00"
    # every READY baseline can be explained: comparables == sample size
    for name, baseline in baselines.items():
        assert len(golden.expected().list_comparables(baseline.id)) == baseline.sample_size, name


def test_the_batch_agrees_with_the_single_calculations_and_a_rerun_is_a_no_op(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    baselines = calculate_all(golden)
    target_a = next(t for t in EXPECTED["targets"] if t["name"] == "A")

    rerun = golden.service().calculate_for_snapshot_date(
        property_id=golden.prop.id,
        data_source_id=golden.source.id,
        snapshot_local_date=date.fromisoformat(target_a["snapshot_date"]),
        stay_date_start=date.fromisoformat(target_a["stay_date"]),
        stay_date_end=date.fromisoformat(target_a["stay_date"]),
    )

    assert (rerun.created, rerun.unchanged) == (0, 1)  # the same baseline: idempotent
    assert rerun.baseline_ids == (baselines["A"].id,)
    assert count(db_session, BookingExpectedBaseline) == len(EXPECTED["targets"])


def test_a_golden_baseline_cannot_be_edited(db_session: Session, factory: BookingFactory) -> None:
    golden = build(db_session, factory)
    baselines = calculate_all(golden)
    rejects: Rejects = make_rejects(db_session)

    with rejects(pg.IntegrityConstraintViolation):
        db_session.execute(
            update(BookingExpectedBaseline)
            .where(BookingExpectedBaseline.id == baselines["A"].id)
            .values(expected_rooms_on_books=99)
        )


# --- scope: bookings -> snapshots -> expected, nothing else -----------------------------------


def test_the_expected_phase_writes_only_baselines_and_comparables(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    written = {BookingExpectedBaseline.__tablename__, BookingExpectedComparable.__tablename__}
    tables = {
        mapper.class_.__tablename__: mapper.class_
        for mapper in Base.registry.mappers
        if mapper.class_.__tablename__ not in written
    }
    before = {name: count(db_session, model) for name, model in tables.items()}

    calculate_all(golden)

    assert {name: count(db_session, model) for name, model in tables.items()} == before
    assert count(db_session, BookingExpectedBaseline) == len(EXPECTED["targets"])
    assert count(db_session, BookingExpectedComparable) == sum(
        t["sample_size"] for t in EXPECTED["targets"]
    )


def test_fictional_guest_data_never_reaches_a_snapshot_or_a_baseline(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    calculate_all(golden)
    rows: list[list[str]] = []
    for model in (BookingSnapshot, BookingExpectedBaseline, BookingExpectedComparable):
        columns = [column.name for column in model.__table__.columns]
        rows.extend(
            [str(getattr(entity, name)) for name in columns]
            for entity in db_session.scalars(select(model))
        )
    dump = json.dumps(rows)

    for guest in ("Ospite Storico", "+39 000 90", "Camera Doppia", "Anna Bianchi"):
        assert guest not in dump


def test_the_generator_is_independent_of_the_application_code() -> None:
    source = (FIXTURE_DIR / "generate_masseria_expected_expected.py").read_text(encoding="utf-8")

    assert "from app" not in source and "import app" not in source
    assert "import decimal" not in source and "from decimal" not in source  # exact fractions
    assert "from fractions import Fraction" in source
