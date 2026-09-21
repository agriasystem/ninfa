"""The cost side of a period and the assembly of a CostPeriodMetric (pure).

Cost of a month = the signed Gate 6 `line_total` of the canonical invoice lines whose INVOICE DATE
falls in the month (INVOICE_DATE_ATTRIBUTION, an explicit V1 policy: no service period, no
competence, no accrual, no prepayment allocation), of one category and ONE currency (no FX, ever).
Credit notes are already negative and are never re-signed; the data source of an invoice is not
looked at (Gate 6 made the invoice identity cross-source).

Quality of a month, over every category of the SAME currency:

    coverage   = SUM(abs) of the lines that are not OTHER  /  SUM(abs) of all the lines   * 100
    confidence = SUM(abs * classification_confidence) / SUM(abs), over the classified lines

`abs` is used so that +1000 and -1000 do not look like "no activity". A month is READY only when
it has cost lines of the category, a complete non-zero occupancy denominator and a coverage of at
least 70 %. No number is guessed: whatever is missing is named in `reason_codes`.
"""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.modules.intelligence.costs.fingerprint import metric_fingerprint
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.precision import CALCULATION_CONTEXT, exact_sum, percent_of
from app.modules.intelligence.costs.types import (
    MIN_CLASSIFICATION_COVERAGE,
    CostPeriodMetric,
    MetricStatus,
    MonthlyCostAggregate,
    OccupancyDenominator,
    ReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory

# (first day of the month, currency) -> category -> aggregate
CostIndex = dict[tuple[date, str], dict[CostCategory, MonthlyCostAggregate]]


def index_costs(rows: Iterable[MonthlyCostAggregate]) -> CostIndex:
    index: CostIndex = {}
    for row in rows:
        index.setdefault((row.month, row.currency), {})[row.cost_category] = row
    return index


def build_period_metric(
    *,
    workspace_id: UUID,
    property_id: UUID,
    booking_data_source_id: UUID,
    month: CalendarMonth,
    cost_category: CostCategory,
    currency: str,
    costs: Mapping[tuple[date, str], Mapping[CostCategory, MonthlyCostAggregate]],
    denominator: OccupancyDenominator,
    min_coverage: Decimal = MIN_CLASSIFICATION_COVERAGE,
) -> CostPeriodMetric:
    """The metric of one (month, category, currency), sealed with its own fingerprint."""
    by_category = costs.get((month.start, currency), {})
    own = by_category.get(cost_category)

    total_abs: Decimal | None = None
    classified_abs: Decimal | None = None
    coverage: Decimal | None = None
    weighted_confidence: Decimal | None = None
    if by_category:
        total_abs = exact_sum(a.absolute_cost for a in by_category.values())
        classified = [a for c, a in by_category.items() if c != CostCategory.OTHER]
        classified_abs = exact_sum(a.absolute_cost for a in classified)
        if total_abs > 0:
            coverage = percent_of(classified_abs, total_abs)
        if classified_abs > 0:
            numerator = exact_sum(a.confidence_weighted_cost for a in classified)
            weighted_confidence = CALCULATION_CONTEXT.divide(numerator, classified_abs)

    cpor: Decimal | None = None
    reasons: tuple[ReasonCode, ...]
    if not by_category:
        status, reasons = MetricStatus.NO_COST_DATA, (ReasonCode.COST_CURRENCY_NOT_PRESENT,)
    elif own is None:
        status, reasons = MetricStatus.NO_COST_DATA, (ReasonCode.COST_CATEGORY_NOT_PRESENT,)
    elif not denominator.complete:
        status, reasons = MetricStatus.INCOMPLETE, (ReasonCode.OCCUPANCY_PERIOD_INCOMPLETE,)
    elif denominator.occupied_room_nights == 0:
        status, reasons = MetricStatus.ZERO_OCCUPANCY, (ReasonCode.ZERO_OCCUPIED_ROOM_NIGHTS,)
    elif coverage is None:
        status = MetricStatus.LOW_CLASSIFICATION_COVERAGE
        reasons = (ReasonCode.COST_CLASSIFICATION_COVERAGE_UNDEFINED,)
    elif coverage < min_coverage:
        status = MetricStatus.LOW_CLASSIFICATION_COVERAGE
        reasons = (ReasonCode.COST_CLASSIFICATION_COVERAGE_LOW,)
    else:
        status, reasons = MetricStatus.READY, ()
        assert denominator.occupied_room_nights is not None
        cpor = CALCULATION_CONTEXT.divide(own.net_cost, Decimal(denominator.occupied_room_nights))

    metric = CostPeriodMetric(
        workspace_id=workspace_id,
        property_id=property_id,
        booking_data_source_id=booking_data_source_id,
        period_start=month.start,
        period_end=month.end,
        cost_category=cost_category,
        currency=currency,
        net_cost=None if own is None else own.net_cost,
        absolute_category_cost=None if own is None else own.absolute_cost,
        total_absolute_cost=total_abs,
        classified_absolute_cost=classified_abs,
        classification_coverage_pct_exact=coverage,
        weighted_classification_confidence_exact=weighted_confidence,
        occupied_room_nights=denominator.occupied_room_nights,
        observed_day_count=denominator.observed_day_count,
        reconstructed_day_count=denominator.reconstructed_day_count,
        missing_day_count=denominator.missing_day_count,
        uncertain_day_count=denominator.uncertain_day_count,
        occupancy_provenance_score_exact=denominator.occupancy_provenance_score_exact,
        invoice_count=0 if own is None else own.invoice_count,
        line_count=0 if own is None else own.line_count,
        credit_note_line_count=0 if own is None else own.credit_note_line_count,
        credit_note_cost=None if own is None else own.credit_note_cost,
        cpor_exact=cpor,
        status=status,
        reason_codes=reasons,
    )
    return replace(metric, calculation_fingerprint=metric_fingerprint(metric))
