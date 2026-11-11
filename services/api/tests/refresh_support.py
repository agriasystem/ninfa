"""A real hotel in the real test database, with REAL commits: what the post-import tests share.

Files go through the same CLI imports the pilot uses; `purge` removes everything a test left, the
queue's rows included, because nothing here is rolled back.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.cli.imports import run_import_bookings, run_import_invoices, run_import_labor
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.analysis import AnalysisStatusService, enqueue_refresh, run_refresh
from app.modules.bookings.mapping import CanonicalField
from app.modules.bookings.service import BookingImportService
from app.modules.decisions.models import Decision, DecisionRun
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.ingestion.canonical_csv import (
    booking_format_options,
    identity_column_mapping,
    labor_format_options,
    read_headers,
)
from app.modules.ingestion.models import DataSourceDomain, FileScope
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.ingestion.scope import ScopePlan
from app.modules.intelligence.expected.seasonality import eligible_stay_dates
from app.modules.intelligence.priority.types import PriorityContext
from app.modules.labor.mapping import LaborField
from app.modules.labor.service import LaborImportService
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.models import SnapshotOrigin
from app.modules.snapshots.repository import RoomInventoryRepository
from app.modules.tenancy.models import Workspace
from app.modules.tenancy.repository import WorkspaceRepository
from tests.decision_support import sync_run
from tests.expected_support import add_snapshots, snapshot_row
from tests.invoice_support import Body, fattura_xml
from tests.pilot_support import labor_csv

ROME = ZoneInfo("Europe/Rome")


def local_today() -> date:
    return datetime.now(ROME).date()


@dataclass
class Hotel:
    engine: Engine
    tenant: TenantContext
    property_id: uuid.UUID
    tmp_dir: Path
    slug: str
    booking_source_id: uuid.UUID | None = None

    def session(self) -> Session:
        return Session(self.engine)

    def source(self, domain: DataSourceDomain) -> uuid.UUID:
        """The property's source of this kind, created the way the pilot does when it has none."""
        with self.session() as session:
            repository = DataSourceRepository(session, self.tenant)
            existing = [
                item
                for item in repository.list_all(property_id=self.property_id)
                if item.domain == domain
            ]
            if existing:
                return existing[0].id
            run_create_data_source(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                domain=domain,
                name=domain.value,
            )
            return next(
                item.id
                for item in repository.list_all(property_id=self.property_id)
                if item.domain == domain
            )

    def bookings_source(self) -> uuid.UUID:
        self.booking_source_id = self.source(DataSourceDomain.BOOKINGS)
        return self.booking_source_id

    def import_bookings(
        self, name: str, rows: list[dict[str, Any]], *, file_scope: FileScope | None = None
    ) -> None:
        """Through the CLI; with `file_scope`, the same two steps on the service (the CLI asks no
        one what a file is, so it has no way of saying it)."""
        source_id = self.bookings_source()
        path = self.tmp_dir / name
        header = list(rows[0])
        lines = [",".join(header), *[",".join(row[key] for key in header) for row in rows]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if file_scope is not None:
            content = path.read_bytes()
            with self.session() as session:
                bookings = BookingImportService(session, self.tenant)
                bookings.save_mapping(
                    source_id,
                    headers=header,
                    column_mapping=identity_column_mapping(header, CanonicalField),
                    format_options=booking_format_options(),
                    property_id=self.property_id,
                )
                result = bookings.import_file(
                    source_id,
                    filename=name,
                    content=content,
                    property_id=self.property_id,
                    scope=ScopePlan(file_scope),
                )
            assert result.succeeded, result
            return
        with self.session() as session:
            exit_code = run_import_bookings(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                data_source_id=source_id,
                file=path,
            )
        assert exit_code == 0

    def import_shifts(
        self,
        name: str,
        rows: Sequence[tuple[date, str, str, str]],
        *,
        on: date | None = None,
        file_scope: FileScope | None = None,
    ) -> uuid.UUID:
        """A labor file of (work date, category, planned hours, planned cost), dated as of `on`.
        With `file_scope`, the same two steps of the CLI on the service."""
        source_id = self.source(DataSourceDomain.LABOR)
        path = self.tmp_dir / name
        lines = ["work_date,labor_category,planned_hours,planned_cost,currency"]
        lines += [f"{day.isoformat()},{cat},{hours},{cost},EUR" for day, cat, hours, cost in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if file_scope is not None:
            content = path.read_bytes()
            headers = read_headers(content)
            with self.session() as session:
                labor = LaborImportService(session, self.tenant)
                labor.save_mapping(
                    source_id,
                    headers=headers,
                    column_mapping=identity_column_mapping(headers, LaborField),
                    format_options=labor_format_options(),
                    property_id=self.property_id,
                )
                result = labor.import_file(
                    source_id,
                    filename=name,
                    content=content,
                    snapshot_local_date=on or local_today(),
                    property_id=self.property_id,
                    scope=ScopePlan(file_scope),
                )
            assert result.succeeded, result
            return source_id
        with self.session() as session:
            exit_code = run_import_labor(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                data_source_id=source_id,
                file=path,
                snapshot_local_date=on or local_today(),
            )
        assert exit_code == 0
        return source_id

    def import_labor(self, days: list[date]) -> uuid.UUID:
        source_id = self.source(DataSourceDomain.LABOR)
        path = labor_csv(self.tmp_dir, work_dates=days)
        with self.session() as session:
            exit_code = run_import_labor(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                data_source_id=source_id,
                file=path,
                snapshot_local_date=local_today(),
            )
        assert exit_code == 0
        return source_id

    def import_invoices(self, days: list[date]) -> None:
        source_id = self.source(DataSourceDomain.COSTS)
        path = self.tmp_dir / "fatture.xml"
        bodies = [
            Body(number=f"F-{index}", date=day.isoformat()) for index, day in enumerate(days, 1)
        ]
        path.write_bytes(fattura_xml(bodies))
        with self.session() as session:
            exit_code = run_import_invoices(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                data_source_id=source_id,
                file=path,
            )
        assert exit_code == 0

    def status(self, now: datetime | None = None) -> Any:
        with self.session() as session:
            return AnalysisStatusService(session, self.tenant).status(self.property_id, now)

    def enqueue(self, scheduled_at: datetime | None = None) -> int | None:
        with self.session() as session:
            job_id = enqueue_refresh(
                session, self.tenant, self.property_id, scheduled_at=scheduled_at
            )
            session.commit()
        return job_id

    def refresh(self) -> Any:
        with self.session() as session:
            return run_refresh(session, self.tenant.workspace_id, self.property_id)

    def set_job(self, job_id: int, status: str) -> None:
        with self.session() as session:
            session.execute(
                text("UPDATE procrastinate_jobs SET status = :s WHERE id = :i"),
                {"s": status, "i": job_id},
            )
            session.commit()

    def runs(self) -> list[DecisionRun]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(DecisionRun)
                    .where(DecisionRun.workspace_id == self.tenant.workspace_id)
                    .order_by(DecisionRun.run_sequence)
                ).all()
            )

    def runs_today(self) -> list[DecisionRun]:
        return [run for run in self.runs() if run.as_of_local_date == local_today()]


