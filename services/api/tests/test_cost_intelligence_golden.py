"""Golden cost intelligence: "MASSERIA NINFA DEMO — COST DATA V1" (Gate 7).

The full chain, end to end, through the real services:

    BOOKINGS (one booking per day, imported by the Gate 2 import service)
      -> SNAPSHOTS (12 months RECONSTRUCTED by the Gate 3 reconstruction service, 5 months OBSERVED
                    day by day by the Gate 3 observed service, one day never observed, one day
                    uncertain, one month with no guest)
      -> COSTS (79 invoices imported by the Gate 6 service: seven FatturaPA XML files of two
                currencies and one structured CSV of a second data source)
      -> COST INTELLIGENCE (the Cost Decision service)          STOP: nothing is stored.

The expected result (`masseria_ninfa_cost_intelligence_v1.expected.json`) was computed
independently of the application code (tests/fixtures/costs/generate_masseria_cost_intelligence_
expected.py: standard library only, exact fractions): occupancy, costs, coverage, CPOR, comparable
selection, statistics, confidence, thresholds, status and reasons. The whole canonical payload of
every evaluation (what the fingerprint hashes) is compared, not just the status.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.bookings.models import Booking
from app.modules.bookings.service import BookingImportService
from app.modules.bookings.suggestions import SuggestionConfidence
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportJobStatus
from app.modules.intelligence.costs.errors import CostDecisionError, CostErrorCode
from app.modules.intelligence.costs.service import CostDecisionService
from app.modules.intelligence.costs.types import CostDecisionEvaluation, EvaluationStatus
from app.modules.invoices.cost_categories import CostCategory
from app.modules.invoices.models import Invoice, InvoiceLine
from app.modules.invoices.service import InvoiceImportService
from app.modules.properties.models import Property
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.suppliers.models import Supplier
from tests.cost_support import statements_of
from tests.snapshot_support import FixedClock
from tests.support import BookingFactory

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "costs"
EXPECTED = json.loads(
    (FIXTURE_DIR / "masseria_ninfa_cost_intelligence_v1.expected.json").read_text("utf-8")
)
CASES = EXPECTED["cases"]
RECONSTRUCTION_CLOCK = datetime.fromisoformat(EXPECTED["reconstruction_clock"])
OBSERVATION_HOUR = EXPECTED["observation_clock_hour_utc"]
BOOKING_FORMAT: dict[str, Any] = {
    "date_formats": {
        "booked_at": "%d/%m/%Y %H:%M",
        "check_in": "%d/%m/%Y",
        "check_out": "%d/%m/%Y",
        "cancelled_at": "%d/%m/%Y %H:%M",
    },
    "decimal_separator": ",",
    "thousands_separator": ".",
}
SOFTWARE_COLUMNS: dict[str, dict[str, str]] = {
    "supplier_name": {"column": "Fornitore"},
    "supplier_vat_number": {"column": "P.IVA"},
    "invoice_number": {"column": "Numero Fattura"},
    "invoice_date": {"column": "Data"},
    "line_description": {"column": "Descrizione"},
    "line_total": {"column": "Importo"},
    "cost_category": {"column": "Categoria"},
}
SOFTWARE_FORMAT: dict[str, Any] = {
    "date_formats": {"invoice_date": "%d/%m/%Y"},
    "decimal_separator": ",",
    "thousands_separator": ".",
}
FRACTION = re.compile(r"^-?\d+/\d+$")
TOLERANCE = Fraction(1, 10**40)
IDS = {"workspace_id", "property_id", "booking_data_source_id"}


@dataclass
class Golden:
    session: Session
    context: TenantContext
    prop: Property
    booking_source: DataSource
    xml_source: DataSource
    csv_source: DataSource
    factory: BookingFactory

    def service(self) -> CostDecisionService:
        return CostDecisionService(self.session, self.context)

    def evaluate(self, month: str, category: str, currency: str) -> CostDecisionEvaluation:
        year, number = (int(part) for part in month.split("-"))
        return self.service().evaluate_cpor_anomaly(
            property_id=self.prop.id,
            booking_data_source_id=self.booking_source.id,
            year=year,
            month=number,
            cost_category=CostCategory(category),
            currency=currency,
        )


# --- building the world, through the real services ----------------------------------------------


def import_bookings(golden: Golden) -> None:
    service = BookingImportService(golden.session, golden.context)
    path = FIXTURE_DIR / "masseria_ninfa_cost_bookings_v1.csv"
    content = path.read_bytes()
    suggestion = service.suggest_mapping(
        golden.booking_source.id, filename=path.name, content=content
    )
    service.save_mapping(
        golden.booking_source.id,
        headers=suggestion.headers,
        column_mapping={
            s.canonical_field.value: {"column": s.suggested_source_column}
            for s in suggestion.suggestions
            if s.suggested_source_column and s.confidence == SuggestionConfidence.HIGH
        },
        format_options=BOOKING_FORMAT,
    )
    result = service.import_file(golden.booking_source.id, filename=path.name, content=content)
    assert (result.status, result.rows_valid, result.rows_invalid) == (
        ImportJobStatus.SUCCEEDED,
        EXPECTED["counts"]["bookings"],
        0,
    ), result


def month_bounds(month: str) -> tuple[date, date]:
    year, number = (int(part) for part in month.split("-"))
    first = date(year, number, 1)
    following = date(year + number // 12, number % 12 + 1, 1)
    return first, following - timedelta(days=1)


def build_snapshots(golden: Golden) -> None:
    clock = FixedClock(RECONSTRUCTION_CLOCK)
    for month in EXPECTED["reconstructed_months"]:
        first, last = month_bounds(month)
        BookingSnapshotReconstructionService(
            golden.session, golden.context, clock=clock
        ).reconstruct(
            property_id=golden.prop.id,
            data_source_id=golden.booking_source.id,
            snapshot_date_start=first,
            snapshot_date_end=last,
            stay_date_start=first,
            stay_date_end=last,
        )
    missing = {date.fromisoformat(d) for days in EXPECTED["missing_days"].values() for d in days}
    for month in EXPECTED["observed_months"]:
        first, last = month_bounds(month)
        day = first
        while day <= last:
            if day not in missing:  # a day nobody looked: there is NO snapshot, not a zero one
                observed_at = datetime.combine(day, time(OBSERVATION_HOUR), tzinfo=UTC)
                ObservedSnapshotService(
                    golden.session, golden.context, clock=FixedClock(observed_at)
                ).take_snapshot(
                    property_id=golden.prop.id,
                    data_source_id=golden.booking_source.id,
                    stay_date_start=day,
                    stay_date_end=day + timedelta(days=2),  # lead times 0, 1 and 2
                )
            day += timedelta(days=1)


def import_costs(golden: Golden) -> None:
    service = InvoiceImportService(golden.session, golden.context)
    for name in EXPECTED["xml_files"]:
        result = service.import_file(
            golden.xml_source.id,
            filename=name,
            content=(FIXTURE_DIR / "invoices" / name).read_bytes(),
        )
        assert result.succeeded, (name, result.error_code, result.details)
    path = FIXTURE_DIR / "invoices" / "software.csv"
    described = service.describe_file(
        golden.csv_source.id, filename=path.name, content=path.read_bytes()
    )
    service.save_mapping(
        golden.csv_source.id,
        headers=described.headers,
        column_mapping=SOFTWARE_COLUMNS,
        category_mapping={"Software": "SOFTWARE"},
        format_options=SOFTWARE_FORMAT,
    )
    result = service.import_file(
        golden.csv_source.id, filename=path.name, content=path.read_bytes()
    )
    assert result.succeeded, (result.error_code, result.details)


def build(session: Session) -> Golden:
    factory = BookingFactory(session)
    workspace = factory.workspace()
    prop = factory.property(workspace, "masseria-ninfa")
    golden = Golden(
        session=session,
        context=TenantContext(workspace.id),
        prop=prop,
        booking_source=factory.data_source(prop, DataSourceDomain.BOOKINGS),
        xml_source=factory.data_source(prop, DataSourceDomain.COSTS),
        csv_source=factory.data_source(prop, DataSourceDomain.COSTS),
        factory=factory,
    )
    import_bookings(golden)  # Gate 2
    build_snapshots(golden)  # Gate 3
    import_costs(golden)  # Gate 6
    return golden


@pytest.fixture(scope="module")
def golden(db_engine: Engine) -> Iterator[Golden]:
    """The golden world, built ONCE for the module (about a thousand statements per month) and
    rolled back at the end: every test below only READS it."""
    connection = db_engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield build(session)
    finally:
        session.close()
        outer.rollback()
        connection.close()


# --- comparing an evaluation with the independent calculation ------------------------------------


def without_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_ids(v) for k, v in value.items() if k not in IDS}
    if isinstance(value, list):
        return [without_ids(v) for v in value]
    return value


def compare(actual: Any, expected: Any, path: str) -> None:
    """A canonical payload against the independent one: exact for everything but decimals, which
    are compared as fractions to better than 1e-40 (the application keeps 50 digits)."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert set(actual) == set(expected), (path, set(actual) ^ set(expected))
        for key, value in expected.items():
            compare(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            compare(actual[index], value, f"{path}[{index}]")
    elif isinstance(expected, str) and FRACTION.match(expected):
        assert isinstance(actual, str), (path, actual)
        assert abs(Fraction(actual) - Fraction(expected)) < TOLERANCE, (path, actual, expected)
    else:
        assert actual == expected, (path, actual, expected)


def check_case(golden: Golden, name: str) -> CostDecisionEvaluation:
    case = CASES[name]
    evaluation = golden.evaluate(case["month"], case["category"], case["currency"])
    assert evaluation.status.value == case["evaluation"]["status"], name
    compare(without_ids(evaluation.canonical_payload()), case["evaluation"], name)
    assert evaluation.workspace_id == golden.context.workspace_id
    assert evaluation.property_id == golden.prop.id
    assert evaluation.booking_data_source_id == golden.booking_source.id
    return evaluation


# --- the golden world contains what it must ---------------------------------------------------


def test_the_chain_was_built_through_the_canonical_services(golden: Golden) -> None:
    session = golden.session

    def count(model: type[Any]) -> int:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)

    assert count(Booking) == EXPECTED["counts"]["bookings"]
    assert count(Invoice) == EXPECTED["counts"]["invoice_documents"]
    assert count(InvoiceLine) == EXPECTED["counts"]["invoice_lines"]
    origins = {o for (o,) in session.execute(select(BookingSnapshot.origin).distinct())}
    assert origins == {SnapshotOrigin.OBSERVED, SnapshotOrigin.RECONSTRUCTED_APPROXIMATE}
    sources = {s for (s,) in session.execute(select(Invoice.data_source_id).distinct())}
    assert sources == {golden.xml_source.id, golden.csv_source.id}  # two data sources of costs
    assert count(Supplier) == 7
    lead_other = session.scalar(
        select(func.count())
        .select_from(BookingSnapshot)
        .where(BookingSnapshot.snapshot_local_date != BookingSnapshot.stay_date)
    )
    assert lead_other and lead_other > 0  # snapshots of lead time > 0 exist and are never used


