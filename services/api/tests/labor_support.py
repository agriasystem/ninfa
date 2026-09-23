"""Shared helpers for the Gate 8 (labor ingestion / LABOR_OVERSTAFFING) tests."""

from __future__ import annotations

import builtins
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSource, DataSourceDomain, ImportFile, ImportJob
from app.modules.labor.models import LaborEntry, LaborImportRow, LaborMappingProfile, LaborSnapshot
from app.modules.labor.roles import LaborCategory, LaborClassificationMethod
from app.modules.properties.models import Property
from app.modules.snapshots.models import BookingSnapshot, SnapshotOrigin
from app.modules.tenancy.models import Workspace
from tests.support import VALID_FINGERPRINT, BookingFactory

# The Gate 8 tests use the SAME shared `factory: BookingFactory` fixture every other gate's tests
# do (no per-module fixture override): these are free functions over it, exactly like
# `costs_source()` in `invoice_support.py` or `CostWorld.create(factory)` in `cost_support.py`.
LaborFactory = BookingFactory


@dataclass
class LaborTenant:
    """A tenant chain with BOTH a BOOKINGS and a LABOR data source (same workspace/property)."""

    workspace: Workspace
    property: Property
    booking_data_source: DataSource
    labor_data_source: DataSource
    booking_import_job: ImportJob
    labor_import_job: ImportJob

    @builtins.property
    def context(self) -> TenantContext:
        return TenantContext(self.workspace.id)


def labor_snapshot_values(
    data_source: DataSource, job: ImportJob, import_file: ImportFile, **overrides: Any
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": data_source.workspace_id,
        "property_id": data_source.property_id,
        "data_source_id": data_source.id,
        "snapshot_local_date": date(2026, 3, 1),
        "source_import_job_id": job.id,
        "source_import_file_id": import_file.id,
        "source_fingerprint": VALID_FINGERPRINT,
    }
    values.update(overrides)
    return values


def labor_entry_values(snapshot: LaborSnapshot, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "workspace_id": snapshot.workspace_id,
        "labor_snapshot_id": snapshot.id,
        "source_row_number": 1,
        "work_date": date(2026, 3, 10),
        "role_raw": "Reception AM",
        "role_normalized": "reception am",
        "labor_category": LaborCategory.FRONT_OFFICE,
        "planned_minutes": 480,
        "actual_minutes": None,
        "planned_cost": None,
        "actual_cost": None,
        "currency": None,
        "classification_method": LaborClassificationMethod.DETERMINISTIC_RULE,
        "classification_confidence": Decimal("80.00"),
    }
    values.update(overrides)
    return values


def _flush[T](factory: BookingFactory, entity: T) -> T:
    factory.session.add(entity)
    factory.session.flush()
    return entity


def labor_data_source(factory: BookingFactory, prop: Property) -> DataSource:
    return factory.data_source(prop, domain=DataSourceDomain.LABOR)


def labor_tenant(factory: BookingFactory) -> LaborTenant:
    workspace = factory.workspace()
    prop = factory.property(workspace)
    booking_source = factory.data_source(prop, domain=DataSourceDomain.BOOKINGS)
    labor_source = labor_data_source(factory, prop)
    return LaborTenant(
        workspace=workspace,
        property=prop,
        booking_data_source=booking_source,
        labor_data_source=labor_source,
        booking_import_job=factory.import_job(booking_source),
        labor_import_job=factory.import_job(labor_source),
    )


def labor_snapshot(
    factory: BookingFactory,
    data_source: DataSource,
    job: ImportJob,
    import_file: ImportFile,
    **overrides: Any,
) -> LaborSnapshot:
    return _flush(
        factory, LaborSnapshot(**labor_snapshot_values(data_source, job, import_file, **overrides))
    )


def labor_entry(factory: BookingFactory, snapshot: LaborSnapshot, **overrides: Any) -> LaborEntry:
    return _flush(factory, LaborEntry(**labor_entry_values(snapshot, **overrides)))


def labor_mapping_profile(
    factory: BookingFactory, data_source: DataSource, **overrides: Any
) -> LaborMappingProfile:
    values: dict[str, Any] = {
        "workspace_id": data_source.workspace_id,
        "property_id": data_source.property_id,
        "data_source_id": data_source.id,
        "column_mapping": {"work_date": {"column": "Date"}},
        "role_mapping": {},
        "format_options": {},
        "header_signature": "b" * 64,
    }
    values.update(overrides)
    return _flush(factory, LaborMappingProfile(**values))


def labor_import_row(
    factory: BookingFactory,
    job: ImportJob,
    import_file: ImportFile,
    source_row_number: int = 1,
    **overrides: Any,
) -> LaborImportRow:
    values: dict[str, Any] = {
        "workspace_id": job.workspace_id,
        "import_job_id": job.id,
        "import_file_id": import_file.id,
        "source_row_number": source_row_number,
        "mapped_payload": {"work_date": "2026-03-10"},
        "normalized_payload": {"work_date": "2026-03-10"},
        "validation_status": "VALID",
        "validation_errors": [],
        "validation_warnings": [],
    }
    values.update(overrides)
    return _flush(factory, LaborImportRow(**values))


def _minutes(hours: str | None) -> int | None:
    if hours is None:
        return None
    return int(Decimal(hours) * 60)


