"""CostDecisionService on real PostgreSQL (Gate 7 groups A, B, D, N, O, P and Q).

Real canonical invoices and real lead-time-0 booking snapshots, read through the tenant-scoped
repositories. The service is read-only: it never writes, never commits, takes no lock.
"""

import ast
import random
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

import app.modules.intelligence.costs as costs_package
from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.costs.errors import CostDecisionError, CostErrorCode
from app.modules.intelligence.costs.service import OPERATING_CATEGORIES, CostDecisionService
from app.modules.intelligence.costs.types import (
    CostDecisionEvaluation,
    EvaluationStatus,
    MetricStatus,
    ReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import DocumentKind, Invoice, InvoiceLine
from app.modules.invoices.service import InvoiceImportService
from app.modules.properties.repository import PropertyRepository
from app.modules.suppliers.models import (
    Supplier,
    SupplierResolutionReview,
)
from tests.cost_support import (
    AUGUST,
    COMPARABLE_MONTHS,
    EUR,
    LAUNDRY,
    OTHER,
    USD,
    UTILITIES,
    CostWorld,
    counts,
    month,
    statements_of,
)
from tests.invoice_support import Body, Cedente, Line, fattura_xml
from tests.support import BookingFactory

D = Decimal
AUG = AUGUST
AUG_DAY = date(2026, 8, 14)
COSTS_DIR = Path(costs_package.__file__).parent


@pytest.fixture
def world(db_session: Session, factory: BookingFactory) -> CostWorld:
    return CostWorld.create(db_session, factory)


def metric(
    world: CostWorld, period: Any = AUG, category: Any = LAUNDRY, currency: str = EUR
) -> Any:
    return world.service().build_period_metric(
        property_id=world.tenant.property.id,
        booking_data_source_id=world.booking_source.id,
        year=period.year,
        month=period.month,
        cost_category=category,
        currency=currency,
    )


def evaluate(
    world: CostWorld, category: Any = LAUNDRY, currency: str = EUR, period: Any = AUG
) -> CostDecisionEvaluation:
    return world.service().evaluate_cpor_anomaly(
        property_id=world.tenant.property.id,
        booking_data_source_id=world.booking_source.id,
        year=period.year,
        month=period.month,
        cost_category=category,
        currency=currency,
    )


def triggered_world(world: CostWorld, *, target_net: str = "4000") -> CostWorld:
    """Eight observed comparable months at a CPOR of 10, and an August that costs more."""
    world.history({m: "10" for m in COMPARABLE_MONTHS})
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, target_net)])
    return world


# --- A. target and tenant -------------------------------------------------------------------------