def test_the_lead_time_zero_snapshots_match_the_designed_occupancy(golden: Golden) -> None:
    rows = golden.session.execute(
        text(
            "SELECT to_char(stay_date, 'YYYY-MM') AS month, count(*), sum(rooms_on_books),"
            " sum(uncertain_rooms), min(origin), max(origin)"
            " FROM booking_snapshots WHERE snapshot_local_date = stay_date AND data_source_id = :s"
            " GROUP BY 1 ORDER BY 1"
        ),
        {"s": golden.booking_source.id},
    ).all()
    stored = {
        month: (n, rooms, uncertain, low, high) for month, n, rooms, uncertain, low, high in rows
    }
    for month, design in EXPECTED["months"].items():
        days_present = design["days"] - design["missing_days"]
        n, rooms, uncertain, low, high = stored[month]
        assert n == days_present, month
        expected_origin = "OBSERVED" if design["kind"] == "O" else "RECONSTRUCTED_APPROXIMATE"
        assert low == high == expected_origin, month
        assert (uncertain > 0) == (design["uncertain_days"] > 0), month
        if design["occupied_room_nights"] is not None:
            assert rooms == design["occupied_room_nights"], month


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_case_matches_the_independent_calculation(golden: Golden, name: str) -> None:
    check_case(golden, name)


