"""DemandForecastService: the expected room demand of ONE target night (read-only, no clock).

Reused (not copied) by LABOR_OVERSTAFFING: the SAME Gate 4 baseline and comparables
(`intelligence.expected.repository`), the SAME remaining-net-pickup pairing
(`intelligence.revenue.pairing.remaining_pairs`), the SAME curve pattern and confidence
(`intelligence.revenue.pattern.analyse`, `intelligence.revenue.confidence.final_confidence`) and
the SAME forecast formula (`intelligence.demand.forecast.forecast_rooms_from_pickup`) that
REV_OCCUPANCY_RISK (Gate 5) evaluates for the same target. There is exactly one implementation of
each of these algorithms in NINFA.

    lead_time == 0   forecast_rooms = rooms_on_books (an OBSERVED fact), demand_confidence = 100
    lead_time  > 0   forecast_rooms = rooms_on_books + expected_remaining_net_pickup (floored at
                      0), demand_confidence = MIN(baseline_confidence, pattern_confidence)

A target that cannot be evaluated at all (not found, not OBSERVED, negative lead time) raises
`DemandForecastError`. A target that IS valid but for which Gate 4/5's machinery cannot build a
reliable remaining-pickup pattern (no READY baseline, fewer than 5 clean pairs) is answered with
`DemandForecastStatus.INSUFFICIENT_DATA`, never invented.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.tenant import TenantContext
from app.modules.intelligence.demand.forecast import forecast_rooms_from_pickup
from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.revenue.confidence import final_confidence
from app.modules.intelligence.revenue.pairing import final_key, remaining_pairs
from app.modules.intelligence.revenue.pattern import analyse
from app.modules.intelligence.revenue.types import MIN_PAIRS, SnapshotPoint
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotHistoryRow


class DemandForecastErrorCode(StrEnum):
    TARGET_NOT_FOUND = "DEMAND_TARGET_NOT_FOUND"
    TARGET_NOT_OBSERVED = "DEMAND_TARGET_NOT_OBSERVED"
    INVALID_TARGET = "DEMAND_INVALID_TARGET"


class DemandForecastError(AppError):
    def __init__(self, code: DemandForecastErrorCode, message: str) -> None:
        super().__init__(code.value, message, status_code=422)
        self.error_code = code


class DemandForecastStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class DemandForecast:
    """The expected room demand of one target night, and how it was reached."""

    status: DemandForecastStatus
    workspace_id: UUID
    property_id: UUID
    booking_data_source_id: UUID
    target_booking_snapshot_id: UUID
    snapshot_local_date: date
    stay_date: date
    lead_time_days: int
    forecast_rooms_exact: Decimal | None
    demand_confidence: Decimal | None
    baseline_id: UUID | None
    pair_count: int
    observed_pair_count: int
    approximate_pair_count: int


def _point(row: SnapshotHistoryRow) -> SnapshotPoint:
    return SnapshotPoint(
        snapshot_id=row.snapshot_id,
        snapshot_local_date=row.snapshot_local_date,
        stay_date=row.stay_date,
        origin=row.origin,
        rooms_on_books=row.rooms_on_books,
        uncertain_rooms=row.uncertain_rooms,
        adr_on_books=row.adr_on_books,
    )


class DemandForecastService:
    """Read-only. Pass any session: the service neither commits nor rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Demand Forecast service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._expected = ExpectedRepository(session, tenant)

    def forecast_for_target(self, target_booking_snapshot_id: UUID) -> DemandForecast:
        """The expected room demand of one OBSERVED booking snapshot.

        `booking_data_source_id` is DERIVED from the target (the same pattern as
        `RevenueDecisionService.evaluate_occupancy_risk`): the caller validates it (domain,
        active, property match) from `DemandForecast.booking_data_source_id` afterwards, exactly
        once, whatever the number of categories evaluated for the same target.
        """
        snapshot = self._snapshots.get_by_id(target_booking_snapshot_id)
        if snapshot is None:
            raise DemandForecastError(
                DemandForecastErrorCode.TARGET_NOT_FOUND,
                "The target booking snapshot was not found",
            )
        booking_data_source_id = snapshot.data_source_id
        if snapshot.origin != SnapshotOrigin.OBSERVED:
            raise DemandForecastError(
                DemandForecastErrorCode.TARGET_NOT_OBSERVED,
                "A demand forecast can only be built from an OBSERVED snapshot",
            )
        if snapshot.stay_date < snapshot.snapshot_local_date:
            raise DemandForecastError(
                DemandForecastErrorCode.INVALID_TARGET,
                "The target stay date is before its snapshot day (negative lead time)",
            )
        lead_time_days = (snapshot.stay_date - snapshot.snapshot_local_date).days

        def finish(
            status: DemandForecastStatus,
            *,
            forecast_rooms_exact: Decimal | None,
            demand_confidence: Decimal | None,
            baseline_id: UUID | None,
            pair_count: int,
            observed_pair_count: int,
            approximate_pair_count: int,
        ) -> DemandForecast:
            return DemandForecast(
                status=status,
                workspace_id=snapshot.workspace_id,
                property_id=snapshot.property_id,
                booking_data_source_id=booking_data_source_id,
                target_booking_snapshot_id=snapshot.id,
                snapshot_local_date=snapshot.snapshot_local_date,
                stay_date=snapshot.stay_date,
                lead_time_days=lead_time_days,
                forecast_rooms_exact=forecast_rooms_exact,
                demand_confidence=demand_confidence,
                baseline_id=baseline_id,
                pair_count=pair_count,
                observed_pair_count=observed_pair_count,
                approximate_pair_count=approximate_pair_count,
            )

        if lead_time_days == 0:
            # An OBSERVED target of its own stay date IS the demand: nothing to forecast.
            return finish(
                DemandForecastStatus.READY,
                forecast_rooms_exact=Decimal(snapshot.rooms_on_books),
                demand_confidence=Decimal(100),
                baseline_id=None,
                pair_count=0,
                observed_pair_count=0,
                approximate_pair_count=0,
            )

        baseline = self._expected.get_for_target_snapshot(target_booking_snapshot_id)
        if baseline is None or baseline.status != ExpectedStatus.READY:
            return finish(
                DemandForecastStatus.INSUFFICIENT_DATA,
                forecast_rooms_exact=None,
                demand_confidence=None,
                baseline_id=None if baseline is None else baseline.id,
                pair_count=0,
                observed_pair_count=0,
                approximate_pair_count=0,
            )

        comparables = self._expected.list_comparables(baseline.id)
        points = {
            row.snapshot_id: _point(row)
            for row in self._snapshots.list_by_ids(
                booking_data_source_id, {c.snapshot_id for c in comparables}
            )
        }
        anchors = [points[c.snapshot_id] for c in comparables if c.snapshot_id in points]
        wanted = {final_key(anchor) for anchor in anchors}
        endpoints = {
            (row.snapshot_local_date, row.stay_date): _point(row)
            for row in self._snapshots.list_by_keys(booking_data_source_id, wanted)
        }
        selection = remaining_pairs(snapshot.snapshot_local_date, anchors, endpoints)
        if selection.pair_count < MIN_PAIRS:
            return finish(
                DemandForecastStatus.INSUFFICIENT_DATA,
                forecast_rooms_exact=None,
                demand_confidence=None,
                baseline_id=baseline.id,
                pair_count=selection.pair_count,
                observed_pair_count=selection.observed_pair_count,
                approximate_pair_count=selection.approximate_pair_count,
            )

        pattern = analyse(selection)
        confidence = final_confidence(Decimal(baseline.confidence_score), pattern.confidence.score)
        forecast_rooms = forecast_rooms_from_pickup(
            snapshot.rooms_on_books, pattern.statistics.expected
        )
        return finish(
            DemandForecastStatus.READY,
            forecast_rooms_exact=forecast_rooms,
            demand_confidence=confidence,
            baseline_id=baseline.id,
            pair_count=selection.pair_count,
            observed_pair_count=selection.observed_pair_count,
            approximate_pair_count=selection.approximate_pair_count,
        )
