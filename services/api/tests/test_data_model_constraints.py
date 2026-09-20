"""Per-entity invariants enforced by PostgreSQL (uniqueness, CHECKs, delete policy).

Rows are written with raw SQL or the bare ORM so the database, not the Pydantic layer, is
what is being tested.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg.errors as pg
import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from app.modules.identity.models import User
from app.modules.ingestion.models import DataSource, ImportFile
from app.modules.properties.models import Property
from app.modules.tenancy.models import MembershipRole, Workspace, WorkspaceMembership
from tests.support import Factory, Rejects, Tenant

# --- helpers ---------------------------------------------------------------------------------


def run(session: Session, sql: str, **params: Any) -> Any:
    return session.execute(text(sql), params)


def insert_user(session: Session, email: str, display_name: str | None = None) -> Any:
    return run(
        session,
        "INSERT INTO users (email, display_name) VALUES (:email, :name) RETURNING id",
        email=email,
        name=display_name,
    ).scalar_one()


def insert_workspace(session: Session, slug: str, name: str = "Workspace", **columns: Any) -> Any:
    return run(
        session,
        "INSERT INTO workspaces (name, slug, is_active, archived_at)"
        " VALUES (:name, :slug, :is_active, :archived_at) RETURNING id",
        name=name,
        slug=slug,
        is_active=columns.get("is_active", True),
        archived_at=columns.get("archived_at"),
    ).scalar_one()


def insert_property(session: Session, workspace_id: uuid.UUID, slug: str, **columns: Any) -> Any:
    return run(
        session,
        "INSERT INTO properties (workspace_id, name, slug, currency, is_active, archived_at)"
        " VALUES (:workspace_id, :name, :slug, :currency, :is_active, :archived_at) RETURNING id",
        workspace_id=workspace_id,
        name=columns.get("name", "Hotel"),
        slug=slug,
        currency=columns.get("currency", "EUR"),
        is_active=columns.get("is_active", True),
        archived_at=columns.get("archived_at"),
    ).scalar_one()


# --- users -----------------------------------------------------------------------------------


def test_user_email_must_be_stored_normalized(db_session: Session, rejects: Rejects) -> None:
    with rejects(pg.CheckViolation, "ck_users_email_normalized"):
        insert_user(db_session, "Mario.Rossi@Example.com")


@pytest.mark.parametrize("email", ["no-at-sign", "missing@tld", "a b@example.com", "@example.com"])
def test_user_email_must_look_like_an_email(
    db_session: Session, rejects: Rejects, email: str
) -> None:
    with rejects(pg.CheckViolation, "ck_users_email_format"):
        insert_user(db_session, email)


def test_user_email_is_unique(db_session: Session, factory: Factory, rejects: Rejects) -> None:
    factory.user("dup@example.com")

    with rejects(pg.UniqueViolation, "uq_users_email"):
        insert_user(db_session, "dup@example.com")


def test_user_email_uniqueness_is_case_insensitive_because_storage_is_normalized(
    db_session: Session, factory: Factory, rejects: Rejects
) -> None:
    """No citext, no functional index: only lower-case rows can exist, so UNIQUE is enough."""
    factory.user("dup@example.com")

    with rejects(pg.CheckViolation, "ck_users_email_normalized"):
        insert_user(db_session, "DUP@example.com")


def test_user_display_name_cannot_be_blank(db_session: Session, rejects: Rejects) -> None:
    with rejects(pg.CheckViolation, "ck_users_display_name_not_blank"):
        insert_user(db_session, "blank@example.com", display_name="   ")


def test_user_table_holds_identity_only_no_credentials(db_engine: Engine) -> None:
    columns = {column["name"] for column in inspect(db_engine).get_columns("users")}

    assert columns == {"id", "email", "display_name", "is_active", "created_at", "updated_at"}


# --- identifiers and timestamps --------------------------------------------------------------


def test_ids_are_uuid_v4_from_the_application_and_from_the_database(
    db_session: Session, factory: Factory
) -> None:
    application_id = factory.user().id
    database_id = insert_user(db_session, "server-side@example.com")

    assert application_id.version == 4
    assert database_id.version == 4  # gen_random_uuid()


def test_timestamps_are_timezone_aware_utc(db_session: Session, factory: Factory) -> None:
    user = factory.user()
    db_session.refresh(user)

    for value in (user.created_at, user.updated_at):
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - user.created_at) < timedelta(minutes=1)


def test_updated_at_moves_forward_on_update(db_engine: Engine) -> None:
    """Needs two real transactions (now() is constant inside one), so it cleans up after itself."""
    email = f"updated-at-{uuid.uuid4().hex[:8]}@example.com"
    with Session(db_engine) as first:
        user = User(email=email)
        first.add(user)
        first.commit()
        user_id, initial = user.id, user.updated_at
    try:
        time.sleep(0.05)
        with Session(db_engine) as second:
            loaded = second.get(User, user_id)
            assert loaded is not None
            loaded.display_name = "Changed"
            second.commit()
            second.refresh(loaded)
            assert loaded.updated_at > initial
    finally:
        with Session(db_engine) as cleanup:
            cleanup.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            cleanup.commit()


# --- workspaces ------------------------------------------------------------------------------


def test_workspace_slug_is_globally_unique(
    db_session: Session, factory: Factory, rejects: Rejects
) -> None:
    factory.workspace("acme")

    with rejects(pg.UniqueViolation, "uq_workspaces_slug"):
        insert_workspace(db_session, "acme")


@pytest.mark.parametrize(
    "slug", ["a", "-abc", "abc-", "a--b", "Has-Upper", "with_underscore", "a b"]
)
def test_workspace_slug_format_is_enforced(
    db_session: Session, rejects: Rejects, slug: str
) -> None:
    with rejects(pg.CheckViolation, "ck_workspaces_slug_format"):
        insert_workspace(db_session, slug)


def test_workspace_name_cannot_be_blank(db_session: Session, rejects: Rejects) -> None:
    with rejects(pg.CheckViolation, "ck_workspaces_name_not_blank"):
        insert_workspace(db_session, "blank-name", name="  ")


def test_archived_workspace_must_be_inactive(db_session: Session, rejects: Rejects) -> None:
    with rejects(pg.CheckViolation, "ck_workspaces_archived_implies_inactive"):
        insert_workspace(db_session, "half-archived", is_active=True, archived_at=datetime.now(UTC))


def test_workspace_can_be_inactive_without_being_archived(db_session: Session) -> None:
    assert insert_workspace(db_session, "suspended", is_active=False)


# --- memberships -----------------------------------------------------------------------------


def test_user_cannot_have_two_memberships_in_the_same_workspace(
    factory: Factory, rejects: Rejects
) -> None:
    workspace, user = factory.workspace(), factory.user()
    factory.membership(workspace, user, MembershipRole.MEMBER)

    with rejects(pg.UniqueViolation, "uq_workspace_memberships_workspace_id_user_id"):
        factory.membership(workspace, user, MembershipRole.ADMIN)


def test_user_can_belong_to_many_workspaces_and_workspace_has_many_users(
    factory: Factory,
) -> None:
    user_1, user_2 = factory.user(), factory.user()
    workspace_1, workspace_2 = factory.workspace(), factory.workspace()

    factory.membership(workspace_1, user_1, MembershipRole.OWNER)
    factory.membership(workspace_2, user_1, MembershipRole.MEMBER)
    factory.membership(workspace_1, user_2, MembershipRole.ADMIN)

    assert {m.workspace_id for m in user_1.memberships} == {workspace_1.id, workspace_2.id}
    assert {m.user_id for m in workspace_1.memberships} == {user_1.id, user_2.id}


def test_membership_role_must_be_a_known_role(
    db_session: Session, factory: Factory, rejects: Rejects
) -> None:
    workspace, user = factory.workspace(), factory.user()

    with rejects(pg.CheckViolation, "ck_workspace_memberships_role_valid"):
        run(
            db_session,
            "INSERT INTO workspace_memberships (workspace_id, user_id, role)"
            " VALUES (:w, :u, 'SUPERUSER')",
            w=workspace.id,
            u=user.id,
        )


def test_membership_requires_existing_user_and_workspace(
    factory: Factory, db_session: Session, rejects: Rejects
) -> None:
    workspace, user = factory.workspace(), factory.user()

    with rejects(pg.ForeignKeyViolation, "fk_workspace_memberships_user_id_users"):
        db_session.add(
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=uuid.uuid4(), role=MembershipRole.MEMBER
            )
        )
    with rejects(pg.ForeignKeyViolation, "fk_workspace_memberships_workspace_id_workspaces"):
        db_session.add(
            WorkspaceMembership(
                workspace_id=uuid.uuid4(), user_id=user.id, role=MembershipRole.MEMBER
            )
        )


# --- properties ------------------------------------------------------------------------------


def test_property_slug_is_unique_inside_a_workspace(factory: Factory, rejects: Rejects) -> None:
    workspace = factory.workspace()
    factory.property(workspace, "villa-rosa")

    with rejects(pg.UniqueViolation, "uq_properties_workspace_id_slug"):
        factory.property(workspace, "villa-rosa")


def test_same_property_slug_is_allowed_in_different_workspaces(factory: Factory) -> None:
    first = factory.property(factory.workspace(), "villa-rosa")
    second = factory.property(factory.workspace(), "villa-rosa")

    assert first.slug == second.slug
    assert first.workspace_id != second.workspace_id


def test_property_defaults_to_rome_timezone_and_euro(db_session: Session, factory: Factory) -> None:
    orm_property = factory.property(factory.workspace())
    raw_id = run(
        db_session,
        "INSERT INTO properties (workspace_id, name, slug) VALUES (:w, 'Raw', 'raw') RETURNING id",
        w=orm_property.workspace_id,
    ).scalar_one()
    raw_property = db_session.get(Property, raw_id)

    assert raw_property is not None
    for prop in (orm_property, raw_property):
        assert (prop.timezone, prop.currency) == ("Europe/Rome", "EUR")


@pytest.mark.parametrize("currency", ["eur", "E1R", "EU_", "€UR"])
def test_property_currency_must_be_three_uppercase_letters(
    db_session: Session, factory: Factory, rejects: Rejects, currency: str
) -> None:
    workspace = factory.workspace()

    with rejects(pg.CheckViolation, "ck_properties_currency_format"):
        insert_property(db_session, workspace.id, "bad-currency", currency=currency)


def test_archived_property_must_be_inactive(
    db_session: Session, factory: Factory, rejects: Rejects
) -> None:
    workspace = factory.workspace()

    with rejects(pg.CheckViolation, "ck_properties_archived_implies_inactive"):
        insert_property(
            db_session, workspace.id, "half-archived", is_active=True, archived_at=datetime.now(UTC)
        )


def test_property_requires_an_existing_workspace(db_session: Session, rejects: Rejects) -> None:
    with rejects(pg.ForeignKeyViolation, "fk_properties_workspace_id_workspaces"):
        insert_property(db_session, uuid.uuid4(), "orphan")


# --- data sources ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("domain", "PAYROLL", "ck_data_sources_domain_valid"),
        ("source_type", "PMS_API", "ck_data_sources_source_type_valid"),
    ],
)
def test_data_source_domain_and_type_are_closed_sets(
    db_session: Session,
    two_tenants: tuple[Tenant, Tenant],
    rejects: Rejects,
    column: str,
    value: str,
    constraint: str,
) -> None:
    a, _ = two_tenants
    values = {"domain": "BOOKINGS", "source_type": "FILE_UPLOAD", column: value}

    with rejects(pg.CheckViolation, constraint):
        run(
            db_session,
            "INSERT INTO data_sources (workspace_id, property_id, name, domain, source_type)"
            " VALUES (:w, :p, 'x', :domain, :source_type)",
            w=a.workspace.id,
            p=a.property.id,
            **values,
        )


def test_data_source_accepts_every_v1_domain(factory: Factory) -> None:
    from app.modules.ingestion.models import DataSourceDomain

    prop = factory.property(factory.workspace())

    domains = {factory.data_source(prop, domain).domain for domain in DataSourceDomain}

    assert domains == {"BOOKINGS", "COSTS", "LABOR"}


# --- import jobs: lifecycle ------------------------------------------------------------------

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


def insert_job(session: Session, tenant: Tenant, **columns: Any) -> Any:
    params = {
        "status": "PENDING",
        "started_at": None,
        "finished_at": None,
        "error_code": None,
        "error_message": None,
        **columns,
    }
    return run(
        session,
        "INSERT INTO import_jobs (workspace_id, property_id, data_source_id, status,"
        " started_at, finished_at, error_code, error_message)"
        " VALUES (:w, :p, :d, :status, :started_at, :finished_at, :error_code, :error_message)"
        " RETURNING id",
        w=tenant.workspace.id,
        p=tenant.property.id,
        d=tenant.data_source.id,
        **params,
    ).scalar_one()


@pytest.mark.parametrize(
    "columns",
    [
        {"status": "PENDING"},
        {"status": "RUNNING", "started_at": NOW},
        {"status": "SUCCEEDED", "started_at": NOW, "finished_at": LATER},
        {"status": "FAILED", "finished_at": NOW, "error_code": "E1", "error_message": "boom"},
    ],
    ids=["pending", "running", "succeeded", "failed-before-start"],
)
def test_import_job_accepts_every_valid_lifecycle_state(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], columns: dict[str, Any]
) -> None:
    assert insert_job(db_session, two_tenants[0], **columns)


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"status": "PENDING", "started_at": NOW}, "ck_import_jobs_lifecycle_consistent"),
        ({"status": "RUNNING"}, "ck_import_jobs_lifecycle_consistent"),
        (
            {"status": "RUNNING", "started_at": NOW, "finished_at": LATER},
            "ck_import_jobs_lifecycle_consistent",
        ),
        ({"status": "SUCCEEDED", "started_at": NOW}, "ck_import_jobs_lifecycle_consistent"),
        ({"status": "FAILED"}, "ck_import_jobs_lifecycle_consistent"),
        (
            {"status": "SUCCEEDED", "started_at": LATER, "finished_at": NOW},
            "ck_import_jobs_finished_after_started",
        ),
        (
            {"status": "SUCCEEDED", "finished_at": NOW, "error_message": "x"},
            "ck_import_jobs_error_only_when_failed",
        ),
        ({"status": "PENDING", "error_code": "E1"}, "ck_import_jobs_error_only_when_failed"),
        # PostgreSQL reports the first failing CHECK alphabetically, so an unknown status is
        # reported by a lifecycle check: any CheckViolation proves the row was refused.
        ({"status": "DONE"}, None),
    ],
)
def test_import_job_rejects_inconsistent_lifecycle_state(
    db_session: Session,
    two_tenants: tuple[Tenant, Tenant],
    rejects: Rejects,
    columns: dict[str, Any],
    constraint: str | None,
) -> None:
    with rejects(pg.CheckViolation, constraint):
        insert_job(db_session, two_tenants[0], **columns)


# --- import files ----------------------------------------------------------------------------


def insert_file(session: Session, tenant: Tenant, **columns: Any) -> Any:
    params = {"original_filename": "f.csv", "size_bytes": None, "sha256": None, **columns}
    return run(
        session,
        "INSERT INTO import_files"
        " (workspace_id, import_job_id, original_filename, size_bytes, sha256)"
        " VALUES (:w, :j, :original_filename, :size_bytes, :sha256) RETURNING id",
        w=tenant.workspace.id,
        j=tenant.import_job.id,
        **params,
    ).scalar_one()


def test_import_file_size_cannot_be_negative(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    with rejects(pg.CheckViolation, "ck_import_files_size_bytes_non_negative"):
        insert_file(db_session, two_tenants[0], size_bytes=-1)


@pytest.mark.parametrize("size", [None, 0, 1, 5 * 1024**3], ids=["unknown", "zero", "one", "5GiB"])
def test_import_file_size_may_be_unknown_zero_or_large(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], size: int | None
) -> None:
    assert insert_file(db_session, two_tenants[0], size_bytes=size)


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "g" * 64, "not-a-hash"])
def test_import_file_sha256_must_be_lowercase_hex(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects, sha256: str
) -> None:
    with rejects(pg.CheckViolation, "ck_import_files_sha256_format"):
        insert_file(db_session, two_tenants[0], sha256=sha256)


def test_import_file_filename_cannot_be_blank(
    db_session: Session, two_tenants: tuple[Tenant, Tenant], rejects: Rejects
) -> None:
    with rejects(pg.CheckViolation, "ck_import_files_original_filename_not_blank"):
        insert_file(db_session, two_tenants[0], original_filename="  ")


def test_sha256_is_not_globally_unique(
    factory: Factory, two_tenants: tuple[Tenant, Tenant]
) -> None:
    """The same content may be imported again, in the same workspace or in another one."""
    a, b = two_tenants
    digest = "ab" * 32

    hashes = [
        factory.import_file(a.import_job, digest).sha256,
        factory.import_file(a.import_job, digest).sha256,
        factory.import_file(b.import_job, digest).sha256,
    ]

    assert hashes == [digest] * 3


# --- delete policy ---------------------------------------------------------------------------


def test_membership_is_really_deleted_and_leaves_user_and_workspace(
    db_session: Session, factory: Factory
) -> None:
    workspace, user = factory.workspace(), factory.user()
    membership = factory.membership(workspace, user)

    db_session.delete(membership)
    db_session.flush()

    assert db_session.get(WorkspaceMembership, membership.id) is None
    assert db_session.get(User, user.id) is not None
    assert db_session.get(Workspace, workspace.id) is not None


def test_deleting_a_user_removes_only_their_memberships(
    db_session: Session, factory: Factory
) -> None:
    workspace, leaving, staying = factory.workspace(), factory.user(), factory.user()
    factory.membership(workspace, leaving)
    kept = factory.membership(workspace, staying)

    run(db_session, "DELETE FROM users WHERE id = :id", id=leaving.id)

    remaining = (
        run(
            db_session,
            "SELECT id FROM workspace_memberships WHERE workspace_id = :w",
            w=workspace.id,
        )
        .scalars()
        .all()
    )
    assert remaining == [kept.id]


def test_an_empty_workspace_can_be_deleted_together_with_its_memberships(
    db_session: Session, factory: Factory
) -> None:
    workspace = factory.workspace()
    factory.membership(workspace, factory.user())

    run(db_session, "DELETE FROM workspaces WHERE id = :id", id=workspace.id)

    assert (
        run(
            db_session,
            "SELECT count(*) FROM workspace_memberships WHERE workspace_id = :w",
            w=workspace.id,
        ).scalar_one()
        == 0
    )


@pytest.mark.parametrize(
    ("parent_table", "parent_attr", "constraint"),
    [
        ("workspaces", "workspace", "fk_properties_workspace_id_workspaces"),
        ("properties", "property", "fk_data_sources_workspace_id_properties"),
        ("data_sources", "data_source", "fk_import_jobs_workspace_id_data_sources"),
        ("import_jobs", "import_job", "fk_import_files_workspace_id_import_jobs"),
    ],
)
def test_parents_of_tenant_data_cannot_be_deleted_while_referenced(
    db_session: Session,
    factory: Factory,
    rejects: Rejects,
    parent_table: str,
    parent_attr: str,
    constraint: str,
) -> None:
    """RESTRICT everywhere except memberships: tenant data never disappears by cascade.

    ON DELETE RESTRICT is reported as RestrictViolation (23001), not ForeignKeyViolation (23503).
    """
    tenant = factory.tenant()
    factory.import_file(tenant.import_job)
    parent = getattr(tenant, parent_attr)

    with rejects(pg.RestrictViolation, constraint):
        run(db_session, f"DELETE FROM {parent_table} WHERE id = :id", id=parent.id)

    assert db_session.get(type(parent), parent.id) is not None
    assert db_session.query(ImportFile).count() == 1
    assert db_session.query(DataSource).count() == 1
