"""Dati overview: the Costi and Personale blocks.

Costs are Cost CPOR V1's own: the signed `line_total` of the canonical invoice lines by INVOICE
DATE of the last CONCLUDED calendar month, in the property's currency, never converted; the cost
per occupied room is that module's own metric. Labor is the canonical planned hours of the next 7
days of the property's ONE active labor source. Nothing is estimated: what cannot be calculated is
`None` with a reason, never a zero.
"""

from dataclasses import fields, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.data_overview.types import (
    Availability,
    CporStatus,
    LaborCategoryRow,
    UnavailableReason,
)
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportFile, ImportJob
from app.modules.intelligence.costs.types import CostDecisionEvaluation
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import DocumentKind
from app.modules.labor.models import LaborSnapshot
from app.modules.labor.roles import LaborCategory
from tests.ask_home_support import five_triggered_evaluations
from tests.cost_support import CostWorld, month
from tests.data_overview_support import (
    AS_OF,
    full_coverage,
    overview_of,
    seed_run,
    uniform_nights,
)
from tests.labor_support import labor_entry, labor_snapshot
from tests.support import BookingFactory, Tenant

D = Decimal
LAUNDRY, UTILITIES, FOOD, OTHER = (
    CostCategory.LAUNDRY,
    CostCategory.UTILITIES,
    CostCategory.FOOD,
    CostCategory.OTHER,
)
JULY, JUNE = month(2026, 7), month(2026, 6)  # AS_OF is 2026-08-01: July is the last concluded month


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


def _run(db_session: Session, world: CostWorld, **kwargs: Any) -> None:
    seed_run(db_session, world.tenant, **kwargs)


# --- costs ----------------------------------------------------------------------------------------


def test_the_cost_of_the_last_concluded_month_is_the_signed_sum_by_invoice_date(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "800.00"), (UTILITIES, "1200.00")])
    world.invoice(date(2026, 7, 20), [(LAUNDRY, "-100.00")], kind=DocumentKind.CREDIT_NOTE)
    world.invoice(date(2026, 7, 28), [(OTHER, "100.00")])
    world.invoice(date(2026, 6, 15), [(LAUNDRY, "1000.00")])
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.state is Availability.AVAILABLE
    assert (costs.month_start, costs.month_end) == (date(2026, 7, 1), date(2026, 7, 31))
    assert costs.total_net_cost == D("2000.00")  # 800 - 100 + 1200 + 100
    assert costs.previous_total_net_cost == D("1000.00")
    assert costs.delta_pct == D("100.00")  # (2000 - 1000) / 1000
    assert {row.category: row.net_cost for row in costs.categories} == {
        "UTILITIES": D("1200.00"),
        "LAUNDRY": D("700.00"),  # the credit note is already negative and is never re-signed
        "OTHER": D("100.00"),
    }
    assert [row.category for row in costs.categories] == ["UTILITIES", "LAUNDRY", "OTHER"]


def test_the_month_in_progress_is_never_shown(db_session: Session, world: CostWorld) -> None:
    world.invoice(date(2026, 7, 10), [(LAUNDRY, "500.00")])
    world.invoice(date(2026, 8, 1), [(LAUNDRY, "9999.00")])  # invoices of the month that has begun
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.total_net_cost == D("500.00")


def test_a_month_without_invoices_is_not_a_zero_cost(db_session: Session, world: CostWorld) -> None:
    world.invoice(date(2026, 6, 15), [(LAUNDRY, "1000.00")])  # only June exists
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.state is Availability.NOT_AVAILABLE
    assert costs.reason is UnavailableReason.NO_DATA
    assert costs.total_net_cost is None  # nothing was invoiced: that is not "0 euro"
    assert costs.categories == ()


def test_only_the_properties_currency_is_summed_and_other_currencies_are_flagged(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 5), [(LAUNDRY, "300.00")])
    world.invoice(date(2026, 7, 6), [(LAUNDRY, "7777.00")], currency="USD")
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.currency == "EUR"
    assert costs.total_net_cost == D("300.00")  # NINFA never converts a currency
    assert costs.other_currencies_present is True


def test_a_property_with_only_foreign_currency_costs_has_no_figure_but_says_so(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 6), [(LAUNDRY, "50.00")], currency="USD")
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.state is Availability.NOT_AVAILABLE
    assert costs.other_currencies_present is True


