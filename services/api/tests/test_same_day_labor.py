"""Several staff files on one day: they live together, replace each other by a stated rule, and
never add up. REAL commits, read back through what the page and the detector read."""

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.analysis import AnalysisUpdateState
from app.modules.data_overview.labor import LaborOverviewReader
from app.modules.data_overview.types import Availability
from app.modules.decisions.models import DecisionRun
from app.modules.decisions.provenance import RunInputProvenance
from app.modules.ingestion.models import DataSourceDomain, ImportJob, ImportJobStatus
from app.modules.intelligence.labor.repository import LaborEvaluationRepository
from app.modules.labor.models import LaborEntry, LaborSnapshot
from app.modules.labor.repository import LaborEntryRepository, LaborSnapshotRepository
from app.modules.labor.roles import LaborCategory
from tests.refresh_support import Hotel, booking_row, local_today, make_hotel, purge


@pytest.fixture
def hotel(db_engine: Engine, tmp_path: Any) -> Iterator[Hotel]:
    built = make_hotel(db_engine, tmp_path)
    yield built
    purge(db_engine, built.tenant.workspace_id)


def day(offset: int) -> Any:
    return local_today() + timedelta(days=offset)


def week(
    first_offset: int, *, category: str = "FRONT_OFFICE", hours: str = "8", cost: str = "120.00"
) -> list[tuple[Any, str, str, str]]:
    return [(day(first_offset + index), category, hours, cost) for index in range(7)]


def snapshots(hotel: Hotel) -> list[LaborSnapshot]:
    with hotel.session() as session:
        return list(
            session.scalars(
                select(LaborSnapshot)
                .where(LaborSnapshot.workspace_id == hotel.tenant.workspace_id)
                .order_by(LaborSnapshot.snapshot_local_date, LaborSnapshot.revision)
            ).all()
        )


def entries_stored(hotel: Hotel) -> int:
    with hotel.session() as session:
        return len(
            session.scalars(
                select(LaborEntry.id).where(LaborEntry.workspace_id == hotel.tenant.workspace_id)
            ).all()
        )


def latest_job(hotel: Hotel) -> ImportJob:
    with hotel.session() as session:
        job = session.scalar(
            select(ImportJob)
            .where(
                ImportJob.workspace_id == hotel.tenant.workspace_id,
                ImportJob.status == ImportJobStatus.SUCCEEDED,
            )
            .order_by(ImportJob.finished_at.desc())
            .limit(1)
        )
    assert job is not None
    return job


def plan(hotel: Hotel, offsets: range) -> dict[Any, tuple[Any, list[Any]]]:
    with hotel.session() as session:
        return LaborEvaluationRepository(session, hotel.tenant).current_plan(
            hotel.source(DataSourceDomain.LABOR),
            local_today(),
            [day(offset) for offset in offsets],
        )


def hours_of(hotel: Hotel, offset: int) -> dict[LaborCategory, int]:
    totals: dict[LaborCategory, int] = {}
    for entry in plan(hotel, range(offset, offset + 1))[day(offset)][1]:
        totals[entry.labor_category] = (
            totals.get(entry.labor_category, 0) + (entry.planned_minutes or 0)
        ) // 60
    return totals


def personale(hotel: Hotel) -> Any:
    """What Dati > Personale reads: the next seven days of the source."""
    with hotel.session() as session:
        return LaborOverviewReader(session, hotel.tenant).read(
            as_of=local_today(),
            currency="EUR",
            source_id=hotel.source(DataSourceDomain.LABOR),
            source_reason=None,
            labor_decision=None,
        )


# --- case A: different weeks ---------------------------------------------------------------------


