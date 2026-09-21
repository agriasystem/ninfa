"""Tenant-scoped data access for Expected baselines and their comparables.

Every query carries the workspace_id of the TenantContext. Repositories flush but never commit:
the service owns the transaction. No pickup, forecast, alert or decision exists here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, insert, select
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.intelligence.expected.calculator import (
    CALCULATION_VERSION,
    METHOD,
    ExpectedComputation,
)
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.selection import HistoricalTarget
from app.modules.snapshots.models import SnapshotOrigin

_INSERT_BLOCK = 2000  # rows per executemany call


@dataclass(frozen=True, slots=True)
class NewBaseline:
    """A calculated baseline ready to be stored, with the comparables it rests on."""

    id: UUID  # generated up front so comparables can point at it in the same transaction
    property_id: UUID
    data_source_id: UUID
    target_snapshot_id: UUID
    target: HistoricalTarget
    computation: ExpectedComputation
    comparable_fingerprint: str


class ExpectedRepository:
    """Expected baselines of ONE workspace."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        self._session = session
        self._tenant = tenant

    # --- reads --------------------------------------------------------------------------------

    def get_for_target_snapshot(
        self, target_snapshot_id: UUID, calculation_version: str = CALCULATION_VERSION
    ) -> BookingExpectedBaseline | None:
        return self._session.scalar(
            select(BookingExpectedBaseline).where(
                BookingExpectedBaseline.workspace_id == self._tenant.workspace_id,
                BookingExpectedBaseline.target_snapshot_id == target_snapshot_id,
                BookingExpectedBaseline.calculation_version == calculation_version,
            )
        )

    def existing_for_targets(
        self, target_snapshot_ids: Sequence[UUID], calculation_version: str = CALCULATION_VERSION
    ) -> dict[UUID, BookingExpectedBaseline]:
        """The stored baselines of these targets (one query), keyed by target snapshot id."""
        if not target_snapshot_ids:
            return {}
        rows = self._session.scalars(
            select(BookingExpectedBaseline).where(
                BookingExpectedBaseline.workspace_id == self._tenant.workspace_id,
                BookingExpectedBaseline.target_snapshot_id.in_(list(target_snapshot_ids)),
                BookingExpectedBaseline.calculation_version == calculation_version,
            )
        )
        return {row.target_snapshot_id: row for row in rows}

    def list_for_snapshot_date(
        self,
        data_source_id: UUID,
        target_snapshot_local_date: date,
        calculation_version: str = CALCULATION_VERSION,
    ) -> Sequence[BookingExpectedBaseline]:
        """The baselines of one snapshot day of a data source, earliest stay date first."""
        return self._session.scalars(
            select(BookingExpectedBaseline)
            .where(
                BookingExpectedBaseline.workspace_id == self._tenant.workspace_id,
                BookingExpectedBaseline.data_source_id == data_source_id,
                BookingExpectedBaseline.target_snapshot_local_date == target_snapshot_local_date,
                BookingExpectedBaseline.calculation_version == calculation_version,
            )
            .order_by(BookingExpectedBaseline.target_stay_date)
        ).all()

    def list_comparables(self, baseline_id: UUID) -> Sequence[BookingExpectedComparable]:
        """The comparables a baseline used, most recent comparable stay date (rank 1) first."""
        return self._session.scalars(
            select(BookingExpectedComparable)
            .where(
                BookingExpectedComparable.workspace_id == self._tenant.workspace_id,
                BookingExpectedComparable.baseline_id == baseline_id,
            )
            .order_by(BookingExpectedComparable.recency_rank)
        ).all()

    def list_comparables_for_baselines(
        self, baseline_ids: Sequence[UUID]
    ) -> dict[UUID, list[BookingExpectedComparable]]:
        """The comparables of many baselines in ONE statement, each list in rank order."""
        grouped: dict[UUID, list[BookingExpectedComparable]] = {}
        if not baseline_ids:
            return grouped
        rows = self._session.scalars(
            select(BookingExpectedComparable)
            .where(
                BookingExpectedComparable.workspace_id == self._tenant.workspace_id,
                BookingExpectedComparable.baseline_id.in_(list(baseline_ids)),
            )
            .order_by(BookingExpectedComparable.baseline_id, BookingExpectedComparable.recency_rank)
        )
        for row in rows:
            grouped.setdefault(row.baseline_id, []).append(row)
        return grouped

    # --- writes -------------------------------------------------------------------------------

    def insert_baselines(self, items: Sequence[NewBaseline]) -> None:
        """Store new baselines (Core executemany). Never updates a stored one."""
        table = cast(Table, BookingExpectedBaseline.__table__)
        for start in range(0, len(items), _INSERT_BLOCK):
            block = [self._baseline_row(item) for item in items[start : start + _INSERT_BLOCK]]
            self._session.execute(insert(table), block)

    def insert_comparables(self, items: Sequence[NewBaseline]) -> None:
        """Store the comparables of the given (already inserted) baselines."""
        table = cast(Table, BookingExpectedComparable.__table__)
        rows = [
            self._comparable_row(item, selected)
            for item in items
            for selected in item.computation.selection.comparables
        ]
        for start in range(0, len(rows), _INSERT_BLOCK):
            self._session.execute(insert(table), rows[start : start + _INSERT_BLOCK])

    # --- row builders -------------------------------------------------------------------------

    def _baseline_row(self, item: NewBaseline) -> dict[str, Any]:
        computation = item.computation
        selection = computation.selection
        statistics = computation.statistics
        band = computation.confidence_band
        return {
            "id": item.id,
            "workspace_id": self._tenant.workspace_id,
            "property_id": item.property_id,
            "data_source_id": item.data_source_id,
            "target_snapshot_id": item.target_snapshot_id,
            "target_origin": SnapshotOrigin.OBSERVED.value,
            "target_snapshot_local_date": item.target.snapshot_local_date,
            "target_stay_date": item.target.stay_date,
            "lead_time_days": item.target.lead_time_days,
            "status": computation.status.value,
            "expected_rooms_on_books": None if statistics is None else statistics.expected,
            "expected_lower": None if statistics is None else statistics.lower,
            "expected_upper": None if statistics is None else statistics.upper,
            "iqr": None if statistics is None else statistics.iqr,
            "sample_size": selection.sample_size,
            "observed_sample_size": selection.observed_count,
            "reconstructed_sample_size": selection.reconstructed_count,
            "rejected_uncertain_count": selection.rejected_uncertain_count,
            "confidence_score": computation.confidence_score,
            "confidence_band": None if band is None else band.value,
            "method": METHOD,
            "calculation_version": CALCULATION_VERSION,
            "comparable_fingerprint": item.comparable_fingerprint,
        }

    def _comparable_row(self, item: NewBaseline, selected: Any) -> dict[str, Any]:
        candidate = selected.candidate
        return {
            "workspace_id": self._tenant.workspace_id,
            "property_id": item.property_id,
            "data_source_id": item.data_source_id,
            "baseline_id": item.id,
            "snapshot_id": candidate.snapshot_id,
            "origin": candidate.origin.value,
            "rooms_on_books": candidate.rooms_on_books,
            "recency_rank": selected.recency_rank,
        }
