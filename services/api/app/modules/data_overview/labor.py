"""The Personale block of the Dati overview: planned labor of the next 7 days, and what it weighs.

Nothing about labor is defined here. The entries are the canonical labor entries (Labor ingestion
V1) and a work date's entries are those of the MOST RECENT labor snapshot that covers it
(`latest_snapshot_rows_by_ work_date`, the labor detector's own rule). A day's hours of a category
are used only when EVERY entry of that day and category has planned minutes - never half known,
the detector's own "actual-first" spirit applied to the plan: an incomplete day is counted and
left out, not guessed.

The economics (`economics_of`) are plain divisions of those sums, with the same care:

    average hourly cost   planned cost / planned hours
    incidence on revenue  planned cost / reference revenue * 100
    revenue per hour      reference revenue / planned hours

The reference revenue is the ON-BOOKS room revenue of EXACTLY the days the labor figures are
about, from the stored OBSERVED snapshots of the analysis day: labor of one week never meets the
revenue of another. It is what is booked so far (never a forecast), so a far-off week reads high
on purpose, and the page calls it "on-books". No FTE and no productivity of a person or of a
department: a role has a share of the cost and an incidence, never revenue of its own.

The labor source is the property's ONE active labor source (`sources.PropertySources`). Read-only;
no clock."""

from collections import defaultdict
from collections.abc import Collection, Mapping
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.data_overview.metrics import to_cents
from app.modules.data_overview.types import (
    Availability,
    LaborCategoryRow,
    LaborDecisionFacts,
    LaborEconomics,
    LaborOverview,
    LaborRevenueGap,
    UnavailableReason,
)
from app.modules.decision_memory.types import FeedItem
from app.modules.intelligence.labor.aggregation import (
    LaborEntryRow,
    latest_snapshot_rows_by_work_date,
)
from app.modules.intelligence.labor.repository import LaborEvaluationRepository

LABOR_WINDOW_DAYS = 7
_SIXTY = Decimal(60)
_HUNDRED = Decimal(100)
_NO_ECONOMICS = LaborEconomics(
    planned_hours=None,
    planned_cost=None,
    average_hourly_cost=None,
    period_start=None,
    period_end=None,
    period_days=0,
    reference_revenue=None,
    revenue_gap=LaborRevenueGap.NO_LABOR,
    cost_to_revenue_pct=None,
    revenue_per_hour=None,
)


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


def _hours(minutes: int) -> Decimal:
    return to_cents(Decimal(minutes) / _SIXTY)


def hourly_cost(cost: Decimal | None, minutes: int) -> Decimal | None:
    """Cost per planned hour, from the exact minutes (never from hours already rounded)."""
    if cost is None or minutes <= 0:
        return None
    return to_cents(cost * _SIXTY / Decimal(minutes))


def percent_of_amount(part: Decimal | None, whole: Decimal | None) -> Decimal | None:
    """`part / whole * 100` to two decimals, or None when there is no whole (never a fake 0 %)."""
    if part is None or whole is None or whole <= 0:
        return None
    return to_cents(part * _HUNDRED / whole)


def economics_of(
    *,
    days_with_hours: Collection[date],
    minutes: int,
    cost: Decimal | None,
    has_incomplete_days: bool,
    revenue_by_day: Mapping[date, Decimal] | None,
) -> LaborEconomics:
    """The whole window's figures (pure). `revenue_by_day` is None when the analysis day has no
    observation of the bookings; a day missing from it has no revenue stored: not a zero."""
    if not days_with_hours or minutes <= 0:
        return _NO_ECONOMICS

    def revenue() -> tuple[Decimal | None, LaborRevenueGap | None]:
        if revenue_by_day is None:
            return None, LaborRevenueGap.NO_ANALYSIS
        if any(day not in revenue_by_day for day in days_with_hours):
            return None, LaborRevenueGap.PERIOD_NOT_COVERED
        if has_incomplete_days:
            return None, LaborRevenueGap.LABOR_INCOMPLETE
        total = sum((revenue_by_day[day] for day in days_with_hours), Decimal(0))
        if total <= 0:
            return None, LaborRevenueGap.NO_REVENUE
        return total, None

    reference, gap = revenue()
    return LaborEconomics(
        planned_hours=_hours(minutes),
        planned_cost=None if cost is None else to_cents(cost),
        average_hourly_cost=hourly_cost(cost, minutes),
        period_start=min(days_with_hours),
        period_end=max(days_with_hours),
        period_days=len(days_with_hours),
        reference_revenue=None if reference is None else to_cents(reference),
        revenue_gap=gap,
        cost_to_revenue_pct=percent_of_amount(cost, reference),
        revenue_per_hour=None
        if reference is None
        else to_cents(reference * _SIXTY / Decimal(minutes)),
    )


