"""Gate 21B: the tenant/property/user/data-source bootstrap CLI (`app/cli/pilot.py`) is the ONLY
supported way to set up a new hotel for a pilot - these tests exercise its real `run_*` functions
directly against a real database session, never a test factory standing in for them (see
docs/architecture/pilot-readiness-v1.md).
"""

from datetime import date

import psycopg.errors as pg
import pytest
from sqlalchemy.orm import Session

from app.cli.pilot import (
    run_create_data_source,
    run_create_property,
    run_create_user,
    run_create_workspace,
    run_grant_access,
    run_set_room_inventory,
)
from app.core.exceptions import NotFoundError
from app.core.tenant import TenantContext
from app.modules.ingestion.models import DataSourceDomain
from app.modules.ingestion.repository import DataSourceRepository
from app.modules.properties.repository import PropertyRepository
from app.modules.snapshots.repository import RoomInventoryRepository
from app.modules.tenancy.models import MembershipRole
from app.modules.tenancy.repository import MembershipRepository, WorkspaceRepository
from tests.support import Rejects


def test_01_full_bootstrap_chain_happy_path(db_session: Session, rejects: Rejects) -> None:
    """create-workspace -> create-property -> create-user -> grant-access -> create-data-source
    -> set-room-inventory, each reading back through the SAME repositories a real HTTP request
    would use - proving the CLI reused the canonical models rather than a parallel setup path."""
    run_create_workspace(db_session, name="Hotel Aurora", slug="hotel-aurora-01")
    workspace = WorkspaceRepository(db_session).get_by_slug("hotel-aurora-01")
    assert workspace is not None

    run_create_property(
        db_session,
        workspace_slug="hotel-aurora-01",
        name="Hotel Aurora",
        slug="hotel-aurora-01",
        timezone="Europe/Rome",
        currency="EUR",
    )
    tenant = TenantContext(workspace_id=workspace.id)
    prop = PropertyRepository(db_session, tenant).get_by_slug("hotel-aurora-01")
    assert prop is not None
    assert prop.timezone == "Europe/Rome"
    assert prop.currency == "EUR"

    run_create_user(db_session, email="operator@example.com", display_name="Operator")
    run_grant_access(
        db_session,
        workspace_slug="hotel-aurora-01",
        email="operator@example.com",
        role=MembershipRole.OWNER,
    )
    membership = MembershipRepository(db_session, tenant).list_all()
    assert len(membership) == 1
    assert membership[0].role == MembershipRole.OWNER

    run_create_data_source(
        db_session,
        workspace_slug="hotel-aurora-01",
        property_slug="hotel-aurora-01",
        domain=DataSourceDomain.BOOKINGS,
        name="Bookings",
    )
    data_sources = DataSourceRepository(db_session, tenant).list_all(property_id=prop.id)
    assert len(data_sources) == 1
    assert data_sources[0].domain == DataSourceDomain.BOOKINGS

    run_set_room_inventory(
        db_session,
        workspace_slug="hotel-aurora-01",
        property_slug="hotel-aurora-01",
        stay_date_start=date(2026, 10, 1),
        stay_date_end=date(2026, 10, 3),
        rooms_available=20,
        rooms_out_of_order=1,
    )
    inventory = RoomInventoryRepository(db_session, tenant).list_for_range(
        prop.id, date(2026, 10, 1), date(2026, 10, 3)
    )
    assert len(inventory) == 3
    assert {row.rooms_available for row in inventory} == {20}
    assert {row.rooms_out_of_order for row in inventory} == {1}


def test_02_create_property_unknown_workspace_rejected(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        run_create_property(
            db_session,
            workspace_slug="does-not-exist",
            name="X",
            slug="x",
            timezone="Europe/Rome",
            currency="EUR",
        )


def test_03_grant_access_unknown_user_rejected(db_session: Session) -> None:
    run_create_workspace(db_session, name="Hotel Aurora", slug="hotel-aurora-03")
    with pytest.raises(NotFoundError):
        run_grant_access(
            db_session,
            workspace_slug="hotel-aurora-03",
            email="nobody@example.com",
            role=MembershipRole.OWNER,
        )


def test_04_create_data_source_unknown_property_rejected(db_session: Session) -> None:
    run_create_workspace(db_session, name="Hotel Aurora", slug="hotel-aurora-04")
    with pytest.raises(NotFoundError):
        run_create_data_source(
            db_session,
            workspace_slug="hotel-aurora-04",
            property_slug="does-not-exist",
            domain=DataSourceDomain.BOOKINGS,
            name="Bookings",
        )


def test_05_duplicate_workspace_slug_rejected_by_the_database(
    db_session: Session, rejects: Rejects
) -> None:
    """The CLI adds no uniqueness check of its own: PostgreSQL's own constraint is the only
    thing standing between two operators racing to create the same slug, exactly as it already
    is for every other write path in this codebase."""
    run_create_workspace(db_session, name="Hotel Aurora", slug="hotel-aurora-05")
    with rejects(pg.UniqueViolation, "uq_workspaces_slug"):
        run_create_workspace(db_session, name="Hotel Aurora Duplicate", slug="hotel-aurora-05")


def test_06_set_room_inventory_start_after_end_rejected(db_session: Session) -> None:
    run_create_workspace(db_session, name="Hotel Aurora", slug="hotel-aurora-06")
    run_create_property(
        db_session,
        workspace_slug="hotel-aurora-06",
        name="Hotel Aurora",
        slug="hotel-aurora-06",
        timezone="Europe/Rome",
        currency="EUR",
    )
    with pytest.raises(SystemExit):
        run_set_room_inventory(
            db_session,
            workspace_slug="hotel-aurora-06",
            property_slug="hotel-aurora-06",
            stay_date_start=date(2026, 10, 5),
            stay_date_end=date(2026, 10, 1),
            rooms_available=10,
            rooms_out_of_order=0,
        )
