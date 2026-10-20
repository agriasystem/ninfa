"""Dati overview: the bookings / occupancy block, the run's states, provenance, freshness, scope.

Every test builds a REAL persisted run (`DecisionService.sync()`), real OBSERVED snapshot rows and
real provenance, then reads the overview back through the real `DecisionMemoryService` - the same
path production takes. Nothing is a hand-built feed.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.ask_ninfa.home_data_service import HomeDataService
from app.modules.ai.ask_ninfa.home_intents import resolve_question
from app.modules.data_overview.service import DataOverviewError, DataOverviewService
from app.modules.data_overview.types import (
    Availability,
    DomainState,
    FreshnessReason,
    NightStatus,
    UnavailableReason,
)
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedState
from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)
from app.modules.decisions.models import Decision, DecisionObservation, DecisionRun
from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.revenue.types import RevenueDecisionType
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from tests.ask_home_support import STAY, five_triggered_evaluations
from tests.data_overview_support import (
    AS_OF,
    full_coverage,
    night_range,
    overview_of,
    seed_run,
    succeeded_import,
    uniform_nights,
    utc,
)
from tests.decision_support import INSUFFICIENT, TRIGGERED, revenue_evaluation
from tests.expected_support import add_snapshots, snapshot_row
from tests.support import BookingFactory, Tenant

D = Decimal


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


# --- the bookings / occupancy block ---------------------------------------------------------------


def test_full_data_gives_today_seven_and_thirty_night_metrics(
    db_session: Session, tenant: Tenant
) -> None:
    nights = {day: (20, 40) for day in night_range(AS_OF, 30)}
    nights[AS_OF] = (29, 40)  # today: 29 of 40 rooms
    seed_run(db_session, tenant, nights=nights)

    occupancy = overview_of(db_session, tenant).occupancy

    assert occupancy.state is Availability.AVAILABLE
    assert occupancy.reason is None
    today, week, month = occupancy.today, occupancy.days_7, occupancy.days_30
    assert today is not None and week is not None and month is not None
    assert (today.room_nights, today.rooms_available, today.occupancy_pct) == (29, 40, D("72.50"))
    # 29 + 6 nights of 20 = 149 rooms over 7 x 40 = 280: 53.21 %
    assert (week.room_nights, week.rooms_available, week.occupancy_pct) == (149, 280, D("53.21"))
    # 29 + 29 nights of 20 = 609 rooms over 30 x 40 = 1200: 50.75 %
    assert (month.room_nights, month.rooms_available, month.occupancy_pct) == (
        609,
        1200,
        D("50.75"),
    )
    assert (today.nights_requested, week.nights_requested, month.nights_requested) == (1, 7, 30)


def test_room_revenue_and_adr_are_the_on_books_figures_of_the_period(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=10, capacity=40, days=7))

    week = overview_of(db_session, tenant, period=7).occupancy.days_7

    assert week is not None
    # the seed helper books each room at 100.00: 7 nights x 10 rooms x 100.00 over 70 room-nights
    assert week.room_revenue == D("7000.00")
    assert week.adr == D("100.00")


def test_the_selected_period_decides_the_selected_block_and_the_night_rows(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40))

    seven = overview_of(db_session, tenant, period=7).occupancy
    thirty = overview_of(db_session, tenant, period=30).occupancy

    assert seven.selected == seven.days_7 and len(seven.nights) == 7
    assert thirty.selected == thirty.days_30 and len(thirty.nights) == 30
    # the three summary periods are always there, whatever the selected one
    assert seven.today is not None and seven.days_30 is not None


def test_a_night_with_an_unknown_capacity_is_left_out_of_the_occupancy_and_is_counted(
    db_session: Session, tenant: Tenant
) -> None:
    nights = uniform_nights(AS_OF, rooms=20, capacity=40, days=7)
    nights[AS_OF + timedelta(days=3)] = (20, None)  # capacity unknown that night
    seed_run(db_session, tenant, nights=nights)

    week = overview_of(db_session, tenant, period=7).occupancy.days_7

    assert week is not None
    assert week.nights_with_data == 7
    assert week.nights_with_capacity == 6
    assert week.occupancy_pct == D("50.00")  # 120 / 240: the unknown night is in neither term
    assert week.room_nights == 140  # but its bookings are real room-nights


def test_every_night_without_a_capacity_means_no_occupancy_percentage(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=12, capacity=None, days=7))

    week = overview_of(db_session, tenant, period=7).occupancy.days_7

    assert week is not None
    assert week.occupancy_pct is None  # never 0 %
    assert week.rooms_available is None
    assert week.room_nights == 84


def test_a_night_without_a_stored_snapshot_is_a_gap_not_a_zero(
    db_session: Session, tenant: Tenant
) -> None:
    nights = uniform_nights(AS_OF, rooms=20, capacity=40, days=7)
    del nights[AS_OF + timedelta(days=2)]
    seed_run(db_session, tenant, nights=nights)

    occupancy = overview_of(db_session, tenant, period=7).occupancy

    gap = occupancy.nights[2]
    assert gap.has_data is False
    assert gap.rooms_on_books is None and gap.occupancy_pct is None
    assert occupancy.days_7 is not None and occupancy.days_7.nights_with_data == 6


def test_only_observed_snapshots_are_read(db_session: Session, tenant: Tenant) -> None:
    nights = uniform_nights(AS_OF, rooms=20, capacity=40, days=3)
    seed_run(db_session, tenant, nights=nights)
    # a night whose only stored row is a reconstruction: approximate by construction, never shown
    reconstructed = AS_OF + timedelta(days=10)
    add_snapshots(
        db_session,
        tenant,
        [
            snapshot_row(
                tenant,
                AS_OF,
                reconstructed,
                rooms=33,
                origin=SnapshotOrigin.RECONSTRUCTED_APPROXIMATE,
            )
        ],
    )

    occupancy = overview_of(db_session, tenant).occupancy

    row = next(night for night in occupancy.nights if night.stay_date == reconstructed)
    assert row.has_data is False


def test_the_source_is_the_runs_own_never_another_booking_source_of_the_property(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7))
    other_source = factory.data_source(tenant.property, DataSourceDomain.BOOKINGS)
    add_snapshots(
        db_session,
        tenant,
        [
            snapshot_row(tenant, AS_OF, day, rooms=39, data_source_id=other_source.id)
            for day in night_range(AS_OF, 7)
        ],
    )

    week = overview_of(db_session, tenant, period=7).occupancy.days_7

    assert week is not None
    assert week.room_nights == 140  # the run's source (20 rooms x 7), not the other source (39)


# --- states: no analysis / no source / no data ---------------------------------------------------


def test_no_run_for_the_day_has_no_booking_figure_and_says_why(
    db_session: Session, tenant: Tenant
) -> None:
    overview = overview_of(db_session, tenant)

    assert overview.feed_state is FeedState.NOT_PROCESSED
    assert overview.occupancy.state is Availability.NOT_AVAILABLE
    assert overview.occupancy.reason is UnavailableReason.NO_ANALYSIS
    assert overview.occupancy.nights == ()
    assert all(state is DomainState.UNKNOWN for state in overview.domain_states.values())
    assert overview.freshness.bookings.known is False


def test_a_previous_run_is_reported_when_today_has_none(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, as_of=AS_OF - timedelta(days=2))

    overview = overview_of(db_session, tenant)

    assert overview.feed_state is FeedState.NOT_PROCESSED
    assert overview.last_successful_analysis is not None
    assert overview.last_successful_analysis.as_of_local_date == AS_OF - timedelta(days=2)


def test_a_run_that_recorded_no_booking_source_has_no_booking_figure(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, 20), with_provenance=False)

    occupancy = overview_of(db_session, tenant).occupancy

    assert occupancy.state is Availability.NOT_AVAILABLE
    assert occupancy.reason is UnavailableReason.NO_BOOKING_SOURCE  # the source is never guessed


def test_a_source_with_no_stored_night_in_the_window_has_no_booking_data(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)  # a run with provenance, but no snapshot at all

    occupancy = overview_of(db_session, tenant).occupancy

    assert occupancy.state is Availability.NOT_AVAILABLE
    assert occupancy.reason is UnavailableReason.NO_BOOKING_DATA


# --- the 7-days-ago comparison --------------------------------------------------------------------


def test_the_comparison_with_seven_days_ago_uses_the_older_observed_snapshot(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=30))
    older = AS_OF - timedelta(days=7)
    # the older snapshot (a week earlier, 30-night horizon) reaches only 22 nights past `AS_OF`
    add_snapshots(
        db_session,
        tenant,
        [
            snapshot_row(tenant, older, day, rooms=15)
            for day in night_range(AS_OF, 23)  # AS_OF .. AS_OF+22
        ],
    )

    occupancy = overview_of(db_session, tenant, period=7).occupancy

    week = occupancy.days_7
    assert week is not None
    assert (week.room_nights_7d_ago, week.room_nights_delta_7d) == (105, 35)  # 7 x 15, 140 - 105
    # the 30-night window is NOT fully covered by the older snapshot: no partial comparison
    assert occupancy.days_30 is not None
    assert occupancy.days_30.room_nights_delta_7d is None
    assert occupancy.nights[0].rooms_on_books_7d_ago == 15


# --- the run's decisions and the nights' status ---------------------------------------------------


def test_nights_targeted_by_a_decision_are_attention_and_link_to_it(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, tenant),
        coverage=full_coverage(),
    )

    overview = overview_of(db_session, tenant)

    by_date = {night.stay_date: night for night in overview.occupancy.nights}
    pickup = by_date[STAY]  # REV_PICKUP_LOW targets 2026-08-15
    occupancy_risk = by_date[AS_OF + timedelta(days=19)]  # REV_OCCUPANCY_RISK targets 2026-08-20
    assert pickup.status is NightStatus.ATTENTION and pickup.decision_id is not None
    assert occupancy_risk.status is NightStatus.ATTENTION and occupancy_risk.decision_id is not None
    assert pickup.decision_id != occupancy_risk.decision_id
    attention = [
        night for night in overview.occupancy.nights if night.status is NightStatus.ATTENTION
    ]
    assert len(attention) == 2  # only the two revenue decisions mark nights


def test_the_decision_list_carries_each_area_and_target_in_the_feeds_own_order(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, tenant),
        coverage=full_coverage(),
    )

    overview = overview_of(db_session, tenant)

    assert {ref.decision_type: ref.domain for ref in overview.decisions} == {
        "REV_PICKUP_LOW": AnalysisDomain.REVENUE,
        "REV_OCCUPANCY_RISK": AnalysisDomain.REVENUE,
        "REV_OTA_DEPENDENCY": AnalysisDomain.DISTRIBUTION,
        "COST_CPOR_ANOMALY": AnalysisDomain.COSTS,
        "LABOR_OVERSTAFFING": AnalysisDomain.LABOR,
    }
    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, AS_OF)
    assert [ref.decision_id for ref in overview.decisions] == [
        item.decision.id for item in feed.items
    ]


def test_a_clean_run_reads_every_night_regular(db_session: Session, tenant: Tenant) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7))

    nights = overview_of(db_session, tenant, period=7).occupancy.nights

    assert {night.status for night in nights} == {NightStatus.REGULAR}


def test_a_run_with_an_inconclusive_check_never_reads_a_night_regular(
    db_session: Session, tenant: Tenant
) -> None:
    inconclusive = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=AS_OF,
        status=INSUFFICIENT,
    )
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7),
        evaluations=[inconclusive],
    )

    overview = overview_of(db_session, tenant, period=7)

    assert overview.feed_state is FeedState.DATA_QUALITY_LIMITED
    assert {night.status for night in overview.occupancy.nights} == {NightStatus.PARTIAL}


def test_a_night_is_attention_even_in_a_data_quality_limited_world(
    db_session: Session, tenant: Tenant
) -> None:
    triggered = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=AS_OF + timedelta(days=2),
        snapshot_local_date=AS_OF,
        decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
        status=TRIGGERED,
    )
    inconclusive = revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        stay_date=STAY,
        snapshot_local_date=AS_OF,
        status=INSUFFICIENT,
    )
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7),
        evaluations=[triggered, inconclusive],
    )

    nights = overview_of(db_session, tenant, period=7).occupancy.nights

    assert nights[2].status is NightStatus.ATTENTION
    assert nights[0].status is NightStatus.PARTIAL


def test_revenue_not_analysed_means_no_night_is_evaluated(
    db_session: Session, tenant: Tenant
) -> None:
    revenue_skipped = AnalysisCoverage(
        domains=tuple(
            DomainCoverage(
                domain,
                DomainCoverageStatus.SKIPPED
                if domain is AnalysisDomain.REVENUE
                else DomainCoverageStatus.EVALUATED,
                DomainSkipReason.NOT_REQUESTED if domain is AnalysisDomain.REVENUE else None,
            )
            for domain in AnalysisDomain
        )
    )
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7),
        coverage=revenue_skipped,
    )

    overview = overview_of(db_session, tenant, period=7)

    # the bookings are real and shown; but nobody analysed revenue, so no night is "regular"
    assert overview.occupancy.state is Availability.AVAILABLE
    assert overview.domain_states[AnalysisDomain.REVENUE] is DomainState.NOT_ANALYZED
    assert {night.status for night in overview.occupancy.nights} == {NightStatus.NOT_EVALUATED}


def test_a_run_without_recorded_coverage_evaluates_nothing(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7),
        unknown_coverage=True,
    )

    overview = overview_of(db_session, tenant, period=7)

    assert overview.coverage is None
    assert {night.status for night in overview.occupancy.nights} == {NightStatus.NOT_EVALUATED}
    assert all(state is DomainState.UNKNOWN for state in overview.domain_states.values())


def test_the_area_states_follow_the_runs_coverage(db_session: Session, tenant: Tenant) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=20, capacity=40, days=7))

    states = overview_of(db_session, tenant).domain_states

    assert states[AnalysisDomain.REVENUE] is DomainState.ANALYZED
    assert states[AnalysisDomain.DISTRIBUTION] is DomainState.ANALYZED
    assert states[AnalysisDomain.COSTS] is DomainState.NOT_ANALYZED  # the automatic policy skips it
    assert states[AnalysisDomain.LABOR] is DomainState.NOT_ANALYZED


# --- freshness ------------------------------------------------------------------------------------


def test_booking_freshness_is_the_runs_own_provenance_fact(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, finished_at=utc(2026, 8, 1, 7, 31))

    freshness = overview_of(db_session, tenant).freshness.bookings

    assert freshness.known is True
    assert freshness.finished_at == utc(2026, 8, 1, 7, 31)
    assert freshness.reason is None


def test_a_source_with_no_successful_import_has_unknown_booking_freshness(
    db_session: Session, tenant: Tenant
) -> None:
    from app.modules.intelligence.priority.types import PriorityContext
    from tests.ask_home_support import unknown_provenance
    from tests.decision_support import sync_run

    context = PriorityContext(tenant.workspace.id, tenant.property.id, AS_OF)
    sync_run(db_session, tenant.context, context, [], None, unknown_provenance())

    freshness = overview_of(db_session, tenant).freshness.bookings

    assert freshness.known is False
    assert freshness.finished_at is None  # never a fabricated timestamp


def test_each_domain_has_its_own_freshness_never_one_timestamp_for_all(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, finished_at=utc(2026, 8, 1, 7, 15))
    cost_source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    labor_source = factory.data_source(tenant.property, DataSourceDomain.LABOR)
    succeeded_import(factory, cost_source, utc(2026, 7, 31, 18, 0))
    succeeded_import(factory, labor_source, utc(2026, 7, 29, 9, 30))

    freshness = overview_of(db_session, tenant).freshness

    assert freshness.bookings.finished_at == utc(2026, 8, 1, 7, 15)
    assert freshness.costs.finished_at == utc(2026, 7, 31, 18, 0)
    assert freshness.labor.finished_at == utc(2026, 7, 29, 9, 30)


def test_a_domain_with_several_sources_has_no_freshness_rather_than_a_guess(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)
    first = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    second = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    succeeded_import(factory, first, utc(2026, 7, 31, 18, 0))
    succeeded_import(factory, second, utc(2026, 7, 30, 18, 0))

    freshness = overview_of(db_session, tenant).freshness

    assert freshness.costs.known is False
    assert freshness.costs.reason is FreshnessReason.SEVERAL_SOURCES  # no property-wide maximum


def test_a_domain_with_no_source_or_no_import_says_which(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)
    factory.data_source(tenant.property, DataSourceDomain.LABOR)  # a source, never imported

    freshness = overview_of(db_session, tenant).freshness

    assert freshness.costs.reason is FreshnessReason.NO_SOURCE
    assert freshness.labor.reason is FreshnessReason.NO_IMPORT


def test_a_failed_import_never_counts_as_fresh(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    from app.modules.ingestion.models import ImportJobStatus

    seed_run(db_session, tenant)
    source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    job = factory.import_job(source)
    job.status = ImportJobStatus.FAILED
    job.finished_at = utc(2026, 8, 1, 6, 0)
    job.error_code = "boom"
    job.error_message = "failed"
    db_session.flush()

    assert overview_of(db_session, tenant).freshness.costs.known is False


# --- scope / safety -------------------------------------------------------------------------------


def test_another_tenant_cannot_read_the_property_at_all(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, 20))
    foreign = factory.tenant()

    with pytest.raises(DataOverviewError):
        DataOverviewService(db_session, foreign.context).overview(tenant.property.id, AS_OF, 30)


def test_a_workspace_that_does_not_exist_reads_nothing(db_session: Session, tenant: Tenant) -> None:
    import uuid

    with pytest.raises(DataOverviewError):
        DataOverviewService(db_session, TenantContext(uuid.uuid4())).overview(
            tenant.property.id, AS_OF, 30
        )


def test_an_archived_property_is_not_readable(db_session: Session, tenant: Tenant) -> None:
    from datetime import UTC, datetime

    tenant.property.archived_at = datetime.now(UTC)
    tenant.property.is_active = False  # the database requires an archived property to be inactive
    db_session.flush()

    with pytest.raises(DataOverviewError):
        overview_of(db_session, tenant)


@pytest.mark.parametrize("period", [0, 1, 14, 31, 365, -7])
def test_only_seven_and_thirty_are_offered(
    db_session: Session, tenant: Tenant, period: int
) -> None:
    with pytest.raises(DataOverviewError):
        overview_of(db_session, tenant, period=period)


def test_the_overview_writes_nothing(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, tenant),
        coverage=full_coverage(),
    )
    tables = (DecisionRun, Decision, DecisionObservation, BookingSnapshot)

    def counts() -> list[int]:
        return [
            int(db_session.scalar(select(func.count()).select_from(model)) or 0) for model in tables
        ]

    before = counts()
    overview_of(db_session, tenant)
    overview_of(db_session, tenant, period=7)

    assert counts() == before  # no sync(), no snapshot, no run: a pure projection


def test_the_overview_is_deterministic(db_session: Session, tenant: Tenant) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=17, capacity=40))

    assert overview_of(db_session, tenant) == overview_of(db_session, tenant)


# --- Dati and Mia never disagree ------------------------------------------------------------------


def test_the_figures_equal_the_ones_mias_semantic_layer_states(
    db_session: Session, tenant: Tenant
) -> None:
    """Dati re-implements ~20 lines of aggregation without importing Mia's code. This pins that both
    give the same occupancy, room revenue and ADR for the same stored snapshots."""
    from zoneinfo import ZoneInfo

    nights: dict[date, tuple[int, int | None]] = {
        day: (10 + index % 9, 40) for index, day in enumerate(night_range(AS_OF, 30))
    }
    nights[AS_OF + timedelta(days=4)] = (12, None)  # a night with an unknown capacity
    seed_run(db_session, tenant, nights=nights)

    overview = overview_of(db_session, tenant)
    feed = DecisionMemoryService(db_session, tenant.context).get_feed(tenant.property.id, AS_OF)
    resolution = resolve_question(
        "Qual è l'occupazione e quanti ricavi nei prossimi 7 giorni?", (), AS_OF
    )
    context = HomeDataService(db_session, tenant.context).collect(
        resolution,
        feed,
        property_id=tenant.property.id,
        timezone=ZoneInfo("Europe/Rome"),
        currency=tenant.property.currency,
    )
    values = {point.label: point.value for section in context.sections for point in section.data}
    week = overview.occupancy.days_7
    assert week is not None
    assert values["Occupazione sulle prenotazioni attuali"] == str(week.occupancy_pct)
    assert values["Ricavi camera sulle prenotazioni attuali"] == str(week.room_revenue)
    assert values["Tariffa media per camera-notte sulle prenotazioni attuali"] == str(week.adr)
    assert values["Camere prenotate (notti con capienza nota)"] == str(
        week.rooms_on_books_with_capacity
    )
