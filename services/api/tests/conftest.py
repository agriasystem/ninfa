from collections.abc import Iterator

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine
from app.main import create_app
from tests.support import BookingFactory, Rejects, Tenant, alembic_config, make_rejects


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # raise_server_exceptions=False lets us assert on the 500 error envelope.
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


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