def analysed_on(
    hotel: Hotel,
    day: date,
    *,
    import_job_id: uuid.UUID | None = None,
    finished_at: datetime | None = None,
    revision: int = 1,
) -> None:
    """What a finished analysis of an earlier day leaves behind: the import it saw and the
    observation it read. With no import named, one of its own: the source had something new."""
    provenance = RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=hotel.bookings_source(),
            import_job_id=import_job_id or uuid.uuid4(),
            last_successful_import_finished_at=finished_at or datetime.now(UTC),
            snapshot_local_date=day,
            observation_revision=revision,
        )
    )
    context = PriorityContext(hotel.tenant.workspace_id, hotel.property_id, day)
    with hotel.session() as session:
        sync_run(session, hotel.tenant, context, [], provenance=provenance)


def booking_row(code: str, offset: int, *, revenue: str = "150.00") -> dict[str, Any]:
    stay = local_today() + timedelta(days=offset)
    return {
        "source_record_id": code,
        "booked_at": (local_today() - timedelta(days=20)).isoformat(),
        "check_in": stay.isoformat(),
        "check_out": (stay + timedelta(days=1)).isoformat(),
        "status": "confirmed",
        "rooms": "1",
        "room_revenue": revenue,
        "channel": "Booking.com",
    }


def slow_stay() -> date:
    return local_today() + timedelta(days=10)


def comparable_nights(stay: date) -> list[date]:
    return [day for day in eligible_stay_dates(stay) if day < local_today()][:8]


