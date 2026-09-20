"""Shared helpers for the database tests (imported by conftest.py and by the test modules)."""

import builtins
import itertools
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
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
    def rejects(error: type[psycopg.Error], constraint: str | None = None) -> Iterator[None]:
        with pytest.raises(IntegrityError) as info, session.begin_nested():
            yield
            session.flush()
        original = info.value.orig
        assert isinstance(original, error), f"expected {error.__name__}, got {original!r}"
        if constraint is not None:
            assert isinstance(original, psycopg.Error)
            assert original.diag.constraint_name == constraint

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