class LaborWorld:
    """Builds a detector scenario directly via ORM (bypassing both import pipelines): a lead-
    time-0 booking snapshot per work date and ONE labor snapshot covering every work date."""

    def __init__(self, session: Session, tenant: LaborTenant) -> None:
        self.session = session
        self.tenant = tenant
        self._labor_snapshot: LaborSnapshot | None = None
        self._row_number = 0

    def booking_day(
        self,
        work_date: date,
        rooms_on_books: int,
        *,
        origin: SnapshotOrigin = SnapshotOrigin.OBSERVED,
        uncertain_rooms: int = 0,
    ) -> BookingSnapshot:
        """A lead-time-0 booking snapshot (`snapshot_local_date == stay_date == work_date`)."""
        uncertain = 0 if origin == SnapshotOrigin.OBSERVED else uncertain_rooms
        snapshot = BookingSnapshot(
            workspace_id=self.tenant.workspace.id,
            property_id=self.tenant.property.id,
            data_source_id=self.tenant.booking_data_source.id,
            snapshot_local_date=work_date,
            as_of_at=datetime.combine(work_date, time(23, 59), tzinfo=UTC),
            stay_date=work_date,
            origin=origin,
            booking_count_on_books=1 if rooms_on_books > 0 else 0,
            rooms_on_books=rooms_on_books,
            allocated_room_revenue_on_books=Decimal("0.00"),
            rooms_available=None,
            occupancy_on_books=None,
            adr_on_books=Decimal("100.00") if rooms_on_books > 0 else None,
            uncertain_booking_count=uncertain,
            uncertain_rooms=uncertain,
            calculation_version="test-v1",
            content_fingerprint=VALID_FINGERPRINT,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def _snapshot(self, snapshot_local_date: date) -> LaborSnapshot:
        if self._labor_snapshot is None:
            job = self.tenant.labor_import_job
            import_file = ImportFile(
                workspace_id=job.workspace_id, import_job_id=job.id, original_filename="world.csv"
            )
            self.session.add(import_file)
            self.session.flush()
            self._labor_snapshot = LaborSnapshot(
                **labor_snapshot_values(
                    self.tenant.labor_data_source,
                    job,
                    import_file,
                    snapshot_local_date=snapshot_local_date,
                )
            )
            self.session.add(self._labor_snapshot)
            self.session.flush()
        return self._labor_snapshot

    def labor_day(
        self,
        as_of_date: date,
        work_date: date,
        category: LaborCategory,
        *,
        role: str = "Test Role",
        planned_hours: str | None = None,
        actual_hours: str | None = None,
        planned_cost: str | None = None,
        actual_cost: str | None = None,
        currency: str | None = None,
        method: LaborClassificationMethod = LaborClassificationMethod.DETERMINISTIC_RULE,
        confidence: str = "80.00",
    ) -> LaborEntry:
        """Adds one entry to the world's (single, shared) labor snapshot, as of `as_of_date`."""
        snapshot = self._snapshot(as_of_date)
        self._row_number += 1
        entry = LaborEntry(
            **labor_entry_values(
                snapshot,
                source_row_number=self._row_number,
                work_date=work_date,
                role_raw=role,
                role_normalized=role.lower(),
                labor_category=category,
                planned_minutes=_minutes(planned_hours),
                actual_minutes=_minutes(actual_hours),
                planned_cost=None if planned_cost is None else Decimal(planned_cost),
                actual_cost=None if actual_cost is None else Decimal(actual_cost),
                currency=currency,
                classification_method=method,
                classification_confidence=Decimal(confidence),
            )
        )
        self.session.add(entry)
        self.session.flush()
        return entry


# --- CSV builders -------------------------------------------------------------------------------

CSV_HEADER = "work_date,role,planned_hours,actual_hours,planned_cost,actual_cost,currency"


def csv_row(
    work_date: str,
    role: str,
    planned_hours: str = "",
    actual_hours: str = "",
    planned_cost: str = "",
    actual_cost: str = "",
    currency: str = "",
) -> str:
    return (
        f"{work_date},{role},{planned_hours},{actual_hours},{planned_cost},{actual_cost},{currency}"
    )


def csv_of(rows: list[str]) -> bytes:
    return "\n".join([CSV_HEADER, *rows]).encode("utf-8")


DEFAULT_COLUMN_MAPPING: dict[str, Any] = {
    "work_date": {"column": "work_date"},
    "role": {"column": "role"},
    "planned_hours": {"column": "planned_hours"},
    "actual_hours": {"column": "actual_hours"},
    "planned_cost": {"column": "planned_cost"},
    "actual_cost": {"column": "actual_cost"},
    "currency": {"column": "currency"},
}


# --- query counting (reused from the cost intelligence tests' own pattern) ----------------------


@contextmanager
def statements_of(session: Session) -> Iterator[list[tuple[str, Any]]]:
    """Every SQL statement (text, parameters) the session's connection executes meanwhile."""
    connection = session.connection()
    assert isinstance(connection, Connection)
    captured: list[tuple[str, Any]] = []

    def record(*args: Any) -> None:
        captured.append((str(args[2]), args[3]))

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        event.remove(connection, "before_cursor_execute", record)
