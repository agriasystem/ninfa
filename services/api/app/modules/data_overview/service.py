"""DataOverviewService: the deterministic, read-only projection behind the Dati page.

    property + analysis day  ->  the run (decisions, coverage, provenance)  ->  the stored facts
                                                                            ->  one DataOverview

The frontend never derives a business figure: every number it shows is read here, from data NINFA
already stores or already calculates (see `types.py`). Nothing is estimated and nothing comes from a
model: this module imports no language-model code, calls no Mia endpoint and has no provider.

Scope and provenance, like every other NINFA read:

* every read goes through the repositories of the request's `TenantContext`; a property of another
  tenant simply does not exist here (`DataOverviewError`);
* bookings come from the run's OWN booking data source (its persisted provenance), never inferred -
  with no run, or a run that recorded no source, there are no booking figures and the page says so;
* the service neither commits nor rolls back, writes nothing, takes no lock and reads no clock:
  `as_of_local_date` is the property-local business date the caller asks about, passed explicitly.
"""

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.data_overview import metrics
from app.modules.data_overview.costs import CostOverviewReader
from app.modules.data_overview.distribution import DistributionReader, OtaEvaluator
from app.modules.data_overview.labor import LaborOverviewReader
from app.modules.data_overview.sources import (
    PropertySources,
    booking_freshness_of,
    booking_provenance_of,
)
from app.modules.data_overview.types import (
    ALLOWED_PERIOD_DAYS,
    COMPARISON_LOOKBACK_DAYS,
    PERIOD_DAYS_LONG,
    PERIOD_DAYS_SHORT,
    Availability,
    DataOverview,
    DecisionRef,
    DomainState,
    FreshnessReason,
    OccupancyOverview,
    OverviewFreshness,
    UnavailableReason,
)
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedItem, FeedResult
from app.modules.decisions.coverage import AnalysisCoverage, AnalysisDomain
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSourceDomain
from app.modules.intelligence.priority.types import PriorityDecisionType
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository

logger = logging.getLogger(__name__)

# The area each of the five decision types belongs to - the same grouping `decisions/coverage.py`
# documents. A `dict` over the enum + a test that every member is a key: a sixth type cannot be
# added without Dati knowing which area it is in.
DOMAIN_OF_DECISION_TYPE: dict[PriorityDecisionType, AnalysisDomain] = {
    PriorityDecisionType.REV_PICKUP_LOW: AnalysisDomain.REVENUE,
    PriorityDecisionType.REV_OCCUPANCY_RISK: AnalysisDomain.REVENUE,
    PriorityDecisionType.REV_OTA_DEPENDENCY: AnalysisDomain.DISTRIBUTION,
    PriorityDecisionType.COST_CPOR_ANOMALY: AnalysisDomain.COSTS,
    PriorityDecisionType.LABOR_OVERSTAFFING: AnalysisDomain.LABOR,
}


class DataOverviewError(Exception):
    """The overview cannot be built for the request itself (an unknown / foreign / archived
    property, or a period that is not offered). Never a data problem: those are `None`s."""


