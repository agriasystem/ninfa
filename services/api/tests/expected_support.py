"""Helpers shared by the Gate 4 (Expected Engine) tests. Synthetic data only."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.modules.intelligence.expected.calculator import (
    CALCULATION_VERSION,
    METHOD,
    ExpectedStatus,
)
from app.modules.intelligence.expected.confidence import ConfidenceBand
from app.modules.intelligence.expected.models import (
    BookingExpectedBaseline,
    BookingExpectedComparable,
)
from app.modules.intelligence.expected.repository import ExpectedRepository
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.expected.service import BookingExpectedService, ExpectedRunResult
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from tests.support import BookingFactory, Tenant

OBSERVED = SnapshotOrigin.OBSERVED
RECONSTRUCTED = SnapshotOrigin.RECONSTRUCTED_APPROXIMATE
TARGET_STAY = date(2026, 8, 15)  # a Saturday
LEAD = 14
TARGET_SNAPSHOT_DAY = TARGET_STAY - timedelta(days=LEAD)  # 2026-08-01
ELIGIBLE = eligible_stay_dates(TARGET_STAY)  # the 24 comparable stay dates, newest first
FINGERPRINT = "d" * 64


def snapshot_row(
    tenant: Tenant,
    snapshot_date: date,
    stay_date: date,
    *,
    rooms: int = 10,
    origin: SnapshotOrigin = OBSERVED,
    uncertain_rooms: int = 0,
    data_source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """A valid, internally consistent `booking_snapshots` row (all CHECKs satisfied)."""
    return {
        "id": uuid.uuid4(),
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "data_source_id": data_source_id or tenant.data_source.id,
        "snapshot_local_date": snapshot_date,
        "as_of_at": None,  # filled below
        "stay_date": stay_date,
        "origin": origin.value,
        "booking_count_on_books": 1 if rooms > 0 else 0,
        "rooms_on_books": rooms,
        "allocated_room_revenue_on_books": Decimal(rooms * 100),
        "rooms_available": None,
        "occupancy_on_books": None,
        "adr_on_books": Decimal("100.00") if rooms > 0 else None,
        "uncertain_booking_count": 1 if uncertain_rooms > 0 else 0,
        "uncertain_rooms": uncertain_rooms,
        "calculation_version": "booking-snapshot-v1",
        "content_fingerprint": FINGERPRINT,
    }


def add_snapshots(session: Session, tenant: Tenant, rows: list[dict[str, Any]]) -> None:
    """Bulk insert snapshot rows through Core (no service, no repository)."""
    for row in rows:
        if row["as_of_at"] is None:
            row["as_of_at"] = datetime.combine(
                row["snapshot_local_date"], datetime.min.time(), tzinfo=UTC
            ) + timedelta(hours=12)
    session.execute(insert(BookingSnapshot), rows)


@dataclass
class Scenario:
    """One tenant with a target observed snapshot and a controllable comparable history."""

    session: Session
    tenant: Tenant
    target_id: uuid.UUID
    history: dict[date, uuid.UUID] = field(default_factory=dict)  # stay date -> snapshot id

    @classmethod
    def create(
        cls,
        session: Session,
        factory: BookingFactory,
        *,
        target_rooms: int = 12,
        tenant: Tenant | None = None,
    ) -> "Scenario":
        tenant = tenant or factory.tenant()
        row = snapshot_row(tenant, TARGET_SNAPSHOT_DAY, TARGET_STAY, rooms=target_rooms)
        add_snapshots(session, tenant, [row])
        return cls(session, tenant, row["id"])

    def add_history(
        self,
        stays: list[date],
        *,
        rooms: list[int] | int = 10,
        origin: SnapshotOrigin = OBSERVED,
        uncertain_rooms: int = 0,
        lead: int = LEAD,
    ) -> list[uuid.UUID]:
        """Snapshots of the given stay dates at exactly `lead` days before each of them."""
        values = rooms if isinstance(rooms, list) else [rooms] * len(stays)
        rows = [
            snapshot_row(
                self.tenant,
                stay - timedelta(days=lead),
                stay,
                rooms=value,
                origin=origin,
                uncertain_rooms=uncertain_rooms,
            )
            for stay, value in zip(stays, values, strict=True)
        ]
        add_snapshots(self.session, self.tenant, rows)
        for stay, row in zip(stays, rows, strict=True):
            if lead == LEAD:
                self.history[stay] = row["id"]
        return [row["id"] for row in rows]

    def commit(self) -> None:
        self.session.commit()

    def service(self) -> BookingExpectedService:
        return BookingExpectedService(self.session, self.tenant.context)

    def calculate(self, target_id: uuid.UUID | None = None) -> ExpectedRunResult:
        self.commit()
        return self.service().calculate_for_target(
            property_id=self.tenant.property.id,
            data_source_id=self.tenant.data_source.id,
            target_snapshot_id=target_id or self.target_id,
        )

    def baseline(self, target_id: uuid.UUID | None = None) -> BookingExpectedBaseline:
        found = ExpectedRepository(self.session, self.tenant.context).get_for_target_snapshot(
            target_id or self.target_id
        )
        assert found is not None
        return found


def baseline_values(
    tenant: Tenant, target_snapshot_id: uuid.UUID, **overrides: Any
) -> dict[str, Any]:
    """Column values of a valid READY baseline (override to build an invalid one)."""
    values: dict[str, Any] = {
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "data_source_id": tenant.data_source.id,
        "target_snapshot_id": target_snapshot_id,
        "target_origin": "OBSERVED",
        "target_snapshot_local_date": TARGET_SNAPSHOT_DAY,
        "target_stay_date": TARGET_STAY,
        "lead_time_days": LEAD,
        "status": ExpectedStatus.READY.value,
        "expected_rooms_on_books": Decimal("12.50"),
        "expected_lower": Decimal("10.00"),
        "expected_upper": Decimal("15.00"),
        "iqr": Decimal("5.00"),
        "sample_size": 6,
        "observed_sample_size": 6,
        "reconstructed_sample_size": 0,
        "rejected_uncertain_count": 0,
        "confidence_score": Decimal("76.67"),
        "confidence_band": ConfidenceBand.MEDIUM.value,
        "method": METHOD,
        "calculation_version": CALCULATION_VERSION,
        "comparable_fingerprint": "e" * 64,
    }
    values.update(overrides)
    return values


def insufficient_values(
    tenant: Tenant, target_snapshot_id: uuid.UUID, **overrides: Any
) -> dict[str, Any]:
    values = baseline_values(
        tenant,
        target_snapshot_id,
        status=ExpectedStatus.INSUFFICIENT_DATA.value,
        expected_rooms_on_books=None,
        expected_lower=None,
        expected_upper=None,
        iqr=None,
        sample_size=4,
        observed_sample_size=4,
        confidence_score=Decimal("0.00"),
        confidence_band=None,
    )
    values.update(overrides)
    return values


def insert_baseline(session: Session, values: dict[str, Any]) -> uuid.UUID:
    values = {"id": uuid.uuid4(), **values}
    session.execute(insert(BookingExpectedBaseline), values)
    return values["id"]  # type: ignore[no-any-return]


def comparable_values(
    tenant: Tenant, baseline_id: uuid.UUID, snapshot_id: uuid.UUID, **overrides: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": tenant.workspace.id,
        "property_id": tenant.property.id,
        "data_source_id": tenant.data_source.id,
        "baseline_id": baseline_id,
        "snapshot_id": snapshot_id,
        "origin": "OBSERVED",
        "rooms_on_books": 10,
        "recency_rank": 1,
    }
    values.update(overrides)
    return values


def insert_comparable(session: Session, values: dict[str, Any]) -> None:
    session.execute(insert(BookingExpectedComparable), values)