def test_a_tenant_context_is_required(db_session: Session) -> None:
    with pytest.raises(TypeError):
        CostDecisionService(db_session, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CostDecisionService(db_session, "a workspace id")  # type: ignore[arg-type]


def test_a_property_of_another_workspace_is_refused_like_an_unknown_one(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)

    def refused(property_id: Any) -> CostDecisionError:
        with pytest.raises(CostDecisionError) as error:
            world.service().build_period_metric(
                property_id=property_id,
                booking_data_source_id=world.booking_source.id,
                year=2026,
                month=8,
                cost_category=LAUNDRY,
                currency=EUR,
            )
        return error.value

    foreign, unknown = refused(stranger.tenant.property.id), refused(__import__("uuid").uuid4())
    assert foreign.error_code == unknown.error_code == CostErrorCode.INVALID_PROPERTY
    assert foreign.details == unknown.details == {"reason": "not_found"}


def test_an_archived_property_is_refused(world: CostWorld) -> None:
    PropertyRepository(world.session, world.context).archive(world.tenant.property.id)
    with pytest.raises(CostDecisionError) as error:
        metric(world)
    assert error.value.details == {"reason": "archived"}


def test_a_bookings_data_source_is_accepted(world: CostWorld) -> None:
    assert metric(world).booking_data_source_id == world.booking_source.id


@pytest.mark.parametrize(
    ("domain", "reason"),
    [(DataSourceDomain.COSTS, "wrong_domain"), (DataSourceDomain.LABOR, "wrong_domain")],
)
def test_only_a_bookings_data_source_can_be_the_denominator(
    world: CostWorld, factory: BookingFactory, domain: DataSourceDomain, reason: str
) -> None:
    source = factory.data_source(world.tenant.property, domain)

    with pytest.raises(CostDecisionError) as error:
        world.service().evaluate_cpor_anomaly(
            property_id=world.tenant.property.id,
            booking_data_source_id=source.id,
            year=2026,
            month=8,
            cost_category=LAUNDRY,
            currency=EUR,
        )

    assert error.value.error_code == CostErrorCode.BOOKING_DATA_SOURCE_INVALID
    assert error.value.details == {
        "reason": reason,
        "reason_code": ReasonCode.BOOKING_DATA_SOURCE_INVALID.value,
    }


def test_an_inactive_booking_data_source_is_refused(world: CostWorld) -> None:
    world.booking_source.is_active = False
    world.session.flush()
    with pytest.raises(CostDecisionError) as error:
        metric(world)
    assert error.value.details is not None and error.value.details["reason"] == "inactive"


def test_a_booking_data_source_of_another_property_is_refused(
    world: CostWorld, factory: BookingFactory
) -> None:
    other_property = factory.property(world.tenant.workspace)
    elsewhere = factory.data_source(other_property, DataSourceDomain.BOOKINGS)

    with pytest.raises(CostDecisionError) as error:
        world.service().build_period_metric(
            property_id=world.tenant.property.id,
            booking_data_source_id=elsewhere.id,
            year=2026,
            month=8,
            cost_category=LAUNDRY,
            currency=EUR,
        )

    assert error.value.details is not None and error.value.details["reason"] == "property_mismatch"


def test_a_data_source_of_another_workspace_is_refused_like_an_unknown_one(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)
    with pytest.raises(CostDecisionError) as error:
        world.service().build_period_metric(
            property_id=world.tenant.property.id,
            booking_data_source_id=stranger.booking_source.id,
            year=2026,
            month=8,
            cost_category=LAUNDRY,
            currency=EUR,
        )
    assert error.value.details is not None and error.value.details["reason"] == "not_found"


@pytest.mark.parametrize(
    ("year", "month_number", "reason"),
    [
        (2026, 0, "bad_month"),
        (2026, 13, "bad_month"),
        (1800, 5, "bad_year"),
        (2026.0, 5, "bad_year"),
    ],
)
def test_a_malformed_period_is_refused(
    world: CostWorld, year: Any, month_number: Any, reason: str
) -> None:
    with pytest.raises(CostDecisionError) as error:
        world.service().build_period_metric(
            property_id=world.tenant.property.id,
            booking_data_source_id=world.booking_source.id,
            year=year,
            month=month_number,
            cost_category=LAUNDRY,
            currency=EUR,
        )
    assert error.value.error_code == CostErrorCode.INVALID_PERIOD
    assert error.value.details == {"reason": reason}


@pytest.mark.parametrize("currency", ["eur", "EURO", "E", "", "€", None, 978])
def test_a_malformed_currency_is_refused_and_nothing_is_converted(
    world: CostWorld, currency: Any
) -> None:
    with pytest.raises(CostDecisionError) as error:
        metric(world, currency=currency)
    assert error.value.error_code == CostErrorCode.INVALID_CURRENCY


def test_a_category_must_be_a_cost_category(world: CostWorld) -> None:
    with pytest.raises(CostDecisionError) as error:
        metric(world, category="LAUNDRY")
    assert error.value.error_code == CostErrorCode.INVALID_CATEGORY


def test_the_service_never_reads_the_clock() -> None:
    forbidden = {"now", "today", "utcnow", "time", "monotonic", "perf_counter", "fromtimestamp"}
    for path in COSTS_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                base = ast.unparse(node.value)
                assert base not in {"datetime", "date", "time", "datetime.datetime"}, (
                    path.name,
                    node.attr,
                )
            if isinstance(node, ast.ImportFrom) and node.module == "time":
                pytest.fail(f"{path.name} imports the time module")


# --- B. the cost side, from real canonical invoices ---------------------------------------------


def test_a_positive_invoice_line_enters_the_month(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    result = metric(world)

    assert result.net_cost == D("620.00") and result.status == MetricStatus.READY
    assert result.cpor_exact == D(2)  # 620 / 310


def test_a_credit_note_line_reduces_the_net_cost_and_is_not_negated_again(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "1000.00")])
    world.invoice(
        date(2026, 8, 20), [(LAUNDRY, "-250.00")], kind=DocumentKind.CREDIT_NOTE, number="NC-1"
    )

    result = metric(world)

    assert result.net_cost == D("750.00")  # 1000 - 250, the stored sign used as it is
    assert result.absolute_category_cost == D("1250.00")
    assert (result.credit_note_line_count, result.credit_note_cost) == (1, D("-250.00"))
    assert (result.invoice_count, result.line_count) == (2, 2)