class LaborOverviewReader:
    """Read-only. Pass any session: it neither commits nor rolls back, and reads no clock."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._repository = LaborEvaluationRepository(session, tenant)

    def read(
        self,
        *,
        as_of: date,
        currency: str,
        source_id: UUID | None,
        source_reason: UnavailableReason | None,
        labor_decision: FeedItem | None,
        revenue_by_day: Mapping[date, Decimal] | None = None,
    ) -> LaborOverview:
        window_end = as_of + timedelta(days=LABOR_WINDOW_DAYS - 1)
        decision = self._decision_facts(labor_decision)

        def unavailable(reason: UnavailableReason) -> LaborOverview:
            return LaborOverview(
                state=Availability.NOT_AVAILABLE,
                reason=reason,
                window_start=as_of,
                window_end=window_end,
                currency=currency,
                days_with_data=0,
                categories=(),
                decision=decision,
                economics=_NO_ECONOMICS,
            )

        if source_id is None:
            return unavailable(source_reason or UnavailableReason.NO_SOURCE)

        days = self.window_days(as_of)
        raw = self._repository.entries_as_of(source_id, as_of, days)
        by_date = latest_snapshot_rows_by_work_date(raw)
        if not by_date:
            return unavailable(UnavailableReason.NO_DATA)

        minutes: dict[str, int] = defaultdict(int)
        cost: dict[str, Decimal] = defaultdict(Decimal)
        cost_complete: dict[str, bool] = defaultdict(lambda: True)
        complete_days: dict[str, int] = defaultdict(int)
        incomplete_days: dict[str, int] = defaultdict(int)
        days_with_hours: set[date] = set()
        for day in days:
            if day not in by_date:
                continue
            groups: dict[str, list[LaborEntryRow]] = defaultdict(list)
            for entry in by_date[day][1]:
                groups[entry.labor_category.value].append(entry)
            for category, entries in groups.items():
                if any(entry.planned_minutes is None for entry in entries):
                    incomplete_days[category] += 1
                    continue
                complete_days[category] += 1
                days_with_hours |= {day}
                minutes[category] += sum(entry.planned_minutes or 0 for entry in entries)
                if all(
                    entry.planned_cost is not None and entry.currency == currency
                    for entry in entries
                ):
                    cost[category] += sum(
                        (entry.planned_cost or Decimal(0) for entry in entries), Decimal(0)
                    )
                else:
                    cost_complete[category] = False

        names = sorted(
            set(complete_days) | set(incomplete_days),
            key=lambda name: (-minutes.get(name, 0), name),
        )

        def cost_of(category: str) -> Decimal | None:
            known = complete_days.get(category, 0) > 0 and cost_complete[category]
            return cost[category] if known else None

        costed = [name for name in names if complete_days.get(name, 0) > 0]
        total_cost: Decimal | None = None
        if costed and all(cost_of(name) is not None for name in costed):
            total_cost = sum((cost[name] for name in costed), Decimal(0))
        economics = economics_of(
            days_with_hours=days_with_hours,
            minutes=sum(minutes.values()),
            cost=total_cost,
            has_incomplete_days=any(incomplete_days.values()),
            revenue_by_day=revenue_by_day,
        )

        categories = tuple(
            LaborCategoryRow(
                category=category,
                planned_hours=_hours(minutes.get(category, 0)),
                days_complete=complete_days.get(category, 0),
                days_incomplete=incomplete_days.get(category, 0),
                planned_cost=None if cost_of(category) is None else to_cents(cost[category]),
                average_hourly_cost=hourly_cost(cost_of(category), minutes.get(category, 0)),
                cost_share_pct=percent_of_amount(cost_of(category), total_cost),
                revenue_incidence_pct=percent_of_amount(
                    cost_of(category), economics.reference_revenue
                ),
            )
            for category in names
        )
        return LaborOverview(
            state=Availability.AVAILABLE,
            reason=None,
            window_start=as_of,
            window_end=window_end,
            currency=currency,
            days_with_data=len(by_date),
            categories=categories,
            decision=decision,
            economics=economics,
        )

    @staticmethod
    def window_days(as_of: date) -> list[date]:
        return [as_of + timedelta(days=offset) for offset in range(LABOR_WINDOW_DAYS)]

    @staticmethod
    def _decision_facts(item: FeedItem | None) -> LaborDecisionFacts | None:
        if item is None:
            return None
        identity = item.decision.identity_payload
        facts = item.observation.facts_payload
        work_date = _iso(identity.get("work_date"))
        category = identity.get("labor_category")
        if work_date is None or not isinstance(category, str):
            return None
        scheduled = _decimal(facts.get("scheduled_hours_exact"))
        expected = _decimal(facts.get("expected_labor_hours_exact"))
        excess = _decimal(facts.get("excess_hours_exact"))
        return LaborDecisionFacts(
            decision_id=item.decision.id,
            work_date=work_date,
            category=category,
            scheduled_hours=None if scheduled is None else to_cents(scheduled),
            expected_hours=None if expected is None else to_cents(expected),
            excess_hours=None if excess is None else to_cents(excess),
        )


__all__ = [
    "LABOR_WINDOW_DAYS",
    "LaborOverviewReader",
    "economics_of",
    "hourly_cost",
    "percent_of_amount",
]
