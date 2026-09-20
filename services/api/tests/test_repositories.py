"""Repositories: tenant scoping is explicit and effective (two real tenants, real PostgreSQL)."""

import dataclasses
import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg.errors as pg
import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.tenant import TenantContext
from app.modules.bookings.repository import (
    BookingChannelRepository,
    BookingImportRowRepository,
    BookingMappingProfileRepository,
    BookingRepository,
)
from app.modules.identity.repository import UserRepository
from app.modules.identity.schemas import UserCreate
from app.modules.ingestion.models import DataSourceDomain, ImportJob, ImportJobStatus
from app.modules.ingestion.repository import (
    DataSourceRepository,
    ImportFileRepository,
    ImportJobRepository,
)
from app.modules.ingestion.schemas import DataSourceCreate, ImportFileCreate, ImportJobCreate
from app.modules.properties.repository import PropertyRepository
from app.modules.properties.schemas import PropertyCreate
from app.modules.tenancy.models import MembershipRole
from app.modules.tenancy.repository import MembershipRepository, WorkspaceRepository
from app.modules.tenancy.schemas import MembershipCreate, WorkspaceCreate
from tests.support import Factory, Rejects, Tenant

TENANT_REPOSITORIES = [
    MembershipRepository,
    PropertyRepository,
    DataSourceRepository,
    ImportJobRepository,
    ImportFileRepository,
    BookingRepository,
    BookingChannelRepository,
    BookingMappingProfileRepository,
    BookingImportRowRepository,
]


# --- TenantContext ---------------------------------------------------------------------------


def test_tenant_context_needs_an_explicit_uuid_workspace() -> None:
    workspace_id = uuid4()

    assert TenantContext(workspace_id).workspace_id == workspace_id
    with pytest.raises(TypeError):
        TenantContext()  # type: ignore[call-arg]  # no default: the scope is always explicit
    for not_a_uuid in (None, "not-a-uuid", str(workspace_id), 42):
        with pytest.raises(TypeError):
            TenantContext(not_a_uuid)  # type: ignore[arg-type]


def test_tenant_context_is_immutable() -> None:
    context = TenantContext(uuid4())

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.workspace_id = uuid4()  # type: ignore[misc]


@pytest.mark.parametrize("repository", TENANT_REPOSITORIES, ids=lambda r: r.__name__)
def test_tenant_repositories_require_a_tenant_and_take_no_workspace_argument(
    repository: type,
) -> None:
    """The scope is fixed once, at construction; no method can be pointed at another workspace."""
    constructor = inspect.signature(repository).parameters
    assert constructor["tenant"].default is inspect.Parameter.empty

    for name, method in inspect.getmembers(repository, inspect.isfunction):
        assert "workspace_id" not in inspect.signature(method).parameters, f"{name}"


@pytest.mark.parametrize("repository", TENANT_REPOSITORIES, ids=lambda r: r.__name__)
def test_every_query_in_a_tenant_repository_names_the_workspace(repository: type) -> None:
    """Guard against a future method that forgets the workspace filter."""
    for name, method in inspect.getmembers(repository, inspect.isfunction):
        source = inspect.getsource(method)
        if "select(" in source or "update(" in source:
            assert "self._tenant.workspace_id" in source, f"{repository.__name__}.{name}"


# --- PropertyRepository ----------------------------------------------------------------------


def test_property_repository_only_sees_its_own_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo_a, repo_b = (PropertyRepository(db_session, t.context) for t in (a, b))
    extra = repo_a.add(PropertyCreate(name="Second", slug="second"))

    assert {p.id for p in repo_a.list_all()} == {a.property.id, extra.id}
    assert {p.id for p in repo_b.list_all()} == {b.property.id}
    assert repo_a.get(b.property.id) is None
    assert repo_b.get(a.property.id) is None
    assert repo_a.get(a.property.id) is not None


def test_property_repository_resolves_a_shared_slug_per_tenant(
    db_session: Session, factory: Factory
) -> None:
    first, second = factory.workspace(), factory.workspace()
    in_first = factory.property(first, "villa-rosa")
    in_second = factory.property(second, "villa-rosa")

    assert (
        PropertyRepository(db_session, TenantContext(first.id)).get_by_slug("villa-rosa")
        == in_first
    )
    assert (
        PropertyRepository(db_session, TenantContext(second.id)).get_by_slug("villa-rosa")
        == in_second
    )