def test_the_invoice_date_decides_the_month(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.lead_zero(month(2026, 7), 10)
    world.lead_zero(month(2026, 9), 10)
    world.invoice(date(2026, 7, 31), [(LAUNDRY, "100.00")])  # the last day of July: July
    world.invoice(date(2026, 8, 1), [(LAUNDRY, "200.00")])  # the first day of August: August
    world.invoice(date(2026, 8, 31), [(LAUNDRY, "300.00")])  # the last day of August: August
    world.invoice(date(2026, 9, 1), [(LAUNDRY, "400.00")])  # the first day of September

    assert metric(world, month(2026, 7)).net_cost == D("100.00")
    assert metric(world, AUG).net_cost == D("500.00")
    assert metric(world, month(2026, 9)).net_cost == D("400.00")


def test_a_line_of_the_previous_or_the_next_month_is_excluded(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(date(2026, 7, 15), [(LAUNDRY, "1000.00")])
    world.invoice(date(2026, 9, 15), [(LAUNDRY, "2000.00")])
    world.invoice(AUG_DAY, [(LAUNDRY, "50.00")])

    assert metric(world).net_cost == D("50.00")


def test_an_invoice_is_counted_once_however_many_data_sources_imported_it(
    db_session: Session, factory: BookingFactory
) -> None:
    """Gate 6 made the invoice identity cross-source: the same document from two COSTS data
    sources is ONE invoice, so its cost enters the month once."""
    world = CostWorld.create(db_session, factory)
    second = world.other_cost_source(factory)
    xml = fattura_xml(
        [Body(number="FA/1", date="2026-08-14", lines=[Line(1, "Servizio lavanderia", "620.00")])],
        cedente=Cedente(name="Lavanderia S.r.l."),
    )
    service = InvoiceImportService(db_session, world.context)
    first_result = service.import_file(world.cost_source.id, filename="a.xml", content=xml)
    second_result = service.import_file(second.id, filename="b.xml", content=xml)
    world.lead_zero(AUG, 10)

    result = metric(world)

    assert first_result.succeeded and second_result.succeeded
    assert (second_result.invoices_created, second_result.invoices_unchanged) == (0, 1)
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 1
    assert result.net_cost == D("620.00") and result.invoice_count == 1  # once, not twice


def test_the_data_source_of_an_invoice_is_never_a_filter(
    world: CostWorld, factory: BookingFactory
) -> None:
    other = world.other_cost_source(factory)
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "100.00")])
    world.invoice_from(factory, other, date(2026, 8, 20), [(LAUNDRY, "23.00")], number="X-1")

    assert metric(world).net_cost == D("123.00")


