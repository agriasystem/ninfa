"""The Costi block of the Dati overview: the last CONCLUDED month's costs, by category.

Nothing is defined here. The cost of a month is Cost CPOR V1's own: the signed `line_total` of the
canonical invoice lines whose INVOICE DATE falls in the calendar month (`INVOICE_DATE_ATTRIBUTION`
- no accrual, no service period), of one currency (NINFA never converts). The cost per occupied
room (CPOR) is that module's own `build_period_metric`, over the lead-time-0 snapshots of the
run's booking source. Only a concluded month is shown: invoices arrive after the fact, so the
month in progress is not a cost of the month - the same reason the cost detector evaluates
concluded months only.

Costs are property-wide and cross-source by design (an invoice is one document whatever source
imported it), so no cost data source needs to be chosen. Read-only; no clock.
"""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.data_overview.metrics import to_cents
from app.modules.data_overview.types import (
    Availability,
    CostCategoryRow,
    CostDecisionFacts,
    CostOverview,
    CporStatus,
    UnavailableReason,
)
from app.modules.decision_memory.types import FeedItem
from app.modules.intelligence.costs.aggregation import build_period_metric, index_costs
from app.modules.intelligence.costs.occupancy import (
    build_denominator,
    index_lead_zero,
    lead_zero_keys,
)
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.intelligence.costs.types import MonthlyCostAggregate, OccupancyDenominator
from app.modules.invoices.cost_categories import CostCategory
from app.modules.snapshots.repository import BookingSnapshotRepository

_HUNDRED = Decimal(100)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _iso(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def last_concluded_month(as_of: date) -> CalendarMonth:
    """The calendar month before the one `as_of` belongs to."""
    return CalendarMonth.of(as_of).shifted(-1)


class CostOverviewReader:
    """Read-only. Pass any session: it neither commits nor rolls back, and reads no clock."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._tenant = tenant
        self._costs = CostLineRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)

    def read(
        self,
        *,
        property_id: UUID,
        as_of: date,
        currency: str,
        source_id: UUID | None,
        cost_decision: FeedItem | None,
    ) -> CostOverview:
        month = last_concluded_month(as_of)
        previous = month.shifted(-1)
        aggregates = self._costs.monthly_aggregates(property_id, previous.start, month.end)
        index = index_costs(aggregates)

        decision = self._decision_facts(cost_decision)
        in_month = index.get((month.start, currency), {})
        other_currencies = any(
            row.month == month.start and row.currency != currency for row in aggregates
        )
        if not in_month:
            return CostOverview(
                state=Availability.NOT_AVAILABLE,
                reason=UnavailableReason.NO_DATA,
                month_start=month.start,
                month_end=month.end,
                previous_month_start=previous.start,
                currency=currency,
                total_net_cost=None,
                previous_total_net_cost=None,
                delta_pct=None,
                other_currencies_present=other_currencies,
                classification_coverage_pct=None,
                categories=(),
                decision=decision,
            )

        total = _sum_net(in_month.values())
        previous_rows = index.get((previous.start, currency), {})
        previous_total = _sum_net(previous_rows.values()) if previous_rows else None

        denominator: OccupancyDenominator | None = None
        if source_id is not None:
            snapshot_rows = self._snapshots.list_by_keys(source_id, lead_zero_keys(month))
            denominator = build_denominator(month, index_lead_zero(snapshot_rows))

        categories = tuple(
            self._category_row(
                category,
                aggregate,
                property_id=property_id,
                month=month,
                currency=currency,
                index=index,
                source_id=source_id,
                denominator=denominator,
                decision=decision,
            )
            for category, aggregate in sorted(
                in_month.items(), key=lambda item: (-item[1].net_cost, item[0].value)
            )
        )
        return CostOverview(
            state=Availability.AVAILABLE,
            reason=None,
            month_start=month.start,
            month_end=month.end,
            previous_month_start=previous.start,
            currency=currency,
            total_net_cost=to_cents(total),
            previous_total_net_cost=None if previous_total is None else to_cents(previous_total),
            delta_pct=_delta_pct(total, previous_total),
            other_currencies_present=other_currencies,
            classification_coverage_pct=_coverage(in_month.values()),
            categories=categories,
            decision=decision,
        )

    def _category_row(
        self,
        category: CostCategory,
        aggregate: MonthlyCostAggregate,
        *,
        property_id: UUID,
        month: CalendarMonth,
        currency: str,
        index: dict[tuple[date, str], dict[CostCategory, MonthlyCostAggregate]],
        source_id: UUID | None,
        denominator: OccupancyDenominator | None,
        decision: CostDecisionFacts | None,
    ) -> CostCategoryRow:
        has_decision = (
            decision is not None
            and decision.period_start == month.start
            and decision.category == category.value
        )
        decision_id = decision.decision_id if has_decision and decision is not None else None
        if category is CostCategory.OTHER:
            status, cpor = CporStatus.NOT_APPLICABLE, None
        elif source_id is None or denominator is None:
            status, cpor = CporStatus.NO_OCCUPANCY_SOURCE, None
        else:
            metric = build_period_metric(
                workspace_id=self._tenant.workspace_id,
                property_id=property_id,
                booking_data_source_id=source_id,
                month=month,
                cost_category=category,
                currency=currency,
                costs=index,
                denominator=denominator,
            )
            status = CporStatus(metric.status.value)
            cpor = None if metric.cpor_exact is None else to_cents(metric.cpor_exact)
        return CostCategoryRow(
            category=category.value,
            net_cost=to_cents(aggregate.net_cost),
            cpor=cpor,
            cpor_status=status,
            decision_id=decision_id,
        )

    @staticmethod
    def _decision_facts(item: FeedItem | None) -> CostDecisionFacts | None:
        if item is None:
            return None
        identity = item.decision.identity_payload
        facts = item.observation.facts_payload
        period_start = _iso(identity.get("target_period_start"))
        category = identity.get("cost_category")
        if period_start is None or not isinstance(category, str):
            return None
        currency = identity.get("currency")
        actual = _decimal(facts.get("actual_cpor_exact"))
        expected = _decimal(facts.get("expected_cpor_exact"))
        return CostDecisionFacts(
            decision_id=item.decision.id,
            period_start=period_start,
            category=category,
            currency=currency if isinstance(currency, str) else None,
            actual_cpor=None if actual is None else to_cents(actual),
            expected_cpor=None if expected is None else to_cents(expected),
        )


def _sum_net(rows: Iterable[MonthlyCostAggregate]) -> Decimal:
    total = Decimal(0)
    for row in rows:
        total += row.net_cost
    return total


def _delta_pct(current: Decimal, previous: Decimal | None) -> Decimal | None:
    """The change against the previous month, in percent - only when there is a positive base to
    compare with (a percentage of zero, or of a net credit, is not defined)."""
    if previous is None or previous <= 0:
        return None
    return to_cents((current - previous) * _HUNDRED / previous)


def _coverage(rows: Iterable[MonthlyCostAggregate]) -> Decimal | None:
    """Share of the month's absolute cost that sits in a real category (not OTHER)."""
    total = classified = Decimal(0)
    for row in rows:
        total += row.absolute_cost
        if row.cost_category is not CostCategory.OTHER:
            classified += row.absolute_cost
    if total <= 0:
        return None
    return to_cents(classified * _HUNDRED / total)


__all__ = ["CostOverviewReader", "last_concluded_month"]
