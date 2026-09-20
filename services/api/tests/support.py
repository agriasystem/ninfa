"""Shared helpers for the database tests (imported by conftest.py and by the test modules)."""

import builtins
import itertools
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.bookings.channels import normalize_channel_name
from app.modules.bookings.models import (
    Booking,
    BookingChannel,
    BookingImportRow,
    BookingMappingProfile,
    BookingStatus,
    ImportRowStatus,
)
from app.modules.identity.models import User
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportFile,
    ImportJob,
)
from app.modules.properties.models import Property
from app.modules.tenancy.models import MembershipRole, Workspace, WorkspaceMembership

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

Rejects = Callable[..., AbstractContextManager[None]]


def alembic_config(database_url: str) -> Config:
    """Alembic configuration bound to an explicit database (never the developer's)."""
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    return config


def make_rejects(session: Session) -> Rejects:
    """Build `rejects(ErrorClass, constraint_name)`: asserts PostgreSQL refuses the body.

    The body runs in a savepoint (the session stays usable afterwards) and is flushed. It
    matches the SQLSTATE class and, optionally, the exact constraint name, so a test cannot
    pass because a *different* constraint fired.
    """

    @contextmanager
    def rejects(
        error: type[psycopg.Error], constraint: str | tuple[str, ...] | None = None
    ) -> Iterator[None]:
        with pytest.raises(IntegrityError) as info, session.begin_nested():
            yield
            session.flush()
        original = info.value.orig
        assert isinstance(original, error), f"expected {error.__name__}, got {original!r}"
        if constraint is not None:
            assert isinstance(original, psycopg.Error)
            allowed = (constraint,) if isinstance(constraint, str) else constraint
            assert original.diag.constraint_name in allowed, original.diag.constraint_name

    return rejects


@dataclass
class Tenant:
    """One complete, self-consistent tenant chain."""

    workspace: Workspace
    property: Property
    data_source: DataSource
    import_job: ImportJob

    @builtins.property
    def context(self) -> TenantContext:
        return TenantContext(self.workspace.id)


class Factory:
    """Creates rows directly through the ORM (independent of the repositories under test)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._counter = itertools.count(1)

    def _flush[T](self, entity: T) -> T:
        self.session.add(entity)
        self.session.flush()
        return entity

    def user(self, email: str | None = None) -> User:
        return self._flush(User(email=email or f"user{next(self._counter)}@example.com"))

    def workspace(self, slug: str | None = None) -> Workspace:
        slug = slug or f"ws-{next(self._counter)}"
        return self._flush(Workspace(name=slug.upper(), slug=slug))

    def membership(
        self, workspace: Workspace, user: User, role: MembershipRole = MembershipRole.MEMBER
    ) -> WorkspaceMembership:
        return self._flush(
            WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=role)
        )

    def property(self, workspace: Workspace, slug: str | None = None) -> Property:
        slug = slug or f"prop-{next(self._counter)}"
        return self._flush(Property(workspace_id=workspace.id, name=slug.upper(), slug=slug))

    def data_source(
        self, prop: Property, domain: DataSourceDomain = DataSourceDomain.BOOKINGS
    ) -> DataSource:
        return self._flush(
            DataSource(
                workspace_id=prop.workspace_id,
                property_id=prop.id,
                name=f"source-{next(self._counter)}",
                domain=domain,
                source_type=DataSourceType.FILE_UPLOAD,
            )
        )

    def import_job(self, data_source: DataSource) -> ImportJob:
        return self._flush(
            ImportJob(
                workspace_id=data_source.workspace_id,
                property_id=data_source.property_id,
                data_source_id=data_source.id,
            )
        )

    def import_file(self, job: ImportJob, sha256: str | None = None) -> ImportFile:
        return self._flush(
            ImportFile(
                workspace_id=job.workspace_id,
                import_job_id=job.id,
                original_filename=f"file-{next(self._counter)}.csv",
                sha256=sha256,
            )
        )

    def tenant(self) -> Tenant:
        workspace = self.workspace()
        prop = self.property(workspace)
        data_source = self.data_source(prop)
        return Tenant(workspace, prop, data_source, self.import_job(data_source))


# --- bookings ---------------------------------------------------------------------------------

VALID_FINGERPRINT = "a" * 64
VALID_SIGNATURE = "b" * 64


def booking_values(
    data_source: DataSource, channel: BookingChannel, job: ImportJob, **overrides: Any
) -> dict[str, Any]:
    """Column values of a valid booking (override any of them to build an invalid one)."""
    values: dict[str, Any] = {
        "workspace_id": data_source.workspace_id,
        "property_id": data_source.property_id,
        "data_source_id": data_source.id,
        "source_record_id": "BK-1",
        "booked_at": datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
        "check_in": date(2026, 3, 10),
        "check_out": date(2026, 3, 13),
        "status": BookingStatus.CONFIRMED,
        "rooms": 1,
        "guests": None,
        "room_revenue": Decimal("450.00"),
        "total_revenue": None,
        "channel_id": channel.id,
        "commission_amount": None,
        "commission_rate": None,
        "cancelled_at": None,
        "room_type": None,
        "rate_plan": None,
        "source_fingerprint": VALID_FINGERPRINT,
        "first_import_job_id": job.id,
        "last_import_job_id": job.id,
    }
    values.update(overrides)
    return values


def insert_core(session: Session, model: type[Any], **values: Any) -> None:
    """INSERT through Core: no ORM relationship or unit-of-work logic in between."""
    session.execute(insert(model), values)


class BookingFactory(Factory):
    """Factory extension with the Gate 2 entities."""

    def channel(self, prop: Property, name: str = "Booking.com", **columns: Any) -> BookingChannel:
        return self._flush(
            BookingChannel(
                workspace_id=prop.workspace_id,
                property_id=prop.id,
                name=name,
                normalized_name=normalize_channel_name(name),
                **columns,
            )
        )

    def booking(
        self, data_source: DataSource, channel: BookingChannel, job: ImportJob, **overrides: Any
    ) -> Booking:
        return self._flush(Booking(**booking_values(data_source, channel, job, **overrides)))

    def profile(self, data_source: DataSource, **overrides: Any) -> BookingMappingProfile:
        values: dict[str, Any] = {
            "workspace_id": data_source.workspace_id,
            "property_id": data_source.property_id,
            "data_source_id": data_source.id,
            "column_mapping": {"check_in": {"column": "Check-in"}},
            "status_mapping": {},
            "channel_mapping": {},
            "format_options": {},
            "header_signature": VALID_SIGNATURE,
        }
        values.update(overrides)
        return self._flush(BookingMappingProfile(**values))

    def import_row(
        self, job: ImportJob, import_file: ImportFile, row_number: int = 1, **overrides: Any
    ) -> BookingImportRow:
        values: dict[str, Any] = {
            "workspace_id": job.workspace_id,
            "import_job_id": job.id,
            "import_file_id": import_file.id,
            "row_number": row_number,
            "mapped_payload": {"check_in": "2026-03-10"},
            "normalized_payload": {"check_in": "2026-03-10"},
            "validation_status": ImportRowStatus.VALID,
            "validation_errors": [],
        }
        values.update(overrides)
        return self._flush(BookingImportRow(**values))
