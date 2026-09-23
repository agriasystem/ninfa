"""The labor side of a work date: raw entry rows -> target plan facts / one comparable day (pure).

Reads no database and no clock: everything here takes already-loaded `LaborEntryRow`s. A row is
the minimal projection of a `LaborEntry` this module needs (see `intelligence.labor.repository`).

ACTUAL-FIRST POLICY (Part D): for a work date's TARGET-CATEGORY rows, use ACTUAL minutes only when
EVERY row has one; else use PLANNED minutes only when EVERY row has one; else the day has no usable
labor data. Never half-actual, half-planned. The SAME basis then decides classification coverage
for the whole day (every category, not just the target one): a row without that basis field simply
does not participate (there is no minutes value to classify on that basis).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID

from app.modules.intelligence.labor.precision import (
    CALCULATION_CONTEXT,
    exact_sum,
    for_display,
    percent_of,
)
from app.modules.intelligence.labor.types import LaborBasis
from app.modules.labor.roles import LaborCategory

_SIXTY = Decimal(60)


class LaborEntryRow(NamedTuple):
    """The minimal projection of a `LaborEntry` the aggregation needs (one row per entry)."""

    labor_snapshot_id: UUID
    labor_category: LaborCategory
    planned_minutes: int | None
    actual_minutes: int | None
    planned_cost: Decimal | None
    actual_cost: Decimal | None
    currency: str | None
    classification_confidence: Decimal


class RawLaborEntryRow(NamedTuple):
    """One `LaborEntry` row as read from the database, with the `snapshot_local_date` of the
    snapshot it belongs to (the repository's projection, grouped here by `latest_snapshot_rows_
    by_work_date` before anything else in this module sees it)."""

    labor_snapshot_id: UUID
    snapshot_local_date: date
    work_date: date
    labor_category: LaborCategory
    planned_minutes: int | None
    actual_minutes: int | None
    planned_cost: Decimal | None
    actual_cost: Decimal | None
    currency: str | None
    classification_confidence: Decimal


@dataclass(frozen=True, slots=True)
class ClassificationQuality:
    """Coverage and weighted confidence of a set of rows, on ONE basis (actual or planned)."""

    total_minutes: int
    classified_minutes: int
    coverage_pct_exact: Decimal | None  # None <=> total_minutes == 0 (never divide by zero)
    weighted_confidence_exact: Decimal | None  # None <=> classified_minutes == 0


@dataclass(frozen=True, slots=True)
class TargetPlan:
    """Everything Part C needs about the target work date's plan for ONE category.

    `complete` is False when the category has at least one row but NOT every row has
    `planned_minutes` (INSUFFICIENT_DATA / LABOR_PLAN_INCOMPLETE, decided by the caller); the
    other fields are then zero/undefined and must not be used.
    """

    complete: bool
    scheduled_minutes: int
    scheduled_hours_exact: Decimal
    quality: ClassificationQuality
    target_plan_quality: Decimal | None  # None <=> quality.coverage/confidence undefined


@dataclass(frozen=True, slots=True)
class HistoricalDay:
    """Everything Part D/H need about ONE historical work date's labor side."""

    basis: LaborBasis
    category_minutes: int
    category_hours_exact: Decimal
    category_cost_exact: Decimal | None
    cost_currency: str | None
    quality: ClassificationQuality


def latest_snapshot_rows_by_work_date(
    rows: Sequence[RawLaborEntryRow],
) -> dict[date, tuple[UUID, list[LaborEntryRow]]]:
    """For each work date, the entries of the MOST RECENT labor snapshot that covers it.

    A rolling near-term export (each snapshot covers only the next few weeks) and a full-horizon
    export (every snapshot restates the whole plan) are both handled correctly: different work
    dates may legitimately resolve to different labor snapshots.
    """
    winning_snapshot_local_date: dict[date, date] = {}
    winning_snapshot_id: dict[date, UUID] = {}
    for row in rows:
        current = winning_snapshot_local_date.get(row.work_date)
        if current is None or row.snapshot_local_date > current:
            winning_snapshot_local_date[row.work_date] = row.snapshot_local_date
            winning_snapshot_id[row.work_date] = row.labor_snapshot_id
    grouped: dict[date, list[LaborEntryRow]] = {}
    for row in rows:
        if row.labor_snapshot_id == winning_snapshot_id.get(row.work_date):
            grouped.setdefault(row.work_date, []).append(
                LaborEntryRow(
                    labor_snapshot_id=row.labor_snapshot_id,
                    labor_category=row.labor_category,
                    planned_minutes=row.planned_minutes,
                    actual_minutes=row.actual_minutes,
                    planned_cost=row.planned_cost,
                    actual_cost=row.actual_cost,
                    currency=row.currency,
                    classification_confidence=row.classification_confidence,
                )
            )
    return {
        work_date: (winning_snapshot_id[work_date], entries)
        for work_date, entries in grouped.items()
    }


def _basis_minutes(row: LaborEntryRow, basis: LaborBasis) -> int | None:
    return row.actual_minutes if basis is LaborBasis.ACTUAL else row.planned_minutes


def classification_quality(
    rows: Sequence[LaborEntryRow], basis: LaborBasis
) -> ClassificationQuality:
    """Coverage/confidence of every row that HAS a value on `basis` (a row without one simply
    does not participate: there is no minutes value of that basis to classify)."""
    participating = [row for row in rows if _basis_minutes(row, basis) is not None]
    total = sum(_basis_minutes(row, basis) or 0 for row in participating)
    if total == 0:
        return ClassificationQuality(0, 0, None, None)
    classified_rows = [row for row in participating if row.labor_category != LaborCategory.OTHER]
    classified = sum(_basis_minutes(row, basis) or 0 for row in classified_rows)
    coverage = percent_of(Decimal(classified), Decimal(total))
    weighted_confidence: Decimal | None = None
    if classified > 0:
        numerator = exact_sum(
            Decimal(_basis_minutes(row, basis) or 0) * row.classification_confidence
            for row in classified_rows
        )
        weighted_confidence = CALCULATION_CONTEXT.divide(numerator, Decimal(classified))
    return ClassificationQuality(total, classified, coverage, weighted_confidence)


def target_plan_quality_of(
    coverage_pct: Decimal | None, weighted_confidence: Decimal | None
) -> Decimal | None:
    """0.60 * weighted category confidence + 0.40 * classification coverage (HALF_UP, 2 dp)."""
    if coverage_pct is None or weighted_confidence is None:
        return None
    raw = CALCULATION_CONTEXT.add(
        CALCULATION_CONTEXT.multiply(Decimal("0.60"), weighted_confidence),
        CALCULATION_CONTEXT.multiply(Decimal("0.40"), coverage_pct),
    )
    return for_display(raw)


def build_target_plan(
    day_rows: Sequence[LaborEntryRow], target_category: LaborCategory
) -> TargetPlan | None:
    """The target plan of ONE work date for ONE category, or None when the category has NO row
    at all that day (NOT_APPLICABLE / LABOR_CATEGORY_NOT_SCHEDULED, decided by the caller)."""
    category_rows = [row for row in day_rows if row.labor_category == target_category]
    if not category_rows:
        return None
    if not all(row.planned_minutes is not None for row in category_rows):
        # Partial planned minutes on the requested category: INSUFFICIENT_DATA, decided by caller.
        return TargetPlan(
            complete=False,
            scheduled_minutes=0,
            scheduled_hours_exact=Decimal(0),
            quality=ClassificationQuality(0, 0, None, None),
            target_plan_quality=None,
        )
    scheduled_minutes = sum(row.planned_minutes or 0 for row in category_rows)
    quality = classification_quality(day_rows, LaborBasis.PLANNED_FALLBACK)
    return TargetPlan(
        complete=True,
        scheduled_minutes=scheduled_minutes,
        scheduled_hours_exact=CALCULATION_CONTEXT.divide(Decimal(scheduled_minutes), _SIXTY),
        quality=quality,
        target_plan_quality=target_plan_quality_of(
            quality.coverage_pct_exact, quality.weighted_confidence_exact
        ),
    )


def build_historical_day(
    day_rows: Sequence[LaborEntryRow], target_category: LaborCategory
) -> HistoricalDay | None:
    """The historical labor side of ONE work date for ONE category, ACTUAL-FIRST.

    Returns None when neither ACTUAL nor PLANNED is complete on the target category (REJECT, the
    day never enters the sample). An empty category (nothing scheduled that day) is a real zero,
    not a rejection: it uses ACTUAL with zero minutes.
    """
    category_rows = [row for row in day_rows if row.labor_category == target_category]
    if not category_rows:
        basis = LaborBasis.ACTUAL
        minutes = 0
        cost: Decimal | None = None
        currency: str | None = None
    elif all(row.actual_minutes is not None for row in category_rows):
        basis = LaborBasis.ACTUAL
        minutes = sum(row.actual_minutes or 0 for row in category_rows)
        costs = [row.actual_cost for row in category_rows if row.actual_cost is not None]
        currencies = {row.currency for row in category_rows if row.actual_cost is not None}
        cost = exact_sum(costs) if costs and len(currencies) == 1 else None
        currency = next(iter(currencies)) if len(currencies) == 1 and costs else None
    elif all(row.planned_minutes is not None for row in category_rows):
        basis = LaborBasis.PLANNED_FALLBACK
        minutes = sum(row.planned_minutes or 0 for row in category_rows)
        cost = None
        currency = None
    else:
        return None  # neither actual nor planned is complete: REJECT

    quality = classification_quality(day_rows, basis)
    if quality.coverage_pct_exact is None:
        return None  # nothing to classify on this basis at all: REJECT (undefined coverage)
    return HistoricalDay(
        basis=basis,
        category_minutes=minutes,
        category_hours_exact=CALCULATION_CONTEXT.divide(Decimal(minutes), _SIXTY),
        category_cost_exact=cost,
        cost_currency=currency,
        quality=quality,
    )