def test_the_cases_cover_every_status_and_every_reason_of_the_specification() -> None:
    statuses = {c["evaluation"]["status"] for c in CASES.values()}
    assert statuses == {s.value for s in EvaluationStatus}
    reasons = {r for c in CASES.values() for r in c["evaluation"]["reason_codes"]}
    assert reasons >= {
        "TRIGGER_CPOR_ANOMALY",
        "CLEAR_WITHIN_EXPECTED_RANGE",
        "LOW_CONFIDENCE",
        "COMPARABLE_SAMPLE_INSUFFICIENT",
        "COST_CLASSIFICATION_COVERAGE_LOW",
        "OCCUPANCY_PERIOD_INCOMPLETE",
        "ZERO_OCCUPIED_ROOM_NIGHTS",
        "EXPECTED_CPOR_NON_POSITIVE",
        "COST_CATEGORY_OTHER_NOT_ACTIONABLE",
        "COST_CATEGORY_NOT_PRESENT",
        "COST_CURRENCY_NOT_PRESENT",
    }


# --- what each case shows ----------------------------------------------------------------------


def test_a_the_laundry_anomaly_is_triggered_for_the_four_reasons(golden: Golden) -> None:
    evaluation = check_case(golden, "A")

    assert evaluation.status == EvaluationStatus.TRIGGERED
    assert evaluation.delta_percent_exact is not None and evaluation.delta_percent_exact >= 20
    assert (
        evaluation.target_metric.cpor_exact is not None and evaluation.upper_fence_exact is not None
    )
    assert evaluation.target_metric.cpor_exact >= evaluation.upper_fence_exact
    assert evaluation.cost_gap_proxy_exact is not None and evaluation.cost_gap_proxy_exact >= 100
    assert evaluation.confidence_score >= 55