@pytest.mark.parametrize(
    ("previous", "expected_delta"),
    [(None, None), ("0.00", None), ("-50.00", None), ("1000.00", D("-50.00"))],
)
def test_the_comparison_needs_a_positive_previous_month(
    db_session: Session, world: CostWorld, previous: str | None, expected_delta: Decimal | None
) -> None:
    world.invoice(date(2026, 7, 5), [(LAUNDRY, "500.00")])
    if previous is not None:
        world.invoice(date(2026, 6, 5), [(LAUNDRY, previous)])
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.delta_pct == expected_delta  # a percentage of zero or of a net credit is undefined
    assert (costs.previous_total_net_cost is None) == (previous is None)


def test_classification_coverage_is_the_share_of_cost_in_a_real_category(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "800.00"), (UTILITIES, "1200.00")])
    world.invoice(date(2026, 7, 20), [(LAUNDRY, "-100.00")], kind=DocumentKind.CREDIT_NOTE)
    world.invoice(date(2026, 7, 28), [(OTHER, "100.00")])
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    # absolute amounts: 900 + 1200 + 100 = 2200, of which 2100 sit in a real category
    assert costs.classification_coverage_pct == D("95.45")


def test_costs_are_property_wide_whatever_the_source_that_imported_them(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "100.00")])
    other = world.other_cost_source(factory)
    world.invoice_from(factory, other, date(2026, 7, 4), [(UTILITIES, "50.00")], number="X-1")
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.total_net_cost == D("150.00")  # an invoice is one document, whatever the source


def test_another_tenants_invoices_are_invisible(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    foreign = CostWorld.create(db_session, factory)
    foreign.invoice(date(2026, 7, 3), [(LAUNDRY, "999.00")])
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    assert costs.state is Availability.NOT_AVAILABLE
    assert costs.total_net_cost is None


# --- the cost per occupied room (CPOR) ------------------------------------------------------------


def test_cpor_is_cost_per_occupied_room_night_from_the_runs_own_booking_source(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "700.00"), (UTILITIES, "1240.00")])
    world.lead_zero(JULY, rooms=10)  # 31 days x 10 rooms = 310 occupied room-nights
    _run(db_session, world)

    costs = overview_of(db_session, world.tenant).costs

    rows = {row.category: row for row in costs.categories}
    assert rows["LAUNDRY"].cpor_status is CporStatus.READY
    assert rows["LAUNDRY"].cpor == D("2.26")  # 700 / 310
    assert rows["UTILITIES"].cpor == D("4.00")  # 1240 / 310


def test_an_incomplete_month_of_occupancy_has_no_cpor_and_says_so(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "700.00")])
    world.lead_zero(JULY, rooms=10, missing=[5])  # one day with no snapshot: an unknown, not a zero
    _run(db_session, world)

    [row] = overview_of(db_session, world.tenant).costs.categories

    assert row.cpor is None
    assert row.cpor_status is CporStatus.INCOMPLETE
    assert row.net_cost == D("700.00")  # the cost itself is still real


def test_a_run_without_a_booking_source_has_no_cpor(db_session: Session, world: CostWorld) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "700.00")])
    world.lead_zero(JULY, rooms=10)
    _run(db_session, world, with_provenance=False)

    [row] = overview_of(db_session, world.tenant).costs.categories

    assert row.cpor is None
    assert row.cpor_status is CporStatus.NO_OCCUPANCY_SOURCE  # the source is never guessed


def test_a_month_with_poorly_classified_costs_has_no_cpor(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(
        date(2026, 7, 3), [(LAUNDRY, "300.00"), (OTHER, "700.00")]
    )  # only 30 % classified
    world.lead_zero(JULY, rooms=10)
    _run(db_session, world)

    rows = {row.category: row for row in overview_of(db_session, world.tenant).costs.categories}

    assert rows["LAUNDRY"].cpor_status is CporStatus.LOW_CLASSIFICATION_COVERAGE
    assert rows["LAUNDRY"].cpor is None


def test_the_unclassified_bucket_has_no_cost_per_room(
    db_session: Session, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "900.00"), (OTHER, "100.00")])
    world.lead_zero(JULY, rooms=10)
    _run(db_session, world)

    rows = {row.category: row for row in overview_of(db_session, world.tenant).costs.categories}

    assert rows["OTHER"].cpor_status is CporStatus.NOT_APPLICABLE
    assert rows["OTHER"].cpor is None