def test_only_the_asked_category_is_summed(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "300.00"), (UTILITIES, "500.00"), (OTHER, "40.00")])

    assert metric(world, category=LAUNDRY).net_cost == D("300.00")
    assert metric(world, category=UTILITIES).net_cost == D("500.00")


def test_other_never_enters_an_operating_category_but_counts_in_the_total(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "700.00"), (OTHER, "300.00")])

    result = metric(world)

    assert result.net_cost == D("700.00") and result.total_absolute_cost == D("1000.00")
    assert result.classification_coverage_pct_exact == D(70)


def test_the_currency_is_exact(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "300.00")], currency=EUR)
    world.invoice(AUG_DAY, [(LAUNDRY, "999.00")], currency=USD)

    assert metric(world, currency=EUR).net_cost == D("300.00")
    assert metric(world, currency=USD).net_cost == D("999.00")
    assert metric(world, currency=EUR).total_absolute_cost == D("300.00")


def test_the_absolute_exposure_sums_absolute_values(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "1000.00")])
    world.invoice(AUG_DAY, [(LAUNDRY, "-1000.00")], kind=DocumentKind.CREDIT_NOTE, number="NC-1")

    result = metric(world)

    assert result.net_cost == D("0.00") and result.absolute_category_cost == D("2000.00")
    assert result.status == MetricStatus.READY  # net zero is not "no activity"


def test_amounts_come_back_as_exact_decimals(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "0.10"), (LAUNDRY, "0.20")])

    result = metric(world)

    assert result.net_cost == D("0.30") and isinstance(result.net_cost, Decimal)
    assert result.cpor_exact is not None
    assert abs(Fraction(result.cpor_exact) - Fraction(30, 100 * 310)) < Fraction(1, 10**40)


def test_a_supplier_default_classified_line_counts_as_classified(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "100.00", "90"), (UTILITIES, "300.00", "100")])

    result = metric(world)

    assert result.weighted_classification_confidence_exact == D(97.5)  # (100*90 + 300*100) / 400


def test_costs_of_another_property_and_another_workspace_never_enter(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)
    stranger.invoice(AUG_DAY, [(LAUNDRY, "9999.00")])
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "100.00")])

    assert metric(world).net_cost == D("100.00")
    assert stranger.session.scalar(select(func.count()).select_from(Invoice)) == 2


def test_no_cost_line_is_not_a_zero_cost(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)

    result = metric(world)

    assert result.status == MetricStatus.NO_COST_DATA and result.net_cost is None
    assert result.reason_codes == (ReasonCode.COST_CURRENCY_NOT_PRESENT,)


# --- D. the denominator, from real snapshots ------------------------------------------------------


def test_the_denominator_is_the_sum_of_the_lead_time_zero_rooms(world: CostWorld) -> None:
    world.lead_zero(AUG, list(range(1, 32)))
    world.invoice(AUG_DAY, [(LAUNDRY, "496.00")])

    result = metric(world)

    assert result.occupied_room_nights == 496 and result.cpor_exact == D(1)


