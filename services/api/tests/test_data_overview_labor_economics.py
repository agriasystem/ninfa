"""Dati > Personale: what the planned labor weighs, computed once, here, on exact values.

Every figure is a plain division of stored facts, and every ratio compares the SAME days: labor
of one week never meets the revenue of another. What cannot be compared is absent, with a stated
reason, never a zero and never a figure from another period.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.modules.data_overview.labor import economics_of, hourly_cost, percent_of_amount
from app.modules.data_overview.types import Availability, LaborRevenueGap
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportFile, ImportJob
from app.modules.labor.models import LaborSnapshot
from app.modules.labor.roles import LaborCategory
from tests.data_overview_support import AS_OF, overview_of, seed_run
from tests.labor_support import labor_entry, labor_snapshot
from tests.support import BookingFactory, Tenant

D = Decimal
DAY_2 = AS_OF + timedelta(days=1)


def _economics(**overrides: object) -> object:
    values: dict[str, object] = {
        "days_with_hours": {AS_OF},
        "minutes": 480,
        "cost": D("120.00"),
        "has_incomplete_days": False,
        "revenue_by_day": {AS_OF: D("400.00")},
    }
    values.update(overrides)
    return economics_of(**values)  # type: ignore[arg-type]


# --- the arithmetic ---------------------------------------------------------------------------


def test_the_three_ratios_are_exact_divisions_of_the_same_days() -> None:
    economics = economics_of(
        days_with_hours={AS_OF, DAY_2},
        minutes=1500,  # 25 h
        cost=D("384.25"),
        has_incomplete_days=False,
        revenue_by_day={AS_OF: D("900.00"), DAY_2: D("539.00"), AS_OF + timedelta(days=5): D("1")},
    )

    assert economics.planned_hours == D("25.00")
    assert economics.planned_cost == D("384.25")
    assert economics.average_hourly_cost == D("15.37")  # 384.25 / 25
    assert economics.reference_revenue == D("1439.00")  # only the two days with hours
    assert economics.cost_to_revenue_pct == D("26.70")  # 384.25 / 1439 * 100, half up
    assert economics.revenue_per_hour == D("57.56")  # 1439 / 25
    assert (economics.period_start, economics.period_end, economics.period_days) == (
        AS_OF,
        DAY_2,
        2,
    )
    assert economics.revenue_gap is None


def test_rates_are_taken_from_the_exact_minutes_not_from_rounded_hours() -> None:
    # 100 minutes are 1.666... hours: rounding them first would give 60.24
    assert hourly_cost(D("100.00"), 100) == D("60.00")


def test_decimal_precision_never_goes_through_a_float() -> None:
    economics = economics_of(
        days_with_hours={AS_OF},
        minutes=60 * 3,
        cost=D("0.10"),
        has_incomplete_days=False,
        revenue_by_day={AS_OF: D("0.30")},
    )

    assert economics.average_hourly_cost == D("0.03")
    assert economics.cost_to_revenue_pct == D("33.33")
    assert economics.revenue_per_hour == D("0.10")


def test_a_share_with_no_whole_is_absent_not_zero() -> None:
    assert percent_of_amount(D("10"), D("0")) is None
    assert percent_of_amount(D("10"), None) is None
    assert percent_of_amount(None, D("10")) is None


# --- what cannot be compared is absent, and says why ---------------------------------------------


def test_zero_hours_have_no_rate_and_no_period() -> None:
    economics = _economics(minutes=0)

    assert economics.planned_hours is None  # type: ignore[attr-defined]
    assert economics.average_hourly_cost is None  # type: ignore[attr-defined]
    assert economics.revenue_per_hour is None  # type: ignore[attr-defined]
    assert economics.revenue_gap is LaborRevenueGap.NO_LABOR  # type: ignore[attr-defined]


def test_zero_revenue_gives_no_ratio_but_hours_and_costs_stay() -> None:
    economics = _economics(revenue_by_day={AS_OF: D("0.00")})

    assert economics.revenue_gap is LaborRevenueGap.NO_REVENUE  # type: ignore[attr-defined]
    assert economics.reference_revenue is None  # type: ignore[attr-defined]
    assert economics.cost_to_revenue_pct is None  # type: ignore[attr-defined]
    assert economics.revenue_per_hour is None  # type: ignore[attr-defined]
    assert economics.planned_hours == D("8.00")  # type: ignore[attr-defined]
    assert economics.average_hourly_cost == D("15.00")  # type: ignore[attr-defined]


def test_with_no_observation_of_the_bookings_there_is_no_revenue_at_all() -> None:
    economics = _economics(revenue_by_day=None)

    assert economics.revenue_gap is LaborRevenueGap.NO_ANALYSIS  # type: ignore[attr-defined]
    assert economics.reference_revenue is None  # type: ignore[attr-defined]


def test_a_day_with_hours_and_no_revenue_stored_blocks_the_comparison() -> None:
    economics = _economics(
        days_with_hours={AS_OF, DAY_2},
        revenue_by_day={AS_OF: D("400.00")},  # nothing stored for the second day: not a zero
    )

    assert economics.revenue_gap is LaborRevenueGap.PERIOD_NOT_COVERED  # type: ignore[attr-defined]
    assert economics.cost_to_revenue_pct is None  # type: ignore[attr-defined]


def test_revenue_of_other_days_alone_is_never_compared() -> None:
    """Labor of one week, revenue of another: the forbidden comparison of the brief."""
    economics = _economics(revenue_by_day={AS_OF - timedelta(days=30): D("9000.00")})

    assert economics.revenue_gap is LaborRevenueGap.PERIOD_NOT_COVERED  # type: ignore[attr-defined]
    assert economics.reference_revenue is None  # type: ignore[attr-defined]


def test_part_of_the_plan_without_hours_would_flatter_the_ratio_so_there_is_none() -> None:
    economics = _economics(has_incomplete_days=True)

    assert economics.revenue_gap is LaborRevenueGap.LABOR_INCOMPLETE  # type: ignore[attr-defined]
    assert economics.cost_to_revenue_pct is None  # type: ignore[attr-defined]


def test_an_unknown_cost_leaves_the_revenue_per_hour_but_no_incidence() -> None:
    economics = _economics(cost=None)

    assert economics.planned_cost is None  # type: ignore[attr-defined]
    assert economics.average_hourly_cost is None  # type: ignore[attr-defined]
    assert economics.cost_to_revenue_pct is None  # type: ignore[attr-defined]
    assert economics.revenue_per_hour == D("50.00")  # type: ignore[attr-defined]


# --- on stored data ------------------------------------------------------------------------------


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


def _labor_world(
    factory: BookingFactory, tenant: Tenant
) -> tuple[DataSource, ImportJob, ImportFile]:
    source = factory.data_source(tenant.property, DataSourceDomain.LABOR)
    job = factory.import_job(source)
    return source, job, factory.import_file(job)


def _shift(
    factory: BookingFactory,
    snapshot: LaborSnapshot,
    day: date,
    category: LaborCategory,
    minutes: int | None,
    cost: str | None,
    row: int,
    *,
    actual: int | None = None,
) -> None:
    labor_entry(
        factory,
        snapshot,
        work_date=day,
        labor_category=category,
        planned_minutes=minutes,
        actual_minutes=actual,
        planned_cost=None if cost is None else D(cost),
        currency=None if cost is None else "EUR",
        source_row_number=row,
    )


def _nights(rooms: dict[date, int]) -> dict[date, tuple[int, int | None]]:
    """Stored nights with these rooms on the books: a room is 100.00 of revenue (the fixture's)."""
    return {day: (count, 40) for day, count in rooms.items()}


def _plan(factory: BookingFactory, tenant: Tenant) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _shift(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, "120.00", 1)
    _shift(factory, snapshot, DAY_2, LaborCategory.HOUSEKEEPING, 240, "60.00", 2)
    _shift(factory, snapshot, AS_OF, LaborCategory.FRONT_OFFICE, 360, "120.00", 3)


def test_the_overview_compares_the_plan_with_the_revenue_of_its_own_days(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _plan(factory, tenant)
    seed_run(
        db_session,
        tenant,
        nights=_nights({AS_OF: 6, DAY_2: 4, AS_OF + timedelta(days=3): 90}),
    )

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.AVAILABLE
    economics = labor.economics
    assert economics.planned_hours == D("18.00")  # (480 + 240 + 360) / 60
    assert economics.planned_cost == D("300.00")
    assert economics.average_hourly_cost == D("16.67")
    assert economics.reference_revenue == D("1000.00")  # the night of day 4 has no hours
    assert economics.cost_to_revenue_pct == D("30.00")
    assert economics.revenue_per_hour == D("55.56")


def test_a_role_has_its_share_and_its_incidence_never_revenue_of_its_own(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _plan(factory, tenant)
    seed_run(db_session, tenant, nights=_nights({AS_OF: 6, DAY_2: 4}))

    rows = {row.category: row for row in overview_of(db_session, tenant).labor.categories}

    housekeeping = rows["HOUSEKEEPING"]
    assert housekeeping.planned_hours == D("12.00")
    assert housekeeping.planned_cost == D("180.00")
    assert housekeeping.average_hourly_cost == D("15.00")
    assert housekeeping.cost_share_pct == D("60.00")  # 180 / 300
    assert housekeeping.revenue_incidence_pct == D("18.00")  # 180 / 1000
    assert housekeeping.days_complete == 2
    assert not hasattr(housekeeping, "revenue_per_hour")
    assert rows["FRONT_OFFICE"].cost_share_pct == D("40.00")


def test_with_no_analysis_yet_hours_and_costs_are_there_and_revenue_is_not_invented(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    _plan(factory, tenant)

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.AVAILABLE
    assert labor.economics.planned_hours == D("18.00")
    assert labor.economics.planned_cost == D("300.00")
    assert labor.economics.reference_revenue is None
    assert labor.economics.cost_to_revenue_pct is None
    assert labor.economics.revenue_per_hour is None
    assert labor.economics.revenue_gap is LaborRevenueGap.NO_ANALYSIS
    assert labor.categories[0].revenue_incidence_pct is None
    assert labor.categories[0].cost_share_pct is not None  # a share of labor needs no revenue


def test_a_cost_in_another_currency_makes_the_total_unknown_not_partial(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _shift(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, "120.00", 1)
    labor_entry(
        factory,
        snapshot,
        work_date=AS_OF,
        labor_category=LaborCategory.KITCHEN,
        planned_minutes=480,
        actual_minutes=None,
        planned_cost=D("99.00"),
        currency="USD",
        source_row_number=2,
    )

    economics = overview_of(db_session, tenant).labor.economics

    assert economics.planned_hours == D("16.00")
    assert economics.planned_cost is None
    assert economics.average_hourly_cost is None


def test_an_incomplete_day_is_left_out_of_the_hours_and_stops_the_ratios(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _shift(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, "120.00", 1)
    _shift(factory, snapshot, AS_OF, LaborCategory.KITCHEN, None, None, 2, actual=60)
    seed_run(db_session, tenant, nights=_nights({AS_OF: 6}))

    economics = overview_of(db_session, tenant).labor.economics

    assert economics.planned_hours == D("8.00")
    assert economics.revenue_gap is LaborRevenueGap.LABOR_INCOMPLETE
    assert economics.cost_to_revenue_pct is None


def test_another_tenants_labor_and_revenue_are_invisible(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    other = factory.tenant()
    _plan(factory, other)
    seed_run(db_session, other, nights=_nights({AS_OF: 6, DAY_2: 4}))

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.NOT_AVAILABLE
    assert labor.economics.planned_hours is None
    assert labor.economics.reference_revenue is None
    assert overview_of(db_session, other).labor.economics.reference_revenue == D("1000.00")


# --- a plan that covers only some of the days -------------------------------------------------


def test_a_plan_of_one_day_in_a_week_is_compared_with_that_day_alone_and_says_so(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    """The real pilot case: the labor file covers one day of the seven. Every figure is what it has
    always been (hours, cost, ratios, the revenue of that day alone), and the response says how many
    days they are about, out of how many."""
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _shift(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, "120.00", 1)
    _shift(factory, snapshot, AS_OF, LaborCategory.FRONT_OFFICE, 360, "100.00", 2)
    # revenue is stored for every night of the week: the six days with no plan must not enter it
    seed_run(db_session, tenant, nights=_nights({AS_OF + timedelta(days=n): 10 for n in range(7)}))

    labor = overview_of(db_session, tenant).labor

    assert labor.window_days == 7
    assert labor.days_with_data == 1
    economics = labor.economics
    assert economics.period_days == 1
    assert (economics.period_start, economics.period_end) == (AS_OF, AS_OF)
    assert economics.planned_hours == D("14.00")
    assert economics.planned_cost == D("220.00")
    assert economics.reference_revenue == D("1000.00")  # that day's 10 rooms, not the week's 7000
    assert economics.cost_to_revenue_pct == D("22.00")  # 220 / 1000, as ever
    assert economics.revenue_per_hour == D("71.43")  # 1000 / 14, as ever


def test_a_plan_of_the_whole_week_covers_every_day_of_the_window(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    for number in range(7):
        _shift(
            factory,
            snapshot,
            AS_OF + timedelta(days=number),
            LaborCategory.HOUSEKEEPING,
            480,
            "120.00",
            number + 1,
        )
    seed_run(db_session, tenant, nights=_nights({AS_OF + timedelta(days=n): 10 for n in range(7)}))

    labor = overview_of(db_session, tenant).labor

    assert labor.economics.period_days == labor.window_days == 7
    assert labor.economics.reference_revenue == D("7000.00")


def test_a_day_with_an_incomplete_plan_is_data_but_not_a_covered_day(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    """Two days have entries, only one has hours: the figures are about one day, and it says so."""
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _shift(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, "120.00", 1)
    # worked hours with no planned ones: the day has data, and no plan to count
    _shift(factory, snapshot, DAY_2, LaborCategory.HOUSEKEEPING, None, None, 2, actual=60)
    seed_run(db_session, tenant, nights=_nights({AS_OF: 10, DAY_2: 10}))

    labor = overview_of(db_session, tenant).labor

    assert labor.days_with_data == 2
    assert labor.economics.period_days == 1
