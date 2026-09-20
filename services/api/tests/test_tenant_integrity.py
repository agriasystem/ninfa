"""DB-level tenant integrity.

These tests deliberately bypass every application safeguard (repositories, Pydantic schemas):
rows are written with the bare ORM or with raw SQL, exactly as a buggy or malicious code path
would. PostgreSQL itself must refuse any row that links two workspaces.
"""

from collections.abc import Callable
from typing import cast
from uuid import UUID

import psycopg.errors as pg
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.ingestion.models import (
    DataSource,
    DataSourceDomain,
    DataSourceType,
    ImportFile,
    ImportJob,
)
from tests.support import Factory, Rejects, Tenant

FK_DATA_SOURCE = "fk_data_sources_workspace_id_properties"
FK_IMPORT_JOB = "fk_import_jobs_workspace_id_data_sources"
FK_IMPORT_FILE = "fk_import_files_workspace_id_import_jobs"

_INSERT_SOURCE = text(
    "INSERT INTO data_sources (workspace_id, property_id, name, domain, source_type)"
    " VALUES (:workspace_id, :property_id, 'raw source', 'BOOKINGS', 'FILE_UPLOAD') RETURNING id"
)
_INSERT_JOB = text(
    "INSERT INTO import_jobs (workspace_id, property_id, data_source_id)"
    " VALUES (:workspace_id, :property_id, :data_source_id) RETURNING id"
)
_INSERT_FILE = text(
    "INSERT INTO import_files (workspace_id, import_job_id, original_filename)"
    " VALUES (:workspace_id, :import_job_id, 'raw.csv') RETURNING id"
)


def raw_source(session: Session, workspace_id: UUID, property_id: UUID) -> UUID:
    return cast(
        UUID,
        session.execute(
            _INSERT_SOURCE, {"workspace_id": workspace_id, "property_id": property_id}
        ).scalar_one(),
    )


def raw_job(session: Session, workspace_id: UUID, property_id: UUID, source_id: UUID) -> UUID:
    params = {"workspace_id": workspace_id, "property_id": property_id, "data_source_id": source_id}
    return cast(UUID, session.execute(_INSERT_JOB, params).scalar_one())


def raw_file(session: Session, workspace_id: UUID, job_id: UUID) -> UUID:
    params = {"workspace_id": workspace_id, "import_job_id": job_id}
    return cast(UUID, session.execute(_INSERT_FILE, params).scalar_one())


# --- DataSource -> Property ------------------------------------------------------------------