def _iso(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def decision_refs_of(items: Sequence[FeedItem]) -> tuple[DecisionRef, ...]:
    """The feed's decisions, in the feed's own (priority) order, reduced to what Dati displays."""
    refs: list[DecisionRef] = []
    for item in items:
        decision = item.decision
        payload = decision.identity_payload
        decision_type = decision.decision_type
        target_date: date | None = None
        category: str | None = None
        if decision_type in (
            PriorityDecisionType.REV_PICKUP_LOW,
            PriorityDecisionType.REV_OCCUPANCY_RISK,
        ):
            target_date = _iso(payload.get("stay_date"))
        elif decision_type is PriorityDecisionType.COST_CPOR_ANOMALY:
            target_date = _iso(payload.get("target_period_start"))
            raw = payload.get("cost_category")
            category = raw if isinstance(raw, str) else None
        elif decision_type is PriorityDecisionType.LABOR_OVERSTAFFING:
            target_date = _iso(payload.get("work_date"))
            raw = payload.get("labor_category")
            category = raw if isinstance(raw, str) else None
        refs.append(
            DecisionRef(
                decision_id=decision.id,
                decision_type=decision_type.value,
                domain=DOMAIN_OF_DECISION_TYPE[decision_type],
                target_date=target_date,
                category=category,
            )
        )
    return tuple(refs)


def _first_of_type(
    items: Sequence[FeedItem], decision_type: PriorityDecisionType
) -> FeedItem | None:
    return next((item for item in items if item.decision.decision_type is decision_type), None)


def _coverage_of(run: DecisionRun | None) -> AnalysisCoverage | None:
    if run is None or run.analysis_coverage is None:
        return None
    try:
        return AnalysisCoverage.from_json(run.analysis_coverage)
    except (KeyError, ValueError):
        return None


class DataOverviewService:
    """Read-only. Pass any session: this service neither commits nor rolls back."""

    def __init__(
        self,
        session: Session,
        tenant: TenantContext,
        *,
        ota_evaluator: OtaEvaluator | None = None,
    ) -> None:
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._memory = DecisionMemoryService(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._sources = PropertySources(session, tenant)
        self._distribution = DistributionReader(session, tenant, ota_evaluator=ota_evaluator)
        self._costs = CostOverviewReader(session, tenant)
        self._labor = LaborOverviewReader(session, tenant)

    def overview(
        self, property_id: UUID, as_of_local_date: date, period_days: int = PERIOD_DAYS_LONG
    ) -> DataOverview:
        if period_days not in ALLOWED_PERIOD_DAYS:
            raise DataOverviewError("period_days must be 7 or 30")
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise DataOverviewError("property not found")
        try:
            timezone = ZoneInfo(prop.timezone)
        except ZoneInfoNotFoundError as error:
            raise DataOverviewError("property has no valid time zone") from error

        as_of = as_of_local_date
        feed = self._memory.get_feed(property_id, as_of)
        run = feed.run
        coverage = _coverage_of(run)
        decisions = decision_refs_of(feed.items)
        states = metrics.domain_states(
            run, coverage, feed.state, (decision.domain for decision in decisions)
        )
        booking_source_id, _ = booking_provenance_of(run)

        occupancy = self._occupancy(
            feed=feed,
            as_of=as_of,
            period_days=period_days,
            source_id=booking_source_id,
            decisions=decisions,
            revenue_state=states[AnalysisDomain.REVENUE],
        )
        distribution = self._distribution.read(
            property_id=property_id,
            as_of=as_of,
            timezone=timezone,
            run_exists=run is not None,
            source_id=booking_source_id,
            state=states[AnalysisDomain.DISTRIBUTION],
            ota_decision=_first_of_type(feed.items, PriorityDecisionType.REV_OTA_DEPENDENCY),
        )
        costs = self._costs.read(
            property_id=property_id,
            as_of=as_of,
            currency=prop.currency,
            source_id=booking_source_id,
            cost_decision=_first_of_type(feed.items, PriorityDecisionType.COST_CPOR_ANOMALY),
        )
        cost_source = self._sources.resolve(property_id, DataSourceDomain.COSTS)
        labor_source = self._sources.resolve(property_id, DataSourceDomain.LABOR)
        labor = self._labor.read(
            as_of=as_of,
            currency=prop.currency,
            source_id=labor_source.source_id,
            source_reason=_unavailable_reason_of(labor_source.reason),
            labor_decision=_first_of_type(feed.items, PriorityDecisionType.LABOR_OVERSTAFFING),
        )
        freshness = OverviewFreshness(
            bookings=booking_freshness_of(run),
            costs=self._sources.freshness(cost_source),
            labor=self._sources.freshness(labor_source),
        )
        return DataOverview(
            property_id=property_id,
            as_of_local_date=as_of,
            period_days=period_days,
            currency=prop.currency,
            feed_state=feed.state,
            coverage=coverage,
            domain_states=states,
            last_successful_analysis=feed.last_successful_analysis,
            freshness=freshness,
            occupancy=occupancy,
            distribution=distribution,
            costs=costs,
            labor=labor,
            decisions=decisions,
        )

    # --- bookings / occupancy ----------------------------------------------------------------

    def _occupancy(
        self,
        *,
        feed: FeedResult,
        as_of: date,
        period_days: int,
        source_id: UUID | None,
        decisions: tuple[DecisionRef, ...],
        revenue_state: DomainState,
    ) -> OccupancyOverview:
        def unavailable(reason: UnavailableReason) -> OccupancyOverview:
            return OccupancyOverview(
                state=Availability.NOT_AVAILABLE,
                reason=reason,
                today=None,
                days_7=None,
                days_30=None,
                selected=None,
                nights=(),
            )

        if feed.run is None:
            return unavailable(UnavailableReason.NO_ANALYSIS)
        if source_id is None:
            return unavailable(UnavailableReason.NO_BOOKING_SOURCE)

        first, last = metrics.window_of(as_of, PERIOD_DAYS_LONG)
        rows = self._snapshots.list_for_snapshot_date(
            source_id,
            as_of,
            stay_date_from=first,
            stay_date_to=last,
            origin=SnapshotOrigin.OBSERVED,
        )
        if not rows:
            return unavailable(UnavailableReason.NO_BOOKING_DATA)

        older = self._snapshots.list_for_snapshot_date(
            source_id,
            as_of - timedelta(days=COMPARISON_LOOKBACK_DAYS),
            stay_date_from=first,
            stay_date_to=last,
            origin=SnapshotOrigin.OBSERVED,
        )
        rooms_7d_ago = {row.stay_date: row.rooms_on_books for row in older}

        today = metrics.period_metrics(rows, as_of, as_of, rooms_7d_ago=rooms_7d_ago)
        days_7 = metrics.period_metrics(
            rows, *metrics.window_of(as_of, PERIOD_DAYS_SHORT), rooms_7d_ago=rooms_7d_ago
        )
        days_30 = metrics.period_metrics(
            rows, *metrics.window_of(as_of, PERIOD_DAYS_LONG), rooms_7d_ago=rooms_7d_ago
        )
        selected = days_7 if period_days == PERIOD_DAYS_SHORT else days_30
        nights = metrics.night_rows(
            rows,
            selected.start_date,
            selected.end_date,
            rooms_7d_ago=rooms_7d_ago,
            decisions_by_night=metrics.index_decisions_by_night(decisions),
            run_exists=True,
            revenue_state=revenue_state,
            run_inconclusive=metrics.run_is_inconclusive(feed.run),
        )
        return OccupancyOverview(
            state=Availability.AVAILABLE,
            reason=None,
            today=today,
            days_7=days_7,
            days_30=days_30,
            selected=selected,
            nights=nights,
        )


def _unavailable_reason_of(reason: FreshnessReason | None) -> UnavailableReason | None:
    if reason is FreshnessReason.SEVERAL_SOURCES:
        return UnavailableReason.SEVERAL_SOURCES
    if reason is FreshnessReason.NO_SOURCE:
        return UnavailableReason.NO_SOURCE
    return None


__all__ = [
    "DOMAIN_OF_DECISION_TYPE",
    "DataOverviewError",
    "DataOverviewService",
    "decision_refs_of",
]