def test_property_repository_cannot_see_a_slug_that_exists_only_elsewhere(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    assert PropertyRepository(db_session, a.context).get_by_slug(b.property.slug) is None


def test_property_repository_stamps_the_workspace_from_the_context(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    created = PropertyRepository(db_session, a.context).add(PropertyCreate(name="New", slug="new"))

    assert created.workspace_id == a.workspace.id
    assert (created.timezone, created.currency) == ("Europe/Rome", "EUR")


def test_property_repository_rejects_a_duplicate_slug_in_the_same_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, _ = two_tenants
    repo = PropertyRepository(db_session, a.context)

    with rejects(pg.UniqueViolation, "uq_properties_workspace_id_slug"):
        repo.add(PropertyCreate(name="Dup", slug=a.property.slug))


def test_property_repository_cannot_archive_another_workspaces_property(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with pytest.raises(NotFoundError):
        PropertyRepository(db_session, a.context).archive(b.property.id)

    assert b.property.is_active is True
    assert b.property.archived_at is None


def test_archiving_a_property_keeps_the_row_and_is_idempotent(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = PropertyRepository(db_session, a.context)

    archived = repo.archive(a.property.id)
    first_archived_at = archived.archived_at
    repo.archive(a.property.id)

    assert archived.is_active is False
    assert first_archived_at is not None and first_archived_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - first_archived_at) < timedelta(minutes=1)
    assert archived.archived_at == first_archived_at
    assert repo.list_all() == []
    assert [p.id for p in repo.list_all(include_archived=True)] == [a.property.id]


# --- DataSourceRepository --------------------------------------------------------------------


def test_data_source_repository_only_sees_its_own_workspace(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo_a, repo_b = (DataSourceRepository(db_session, t.context) for t in (a, b))

    assert [s.id for s in repo_a.list_all()] == [a.data_source.id]
    assert [s.id for s in repo_b.list_all()] == [b.data_source.id]
    assert repo_a.get(b.data_source.id) is None
    assert repo_b.get(a.data_source.id) is None
    # Filtering by another tenant's property id still cannot leak anything.
    assert repo_a.list_all(property_id=b.property.id) == []


def test_data_source_repository_cannot_attach_to_another_workspaces_property(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo = DataSourceRepository(db_session, a.context)

    with pytest.raises(NotFoundError):
        repo.add(
            DataSourceCreate(
                property_id=b.property.id, name="Stolen", domain=DataSourceDomain.COSTS
            )
        )

    assert [s.id for s in repo.list_all()] == [a.data_source.id]


def test_data_source_repository_creates_sources_for_its_own_property(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants

    created = DataSourceRepository(db_session, a.context).add(
        DataSourceCreate(
            property_id=a.property.id, name="Bookings file", domain=DataSourceDomain.BOOKINGS
        )
    )

    assert (created.workspace_id, created.property_id) == (a.workspace.id, a.property.id)
    assert created.source_type == "FILE_UPLOAD"
    assert created.is_active is True


def test_data_source_repository_cannot_deactivate_another_workspaces_source(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants

    with pytest.raises(NotFoundError):
        DataSourceRepository(db_session, a.context).deactivate(b.data_source.id)

    assert b.data_source.is_active is True


def test_deactivating_a_data_source_keeps_the_row(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = DataSourceRepository(db_session, a.context)

    repo.deactivate(a.data_source.id)

    assert repo.list_all() == []
    assert [s.id for s in repo.list_all(include_inactive=True)] == [a.data_source.id]
    assert repo.get(a.data_source.id) is not None


# --- ImportJobRepository / ImportFileRepository ----------------------------------------------


def test_import_job_repository_derives_the_property_from_the_data_source(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    second_property = factory.property(a.workspace)
    second_source = factory.data_source(second_property)

    job = ImportJobRepository(db_session, a.context).add(
        ImportJobCreate(data_source_id=second_source.id)
    )

    assert (job.workspace_id, job.property_id) == (a.workspace.id, second_property.id)
    assert job.status == ImportJobStatus.PENDING


def test_import_job_repository_cannot_use_another_workspaces_data_source(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo = ImportJobRepository(db_session, a.context)

    with pytest.raises(NotFoundError):
        repo.add(ImportJobCreate(data_source_id=b.data_source.id))

    assert [j.id for j in repo.list_all()] == [a.import_job.id]


def test_import_job_repository_only_sees_its_own_workspace_and_filters_by_status(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo_a = ImportJobRepository(db_session, a.context)
    running = repo_a.add(ImportJobCreate(data_source_id=a.data_source.id))
    running.status = ImportJobStatus.RUNNING
    running.started_at = datetime.now(UTC)
    db_session.flush()

    assert repo_a.get(b.import_job.id) is None
    assert {j.id for j in repo_a.list_all()} == {a.import_job.id, running.id}
    assert [j.id for j in repo_a.list_all(status=ImportJobStatus.RUNNING)] == [running.id]
    assert [j.id for j in repo_a.list_all(status=ImportJobStatus.PENDING)] == [a.import_job.id]
    assert [j.id for j in ImportJobRepository(db_session, b.context).list_all()] == [
        b.import_job.id
    ]


def test_import_file_repository_cannot_attach_to_another_workspaces_job(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo = ImportFileRepository(db_session, a.context)

    with pytest.raises(NotFoundError):
        repo.add(b.import_job.id, ImportFileCreate(original_filename="stolen.csv"))

    assert repo.list_for_job(b.import_job.id) == []


def test_import_file_repository_stores_metadata_for_its_own_job(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = ImportFileRepository(db_session, a.context)

    created = repo.add(
        a.import_job.id,
        ImportFileCreate(original_filename="bookings.csv", mime_type="text/csv", size_bytes=10),
    )

    assert (created.workspace_id, created.import_job_id) == (a.workspace.id, a.import_job.id)
    assert created.storage_key is None  # no storage exists yet
    assert [f.id for f in repo.list_for_job(a.import_job.id)] == [created.id]


def test_duplicate_detection_by_hash_never_crosses_workspaces(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    digest = "0f" * 32
    repo_a, repo_b = (ImportFileRepository(db_session, t.context) for t in (a, b))
    in_a = repo_a.add(a.import_job.id, ImportFileCreate(original_filename="x.csv", sha256=digest))
    in_b = repo_b.add(b.import_job.id, ImportFileCreate(original_filename="x.csv", sha256=digest))

    assert [f.id for f in repo_a.find_by_sha256(digest)] == [in_a.id]
    assert [f.id for f in repo_b.find_by_sha256(digest)] == [in_b.id]


# --- MembershipRepository / WorkspaceRepository / UserRepository -----------------------------


def test_membership_repository_is_scoped_to_its_workspace(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    user = factory.user()
    repo_a, repo_b = (MembershipRepository(db_session, t.context) for t in (a, b))

    repo_a.add(MembershipCreate(user_id=user.id, role=MembershipRole.OWNER))

    assert [m.user_id for m in repo_a.list_all()] == [user.id]
    assert repo_b.list_all() == []
    assert repo_b.get_for_user(user.id) is None
    with pytest.raises(NotFoundError):
        repo_b.remove(user.id)  # another workspace's membership cannot be revoked from here


def test_membership_repository_rejects_duplicates_and_really_deletes(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    a, _ = two_tenants
    user = factory.user()
    repo = MembershipRepository(db_session, a.context)
    repo.add(MembershipCreate(user_id=user.id, role=MembershipRole.MEMBER))

    with rejects(pg.UniqueViolation, "uq_workspace_memberships_workspace_id_user_id"):
        repo.add(MembershipCreate(user_id=user.id, role=MembershipRole.ADMIN))

    repo.remove(user.id)
    assert repo.get_for_user(user.id) is None


def test_workspace_repository_lists_a_users_workspaces_and_hides_archived(
    db_session: Session, factory: Factory
) -> None:
    user, stranger = factory.user(), factory.user()
    alpha, beta, gamma = (factory.workspace(slug) for slug in ("alpha", "beta", "gamma"))
    for workspace in (alpha, beta):
        factory.membership(workspace, user)
    factory.membership(gamma, stranger)
    repo = WorkspaceRepository(db_session)

    assert [w.slug for w in repo.list_for_user(user.id)] == ["alpha", "beta"]
    repo.archive(beta.id)
    assert [w.slug for w in repo.list_for_user(user.id)] == ["alpha"]
    assert [w.slug for w in repo.list_for_user(user.id, include_archived=True)] == ["alpha", "beta"]


def test_workspace_repository_archives_without_deleting(db_session: Session) -> None:
    repo = WorkspaceRepository(db_session)
    workspace = repo.add(WorkspaceCreate(name="Acme", slug="acme"))

    archived = repo.archive(workspace.id)
    first_archived_at = archived.archived_at
    repo.archive(workspace.id)

    assert archived.is_active is False
    assert first_archived_at is not None and first_archived_at.utcoffset() == timedelta(0)
    assert archived.archived_at == first_archived_at
    assert repo.get_by_slug("acme") is archived
    with pytest.raises(NotFoundError):
        repo.archive(uuid4())


def test_user_repository_normalises_and_finds_by_email_case_insensitively(
    db_session: Session, rejects: Rejects
) -> None:
    repo = UserRepository(db_session)
    user = repo.add(UserCreate(email="  Anna.Bianchi@Example.COM "))

    assert user.email == "anna.bianchi@example.com"
    assert repo.get_by_email("ANNA.BIANCHI@example.com") is user
    with rejects(pg.UniqueViolation, "uq_users_email"):
        repo.add(UserCreate(email="anna.bianchi@EXAMPLE.com"))


def test_user_repository_deactivates_without_deleting(db_session: Session) -> None:
    repo = UserRepository(db_session)
    user = repo.add(UserCreate(email="leaver@example.com"))

    repo.deactivate(user.id)

    assert repo.get(user.id) is not None
    assert user.is_active is False
    with pytest.raises(NotFoundError):
        repo.deactivate(uuid4())


# --- not-found is not an oracle --------------------------------------------------------------


def test_foreign_and_missing_entities_are_indistinguishable(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo = PropertyRepository(db_session, a.context)

    with pytest.raises(NotFoundError) as foreign:
        repo.archive(b.property.id)
    with pytest.raises(NotFoundError) as missing:
        repo.archive(uuid4())

    assert (foreign.value.code, foreign.value.message, foreign.value.status_code) == (
        missing.value.code,
        missing.value.message,
        missing.value.status_code,
    )


# --- ImportJobRepository lifecycle (used by the Gate 2 import) --------------------------------


def status_of(job: ImportJob) -> ImportJobStatus:
    return job.status


def test_an_import_job_moves_pending_running_succeeded(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = ImportJobRepository(db_session, a.context)
    job = repo.add(ImportJobCreate(data_source_id=a.data_source.id))
    assert (job.status, job.started_at, job.finished_at) == (ImportJobStatus.PENDING, None, None)

    repo.start(job.id)
    assert job.status == ImportJobStatus.RUNNING and job.started_at is not None
    repo.succeed(job.id)

    assert status_of(job) == ImportJobStatus.SUCCEEDED
    assert job.finished_at is not None and job.started_at <= job.finished_at
    assert (job.error_code, job.error_message) == (None, None)


@pytest.mark.parametrize("from_running", [False, True])
def test_an_import_job_can_fail_before_or_after_starting(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], from_running: bool
) -> None:
    a, _ = two_tenants
    repo = ImportJobRepository(db_session, a.context)
    job = repo.add(ImportJobCreate(data_source_id=a.data_source.id))
    if from_running:
        repo.start(job.id)

    repo.fail(job.id, error_code="SOME_CODE", error_message="x" * 5000)

    assert (job.status, job.error_code) == (ImportJobStatus.FAILED, "SOME_CODE")
    assert job.finished_at is not None
    assert job.error_message is not None and len(job.error_message) == 1000  # bounded


def test_invalid_import_job_transitions_are_refused(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    repo = ImportJobRepository(db_session, a.context)
    job = repo.add(ImportJobCreate(data_source_id=a.data_source.id))

    with pytest.raises(AppError) as info:
        repo.succeed(job.id)  # a PENDING job cannot succeed
    assert (info.value.code, info.value.status_code) == ("invalid_import_job_transition", 409)

    repo.start(job.id)
    with pytest.raises(AppError):
        repo.start(job.id)  # already running
    repo.succeed(job.id)

    with pytest.raises(AppError):
        repo.start(job.id)  # a finished job is final
    with pytest.raises(AppError):
        repo.succeed(job.id)
    with pytest.raises(AppError):
        repo.fail(job.id, error_code="X", error_message="y")
    assert status_of(job) == ImportJobStatus.SUCCEEDED


def test_import_job_transitions_stay_inside_the_tenant(
    db_session: Session, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    repo = ImportJobRepository(db_session, a.context)

    with pytest.raises(NotFoundError):
        repo.start(b.import_job.id)
    with pytest.raises(NotFoundError):
        repo.fail(b.import_job.id, error_code="X", error_message="y")
    assert status_of(b.import_job) == ImportJobStatus.PENDING


def test_a_file_hash_is_only_a_duplicate_within_the_same_data_source_and_after_success(
    db_session: Session, factory: Factory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = two_tenants
    digest = "9a" * 32
    other_source = factory.data_source(a.property)
    repo = ImportFileRepository(db_session, a.context)
    pending = factory.import_file(a.import_job, digest)  # its job is still PENDING

    assert repo.find_successful_for_data_source(a.data_source.id, digest) is None

    a.import_job.status = ImportJobStatus.RUNNING
    a.import_job.started_at = datetime.now(UTC)
    db_session.flush()
    a.import_job.status = ImportJobStatus.SUCCEEDED
    a.import_job.finished_at = datetime.now(UTC)
    db_session.flush()

    assert repo.find_successful_for_data_source(a.data_source.id, digest) == pending
    assert repo.find_successful_for_data_source(other_source.id, digest) is None  # another source
    assert repo.find_successful_for_data_source(b.data_source.id, digest) is None  # another tenant
    assert (
        ImportFileRepository(db_session, b.context).find_successful_for_data_source(
            a.data_source.id, digest
        )
        is None
    )
