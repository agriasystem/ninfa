"""RevenueDecisionService: evaluates REV_PICKUP_LOW and REV_OCCUPANCY_RISK for OBSERVED targets.

    validate -> load baselines, comparables, anchors, endpoints (set-based) -> evaluate in memory

The service is READ-ONLY: it writes nothing, never commits or rolls back, takes no advisory lock
and reads no clock. It persists no Decision (there is no such table yet); an evaluation is a value
returned to the caller. All the database work is a fixed handful of statements whatever the number
of targets: the targets, the Gate 4 baselines, their comparables, the comparable snapshots
(anchors) and ONE keyed read of every other curve endpoint, so a batch never asks per target.

Everything is read through the repositories of the TenantContext: a target, baseline or snapshot
of another workspace simply does not exist for this service, and an unknown id and a foreign id
raise the same error.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.expected.calculator import ExpectedStatus
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.revenue.errors import RevenueDecisionError, RevenueErrorCode
from app.modules.intelligence.revenue.impact import ReferenceAdr, reference_adr
from app.modules.intelligence.revenue.occupancy import evaluate_occupancy
from app.modules.intelligence.revenue.pairing import (
    SnapshotKey,
    final_key,
    pickup_pairs,
    pickup_prior_key,
    prior_key,
    remaining_pairs,
)
from app.modules.intelligence.revenue.pattern import empty_selection
from app.modules.intelligence.revenue.pickup import evaluate_pickup
from app.modules.intelligence.revenue.types import (
    RevenueDecisionEvaluation,
    RevenueSignals,
    SnapshotPoint,
    TargetContext,
)
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotHistoryRow

logger = logging.getLogger(__name__)

MAX_STAY_RANGE_DAYS = 731


@dataclass(frozen=True, slots=True)
class _Loaded:
    """Everything the evaluation of a batch of targets reads, fetched set-based."""

    baselines: dict[UUID, BookingExpectedBaseline]  # by target snapshot id
    anchors: dict[UUID, list[SnapshotPoint]]  # by baseline id, in comparable rank order
    anchor_adrs: dict[UUID, list[Decimal | None]]  # by baseline id
    endpoints: dict[SnapshotKey, SnapshotPoint]


@dataclass(frozen=True, slots=True)
class _Prepared:
    """One target with everything read for it: the detectors themselves are pure."""

    context: TargetContext
    anchors: list[SnapshotPoint]
    reference: ReferenceAdr
    endpoints: dict[SnapshotKey, SnapshotPoint]

    def _has_pairs(self) -> bool:
        return self.context.baseline_status == ExpectedStatus.READY and bool(self.anchors)

    def pickup(self) -> RevenueDecisionEvaluation:
        context = self.context
        selection = (
            pickup_pairs(context.snapshot_local_date, self.anchors, self.endpoints)
            if self._has_pairs()
            else empty_selection()
        )
        return evaluate_pickup(
            context,
            prior=self.endpoints.get(prior_key(context.snapshot_local_date, context.stay_date)),
            selection=selection,
            reference=self.reference,
        )

    def occupancy(self) -> RevenueDecisionEvaluation:
        context = self.context
        selection = (
            remaining_pairs(context.snapshot_local_date, self.anchors, self.endpoints)
            if self._has_pairs()
            else empty_selection()
        )
        return evaluate_occupancy(context, selection=selection, reference=self.reference)

    def signals(self) -> RevenueSignals:
        return RevenueSignals(self.pickup(), self.occupancy())


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


class RevenueDecisionService:
    """Read-only. Pass any session: the service neither commits nor rolls back."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Revenue Decision service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._expected = ExpectedRepository(session, tenant)

    # --- public API ---------------------------------------------------------------------------

    def evaluate_pickup_low(self, target_snapshot_id: UUID) -> RevenueDecisionEvaluation:
        """REV_PICKUP_LOW for ONE observed snapshot."""
        [prepared] = self._prepare([self._load_target(target_snapshot_id)], pickup=True)
        return prepared.pickup()

    def evaluate_occupancy_risk(self, target_snapshot_id: UUID) -> RevenueDecisionEvaluation:
        """REV_OCCUPANCY_RISK for ONE observed snapshot."""
        [prepared] = self._prepare([self._load_target(target_snapshot_id)], occupancy=True)
        return prepared.occupancy()

    def evaluate_revenue_signals(self, target_snapshot_id: UUID) -> RevenueSignals:
        """Both detectors on ONE observed snapshot."""
        [prepared] = self._prepare(
            [self._load_target(target_snapshot_id)], pickup=True, occupancy=True
        )
        return prepared.signals()

    def evaluate_snapshot_date(
        self,
        *,
        property_id: UUID,
        data_source_id: UUID,
        snapshot_local_date: date,
        stay_date_start: date,
        stay_date_end: date,
    ) -> tuple[RevenueSignals, ...]:
        """Both detectors on every OBSERVED snapshot of one snapshot day and stay-date range
        (both ends included) of one data source, earliest stay date first.

        Targets whose stay date precedes their snapshot day (a night already over) are not
        evaluated. The history of the whole batch is read once.
        """
        for value, name in (
            (snapshot_local_date, "snapshot_local_date"),
            (stay_date_start, "stay_date_start"),
            (stay_date_end, "stay_date_end"),
        ):
            if isinstance(value, datetime) or not isinstance(value, date):
                raise TypeError(f"{name} must be a date")
        if stay_date_start > stay_date_end:
            raise RevenueDecisionError(
                RevenueErrorCode.INVALID_RANGE,
                "The stay date range ends before it starts",
                details={"reason": "start_after_end"},
            )
        if (stay_date_end - stay_date_start).days + 1 > MAX_STAY_RANGE_DAYS:
            raise RevenueDecisionError(
                RevenueErrorCode.INVALID_RANGE,
                f"The stay date range is longer than {MAX_STAY_RANGE_DAYS} days",
                details={"reason": "too_long", "max_days": MAX_STAY_RANGE_DAYS},
            )
        self._validate_source(property_id, data_source_id)
        stored = self._snapshots.list_for_snapshot_date(
            data_source_id,
            snapshot_local_date,
            stay_date_from=max(stay_date_start, snapshot_local_date),
            stay_date_to=stay_date_end,
            origin=SnapshotOrigin.OBSERVED,
        )
        signals = tuple(
            prepared.signals() for prepared in self._prepare(stored, pickup=True, occupancy=True)
        )
        logger.info(
            "revenue signals evaluated workspace_id=%s property_id=%s data_source_id=%s targets=%d",
            self._tenant.workspace_id,
            property_id,
            data_source_id,
            len(signals),
        )
        return signals

    # --- validation ---------------------------------------------------------------------------

    def _validate_source(self, property_id: UUID, data_source_id: UUID) -> None:
        """Property and data source must be usable and belong to this workspace."""
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise RevenueDecisionError(
                RevenueErrorCode.INVALID_PROPERTY,
                "The property cannot be used for Revenue Decision Detection",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.BOOKINGS:
            reason = "wrong_domain"
        elif not data_source.is_active:
            reason = "inactive"
        elif data_source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise RevenueDecisionError(
                RevenueErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for Revenue Decision Detection",
                details={"reason": reason},
            )

    def _load_target(self, target_snapshot_id: UUID) -> BookingSnapshot:
        snapshot = self._snapshots.get_by_id(target_snapshot_id)
        if snapshot is None:  # unknown and "of another workspace" are indistinguishable
            raise RevenueDecisionError(
                RevenueErrorCode.TARGET_NOT_FOUND, "The target snapshot was not found"
            )
        self._validate_source(snapshot.property_id, snapshot.data_source_id)
        if snapshot.origin != SnapshotOrigin.OBSERVED:
            raise RevenueDecisionError(
                RevenueErrorCode.TARGET_NOT_OBSERVED,
                "A revenue decision can only be evaluated on an OBSERVED snapshot",
                details={"origin": snapshot.origin.value},
            )
        if snapshot.stay_date < snapshot.snapshot_local_date:
            raise RevenueDecisionError(
                RevenueErrorCode.INVALID_TARGET,
                "The target stay date is before its snapshot day (negative lead time)",
                details={"reason": "negative_lead_time"},
            )
        return snapshot

    # --- the evaluation -----------------------------------------------------------------------

    def _prepare(
        self, targets: Sequence[BookingSnapshot], *, pickup: bool = False, occupancy: bool = False
    ) -> list[_Prepared]:
        """Read everything the requested detectors need, once, for all the targets."""
        if not targets:
            return []
        data_source_id = targets[0].data_source_id
        loaded = self._load(targets, data_source_id, pickup=pickup, occupancy=occupancy)
        prepared: list[_Prepared] = []
        for snapshot in targets:
            baseline = loaded.baselines.get(snapshot.id)
            context = TargetContext(
                workspace_id=snapshot.workspace_id,
                property_id=snapshot.property_id,
                data_source_id=snapshot.data_source_id,
                target_snapshot_id=snapshot.id,
                snapshot_local_date=snapshot.snapshot_local_date,
                stay_date=snapshot.stay_date,
                rooms_on_books=snapshot.rooms_on_books,
                rooms_available=snapshot.rooms_available,
                adr_on_books=snapshot.adr_on_books,
                baseline_id=None if baseline is None else baseline.id,
                baseline_status=None if baseline is None else baseline.status,
                baseline_confidence=(
                    None if baseline is None else Decimal(baseline.confidence_score)
                ),
            )
            anchors = [] if baseline is None else loaded.anchors.get(baseline.id, [])
            prepared.append(
                _Prepared(
                    context=context,
                    anchors=anchors,
                    reference=reference_adr(
                        snapshot.adr_on_books,
                        [] if baseline is None else loaded.anchor_adrs.get(baseline.id, []),
                    ),
                    endpoints=loaded.endpoints,
                )
            )
        return prepared

    def _load(
        self,
        targets: Sequence[BookingSnapshot],
        data_source_id: UUID,
        *,
        pickup: bool,
        occupancy: bool,
    ) -> _Loaded:
        # 1. the Gate 4 baselines of the targets, then their comparables (two statements)
        baselines = self._expected.existing_for_targets([target.id for target in targets])
        comparables = self._expected.list_comparables_for_baselines(
            [baseline.id for baseline in baselines.values()]
        )

        # 2. the comparable snapshots themselves (the ANCHORS of the curve pairs), one statement
        snapshot_ids = {c.snapshot_id for rows in comparables.values() for c in rows}
        points = {
            row.snapshot_id: _point(row)
            for row in self._snapshots.list_by_ids(data_source_id, snapshot_ids)
        }
        anchors: dict[UUID, list[SnapshotPoint]] = {}
        anchor_adrs: dict[UUID, list[Decimal | None]] = {}
        for baseline_id, rows in comparables.items():
            found = [points[c.snapshot_id] for c in rows if c.snapshot_id in points]
            anchors[baseline_id] = found
            anchor_adrs[baseline_id] = [point.adr_on_books for point in found]

        # 3. every other endpoint any pair or target needs, by exact key, in ONE statement
        wanted: set[SnapshotKey] = set()
        if pickup:
            wanted.update(prior_key(t.snapshot_local_date, t.stay_date) for t in targets)
        for target in targets:
            baseline = baselines.get(target.id)
            if baseline is None or baseline.status != ExpectedStatus.READY:
                continue
            for anchor in anchors.get(baseline.id, []):
                if pickup:
                    wanted.add(pickup_prior_key(anchor))
                if occupancy:
                    wanted.add(final_key(anchor))
        endpoints = {
            (row.snapshot_local_date, row.stay_date): _point(row)
            for row in self._snapshots.list_by_keys(data_source_id, wanted)
        }
        return _Loaded(baselines, anchors, anchor_adrs, endpoints)