def test_two_different_weeks_the_same_day_live_side_by_side(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    hotel.import_shifts("b.csv", week(7))

    assert [snapshot.revision for snapshot in snapshots(hotel)] == [1, 2]
    assert plan(hotel, range(0, 14)).keys() == {day(offset) for offset in range(14)}
    assert hours_of(hotel, 3) == {LaborCategory.FRONT_OFFICE: 8}
    assert hours_of(hotel, 10) == {LaborCategory.FRONT_OFFICE: 8}
    assert latest_job(hotel).changed_data is True


def test_two_weeks_do_not_change_each_others_figures(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    figures = personale(hotel).economics

    hotel.import_shifts("b.csv", week(7))

    after = personale(hotel).economics
    assert after.planned_hours == figures.planned_hours == Decimal("56.00")
    assert after.planned_cost == figures.planned_cost == Decimal("840.00")


# --- case B: a second version of the same week ---------------------------------------------------


def test_a_second_version_of_a_week_replaces_it_and_hours_and_costs_never_add_up(
    hotel: Hotel,
) -> None:
    hotel.import_shifts("a.csv", week(0))
    hotel.import_shifts("a-v2.csv", week(0, hours="6", cost="90.00"))

    view = personale(hotel)
    assert view.state is Availability.AVAILABLE
    assert view.economics.planned_hours == Decimal("42.00")  # 7 x 6, never 7 x 14
    assert view.economics.planned_cost == Decimal("630.00")
    assert hours_of(hotel, 0) == {LaborCategory.FRONT_OFFICE: 6}


def test_the_replaced_version_stays_with_the_import_that_brought_it(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    job_a = latest_job(hotel).id
    hotel.import_shifts("a-v2.csv", week(0, hours="6"))
    job_b = latest_job(hotel).id

    first, second = snapshots(hotel)

    assert (first.revision, first.source_import_job_id) == (1, job_a)
    assert (second.revision, second.source_import_job_id) == (2, job_b)
    assert entries_stored(hotel) == 14  # nothing deleted
    with hotel.session() as session:
        kept = LaborEntryRepository(session, hotel.tenant).list_for_snapshot(first.id)
        counting = plan(hotel, range(0, 1))[day(0)]
    assert {entry.planned_minutes for entry in kept} == {480}  # what the first file said
    assert counting[0] == second.id  # what counts now


def test_going_back_to_the_first_version_is_a_change_and_not_a_no_op(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    hotel.import_shifts("a-v2.csv", week(0, hours="6"))

    hotel.import_shifts("a-again.csv", week(0))

    assert latest_job(hotel).changed_data is True
    assert [snapshot.revision for snapshot in snapshots(hotel)] == [1, 2, 3]
    assert hours_of(hotel, 0) == {LaborCategory.FRONT_OFFICE: 8}


# --- case C: files that overlap ------------------------------------------------------------------


def test_overlapping_files_share_the_days_by_the_stated_rule(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))  # days 0..6, 8 hours
    hotel.import_shifts("b.csv", week(4, hours="6"))  # days 4..10, 6 hours

    assert hours_of(hotel, 3) == {LaborCategory.FRONT_OFFICE: 8}
    assert hours_of(hotel, 4) == {LaborCategory.FRONT_OFFICE: 6}
    assert hours_of(hotel, 6) == {LaborCategory.FRONT_OFFICE: 6}
    assert hours_of(hotel, 10) == {LaborCategory.FRONT_OFFICE: 6}
    # the seven days of Personale: 4 x 8 + 3 x 6, with nothing counted twice
    assert personale(hotel).economics.planned_hours == Decimal("50.00")


def test_an_overlap_leaves_the_departments_the_new_file_does_not_name(hotel: Hotel) -> None:
    both = [*week(0), *week(0, category="HOUSEKEEPING", hours="5", cost="60.00")]
    hotel.import_shifts("a.csv", both)

    hotel.import_shifts("b.csv", week(4, hours="6"))  # Reception only

    assert hours_of(hotel, 5) == {LaborCategory.FRONT_OFFICE: 6, LaborCategory.HOUSEKEEPING: 5}


def test_separate_files_per_department_on_the_same_week_are_all_kept(hotel: Hotel) -> None:
    hotel.import_shifts("reception.csv", week(0))
    hotel.import_shifts("housekeeping.csv", week(0, category="HOUSEKEEPING", hours="5"))

    assert hours_of(hotel, 2) == {LaborCategory.FRONT_OFFICE: 8, LaborCategory.HOUSEKEEPING: 5}
    assert len(snapshots(hotel)) == 2


def test_a_correction_that_drops_a_department_on_a_day_takes_it_off_that_day(hotel: Hotel) -> None:
    hotel.import_shifts(
        "a.csv",
        [
            (day(0), "FRONT_OFFICE", "8", "100.00"),
            (day(0), "SPA_WELLNESS", "4", "50.00"),
            (day(1), "FRONT_OFFICE", "8", "100.00"),
            (day(1), "SPA_WELLNESS", "4", "50.00"),
        ],
    )

    hotel.import_shifts(
        "b.csv",
        [
            (day(0), "FRONT_OFFICE", "8", "100.00"),
            (day(1), "FRONT_OFFICE", "8", "100.00"),
            (day(1), "SPA_WELLNESS", "4", "50.00"),
        ],
    )

    assert hours_of(hotel, 0) == {LaborCategory.FRONT_OFFICE: 8}
    assert hours_of(hotel, 1) == {LaborCategory.FRONT_OFFICE: 8, LaborCategory.SPA_WELLNESS: 4}


# --- case D: the same data again -----------------------------------------------------------------


def test_the_same_file_again_is_a_no_op(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    stored = entries_stored(hotel)

    hotel.import_shifts("a-again.csv", week(0))

    assert latest_job(hotel).changed_data is False
    assert len(snapshots(hotel)) == 1
    assert entries_stored(hotel) == stored


def test_the_same_plan_in_another_order_is_a_no_op(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))

    hotel.import_shifts("shuffled.csv", list(reversed(week(0))))

    assert latest_job(hotel).changed_data is False
    assert len(snapshots(hotel)) == 1


def test_a_file_that_repeats_part_of_what_counts_is_a_no_op(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))

    hotel.import_shifts("three-days.csv", week(0)[:3])

    assert latest_job(hotel).changed_data is False
    assert len(snapshots(hotel)) == 1


def test_the_first_of_two_weeks_again_is_a_no_op_too(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    hotel.import_shifts("b.csv", week(7))

    hotel.import_shifts("a-again.csv", week(0))

    assert latest_job(hotel).changed_data is False
    assert len(snapshots(hotel)) == 2


def test_the_same_data_the_next_day_is_a_no_op_as_well(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))

    hotel.import_shifts("a-again.csv", week(0), on=day(1))

    assert latest_job(hotel).changed_data is False
    assert len(snapshots(hotel)) == 1


def test_identical_data_does_not_say_new_data(hotel: Hotel) -> None:
    hotel.import_bookings("b.csv", [booking_row("A", 3)])
    hotel.import_shifts("a.csv", week(0))
    hotel.refresh()
    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE

    hotel.import_shifts("a-again.csv", week(0))

    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE


# --- the snapshot date stays what it was ----------------------------------------------------------


def test_a_file_dated_earlier_does_not_speak_for_what_came_after_it(hotel: Hotel) -> None:
    """Knowledge is dated: as of yesterday, today's file did not exist yet."""
    hotel.import_shifts("today.csv", week(0, hours="6"))
    hotel.import_shifts("yesterday.csv", week(0), on=day(-1))

    with hotel.session() as session:
        as_of_yesterday = LaborEvaluationRepository(session, hotel.tenant).current_plan(
            hotel.source(DataSourceDomain.LABOR), day(-1), [day(0)]
        )
    assert as_of_yesterday[day(0)][1][0].planned_minutes == 480
    assert hours_of(hotel, 0) == {LaborCategory.FRONT_OFFICE: 6}


def test_two_revisions_get_the_next_number_each_within_their_own_day(hotel: Hotel) -> None:
    hotel.import_shifts("a.csv", week(0))
    hotel.import_shifts("b.csv", week(7))
    hotel.import_shifts("c.csv", week(14), on=day(1))

    assert [(s.snapshot_local_date, s.revision) for s in snapshots(hotel)] == [
        (day(0), 1),
        (day(0), 2),
        (day(1), 1),
    ]
    with hotel.session() as session:
        latest = LaborSnapshotRepository(session, hotel.tenant).get_by_identity(
            hotel.source(DataSourceDomain.LABOR), day(0)
        )
    assert latest is not None and latest.revision == 2


# --- isolation, and what the analysis says it read ------------------------------------------------


def test_files_of_one_hotel_never_touch_another(
    hotel: Hotel, db_engine: Engine, tmp_path: Any
) -> None:
    other = make_hotel(db_engine, tmp_path, name="Hotel Altro")
    try:
        other.import_shifts("x.csv", week(0, hours="3"))
        hotel.import_shifts("a.csv", week(0))
        hotel.import_shifts("a-v2.csv", week(0, hours="6"))

        assert [snapshot.revision for snapshot in snapshots(other)] == [1]
        assert hours_of(other, 0) == {LaborCategory.FRONT_OFFICE: 3}
        with other.session() as session:
            foreign = LaborEvaluationRepository(session, other.tenant).current_plan(
                hotel.source(DataSourceDomain.LABOR), local_today(), [day(0)]
            )
        assert foreign == {}
    finally:
        purge(db_engine, other.tenant.workspace_id)


def test_the_run_says_which_import_and_which_files_it_read(hotel: Hotel) -> None:
    hotel.import_bookings("b.csv", [booking_row("A", 1)])
    hotel.import_shifts("a.csv", week(0))
    hotel.refresh()
    job_a = latest_job(hotel).id
    hotel.import_shifts("a-v2.csv", week(0, hours="6"))
    job_b = latest_job(hotel).id
    hotel.refresh()

    first_file, second_file = snapshots(hotel)
    with Session(hotel.engine) as session:
        runs = list(
            session.scalars(
                select(DecisionRun)
                .where(DecisionRun.workspace_id == hotel.tenant.workspace_id)
                .order_by(DecisionRun.run_sequence)
            ).all()
        )
    assert len(runs) == 2
    assert runs[0].input_provenance is not None and runs[1].input_provenance is not None
    a = RunInputProvenance.from_json(runs[0].input_provenance).labor
    b = RunInputProvenance.from_json(runs[1].input_provenance).labor
    assert a is not None and b is not None
    assert (a.import_job_id, a.snapshot_ids) == (job_a, (first_file.id,))
    assert (b.import_job_id, b.snapshot_ids) == (job_b, (second_file.id,))


def test_a_second_file_on_the_same_day_brings_the_analysis_up_to_date(hotel: Hotel) -> None:
    hotel.import_bookings("b.csv", [booking_row("A", 1)])
    hotel.import_shifts("a.csv", week(0))
    hotel.refresh()

    hotel.import_shifts("b.csv", week(7))

    assert hotel.status().state is AnalysisUpdateState.NEW_DATA
    outcome = hotel.refresh()
    assert outcome.result.is_idempotent_replay is False
    assert hotel.status().state is AnalysisUpdateState.UP_TO_DATE
