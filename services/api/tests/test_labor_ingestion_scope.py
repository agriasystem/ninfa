"""Tenant integrity (raw SQL, DB-level) and product scope of the labor module (Gate 8)."""

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.modules.labor.models import LaborImportRow, LaborMappingProfile
from tests.labor_support import LaborFactory, LaborTenant, labor_snapshot, labor_tenant
from tests.support import Rejects


@pytest.fixture
def tenant(factory: LaborFactory) -> LaborTenant:
    return labor_tenant(factory)


@pytest.fixture
def other_tenant(factory: LaborFactory) -> LaborTenant:
    return labor_tenant(factory)


def _snapshot(factory: LaborFactory, tenant: LaborTenant):  # type: ignore[no-untyped-def]
    return labor_snapshot(
        factory,
        tenant.labor_data_source,
        tenant.labor_import_job,
        factory.import_file(tenant.labor_import_job),
    )


_INSERT_SNAPSHOT = text(
    "INSERT INTO labor_snapshots"
    " (workspace_id, property_id, data_source_id, snapshot_local_date,"
    " source_import_job_id, source_import_file_id, source_fingerprint)"
    " VALUES"
    " (:workspace_id, :property_id, :data_source_id, '2026-03-01', :job_id, :file_id, :fp)"
)


# --- cross-tenant, raw SQL (bypassing the ORM's own workspace scoping entirely) -----------------


def test_snapshot_cannot_reference_another_workspaces_property(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            _INSERT_SNAPSHOT,
            {
                "workspace_id": tenant.workspace.id,
                "property_id": other_tenant.property.id,  # foreign property
                "data_source_id": tenant.labor_data_source.id,
                "job_id": tenant.labor_import_job.id,
                "file_id": factory.import_file(tenant.labor_import_job).id,
                "fp": "a" * 64,
            },
        )


def test_snapshot_cannot_reference_another_workspaces_data_source(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            _INSERT_SNAPSHOT,
            {
                "workspace_id": tenant.workspace.id,
                "property_id": tenant.property.id,
                "data_source_id": other_tenant.labor_data_source.id,  # foreign source
                "job_id": tenant.labor_import_job.id,
                "file_id": factory.import_file(tenant.labor_import_job).id,
                "fp": "a" * 64,
            },
        )


def test_snapshot_cannot_reference_another_workspaces_import_job(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            _INSERT_SNAPSHOT,
            {
                "workspace_id": tenant.workspace.id,
                "property_id": tenant.property.id,
                "data_source_id": tenant.labor_data_source.id,
                "job_id": other_tenant.labor_import_job.id,  # foreign job
                "file_id": factory.import_file(tenant.labor_import_job).id,
                "fp": "a" * 64,
            },
        )


def test_snapshot_cannot_reference_another_workspaces_import_file(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            _INSERT_SNAPSHOT,
            {
                "workspace_id": tenant.workspace.id,
                "property_id": tenant.property.id,
                "data_source_id": tenant.labor_data_source.id,
                "job_id": tenant.labor_import_job.id,
                "file_id": factory.import_file(other_tenant.labor_import_job).id,  # foreign file
                "fp": "a" * 64,
            },
        )


def test_entry_cannot_reference_another_workspaces_snapshot(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    foreign_snapshot = _snapshot(factory, other_tenant)
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            text(
                "INSERT INTO labor_entries (workspace_id, labor_snapshot_id, source_row_number,"
                " work_date, labor_category, planned_minutes, classification_method,"
                " classification_confidence)"
                " VALUES (:workspace_id, :snapshot_id, 1, '2026-03-10', 'OTHER', 480,"
                " 'UNCLASSIFIED', 0.00)"
            ),
            {"workspace_id": tenant.workspace.id, "snapshot_id": foreign_snapshot.id},
        )


def test_mapping_profile_cannot_reference_another_workspaces_data_source(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            insert(LaborMappingProfile),
            {
                "workspace_id": tenant.workspace.id,
                "property_id": tenant.property.id,
                "data_source_id": other_tenant.labor_data_source.id,
                "column_mapping": {},
                "role_mapping": {},
                "format_options": {},
                "header_signature": "b" * 64,
            },
        )


def test_import_row_cannot_reference_another_workspaces_import_file(
    db_session: Session,
    factory: LaborFactory,
    tenant: LaborTenant,
    other_tenant: LaborTenant,
    rejects: Rejects,
) -> None:
    foreign_file = factory.import_file(other_tenant.labor_import_job)
    with rejects(psycopg.errors.ForeignKeyViolation):
        db_session.execute(
            insert(LaborImportRow),
            {
                "workspace_id": tenant.workspace.id,
                "import_job_id": tenant.labor_import_job.id,
                "import_file_id": foreign_file.id,
                "source_row_number": 1,
                "mapped_payload": {},
                "validation_status": "INVALID",
                "validation_errors": [{"field": "x", "code": "y"}],
                "validation_warnings": [],
            },
        )


# --- product scope: no business API, no employee model, no priority/decision ---------------------


def test_openapi_still_exposes_only_the_health_endpoint(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert list(paths) == ["/api/v1/health"]


def test_no_labor_business_endpoints_exist(client: TestClient) -> None:
    for path in ("/labor", "/staffing", "/overstaffing", "/shifts"):
        response = client.get(path)
        assert response.status_code == 404


def test_no_employee_or_payroll_model_exists() -> None:
    import app.models

    names = " ".join(app.models.__all__).lower()
    for forbidden in ("employee", "payroll", "shift", "roster"):
        assert forbidden not in names


def test_no_priority_table_exists() -> None:
    # "decision" is deliberately not checked here any more: Gate 11 legitimately adds
    # `decisions`/`decision_runs`/`decision_observations` elsewhere - the invariant this test
    # still protects is that LABOR INGESTION ITSELF never grows a priority table of its own.
    import app.models  # noqa: F401
    from app.db.base import Base

    table_names = " ".join(Base.metadata.tables).lower()
    assert "priority" not in table_names