def test_a_snapshot_taken_before_the_stay_night_is_never_used(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.snapshot(date(2026, 7, 25), date(2026, 8, 5), 99)  # lead time 11, more rooms
    world.snapshot(date(2026, 8, 5), date(2026, 8, 6), 88)  # a snapshot of another night
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    assert metric(world).occupied_room_nights == 310


def test_a_snapshot_of_a_stay_date_outside_the_month_is_excluded(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.snapshot(date(2026, 9, 1), date(2026, 9, 1), 50)
    world.snapshot(date(2026, 7, 31), date(2026, 7, 31), 50)
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    assert metric(world).occupied_room_nights == 310


def test_a_snapshot_of_another_data_source_is_excluded(
    world: CostWorld, factory: BookingFactory
) -> None:
    second = factory.data_source(world.tenant.property, DataSourceDomain.BOOKINGS)
    world.lead_zero(AUG, 10)
    world.lead_zero(AUG, 3, data_source_id=second.id)  # another source, same month
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    assert metric(world).occupied_room_nights == 310  # only the explicit source counts


def test_a_snapshot_of_another_workspace_is_excluded(
    world: CostWorld, factory: BookingFactory
) -> None:
    stranger = CostWorld.create(world.session, factory)
    stranger.lead_zero(AUG, 7)
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    assert metric(world).occupied_room_nights == 310


def test_observed_and_reconstructed_days_are_counted_and_scored(world: CostWorld) -> None:
    world.lead_zero(AUG, 10, reconstructed=range(1, 11))
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    result = metric(world)

    assert (result.observed_day_count, result.reconstructed_day_count) == (21, 10)
    expected = D(2700) / D(31)
    assert result.occupancy_provenance_score_exact is not None
    assert abs(result.occupancy_provenance_score_exact - expected) < D("1e-20")


def test_an_uncertain_snapshot_makes_the_month_incomplete(world: CostWorld) -> None:
    world.lead_zero(AUG, 10, uncertain=[15])
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    result = metric(world)

    assert result.status == MetricStatus.INCOMPLETE and result.uncertain_day_count == 1
    assert result.occupied_room_nights is None


def test_a_missing_day_makes_the_month_incomplete_and_is_not_a_zero(world: CostWorld) -> None:
    world.lead_zero(AUG, 10, missing=[31])
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    result = metric(world)

    assert result.status == MetricStatus.INCOMPLETE and result.missing_day_count == 1
    assert result.occupied_room_nights is None and result.cpor_exact is None


def test_a_day_with_zero_rooms_is_valid_when_its_snapshot_exists(world: CostWorld) -> None:
    world.lead_zero(AUG, [10] * 14 + [0] + [10] * 16)
    world.invoice(AUG_DAY, [(LAUNDRY, "600.00")])

    result = metric(world)

    assert result.status == MetricStatus.READY and result.occupied_room_nights == 300


def test_a_month_without_any_snapshot_is_incomplete(world: CostWorld) -> None:
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])
    assert metric(world).status == MetricStatus.INCOMPLETE


def test_a_month_with_no_occupied_room_night_is_not_divided(world: CostWorld) -> None:
    world.lead_zero(AUG, 0)
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")])

    result = metric(world)

    assert result.status == MetricStatus.ZERO_OCCUPANCY and result.cpor_exact is None
    assert evaluate(world).status == EvaluationStatus.NOT_APPLICABLE


# --- the evaluation, end to end -------------------------------------------------------------------


def test_an_anomalous_month_triggers_through_the_service(world: CostWorld) -> None:
    triggered_world(world)

    evaluation = evaluate(world)

    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.expected_cpor_exact == D(10) and evaluation.sample_count == 8
    assert evaluation.cost_gap_proxy_exact == D(900)
    assert evaluation.workspace_id == world.tenant.workspace.id
    assert evaluation.booking_data_source_id == world.booking_source.id


def test_a_normal_month_is_clear_through_the_service(world: CostWorld) -> None:
    triggered_world(world, target_net="3100")
    assert evaluate(world).status == EvaluationStatus.CLEAR


def test_a_month_without_enough_history_is_insufficient(world: CostWorld) -> None:
    world.history({m: "10" for m in COMPARABLE_MONTHS[:4]})
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "4000.00")])

    evaluation = evaluate(world)

    assert evaluation.status == EvaluationStatus.INSUFFICIENT_DATA
    assert evaluation.reason_codes == (ReasonCode.COMPARABLE_SAMPLE_INSUFFICIENT,)


def test_the_other_category_is_not_applicable_through_the_service(world: CostWorld) -> None:
    triggered_world(world)
    evaluation = evaluate(world, category=OTHER)
    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.COST_CATEGORY_OTHER_NOT_ACTIONABLE,)