def test_b_a_normal_month_is_clear_and_a_credit_note_lowered_its_cost(golden: Golden) -> None:
    evaluation = check_case(golden, "B")

    assert evaluation.status == EvaluationStatus.CLEAR
    metric = evaluation.target_metric
    assert metric.credit_note_line_count == 1 and metric.credit_note_cost is not None
    assert metric.credit_note_cost < 0  # 184.00 written positive, stored negative, not reversed
    assert metric.absolute_category_cost is not None and metric.net_cost is not None
    assert metric.absolute_category_cost - metric.net_cost == 2 * abs(metric.credit_note_cost)
    assert metric.period_start == date(2026, 7, 1)  # the July 31 invoice stays in July


def test_c_a_high_delta_inside_a_volatile_history_is_not_an_anomaly(golden: Golden) -> None:
    evaluation = check_case(golden, "C")
    assert evaluation.relative_condition is True and evaluation.upper_fence_condition is False
    assert evaluation.status == EvaluationStatus.CLEAR


def test_d_a_small_gap_is_not_an_anomaly(golden: Golden) -> None:
    evaluation = check_case(golden, "D")
    assert evaluation.relative_condition and evaluation.upper_fence_condition
    assert evaluation.gap_condition is False and evaluation.status == EvaluationStatus.CLEAR
    assert evaluation.cost_gap_proxy_exact is not None and evaluation.cost_gap_proxy_exact < 100


def test_e_a_weak_baseline_suppresses_an_anomaly(golden: Golden) -> None:
    evaluation = check_case(golden, "E")
    assert evaluation.status == EvaluationStatus.SUPPRESSED_LOW_CONFIDENCE
    assert evaluation.relative_condition and evaluation.upper_fence_condition
    assert evaluation.gap_condition and evaluation.confidence_score < 55
    assert evaluation.observed_period_count == 0  # every comparable is a reconstruction
    assert evaluation.cost_gap_proxy_exact is not None  # kept for the audit, never shown


def test_f_too_few_comparables_is_insufficient_data(golden: Golden) -> None:
    evaluation = check_case(golden, "F")
    assert evaluation.sample_count == 3 and evaluation.expected_cpor_exact is None


def test_g_too_much_other_makes_the_month_insufficient(golden: Golden) -> None:
    evaluation = check_case(golden, "G")
    coverage = evaluation.target_metric.classification_coverage_pct_exact
    assert coverage is not None and coverage < 70


def test_h_other_is_not_actionable(golden: Golden) -> None:
    assert check_case(golden, "H").status == EvaluationStatus.NOT_APPLICABLE


def test_i_a_month_with_a_day_nobody_observed_is_insufficient(golden: Golden) -> None:
    evaluation = check_case(golden, "I")
    assert evaluation.target_metric.missing_day_count == 1
    assert evaluation.target_metric.occupied_room_nights is None  # not 30 days' worth


def test_j_a_month_without_guests_is_not_divided(golden: Golden) -> None:
    evaluation = check_case(golden, "J")
    assert evaluation.target_metric.occupied_room_nights == 0
    assert evaluation.target_metric.cpor_exact is None
    assert evaluation.target_metric.net_cost is not None  # there is a cost, and no room to divide