def test_a_cost_decision_is_attached_to_its_category_and_carries_its_own_figures(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "700.00"), (UTILITIES, "300.00")])
    world.lead_zero(JULY, rooms=10)
    _run(
        db_session,
        world,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, world.tenant),
        coverage=full_coverage(),
    )

    costs = overview_of(db_session, world.tenant).costs

    assert costs.decision is not None
    assert (costs.decision.period_start, costs.decision.category) == (date(2026, 7, 1), "LAUNDRY")
    assert costs.decision.expected_cpor == D("3.25")
    rows = {row.category: row for row in costs.categories}
    assert rows["LAUNDRY"].decision_id == costs.decision.decision_id
    assert rows["UTILITIES"].decision_id is None


def test_a_decision_for_another_month_is_shown_but_not_attached_to_a_row(
    db_session: Session, factory: BookingFactory, world: CostWorld
) -> None:
    world.invoice(date(2026, 6, 3), [(LAUNDRY, "700.00")])  # June is NOT the displayed month
    world.invoice(date(2026, 7, 3), [(LAUNDRY, "700.00")])
    evaluations = five_triggered_evaluations(factory, world.tenant)
    _run(db_session, world, evaluations=evaluations, coverage=full_coverage())
    # re-seed on a different analysis day whose decision targets June
    cost_evaluation_of_july = evaluations[3]
    assert isinstance(cost_evaluation_of_july, CostDecisionEvaluation)
    june_cost = replace(
        cost_evaluation_of_july,
        target_period_start=date(2026, 6, 1),
        target_period_end=date(2026, 6, 30),
        calculation_fingerprint="e" * 64,
    )
    seed_run(
        db_session,
        world.tenant,
        as_of=AS_OF + timedelta(days=1),
        evaluations=[june_cost],
        coverage=full_coverage(),
    )

    costs = overview_of(db_session, world.tenant, as_of=AS_OF + timedelta(days=1)).costs

    assert costs.decision is not None and costs.decision.period_start == date(2026, 6, 1)
    assert all(row.decision_id is None for row in costs.categories)


# --- labor ----------------------------------------------------------------------------------------


def _labor_world(
    factory: BookingFactory, tenant: Tenant
) -> tuple[DataSource, ImportJob, ImportFile]:
    source = factory.data_source(tenant.property, DataSourceDomain.LABOR)
    job = factory.import_job(source)
    file = factory.import_file(job)
    return source, job, file


def _entry(
    factory: BookingFactory,
    snapshot: LaborSnapshot,
    day: date,
    category: LaborCategory,
    minutes: int | None,
    *,
    row: int = 1,
    cost: str | None = None,
    currency: str | None = None,
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
        currency=currency,
        source_row_number=row,
    )


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