def test_the_history_only_uses_months_before_the_target(world: CostWorld) -> None:
    triggered_world(world)
    # future months with wild costs must not move the baseline
    for period in (month(2026, 9), month(2026, 10)):
        world.history({period: "1000"})

    evaluation = evaluate(world)

    assert evaluation.expected_cpor_exact == D(10)
    used = {p.period_start for p in evaluation.comparable_periods}
    assert date(2026, 9, 1) not in used and date(2026, 10, 1) not in used
    assert all(p.period_end < date(2026, 8, 1) for p in evaluation.comparable_periods)


def test_history_older_than_36_months_is_not_read(world: CostWorld) -> None:
    triggered_world(world)
    world.history({month(2023, 7): "500", month(2022, 8): "500"})  # 37 and 48 months back

    evaluation = evaluate(world)

    assert evaluation.expected_cpor_exact == D(10)
    assert all(p.period_start >= date(2023, 8, 1) for p in evaluation.comparable_periods)


def test_evaluate_month_returns_one_evaluation_per_category_in_order(world: CostWorld) -> None:
    triggered_world(world)

    evaluations = world.service().evaluate_month(
        property_id=world.tenant.property.id,
        booking_data_source_id=world.booking_source.id,
        year=2026,
        month=8,
        currency=EUR,
    )

    assert [e.cost_category for e in evaluations] == list(OPERATING_CATEGORIES)
    assert CostCategory.OTHER not in OPERATING_CATEGORIES
    by_category = {e.cost_category: e for e in evaluations}
    assert by_category[LAUNDRY].status == EvaluationStatus.TRIGGERED
    assert by_category[UTILITIES].status == EvaluationStatus.NOT_APPLICABLE  # nothing invoiced
    assert by_category[UTILITIES].reason_codes == (ReasonCode.COST_CATEGORY_NOT_PRESENT,)


def test_evaluate_month_honours_an_explicit_category_list(world: CostWorld) -> None:
    triggered_world(world)
    evaluations = world.service().evaluate_month(
        property_id=world.tenant.property.id,
        booking_data_source_id=world.booking_source.id,
        year=2026,
        month=8,
        currency=EUR,
        cost_categories=[UTILITIES, LAUNDRY, OTHER],
    )
    assert [e.cost_category for e in evaluations] == [UTILITIES, LAUNDRY, OTHER]


# --- N. currency ----------------------------------------------------------------------------------


def test_the_same_category_in_two_currencies_stays_two_separate_worlds(world: CostWorld) -> None:
    world.history({m: "10" for m in COMPARABLE_MONTHS}, currency=EUR)
    world.history({m: "2" for m in COMPARABLE_MONTHS}, currency=USD, snapshots=False)
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "4000.00")], currency=EUR)  # 12.9 against 10
    world.invoice(AUG_DAY, [(LAUNDRY, "620.00")], currency=USD)  # 2.0 against 2

    eur, usd = evaluate(world, currency=EUR), evaluate(world, currency=USD)

    assert eur.status == EvaluationStatus.TRIGGERED and eur.expected_cpor_exact == D(10)
    assert usd.status == EvaluationStatus.CLEAR and usd.expected_cpor_exact == D(2)
    assert eur.currency == EUR and usd.currency == USD


def test_a_currency_with_no_invoice_in_the_month_is_not_applicable(world: CostWorld) -> None:
    triggered_world(world)

    evaluation = evaluate(world, currency=USD)

    assert evaluation.status == EvaluationStatus.NOT_APPLICABLE
    assert evaluation.reason_codes == (ReasonCode.COST_CURRENCY_NOT_PRESENT,)


def test_no_currency_conversion_exists_anywhere() -> None:
    for path in COSTS_DIR.glob("*.py"):
        text_ = path.read_text(encoding="utf-8").lower()
        for word in ("exchange", "fx_rate", "forex", "convert_currency", "base_currency"):
            assert word not in text_.replace("no fx", ""), (path.name, word)