def test_k_a_history_of_credit_notes_has_no_positive_expectation(golden: Golden) -> None:
    evaluation = check_case(golden, "K")
    assert evaluation.expected_cpor_exact is not None and evaluation.expected_cpor_exact < 0
    assert evaluation.delta_percent_exact is None


def test_m_reconstructed_clean_months_enter_the_baseline_and_lower_its_provenance(
    golden: Golden,
) -> None:
    evaluation = check_case(golden, "A")

    assert evaluation.approximate_period_count == 9 and evaluation.observed_period_count == 1
    assert evaluation.provenance_score_exact is not None and evaluation.provenance_score_exact < 100
    assert evaluation.confidence_cap == 85  # a reconstructed month caps the baseline
    assert any(not p.is_fully_observed for p in evaluation.comparable_periods)


def test_n_a_month_with_an_uncertain_snapshot_never_enters_a_baseline(golden: Golden) -> None:
    evaluation = check_case(golden, "A")

    assert evaluation.rejected_incomplete_occupancy_count == 1  # September 2025
    assert date(2025, 9, 1) not in {p.period_start for p in evaluation.comparable_periods}
    assert date(2026, 6, 1) not in {p.period_start for p in evaluation.comparable_periods}
    assert evaluation.rejected_low_classification_count == 1  # June 2026: too much OTHER


def test_o_two_currencies_are_never_mixed_or_converted(golden: Golden) -> None:
    eur, usd = check_case(golden, "A"), check_case(golden, "O")

    assert (
        eur.status == EvaluationStatus.TRIGGERED
        and usd.status == EvaluationStatus.INSUFFICIENT_DATA
    )
    assert usd.target_metric.net_cost is not None and usd.target_metric.net_cost == 5000
    assert usd.sample_count == 1  # the single USD month of 2025-08, never EUR months "converted"
    assert eur.target_metric.net_cost != usd.target_metric.net_cost
    # a USD invoice in 2025-08 changed nothing of the EUR history
    august_2025 = next(p for p in eur.comparable_periods if p.period_start == date(2025, 8, 1))
    assert august_2025.net_cost == check_case_metric(golden, "2025-08", "LAUNDRY", "EUR")


def check_case_metric(golden: Golden, month: str, category: str, currency: str) -> Any:
    year, number = (int(part) for part in month.split("-"))
    return (
        golden.service()
        .build_period_metric(
            property_id=golden.prop.id,
            booking_data_source_id=golden.booking_source.id,
            year=year,
            month=number,
            cost_category=CostCategory(category),
            currency=currency,
        )
        .net_cost
    )


def test_p_a_category_nobody_invoiced_is_not_applicable_and_not_zero(golden: Golden) -> None:
    evaluation = check_case(golden, "P")
    assert evaluation.target_metric.net_cost is None


def test_q_a_month_with_no_invoice_at_all_is_not_applicable(golden: Golden) -> None:
    evaluation = check_case(golden, "Q")
    assert evaluation.target_metric.total_absolute_cost is None


# --- the batch, determinism, read-only, isolation -------------------------------------------------


def test_a_batch_of_categories_equals_the_single_evaluations_and_reads_the_history_once(
    golden: Golden,
) -> None:
    categories = EXPECTED["evaluate_month_2026_08_eur"]["categories"]
    singles = {c: golden.evaluate("2026-08", c, "EUR") for c in categories}

    with statements_of(golden.session) as statements:
        batch = golden.service().evaluate_month(
            property_id=golden.prop.id,
            booking_data_source_id=golden.booking_source.id,
            year=2026,
            month=8,
            currency="EUR",
            cost_categories=[CostCategory(c) for c in categories],
        )

    assert len(statements) <= 5
    assert {e.cost_category.value: e.calculation_fingerprint for e in batch} == {
        c: e.calculation_fingerprint for c, e in singles.items()
    }


def test_the_evaluation_is_deterministic(golden: Golden) -> None:
    first, second = (
        golden.evaluate("2026-08", "LAUNDRY", "EUR"),
        golden.evaluate("2026-08", "LAUNDRY", "EUR"),
    )
    assert first == second and first.calculation_fingerprint == second.calculation_fingerprint