def test_planned_hours_are_the_planned_minutes_of_the_next_seven_days_by_category(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _entry(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 480, row=1)
    _entry(factory, snapshot, AS_OF, LaborCategory.HOUSEKEEPING, 240, row=2)  # two shifts, one day
    _entry(factory, snapshot, AS_OF + timedelta(days=1), LaborCategory.HOUSEKEEPING, 420, row=3)
    _entry(factory, snapshot, AS_OF, LaborCategory.FRONT_OFFICE, 360, row=4)
    _entry(
        factory, snapshot, AS_OF + timedelta(days=9), LaborCategory.KITCHEN, 600, row=5
    )  # outside
    seed_run(db_session, tenant)

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.AVAILABLE
    assert (labor.window_start, labor.window_end) == (AS_OF, AS_OF + timedelta(days=6))
    rows = {row.category: row for row in labor.categories}
    assert rows["HOUSEKEEPING"].planned_hours == D("19.00")  # (480 + 240 + 420) / 60
    assert rows["HOUSEKEEPING"].days_complete == 2
    assert rows["FRONT_OFFICE"].planned_hours == D("6.00")
    assert "KITCHEN" not in rows  # a day outside the 7-day window is not read
    assert labor.days_with_data == 2
    assert [row.category for row in labor.categories][0] == "HOUSEKEEPING"  # most hours first


def test_a_day_with_an_entry_lacking_planned_minutes_is_counted_and_left_out(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _entry(factory, snapshot, AS_OF, LaborCategory.KITCHEN, 480, row=1)
    _entry(factory, snapshot, AS_OF + timedelta(days=1), LaborCategory.KITCHEN, 480, row=2)
    # an actuals-only shift: it has worked minutes but no planned minutes (a row with neither is
    # refused by the database)
    _entry(
        factory, snapshot, AS_OF + timedelta(days=1), LaborCategory.KITCHEN, None, row=3, actual=300
    )
    seed_run(db_session, tenant)

    [row] = overview_of(db_session, tenant).labor.categories

    # day 2 is half known (one shift has no planned minutes): never half-counted
    assert (row.planned_hours, row.days_complete, row.days_incomplete) == (D("8.00"), 1, 1)


def test_the_most_recent_labor_snapshot_that_covers_a_day_wins(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    older = labor_snapshot(
        factory, source, job, file, snapshot_local_date=AS_OF - timedelta(days=3)
    )
    newer_job = factory.import_job(source)
    newer = labor_snapshot(
        factory,
        source,
        newer_job,
        factory.import_file(newer_job),
        snapshot_local_date=AS_OF,
        source_fingerprint="b" * 64,
    )
    _entry(factory, older, AS_OF, LaborCategory.KITCHEN, 480)
    _entry(factory, newer, AS_OF, LaborCategory.KITCHEN, 300)
    seed_run(db_session, tenant)

    [row] = overview_of(db_session, tenant).labor.categories

    assert row.planned_hours == D("5.00")  # the plan as last restated, not the old one


def test_a_snapshot_taken_after_the_analysis_day_is_never_read(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    future = labor_snapshot(
        factory, source, job, file, snapshot_local_date=AS_OF + timedelta(days=1)
    )
    _entry(factory, future, AS_OF, LaborCategory.KITCHEN, 480)
    seed_run(db_session, tenant)

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.NOT_AVAILABLE
    assert labor.reason is UnavailableReason.NO_DATA  # what is not yet known is not used


def test_planned_cost_needs_every_shift_costed_in_the_property_currency(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    source, job, file = _labor_world(factory, tenant)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _entry(
        factory, snapshot, AS_OF, LaborCategory.KITCHEN, 480, row=1, cost="120.00", currency="EUR"
    )
    _entry(
        factory,
        snapshot,
        AS_OF,
        LaborCategory.HOUSEKEEPING,
        480,
        row=2,
        cost="90.00",
        currency="USD",
    )
    _entry(factory, snapshot, AS_OF, LaborCategory.FRONT_OFFICE, 480, row=3)  # no cost at all
    seed_run(db_session, tenant)

    rows = {row.category: row for row in overview_of(db_session, tenant).labor.categories}

    assert rows["KITCHEN"].planned_cost == D("120.00")
    assert rows["HOUSEKEEPING"].planned_cost is None  # never converted
    assert rows["FRONT_OFFICE"].planned_cost is None


def test_no_ratio_is_ever_calculated() -> None:
    """NINFA defines no labor incidence, productivity, FTE or labor-cost-to-revenue ratio, so the
    category row carries hours, the days they rest on and a planned cost - nothing derived."""
    assert {field.name for field in fields(LaborCategoryRow)} == {
        "category",
        "planned_hours",
        "days_complete",
        "days_incomplete",
        "planned_cost",
    }


def test_several_labor_sources_are_not_chosen_between(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    for _ in range(2):
        source, job, file = _labor_world(factory, tenant)
        snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
        _entry(factory, snapshot, AS_OF, LaborCategory.KITCHEN, 480)
    seed_run(db_session, tenant)

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.NOT_AVAILABLE
    assert labor.reason is UnavailableReason.SEVERAL_SOURCES


def test_a_property_without_a_labor_source_has_no_labor_block(
    db_session: Session, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)

    labor = overview_of(db_session, tenant).labor

    assert labor.state is Availability.NOT_AVAILABLE
    assert labor.reason is UnavailableReason.NO_SOURCE
    assert labor.categories == ()


def test_another_tenants_labor_is_invisible(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    foreign = factory.tenant()
    source, job, file = _labor_world(factory, foreign)
    snapshot = labor_snapshot(factory, source, job, file, snapshot_local_date=AS_OF)
    _entry(factory, snapshot, AS_OF, LaborCategory.KITCHEN, 480)
    seed_run(db_session, tenant)

    assert overview_of(db_session, tenant).labor.reason is UnavailableReason.NO_SOURCE


def test_an_overstaffing_decision_carries_its_own_facts(
    db_session: Session, factory: BookingFactory, tenant: Tenant
) -> None:
    seed_run(
        db_session,
        tenant,
        nights=uniform_nights(AS_OF, rooms=20, capacity=40),
        evaluations=five_triggered_evaluations(factory, tenant),
        coverage=full_coverage(),
    )

    decision = overview_of(db_session, tenant).labor.decision

    assert decision is not None
    assert decision.work_date == AS_OF and decision.category == "HOUSEKEEPING"
    assert (decision.scheduled_hours, decision.expected_hours, decision.excess_hours) == (
        D("32.00"),
        D("24.00"),
        D("8.00"),
    )
