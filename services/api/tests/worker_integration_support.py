"""Committed (real-commit) hotels for the worker integration tests of Gates 25B/26B.

The worker opens its OWN Session on the test database, so these tests cannot use the rolled-back
`db_session` fixture: they bootstrap through the real pilot CLI functions with real commits and
delete everything they created afterwards.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.cli.imports import run_import_bookings
from app.cli.pilot import run_create_data_source, run_create_property, run_create_workspace
from app.core.tenant import TenantContext
from app.db.base import Base
from app.modules.decisions.models import DecisionRun
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.properties.models import Property
from app.modules.properties.repository import PropertyRepository
from app.modules.tenancy.models import Workspace
from app.modules.tenancy.repository import WorkspaceRepository
from tests.pilot_support import booking_csv


@dataclass
class Hotel:
    engine: Engine
    slug: str
    tenant: TenantContext
    property_id: uuid.UUID
    data_source_id: uuid.UUID
    stay_dates: list[date]

    def import_bookings(self, tmp_path: Path, filename: str = "bookings.csv") -> None:
        with Session(self.engine) as session:
            code = run_import_bookings(
                session,
                workspace_slug=self.slug,
                property_slug=self.slug,
                data_source_id=self.data_source_id,
                file=booking_csv(tmp_path, stay_dates=self.stay_dates, filename=filename),
            )
        assert code == 0

    def runs(self) -> list[DecisionRun]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(DecisionRun).where(DecisionRun.workspace_id == self.tenant.workspace_id)
                ).all()
            )


def purge(engine: Engine, workspace_id: uuid.UUID) -> None:
    """Delete everything a workspace owns, children before parents (FK dependency order)."""
    with Session(engine) as session:
        for table in reversed(Base.metadata.sorted_tables):
            if "workspace_id" in table.c and table.name not in {"properties", "workspaces"}:
                session.execute(delete(table).where(table.c.workspace_id == workspace_id))
        session.execute(delete(Property).where(Property.workspace_id == workspace_id))
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()


def create_hotel(engine: Engine, label: str, *, timezone: str = "Europe/Rome") -> Hotel:
    slug = f"w26b-{label}-{uuid.uuid4().hex[:8]}"
    stay_dates = [date.today() + timedelta(days=14), date.today() + timedelta(days=15)]
    with Session(engine) as session:
        run_create_workspace(session, name="Hotel Policy", slug=slug)
        run_create_property(
            session,
            workspace_slug=slug,
            name="Hotel Policy",
            slug=slug,
            timezone=timezone,
            currency="EUR",
        )
        workspace = WorkspaceRepository(session).get_by_slug(slug)
        assert workspace is not None
        tenant = TenantContext(workspace_id=workspace.id)
        prop = PropertyRepository(session, tenant).get_by_slug(slug)
        assert prop is not None
        run_create_data_source(
            session,
            workspace_slug=slug,
            property_slug=slug,
            domain=DataSourceDomain.BOOKINGS,
            name="Bookings",
        )
        source = DataSourceRepository(session, tenant).list_all(property_id=prop.id)[0]
        return Hotel(engine, slug, tenant, prop.id, source.id, stay_dates)