def test_evaluating_the_whole_world_writes_nothing(golden: Golden) -> None:
    def snapshot() -> list[Any]:
        return [
            golden.session.execute(
                text(
                    "SELECT count(*), md5(string_agg(md5(CAST(t AS text)), '' ORDER BY 1))"
                    f" FROM {table} t"
                )
            ).one()
            for table in ("booking_snapshots", "invoices", "invoice_lines", "suppliers", "bookings")
        ]

    before = snapshot()
    with statements_of(golden.session) as statements:
        for name in CASES:
            check_case(golden, name)
    assert snapshot() == before
    kinds = {s.lstrip().split()[0].upper() for s, _ in statements}
    assert kinds == {"SELECT"}, kinds  # never an INSERT, UPDATE, DELETE or lock
    assert not golden.session.new and not golden.session.dirty and not golden.session.deleted


def test_no_decision_priority_or_cost_metric_table_exists() -> None:
    names = " ".join(sorted(Base.metadata.tables))
    for word in ("decision", "priority", "recommendation", "cpor", "cost_metric", "baseline_cost"):
        assert word not in names, word


def test_another_workspace_cannot_evaluate_this_property(golden: Golden) -> None:
    stranger = golden.factory.workspace()
    service = CostDecisionService(golden.session, TenantContext(stranger.id))

    with pytest.raises(CostDecisionError) as error:
        service.evaluate_cpor_anomaly(
            property_id=golden.prop.id,
            booking_data_source_id=golden.booking_source.id,
            year=2026,
            month=8,
            cost_category=CostCategory.LAUNDRY,
            currency="EUR",
        )

    assert error.value.error_code == CostErrorCode.INVALID_PROPERTY


def test_the_costs_data_sources_are_not_valid_denominators(golden: Golden) -> None:
    for source in (golden.xml_source, golden.csv_source):
        with pytest.raises(CostDecisionError) as error:
            golden.service().evaluate_cpor_anomaly(
                property_id=golden.prop.id,
                booking_data_source_id=source.id,
                year=2026,
                month=8,
                cost_category=CostCategory.LAUNDRY,
                currency="EUR",
            )
        assert error.value.error_code == CostErrorCode.BOOKING_DATA_SOURCE_INVALID


def test_a_triggered_evaluation_can_be_explained_from_its_facts_alone(golden: Golden) -> None:
    facts = golden.evaluate("2026-08", "LAUNDRY", "EUR").payload()
    metric = facts["target_metric"]

    assert (metric["period_start"], metric["cost_category"], metric["currency"]) == (
        "2026-08-01",
        "LAUNDRY",
        "EUR",
    )
    for key in ("invoice_count", "line_count", "credit_note_cost", "occupied_room_nights"):
        assert key in metric
    assert (metric["observed_day_count"], metric["reconstructed_day_count"]) == (31, 0)
    for key in (
        "expected_cpor",
        "p25",
        "p75",
        "iqr",
        "upper_fence",
        "delta_cpor",
        "delta_percent",
        "expected_cost_for_target_volume",
        "cost_gap_proxy",
        "baseline_confidence",
        "target_quality",
        "confidence_score",
        "sample_score",
        "provenance_score",
        "classification_score",
        "stability_score",
    ):
        assert facts[key] is not None, key
    assert (
        len(facts["comparable_periods"]) == 10 and facts["thresholds"]["min_confidence"] == "55.00"
    )
    assert facts["reason_codes"] == ["TRIGGER_CPOR_ANOMALY"]


def test_the_golden_files_are_reproducible_from_the_generator() -> None:
    """Running the generator changes no committed byte (it is deterministic)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cost_intelligence_generator",
        FIXTURE_DIR / "generate_masseria_cost_intelligence_expected.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.build()
    expected_text = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert (FIXTURE_DIR / "masseria_ninfa_cost_intelligence_v1.expected.json").read_bytes() == (
        expected_text.encode("utf-8")
    )
    assert (FIXTURE_DIR / "masseria_ninfa_cost_bookings_v1.csv").read_bytes() == module.csv_of(
        module.booking_rows()
    ).encode("utf-8")
    for name, (supplier, currency) in module.XML_FILES.items():
        assert (FIXTURE_DIR / "invoices" / name).read_bytes() == module.xml_file(
            supplier, currency
        ).encode("utf-8"), name
    assert (FIXTURE_DIR / "invoices" / "software.csv").read_bytes() == module.software_csv().encode(
        "utf-8"
    )
    assert isinstance(UUID(int=0), UUID)  # (keeps the import used for type documentation)