def test_data_source_in_the_same_workspace_as_its_property_is_accepted(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    assert raw_source(db_session, a.workspace.id, a.property.id)
    assert a.data_source.workspace_id == a.property.workspace_id


def test_data_source_of_workspace_a_cannot_reference_property_of_workspace_b_via_orm(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_DATA_SOURCE):
        db_session.add(
            DataSource(
                workspace_id=a.workspace.id,
                property_id=b.property.id,  # <- the mistake
                name="wrong",
                domain=DataSourceDomain.BOOKINGS,
                source_type=DataSourceType.FILE_UPLOAD,
            )
        )


def test_data_source_of_workspace_a_cannot_reference_property_of_workspace_b_via_raw_sql(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_DATA_SOURCE):
        raw_source(db_session, a.workspace.id, b.property.id)
    with rejects(pg.ForeignKeyViolation, FK_DATA_SOURCE):
        raw_source(db_session, b.workspace.id, a.property.id)


def test_data_source_cannot_reference_an_unknown_property(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, _ = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_DATA_SOURCE):
        raw_source(db_session, a.workspace.id, UUID(int=1))


def test_data_source_cannot_be_moved_to_another_workspace_by_update(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants
    unreferenced = factory.data_source(a.property)  # no job depends on it

    with rejects(pg.ForeignKeyViolation, FK_DATA_SOURCE):
        db_session.execute(
            text("UPDATE data_sources SET workspace_id = :b WHERE id = :id"),
            {"b": b.workspace.id, "id": unreferenced.id},
        )


def test_referenced_data_source_cannot_be_moved_either(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    """A source that jobs point at is additionally pinned by the jobs' composite key."""
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation):
        db_session.execute(
            text("UPDATE data_sources SET workspace_id = :b WHERE id = :id"),
            {"b": b.workspace.id, "id": a.data_source.id},
        )


# --- ImportJob -> DataSource / Property ------------------------------------------------------


def test_import_job_consistent_within_one_tenant_is_accepted(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    job_id = raw_job(db_session, a.workspace.id, a.property.id, a.data_source.id)

    status = db_session.execute(
        text("SELECT status FROM import_jobs WHERE id = :id"), {"id": job_id}
    ).scalar_one()
    assert status == "PENDING"  # server-side default


def test_import_job_cannot_reference_data_source_of_another_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    # Job in A pointing at B's data source (and B's property, so that pair is itself coherent).
    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        raw_job(db_session, a.workspace.id, b.property.id, b.data_source.id)
    # Job declared in B but pointing at A's data source.
    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        raw_job(db_session, b.workspace.id, a.property.id, a.data_source.id)


def test_import_job_cannot_reference_property_of_another_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    # Data source and workspace are A's, the property is B's.
    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        raw_job(db_session, a.workspace.id, b.property.id, a.data_source.id)


def test_import_job_property_must_be_the_data_sources_own_property(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    """Stricter than 'same workspace': a job cannot name a different property of its tenant."""
    a, _ = two_tenants
    other_property_of_a = factory.property(a.workspace)

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        raw_job(db_session, a.workspace.id, other_property_of_a.id, a.data_source.id)


def test_import_job_cross_tenant_via_orm_is_rejected(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        db_session.add(
            ImportJob(
                workspace_id=a.workspace.id,
                property_id=a.property.id,
                data_source_id=b.data_source.id,  # <- the mistake
            )
        )


def test_import_job_cannot_reference_an_unknown_data_source(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, _ = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        raw_job(db_session, a.workspace.id, a.property.id, UUID(int=1))


def test_import_job_cannot_be_moved_to_another_workspace_by_update(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_JOB):
        db_session.execute(
            text("UPDATE import_jobs SET workspace_id = :b WHERE id = :id"),
            {"b": b.workspace.id, "id": a.import_job.id},
        )


# --- ImportFile -> ImportJob -----------------------------------------------------------------


def test_import_file_in_the_same_workspace_as_its_job_is_accepted(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    assert raw_file(db_session, a.workspace.id, a.import_job.id)


def test_import_file_cannot_reference_import_job_of_another_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_FILE):
        raw_file(db_session, a.workspace.id, b.import_job.id)
    with rejects(pg.ForeignKeyViolation, FK_IMPORT_FILE):
        raw_file(db_session, b.workspace.id, a.import_job.id)


def test_import_file_cross_tenant_via_orm_is_rejected(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_FILE):
        db_session.add(
            ImportFile(
                workspace_id=a.workspace.id,
                import_job_id=b.import_job.id,  # <- the mistake
                original_filename="wrong.csv",
            )
        )


def test_import_file_cannot_reference_an_unknown_job(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, _ = two_tenants

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_FILE):
        raw_file(db_session, a.workspace.id, UUID(int=1))


def test_import_file_cannot_be_moved_to_another_workspace_by_update(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, b = two_tenants
    import_file = factory.import_file(a.import_job)

    with rejects(pg.ForeignKeyViolation, FK_IMPORT_FILE):
        db_session.execute(
            text("UPDATE import_files SET workspace_id = :b WHERE id = :id"),
            {"b": b.workspace.id, "id": import_file.id},
        )


# --- the explicit cross-tenant security scenario ---------------------------------------------


def test_no_application_mistake_can_produce_an_inconsistent_tenant_relationship(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    """Workspaces A and B, each with property/data source/job. Try every wrong link.

    Nothing here goes through a repository or a schema: it is the worst case where application
    code is simply wrong. Every attempt must be refused by PostgreSQL, and neither tenant's
    data may change.
    """
    a, b = two_tenants
    wa, pa, da, ja = a.workspace.id, a.property.id, a.data_source.id, a.import_job.id
    wb, pb, db_, jb = b.workspace.id, b.property.id, b.data_source.id, b.import_job.id

    attempts: list[tuple[str, Callable[[], UUID], str]] = [
        ("source A -> property B", lambda: raw_source(db_session, wa, pb), FK_DATA_SOURCE),
        ("source B -> property A", lambda: raw_source(db_session, wb, pa), FK_DATA_SOURCE),
        ("job A -> source B", lambda: raw_job(db_session, wa, pb, db_), FK_IMPORT_JOB),
        ("job B -> source A", lambda: raw_job(db_session, wb, pa, da), FK_IMPORT_JOB),
        ("job A -> property B", lambda: raw_job(db_session, wa, pb, da), FK_IMPORT_JOB),
        ("job B -> property A", lambda: raw_job(db_session, wb, pa, db_), FK_IMPORT_JOB),
        ("file A -> job B", lambda: raw_file(db_session, wa, jb), FK_IMPORT_FILE),
        ("file B -> job A", lambda: raw_file(db_session, wb, ja), FK_IMPORT_FILE),
    ]
    for label, attempt, constraint in attempts:
        with rejects(pg.ForeignKeyViolation, constraint):
            attempt()
        assert db_session.is_active, f"session unusable after {label}"

    for model in (DataSource, ImportJob, ImportFile):
        counts = db_session.execute(
            select(model.workspace_id, func.count()).group_by(model.workspace_id)
        )
        per_workspace: dict[UUID, int] = {row[0]: row[1] for row in counts}
        expected = 0 if model is ImportFile else 1
        assert per_workspace.get(wa, 0) == expected
        assert per_workspace.get(wb, 0) == expected


# --- why the foreign keys are composite -------------------------------------------------------


def test_a_plain_single_column_foreign_key_would_have_missed_the_mistake(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    """Control experiment: the tests above are only meaningful if a naive design fails them.

    Inside this test's rolled-back transaction, swap the composite key for the obvious
    `FOREIGN KEY (property_id) REFERENCES properties(id)`. The very same cross-tenant row is then
    accepted, i.e. an inconsistent tenant relationship exists and nothing complains.
    """
    a, b = two_tenants
    db_session.execute(
        text("ALTER TABLE data_sources DROP CONSTRAINT fk_data_sources_workspace_id_properties")
    )
    db_session.execute(
        text(
            "ALTER TABLE data_sources ADD CONSTRAINT naive_fk"
            " FOREIGN KEY (property_id) REFERENCES properties (id)"
        )
    )

    leaked = raw_source(db_session, a.workspace.id, b.property.id)  # accepted!

    mismatched = db_session.execute(
        text(
            "SELECT count(*) FROM data_sources d JOIN properties p ON p.id = d.property_id"
            " WHERE d.id = :id AND d.workspace_id <> p.workspace_id"
        ),
        {"id": leaked},
    ).scalar_one()
    assert mismatched == 1
