"""The Personale block of the Dati overview: planned hours of the next 7 days, by category.

Nothing is defined here. The entries are the canonical labor entries (Labor ingestion V1) and a
work date's entries are those of the MOST RECENT labor snapshot that covers it
(`latest_snapshot_rows_by_ work_date`, the labor detector's own rule). A day's hours of a category
are used only when EVERY entry of that day and category has planned minutes - never half known,
the detector's own "actual-first" spirit applied to the plan: an incomplete day is counted and
left out, not guessed.

No incidence, productivity, FTE or labor-cost-to-revenue ratio is calculated: NINFA defines none.
The labor source is the property's ONE active labor source (`sources.PropertySources`); the
automatic analysis skips labor, so there is no "source the run used" to follow. Read-only; no
clock."""

from collections import defaultdict
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
    LaborOverview,
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
            )

        if source_id is None:
            return unavailable(source_reason or UnavailableReason.NO_SOURCE)

        days = [as_of + timedelta(days=offset) for offset in range(LABOR_WINDOW_DAYS)]
        raw = self._repository.entries_as_of(source_id, as_of, days)
        by_date = latest_snapshot_rows_by_work_date(raw)
        if not by_date:
            return unavailable(UnavailableReason.NO_DATA)

        minutes: dict[str, int] = defaultdict(int)
        cost: dict[str, Decimal] = defaultdict(Decimal)
        cost_complete: dict[str, bool] = defaultdict(lambda: True)
        complete_days: dict[str, int] = defaultdict(int)
        incomplete_days: dict[str, int] = defaultdict(int)
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

        categories = tuple(
            LaborCategoryRow(
                category=category,
                planned_hours=_hours(minutes.get(category, 0)),
                days_complete=complete_days.get(category, 0),
                days_incomplete=incomplete_days.get(category, 0),
                planned_cost=(
                    to_cents(cost[category])
                    if complete_days.get(category, 0) > 0 and cost_complete[category]
                    else None
                ),
            )
            for category in sorted(
                set(complete_days) | set(incomplete_days),
                key=lambda name: (-minutes.get(name, 0), name),
            )
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
        )

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


__all__ = ["LABOR_WINDOW_DAYS", "LaborOverviewReader"]
