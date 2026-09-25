from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, get_session
from app.main import create_app
from tests.support import BookingFactory, Rejects, Tenant, alembic_config, make_rejects


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False lets us assert on the 500 error envelope.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def api_client(app: FastAPI, db_session: Session) -> Iterator[TestClient]:
    """A `TestClient` wired to the SAME rolled-back `db_session` transaction as `factory`: data a
    test builds with `factory` is visible to its own HTTP calls, and nothing an HTTP call writes
    outlives the test. Unauthenticated by default (no override of `get_current_principal` - real
    routes still answer 401); pair with `authenticated_as` to add a real test principal via
    `app.dependency_overrides`, never a spoofable header.
    """
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def authenticated_as(app: FastAPI) -> Callable[[UUID], None]:
    """`authenticated_as(user.id)`: overrides `get_current_principal` for THIS test's `app`
    instance with a real `AuthenticatedPrincipal` - the FastAPI dependency override the Gate 12
    review asked tests to use, never `X-User-Id` or any other spoofable header."""

    def _set(user_id: UUID) -> None:
        app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(user_id)

    return _set


# --- database ---------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Iterator[Engine]:
    """Engine on the test database, migrated to head once per test session."""
    command.upgrade(alembic_config(test_database_url), "head")
    engine = create_db_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back: tests leave no data behind.

    Statements that are expected to fail must run inside `rejects(...)`, which uses a savepoint
    so the session stays usable afterwards.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def rejects(db_session: Session) -> Rejects:
    return make_rejects(db_session)


@pytest.fixture
def factory(db_session: Session) -> BookingFactory:
    return BookingFactory(db_session)


@pytest.fixture
def two_tenants(factory: BookingFactory) -> tuple[Tenant, Tenant]:
    """Workspace A and workspace B, each with property, data source and import job."""
    return factory.tenant(), factory.tenant()