# --- O. read-only ---------------------------------------------------------------------------------


def test_an_evaluation_writes_nothing_and_takes_no_lock(world: CostWorld) -> None:
    triggered_world(world)
    review_count = world.session.scalar(select(func.count()).select_from(SupplierResolutionReview))
    before = counts(world.session)
    world.session.flush()

    with statements_of(world.session) as statements:
        evaluate(world)
        world.service().evaluate_month(
            property_id=world.tenant.property.id,
            booking_data_source_id=world.booking_source.id,
            year=2026,
            month=8,
            currency=EUR,
        )

    assert counts(world.session) == before  # no snapshot, invoice, line or supplier row changed
    assert not world.session.new and not world.session.dirty and not world.session.deleted
    sql = " ".join(s.lstrip().split()[0].upper() for s, _ in statements)
    assert set(sql.split()) == {"SELECT"}, sql  # never an INSERT, UPDATE, DELETE or lock
    assert all("advisory" not in s.lower() for s, _ in statements)
    assert (
        world.session.scalar(select(func.count()).select_from(SupplierResolutionReview))
        == review_count
    )


def test_stored_rows_are_bit_for_bit_unchanged_by_an_evaluation(world: CostWorld) -> None:
    triggered_world(world)

    def dump() -> list[Any]:
        return [
            world.session.execute(
                text(f"SELECT md5(CAST(t AS text)) FROM {table} t ORDER BY 1")
            ).all()
            for table in ("booking_snapshots", "invoices", "invoice_lines", "suppliers")
        ]

    before = dump()
    evaluate(world)
    assert dump() == before


def test_a_pending_supplier_review_neither_blocks_nor_is_resolved(world: CostWorld) -> None:
    triggered_world(world)
    other = Supplier(
        workspace_id=world.tenant.workspace.id, legal_name="Altro", normalized_name="altro"
    )
    world.session.add(other)
    world.session.flush()
    world.session.add(
        SupplierResolutionReview(
            workspace_id=world.tenant.workspace.id,
            provisional_supplier_id=other.id,
            candidate_supplier_id=world.supplier_id,
            reason="FUZZY_NAME_SIMILARITY",
            similarity_score=D("0.9"),
        )
    )
    world.session.flush()

    evaluation = evaluate(world)

    assert evaluation.status == EvaluationStatus.TRIGGERED  # a review does not silence a category
    review = world.session.scalars(select(SupplierResolutionReview)).one()
    assert review.status.value == "PENDING" and review.resolved_at is None


# --- P. performance -------------------------------------------------------------------------------


def statement_kinds(statements: list[tuple[str, Any]]) -> dict[str, int]:
    tables = {"booking_snapshots": 0, "invoices": 0, "properties": 0, "data_sources": 0}
    for sql, _ in statements:
        for table in tables:
            if f"FROM {table}" in sql or f"JOIN {table}" in sql:
                tables[table] += 1
    return tables


def test_one_evaluation_costs_a_bounded_number_of_statements(world: CostWorld) -> None:
    triggered_world(world)

    with statements_of(world.session) as statements:
        evaluate(world)

    kinds = statement_kinds(statements)
    assert len(statements) <= 5  # property, data source, ONE cost aggregate, ONE snapshot read
    assert kinds["booking_snapshots"] == 1 and kinds["invoices"] == 1


def test_many_categories_do_not_grow_the_number_of_statements(world: CostWorld) -> None:
    triggered_world(world)
    one = statements_for(world, [LAUNDRY])
    many = statements_for(world, list(OPERATING_CATEGORIES))

    assert len(many) == len(one) <= 5  # the history is read once for the whole batch
    assert statement_kinds(many) == statement_kinds(one)


def statements_for(world: CostWorld, categories: list[CostCategory]) -> list[tuple[str, Any]]:
    with statements_of(world.session) as statements:
        world.service().evaluate_month(
            property_id=world.tenant.property.id,
            booking_data_source_id=world.booking_source.id,
            year=2026,
            month=8,
            currency=EUR,
            cost_categories=categories,
        )
    return statements


