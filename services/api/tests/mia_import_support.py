"""Worlds for the Mia import and structure tool tests: real imports, sources and remembered answers.

Everything is a real row in the real database (rolled back): jobs through the factory with the
lifecycle CHECKs satisfied, remembered words and families through the real mapping profile, so the
tools read exactly what the data-sources screens read.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.modules.data_sources.source_learning import Learning, Memory, Trust, Via, stored_learning
from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    FileScope,
    ImportFile,
    ImportJob,
    ImportJobStatus,
)
from tests.mia_support import MiaWorld, mia_world
from tests.support import BookingFactory

NOON = datetime(2026, 7, 31, 9, 15, tzinfo=UTC)


def empty_world(factory: BookingFactory, db_session: Session) -> MiaWorld:
    """A property with NO active data source and NO import at all (the tenant chain of the factory
    always carries one of each: this takes them away, as a property nobody has set up)."""
    world = mia_world(factory, db_session)
    tenant = world.at.tenant
    db_session.delete(tenant.import_job)
    tenant.data_source.is_active = False
    db_session.flush()
    return world


def finish(
    job: ImportJob,
    status: ImportJobStatus,
    finished_at: datetime,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    changed_data: bool | None = None,
    file_scope: FileScope | None = None,
    remembered_file_scope: FileScope | None = None,
    session: Session,
) -> ImportJob:
    """Put a job in a terminal state with every lifecycle CHECK of `import_jobs` satisfied."""
    job.status = status
    job.started_at = finished_at - timedelta(minutes=2)
    job.finished_at = finished_at
    job.error_code = error_code
    job.error_message = error_message
    job.changed_data = changed_data
    job.file_scope = file_scope
    job.remembered_file_scope = remembered_file_scope
    session.flush()
    return job


def add_import(
    factory: BookingFactory,
    source: DataSource,
    status: ImportJobStatus,
    finished_at: datetime,
    *,
    file_name: str | None = "prenotazioni.csv",
    **fields: Any,
) -> ImportJob:
    job = factory.import_job(source)
    finish(job, status, finished_at, session=factory.session, **fields)
    if file_name is not None:
        attached = factory.import_file(job)
        attached.original_filename = file_name
        factory.session.flush()
    return job


def attach_file_name(factory: BookingFactory, job: ImportJob, name: str) -> ImportFile:
    attached = factory.import_file(job)
    attached.original_filename = name
    factory.session.flush()
    return attached


def family(
    *,
    answers: dict[str, str] | None = None,
    scope: FileScope | None = None,
    columns: tuple[str, ...] = ("Codice prenotazione", "Check-in", "Check-out"),
    person: dict[str, str] | None = None,
) -> Memory:
    """One kind of file a person confirmed, as a source remembers it."""
    return Memory(
        trust=Trust.PERSON,
        origin=Via.ANSWERS,
        domain=DataSourceDomain.BOOKINGS.value,
        shape=[(column, "TEXT") for column in columns],
        mapped={"check_in": columns[1]},
        person=person or {"check_in": columns[1]},
        answers=answers or {},
        id="f1",
        touched=1,
        file_scope=scope,
    )


def teach(
    factory: BookingFactory,
    source: DataSource,
    *,
    words: dict[str, str] | None = None,
    channels: dict[str, Any] | None = None,
    families: list[Memory] | None = None,
) -> None:
    """A stored profile for a BOOKINGS source: remembered words (`status_mapping`) and families."""
    learning = Learning(seq=len(families or []), current="", families=families or [])
    factory.profile(
        source,
        status_mapping=words or {},
        channel_mapping=channels or {},
        format_options={"learning": stored_learning(learning)} if families else {},
    )


__all__ = [
    "NOON",
    "add_import",
    "attach_file_name",
    "empty_world",
    "family",
    "finish",
    "teach",
]
