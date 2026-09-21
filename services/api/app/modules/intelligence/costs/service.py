"""CostDecisionService: builds cost period metrics and evaluates COST_CPOR_ANOMALY.

    validate -> load the cost aggregates and the lead-time-0 snapshots (set-based) -> evaluate

The service is READ-ONLY: it writes nothing, never commits or rolls back, takes no advisory lock
and reads no clock (the target month is always passed in, so a run can be replayed and
back-tested). It persists no Decision (there is no such table): an evaluation is a value returned
to the caller. All the database work is a fixed handful of statements whatever the number of
categories, days or historical months: the property, the data source, ONE aggregate of the
canonical invoice lines of the whole history window and ONE keyed read of the lead-time-0
snapshots of the months involved.

The booking data source is always explicit: the occupancy denominator must have a stated
provenance, so it is never chosen automatically. Costs are NOT filtered by data source (the
Gate 6 invoice identity is cross-source). Everything is read through the repositories of the
TenantContext: a property, source or invoice of another workspace simply does not exist here.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.costs.aggregation import CostIndex, build_period_metric, index_costs
from app.modules.intelligence.costs.detector import evaluate_cpor_anomaly
from app.modules.intelligence.costs.errors import CostDecisionError, CostErrorCode
from app.modules.intelligence.costs.occupancy import (
    build_denominator,
    index_lead_zero,
    lead_zero_keys,
)
from app.modules.intelligence.costs.periods import CalendarMonth
from app.modules.intelligence.costs.repository import CostLineRepository
from app.modules.intelligence.costs.selection import (
    ComparableSelection,
    candidate_months,
    select_comparables,
)
from app.modules.intelligence.costs.types import (
    COST_THRESHOLDS,
    CostDecisionEvaluation,
    CostPeriodMetric,
    CostThresholds,
    ReasonCode,
)
from app.modules.invoices.cost_categories import CostCategory
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotHistoryRow

logger = logging.getLogger(__name__)

_CURRENCY = re.compile(r"^[A-Z]{3}$")
MIN_YEAR, MAX_YEAR = 1970, 2100
# The categories a month is evaluated for by default: every one except OTHER (which is a data
# quality bucket, not an operating category).
OPERATING_CATEGORIES: tuple[CostCategory, ...] = tuple(
    category for category in CostCategory if category != CostCategory.OTHER
)


@dataclass(frozen=True, slots=True)
class _Scope:
    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID


@dataclass(frozen=True, slots=True)
class _Dataset:
    """Everything one request reads, fetched set-based; the calculation itself is pure."""

    scope: _Scope
    costs: CostIndex
    lead_zero: dict[CalendarMonth, dict[date, SnapshotHistoryRow]]

    def metric(
        self, month: CalendarMonth, category: CostCategory, currency: str
    ) -> CostPeriodMetric:
        rows = self.lead_zero.get(month, {})
        return build_period_metric(
            workspace_id=self.scope.workspace_id,
            property_id=self.scope.property_id,
            booking_data_source_id=self.scope.booking_data_source_id,
            month=month,
            cost_category=category,
            currency=currency,
            costs=self.costs,
            denominator=build_denominator(month, rows),
        )

    def evaluate(
        self,
        target: CalendarMonth,
        category: CostCategory,
        currency: str,
        thresholds: CostThresholds,
    ) -> CostDecisionEvaluation:
        def select() -> ComparableSelection:
            return select_comparables(
                target,
                lambda month: self.metric(month, category, currency),
                min_comparables=thresholds.min_comparables,
                max_comparables=thresholds.max_comparables,
                lookback_months=thresholds.lookback_months,
                season_window_months=thresholds.season_window_months,
            )

        return evaluate_cpor_anomaly(self.metric(target, category, currency), select, thresholds)


class CostDecisionService:
    """Read-only. Pass any session: the service neither commits nor rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Cost Decision service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._costs = CostLineRepository(session, tenant)

    # --- public API ---------------------------------------------------------------------------

    def build_period_metric(
        self,
        *,
        property_id: UUID,
        booking_data_source_id: UUID,
        year: int,
        month: int,
        cost_category: CostCategory,
        currency: str,
    ) -> CostPeriodMetric:
        """The CPOR metric of ONE calendar month, category and currency (no history is read)."""
        target = _month(year, month)
        _category(cost_category)
        _currency(currency)
        scope = self._validate(property_id, booking_data_source_id)
        dataset = self._load(scope, target, months=[target], history=False)
        return dataset.metric(target, cost_category, currency)

    def evaluate_cpor_anomaly(
        self,
        *,
        property_id: UUID,
        booking_data_source_id: UUID,
        year: int,
        month: int,
        cost_category: CostCategory,
        currency: str,
    ) -> CostDecisionEvaluation:
        """COST_CPOR_ANOMALY for ONE calendar month, category and currency."""
        [evaluation] = self._evaluate(
            property_id, booking_data_source_id, year, month, [cost_category], currency
        )
        return evaluation

    def evaluate_month(
        self,
        *,
        property_id: UUID,
        booking_data_source_id: UUID,
        year: int,
        month: int,
        currency: str,
        cost_categories: Sequence[CostCategory] | None = None,
    ) -> tuple[CostDecisionEvaluation, ...]:
        """COST_CPOR_ANOMALY for several categories of ONE month and currency, in the order given
        (default: every operating category, that is every one but OTHER). The history is read
        ONCE for the whole batch."""
        categories = list(OPERATING_CATEGORIES if cost_categories is None else cost_categories)
        return self._evaluate(
            property_id, booking_data_source_id, year, month, categories, currency
        )

    # --- validation ---------------------------------------------------------------------------

    def _validate(self, property_id: UUID, booking_data_source_id: UUID) -> _Scope:
        """The property and the BOOKINGS data source must be usable and belong to this workspace
        (a foreign id and an unknown id are indistinguishable)."""
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise CostDecisionError(
                CostErrorCode.INVALID_PROPERTY,
                "The property cannot be used for Cost Decision Detection",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        source = self._data_sources.get(booking_data_source_id)
        reason = None
        if source is None:
            reason = "not_found"
        elif source.domain != DataSourceDomain.BOOKINGS:
            reason = "wrong_domain"
        elif not source.is_active:
            reason = "inactive"
        elif source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise CostDecisionError(
                CostErrorCode.BOOKING_DATA_SOURCE_INVALID,
                "The data source cannot be used as the occupancy denominator",
                details={
                    "reason": reason,
                    "reason_code": ReasonCode.BOOKING_DATA_SOURCE_INVALID.value,
                },
            )
        return _Scope(self._tenant.workspace_id, prop.id, booking_data_source_id)

    # --- the evaluation -----------------------------------------------------------------------

    def _evaluate(
        self,
        property_id: UUID,
        booking_data_source_id: UUID,
        year: int,
        month: int,
        categories: Sequence[CostCategory],
        currency: str,
    ) -> tuple[CostDecisionEvaluation, ...]:
        target = _month(year, month)
        for category in categories:
            _category(category)
        _currency(currency)
        scope = self._validate(property_id, booking_data_source_id)
        needed = [target, *candidate_months(target)]
        dataset = self._load(scope, target, months=needed, history=True)
        evaluations = tuple(
            dataset.evaluate(target, category, currency, COST_THRESHOLDS) for category in categories
        )
        logger.info(
            "cost cpor evaluated workspace_id=%s property_id=%s data_source_id=%s "
            "period=%s-%02d targets=%d",
            scope.workspace_id,
            scope.property_id,
            scope.booking_data_source_id,
            target.year,
            target.month,
            len(evaluations),
        )
        return evaluations

    def _load(
        self,
        scope: _Scope,
        target: CalendarMonth,
        *,
        months: Sequence[CalendarMonth],
        history: bool,
    ) -> _Dataset:
        """Two statements: the cost aggregates of the window and the lead-time-0 snapshots."""
        first = target.shifted(-COST_THRESHOLDS.lookback_months).start if history else target.start
        aggregates = self._costs.monthly_aggregates(scope.property_id, first, target.end)
        keys = [key for month in months for key in lead_zero_keys(month)]
        rows = self._snapshots.list_by_keys(scope.booking_data_source_id, keys)
        by_day = index_lead_zero(rows)
        lead_zero = {
            month: {day: by_day[day] for day in month.day_list() if day in by_day}
            for month in months
        }
        return _Dataset(scope, index_costs(aggregates), lead_zero)


def _month(year: int, month: int) -> CalendarMonth:
    for value, reason in ((year, "bad_year"), (month, "bad_month")):
        if isinstance(value, bool) or not isinstance(value, int):
            raise CostDecisionError(
                CostErrorCode.INVALID_PERIOD,
                "The period must be a calendar month given as integers",
                details={"reason": reason},
            )
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise CostDecisionError(
            CostErrorCode.INVALID_PERIOD,
            f"The year must be between {MIN_YEAR} and {MAX_YEAR}",
            details={"reason": "bad_year"},
        )
    if not 1 <= month <= 12:
        raise CostDecisionError(
            CostErrorCode.INVALID_PERIOD,
            "The month must be between 1 and 12",
            details={"reason": "bad_month"},
        )
    return CalendarMonth(year, month)


def _category(category: object) -> None:
    if not isinstance(category, CostCategory):
        raise CostDecisionError(
            CostErrorCode.INVALID_CATEGORY, "The cost category must be a CostCategory"
        )


def _currency(currency: object) -> None:
    if not isinstance(currency, str) or not _CURRENCY.match(currency):
        raise CostDecisionError(
            CostErrorCode.INVALID_CURRENCY,
            "The currency must be three upper-case letters: NINFA never converts currencies",
        )