def test_the_statements_do_not_grow_with_invoices_or_days_or_comparables(
    world: CostWorld, factory: BookingFactory
) -> None:
    triggered_world(world)
    baseline = len(statements_for(world, [LAUNDRY]))
    for day in range(1, 29):  # 84 more invoices with 3 lines each, spread over the months
        for period in COMPARABLE_MONTHS:
            world.invoice(
                date(period.year, period.month, day),
                [(LAUNDRY, "1.00"), (UTILITIES, "2.00"), (OTHER, "0.50")],
            )

    with_more = len(statements_for(world, [LAUNDRY]))

    assert with_more == baseline  # no query per invoice, per day or per comparable month


def test_no_statement_is_issued_per_day_or_per_comparable(world: CostWorld) -> None:
    triggered_world(world)
    with statements_of(world.session) as statements:
        evaluate(world)
    # one snapshot statement carries all the (day, day) keys of the 16 months involved
    assert sum(1 for s, _ in statements if "booking_snapshots" in s) == 1
    assert sum(1 for s, _ in statements if "invoice_lines" in s) == 1
    assert len(statements) <= 5


# --- Q. determinism -------------------------------------------------------------------------------


def test_the_same_call_twice_gives_the_same_evaluation_and_fingerprint(world: CostWorld) -> None:
    triggered_world(world)
    first, second = evaluate(world), evaluate(world)
    assert first == second and first.calculation_fingerprint == second.calculation_fingerprint


def strip(payload: dict[str, Any]) -> dict[str, Any]:
    """The evaluation without the ids that differ between two tenants."""
    text_ = repr(payload)
    for key in ("workspace_id", "property_id", "booking_data_source_id", "calculation_fingerprint"):
        payload = {k: (v if k != key else "x") for k, v in payload.items()}
        if isinstance(payload.get("target_metric"), dict):
            payload["target_metric"] = {
                k: ("x" if k == key else v) for k, v in payload["target_metric"].items()
            }
    assert text_
    return payload


def test_the_order_of_the_rows_in_the_database_does_not_change_the_result(
    db_session: Session, factory: BookingFactory
) -> None:
    ordered = CostWorld.create(db_session, factory)
    shuffled = CostWorld.create(db_session, factory)
    months = [*COMPARABLE_MONTHS, AUG]
    for period in months:
        ordered.lead_zero(period, 10)
        ordered.invoice(
            date(period.year, period.month, 9), [(LAUNDRY, "4000" if period == AUG else "3100")]
        )
    randomizer = random.Random(7)
    randomizer.shuffle(months)
    for period in months:
        shuffled.lead_zero(period, 10)
        shuffled.invoice(
            date(period.year, period.month, 9), [(LAUNDRY, "4000" if period == AUG else "3100")]
        )

    first, second = evaluate(ordered), evaluate(shuffled)

    assert first.status == second.status == EvaluationStatus.TRIGGERED
    assert strip(first.payload()) == strip(second.payload())
    assert first.expected_cpor_exact == second.expected_cpor_exact
    assert first.confidence_score == second.confidence_score
    assert [p.cpor_exact for p in first.comparable_periods] == [
        p.cpor_exact for p in second.comparable_periods
    ]


def test_the_lines_of_an_invoice_line_count_and_the_rows_agree(world: CostWorld) -> None:
    world.lead_zero(AUG, 10)
    world.invoice(AUG_DAY, [(LAUNDRY, "10.00"), (LAUNDRY, "20.00"), (UTILITIES, "5.00")])
    stored = world.session.scalar(select(func.count()).select_from(InvoiceLine))
    result = metric(world)
    assert stored == 3 and result.line_count == 2 and result.invoice_count == 1
    assert TenantContext(world.tenant.workspace.id) == world.context
