"""BookingExpectedService: turns OBSERVED target snapshots into immutable Expected baselines.

    validate -> lock the data source -> fetch the exact comparable snapshots (one query) ->
    calculate in memory -> compare with what is stored -> insert baselines + comparables -> commit

One transaction per run, under the same per-data-source advisory lock as the booking import and
the snapshot services. Expected is a HISTORICAL LEVEL, not a forecast: the service never
computes a final occupancy, a remaining pickup, an alert or a decision, and it reads no clock.

A baseline is a record of what was known when it was calculated. A second run with the same
comparables and result is a no-op; a run that would produce something different for the same
target and `calculation_version` (typically because history arrived in the meantime) raises
`EXPECTED_BASELINE_CONFLICT` and stores nothing. To change the rules, use a new version.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.db.locks import lock_data_source
from app.modules.ingestion.models import DataSourceDomain, DataSourceType
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.intelligence.expected.calculator import (
    CALCULATION_VERSION,
    METHOD,
    ExpectedStatus,
    comparable_fingerprint,
    compute_expected,
)
from app.modules.intelligence.expected.errors import ExpectedError, ExpectedErrorCode
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.expected.repository import ExpectedRepository, NewBaseline
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.selection import Candidate, HistoricalTarget
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.snapshots.repository import BookingSnapshotRepository, SnapshotKey

logger = logging.getLogger(__name__)

MAX_STAY_RANGE_DAYS = 731
_MAX_REPORTED_CONFLICTS = 20


@dataclass(frozen=True, slots=True)
class ExpectedRunResult:
    """Outcome of a run. Counts and ids only; the baselines are read back through the repository.

    `ready` and `insufficient` count every baseline of the run, new or already stored.
    """

    property_id: UUID
    data_source_id: UUID
    created: int
    unchanged: int
    ready: int
    insufficient: int
    skipped_negative_lead_time: int
    baseline_ids: tuple[UUID, ...]
    calculation_version: str = CALCULATION_VERSION

    @property
    def total(self) -> int:
        return self.created + self.unchanged


class BookingExpectedService:
    """Pass a session with no uncommitted work: the service commits it (and rolls it back on
    failure), exactly like the booking import and the snapshot services."""

    def __init__(self, session: Session, tenant: TenantContext) -> None:
        if not isinstance(tenant, TenantContext):
            raise TypeError("the Expected service needs a TenantContext")
        self._session = session
        self._tenant = tenant
        self._properties = PropertyRepository(session, tenant)
        self._data_sources = DataSourceRepository(session, tenant)
        self._snapshots = BookingSnapshotRepository(session, tenant)
        self._expected = ExpectedRepository(session, tenant)

    # --- public API ---------------------------------------------------------------------------

    def calculate_for_target(
        self, *, property_id: UUID, data_source_id: UUID, target_snapshot_id: UUID
    ) -> ExpectedRunResult:
        """The Expected baseline of ONE observed snapshot (idempotent, immutable)."""

        def run() -> ExpectedRunResult:
            self._validate_source(property_id, data_source_id)
            target = self._load_target(property_id, data_source_id, target_snapshot_id)
            return self._process(property_id, data_source_id, [target], skipped=0)

        return self._finish(run)

    def calculate_for_snapshot_date(
        self,
        *,
        property_id: UUID,
        data_source_id: UUID,
        snapshot_local_date: date,
        stay_date_start: date,
        stay_date_end: date,
    ) -> ExpectedRunResult:
        """The baselines of every OBSERVED snapshot of one snapshot day and stay-date range
        (both ends included) of one data source, in one transaction.

        Targets whose stay date precedes their snapshot day (a negative lead time: the night was
        already over) are skipped and counted, not an error. Comparable history is fetched once
        for the whole batch.
        """
        for value, name in (
            (snapshot_local_date, "snapshot_local_date"),
            (stay_date_start, "stay_date_start"),
            (stay_date_end, "stay_date_end"),
        ):
            if isinstance(value, datetime) or not isinstance(value, date):
                raise TypeError(f"{name} must be a date")
        if stay_date_start > stay_date_end:
            raise ExpectedError(
                ExpectedErrorCode.INVALID_RANGE,
                "The stay date range ends before it starts",
                details={"reason": "start_after_end"},
            )
        if (stay_date_end - stay_date_start).days + 1 > MAX_STAY_RANGE_DAYS:
            raise ExpectedError(
                ExpectedErrorCode.INVALID_RANGE,
                f"The stay date range is longer than {MAX_STAY_RANGE_DAYS} days",
                details={"reason": "too_long", "max_days": MAX_STAY_RANGE_DAYS},
            )

        def run() -> ExpectedRunResult:
            self._validate_source(property_id, data_source_id)
            stored = self._snapshots.list_for_snapshot_date(
                data_source_id,
                snapshot_local_date,
                stay_date_from=stay_date_start,
                stay_date_to=stay_date_end,
                origin=SnapshotOrigin.OBSERVED,
            )
            usable = [row for row in stored if row.stay_date >= row.snapshot_local_date]
            return self._process(
                property_id, data_source_id, usable, skipped=len(stored) - len(usable)
            )

        return self._finish(run)

    # --- validation ---------------------------------------------------------------------------

    def _validate_source(self, property_id: UUID, data_source_id: UUID) -> None:
        """Property and data source must be usable and belong to this workspace."""
        prop = self._properties.get(property_id)
        if prop is None or prop.archived_at is not None:
            raise ExpectedError(
                ExpectedErrorCode.INVALID_PROPERTY,
                "The property cannot be used for the Expected Engine",
                details={"reason": "not_found" if prop is None else "archived"},
            )
        data_source = self._data_sources.get(data_source_id)
        reason = None
        if data_source is None:
            reason = "not_found"
        elif data_source.domain != DataSourceDomain.BOOKINGS:
            reason = "wrong_domain"
        elif data_source.source_type != DataSourceType.FILE_UPLOAD:
            reason = "wrong_source_type"
        elif not data_source.is_active:
            reason = "inactive"
        elif data_source.property_id != prop.id:
            reason = "property_mismatch"
        if reason is not None:
            raise ExpectedError(
                ExpectedErrorCode.INVALID_DATA_SOURCE,
                "The data source cannot be used for the Expected Engine",
                details={"reason": reason},
            )

    def _load_target(
        self, property_id: UUID, data_source_id: UUID, target_snapshot_id: UUID
    ) -> BookingSnapshot:
        snapshot = self._snapshots.get_by_id(target_snapshot_id)
        if snapshot is None:  # unknown and "of another workspace" are indistinguishable
            raise ExpectedError(
                ExpectedErrorCode.TARGET_NOT_FOUND, "The target snapshot was not found"
            )
        if snapshot.data_source_id != data_source_id or snapshot.property_id != property_id:
            reason = (
                "data_source_mismatch"
                if snapshot.data_source_id != data_source_id
                else "property_mismatch"
            )
            raise ExpectedError(
                ExpectedErrorCode.INVALID_TARGET,
                "The target snapshot does not belong to this property and data source",
                details={"reason": reason},
            )
        if snapshot.origin != SnapshotOrigin.OBSERVED:
            raise ExpectedError(
                ExpectedErrorCode.TARGET_NOT_OBSERVED,
                "An Expected baseline can only be calculated for an OBSERVED snapshot",
                details={"origin": snapshot.origin.value},
            )
        if snapshot.stay_date < snapshot.snapshot_local_date:
            raise ExpectedError(
                ExpectedErrorCode.INVALID_TARGET,
                "The target stay date is before its snapshot day (negative lead time)",
                details={"reason": "negative_lead_time"},
            )
        return snapshot

    # --- the calculation ----------------------------------------------------------------------

    def _finish(self, run: Callable[[], ExpectedRunResult]) -> ExpectedRunResult:
        try:
            result = run()
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return result

    def _process(
        self,
        property_id: UUID,
        data_source_id: UUID,
        targets: Sequence[BookingSnapshot],
        *,
        skipped: int,
    ) -> ExpectedRunResult:
        lock_data_source(self._session, data_source_id)

        # 1. every exact (snapshot day, stay date) key any target could compare with
        plans: list[tuple[BookingSnapshot, HistoricalTarget, list[SnapshotKey]]] = []
        wanted: set[SnapshotKey] = set()
        for snapshot in targets:
            lead = (snapshot.stay_date - snapshot.snapshot_local_date).days
            target = HistoricalTarget(snapshot.stay_date, lead)
            keys = [
                (stay - timedelta(days=lead), stay)
                for stay in eligible_stay_dates(snapshot.stay_date)
            ]
            plans.append((snapshot, target, keys))
            wanted.update(keys)

        # 2. ONE query for all of them, then everything else happens in memory
        by_key = {
            (row.snapshot_local_date, row.stay_date): Candidate(
                snapshot_id=row.snapshot_id,
                snapshot_local_date=row.snapshot_local_date,
                stay_date=row.stay_date,
                origin=row.origin,
                rooms_on_books=row.rooms_on_books,
                uncertain_rooms=row.uncertain_rooms,
            )
            for row in self._snapshots.list_by_keys(data_source_id, wanted)
        }

        calculated: list[NewBaseline] = []
        for snapshot, target, keys in plans:
            computation = compute_expected(target, [by_key[k] for k in keys if k in by_key])
            calculated.append(
                NewBaseline(
                    id=uuid4(),
                    property_id=property_id,
                    data_source_id=data_source_id,
                    target_snapshot_id=snapshot.id,
                    target=target,
                    computation=computation,
                    comparable_fingerprint=comparable_fingerprint(
                        data_source_id=data_source_id,
                        target_snapshot_id=snapshot.id,
                        target=target,
                        computation=computation,
                    ),
                )
            )

        # 3. compare with what is stored: same -> no-op, different -> conflict, absent -> insert
        stored = self._expected.existing_for_targets(
            [item.target_snapshot_id for item in calculated]
        )
        to_insert: list[NewBaseline] = []
        baseline_ids: list[UUID] = []
        conflicts: list[dict[str, str]] = []
        for item in calculated:
            current = stored.get(item.target_snapshot_id)
            if current is None:
                to_insert.append(item)
                baseline_ids.append(item.id)
            elif _signature(current) == _new_signature(item):
                baseline_ids.append(current.id)
            else:
                conflicts.append(
                    {
                        "target_snapshot_id": str(item.target_snapshot_id),
                        "reason": (
                            "different_comparables"
                            if current.comparable_fingerprint != item.comparable_fingerprint
                            else "different_result"
                        ),
                    }
                )
        if conflicts:
            raise ExpectedError(
                ExpectedErrorCode.BASELINE_CONFLICT,
                "A stored baseline with a different result exists for the same target and "
                "calculation version; it is never updated",
                details={
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts[:_MAX_REPORTED_CONFLICTS],
                    "calculation_version": CALCULATION_VERSION,
                },
                status_code=HTTPStatus.CONFLICT,
            )

        self._expected.insert_baselines(to_insert)
        self._expected.insert_comparables(to_insert)
        ready = sum(item.computation.status == ExpectedStatus.READY for item in calculated)
        logger.info(
            "expected baselines stored workspace_id=%s property_id=%s data_source_id=%s "
            "created=%d unchanged=%d ready=%d insufficient=%d",
            self._tenant.workspace_id,
            property_id,
            data_source_id,
            len(to_insert),
            len(calculated) - len(to_insert),
            ready,
            len(calculated) - ready,
        )
        return ExpectedRunResult(
            property_id=property_id,
            data_source_id=data_source_id,
            created=len(to_insert),
            unchanged=len(calculated) - len(to_insert),
            ready=ready,
            insufficient=len(calculated) - ready,
            skipped_negative_lead_time=skipped,
            baseline_ids=tuple(baseline_ids),
        )


def _new_signature(item: NewBaseline) -> tuple[Any, ...]:
    computation = item.computation
    selection = computation.selection
    statistics = computation.statistics
    return (
        computation.status.value,
        None if statistics is None else statistics.expected,
        None if statistics is None else statistics.lower,
        None if statistics is None else statistics.upper,
        None if statistics is None else statistics.iqr,
        selection.sample_size,
        selection.observed_count,
        selection.reconstructed_count,
        selection.rejected_uncertain_count,
        computation.confidence_score,
        None if computation.confidence_band is None else computation.confidence_band.value,
        METHOD,
        CALCULATION_VERSION,
        item.comparable_fingerprint,
    )


def _signature(row: BookingExpectedBaseline) -> tuple[Any, ...]:
    """The stored baseline in the same shape as `_new_signature` (Decimals compare by value)."""
    return (
        row.status.value,
        row.expected_rooms_on_books,
        row.expected_lower,
        row.expected_upper,
        row.iqr,
        row.sample_size,
        row.observed_sample_size,
        row.reconstructed_sample_size,
        row.rejected_uncertain_count,
        Decimal(row.confidence_score),
        None if row.confidence_band is None else row.confidence_band.value,
        row.method,
        row.calculation_version,
        row.comparable_fingerprint,
    )