def curve_prior_days_keeping_anchors(stay: date) -> set[date]:
    """Days whose loss takes the seven-days-earlier end from most curve pairs, and still leaves the
    five comparables a baseline needs: a prior's day is often another night's comparable."""
    nights = comparable_nights(stay)
    anchors = {night - timedelta(days=10) for night in nights}
    days: set[date] = set()
    for night in nights:
        prior = night - timedelta(days=17)
        if len(anchors - days - {prior}) >= 5:
            days.add(prior)
    return days


def seed_slow_night(
    hotel: Hotel,
    *,
    rooms_a_week_ago: int = 1,
    unfinished: Collection[date] = frozenset(),
    repeated: Collection[date] = frozenset(),
    origin: SnapshotOrigin = SnapshotOrigin.OBSERVED,
    analysed: bool = True,
) -> date:
    """A night ten days away whose comparable nights all gained rooms in their last week: what
    makes the real detectors speak, from real snapshots and real engines.

    Each day of that history had its finished analysis, with something new in it, as a real one
    would have. Except `unfinished` days (the job died after the observation: rows and no run) and
    `repeated` ones (the day only repeated what the day before said). `analysed=False`: none yet.
    """
    stay = slow_stay()
    source = hotel.bookings_source()
    tenant = SimpleNamespace(
        workspace=SimpleNamespace(id=hotel.tenant.workspace_id),
        property=SimpleNamespace(id=hotel.property_id),
        data_source=SimpleNamespace(id=source),
    )
    week_ago = local_today() - timedelta(days=7)
    rows = [snapshot_row(tenant, week_ago, stay, rooms=rooms_a_week_ago)]  # type: ignore[arg-type]
    for past in comparable_nights(stay):
        for snapshot_day, rooms in (
            (past - timedelta(days=17), 10),
            (past - timedelta(days=10), 20),
            (past, 30),
        ):
            rows.append(
                snapshot_row(tenant, snapshot_day, past, rooms=rooms, origin=origin)  # type: ignore[arg-type]
            )
    with hotel.session() as session:
        add_snapshots(session, tenant, rows)  # type: ignore[arg-type]
        RoomInventoryRepository(session, hotel.tenant).set_for_date(
            hotel.property_id, stay, rooms_available=40
        )
        session.commit()
    if analysed:
        days = sorted({row["snapshot_local_date"] for row in rows})
        previous = uuid.uuid4()
        analysed_on(hotel, days[0] - timedelta(days=1), import_job_id=previous)
        for day in days:
            if day not in unfinished:
                previous = previous if day in repeated else uuid.uuid4()
                analysed_on(hotel, day, import_job_id=previous)
    return stay


def pickup_decisions(hotel: Hotel) -> list[tuple[Any, ...]]:
    with hotel.session() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    Decision.id,
                    Decision.status,
                    Decision.episode_count,
                    Decision.resolved_local_date,
                ).where(
                    Decision.workspace_id == hotel.tenant.workspace_id,
                    Decision.decision_type == "REV_PICKUP_LOW",
                )
            ).all()
        ]


def rooms_on(night_offset: int, count: int) -> list[dict[str, Any]]:
    return [booking_row(f"R{index}", night_offset) for index in range(count)]


def purge(engine: Engine, workspace_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(
            text("DELETE FROM procrastinate_jobs WHERE args ->> 'workspace_id' = :w"),
            {"w": str(workspace_id)},
        )
        for table in reversed(Base.metadata.sorted_tables):
            if "workspace_id" in table.c and table.name not in {"properties", "workspaces"}:
                session.execute(delete(table).where(table.c.workspace_id == workspace_id))
        session.execute(delete(Property).where(Property.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


def make_hotel(engine: Engine, tmp_path: Path, *, name: str = "Hotel Refresh") -> Hotel:
    slug = f"refresh-{uuid.uuid4().hex[:10]}"
    with Session(engine) as session:
        run_create_workspace(session, name=name, slug=slug)
        run_create_property(
            session,
            workspace_slug=slug,
            name=name,
            slug=slug,
            timezone="Europe/Rome",
            currency="EUR",
        )
        workspace = WorkspaceRepository(session).get_by_slug(slug)
        assert workspace is not None
        tenant = TenantContext(workspace.id)
        prop = PropertyRepository(session, tenant).get_by_slug(slug)
        assert prop is not None
        property_id = prop.id
    return Hotel(engine, tenant, property_id, tmp_path, slug)
