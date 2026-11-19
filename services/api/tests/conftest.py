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
    """The real settings, with two test-only overrides: `session_cookie_secure=False` and a
    guaranteed UNCONFIGURED language-model provider.

    The provider override keeps the suite hermetic: a developer who has configured a real
    `ASK_NINFA_PROVIDER=anthropic` + key in the root `.env` (to run a real-model smoke test) must
    never have the ordinary tests reach the network - "no provider override: the real default" tests
    mean the unconfigured default. Tests that exercise the Anthropic adapter build their own
    settings with a fake key.

    On `session_cookie_secure`:

    `TestClient` talks to `http://testserver` (plain HTTP, by construction - there is no TLS in
    an in-process test). A `Secure` cookie is never resent by ANY spec-compliant HTTP client
    (including this one) over a plain-HTTP connection, so a cookie-based test would silently see
    every request after the first arrive with no cookie at all. This is exactly the "explicit
    local HTTP development" override ADR 0019 describes - applied here for the same reason, not a
    weakening of the real (still `Secure=True`) default `test_auth_login.py::
    test_default_prefers_secure_true` itself verifies.
    """
    return get_settings().model_copy(
        update={
            "session_cookie_secure": False,
            "ask_ninfa_provider": "unconfigured",
            "anthropic_api_key": None,
            # The same for Smart Import's model layer: no provider, whatever the machine or the
            # root `.env` selects (`services/conftest.py` also forces it in the environment, and
            # `tests/offline_guard.py` fails any test that tries to leave the machine).
            "smart_import_ai_mode": "off",
            "import_understanding_provider": "unconfigured",
            "openai_api_key": None,
        }
    )


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


# --- which engine reads the columns, for the tests of what the model layer adds on top of it ---


@pytest.fixture
def rules_engine(request: pytest.FixtureRequest) -> Iterator[str]:
    """The engine that reads the columns (`v3` or `v4`) for the code inside the test, whatever the
    process was started with (ADR 0056).

    The semantic (model) layer starts from what the rules left open, so which file reaches the model
    depends on the engine: V4 reads deterministically a column V3 asked the model about (a status
    named `Condizione`), and then the model is NOT asked - which is the point of V4, not a failure.
    A test that is about the layer says which engine it speaks of:

    * `usefixtures("rules_engine")` runs it under BOTH engines - the guarantee holds whoever reads;
    * plus `@pytest.mark.rules_v3_only` when its premise is a gap only V3's rules leave (the test
      then runs under V3 alone, and the V4 side of the same promise is in
      `test_smart_import_ai_with_each_engine.py`).
    """
    from app.modules.data_sources.algorithmic.selector import use_engine

    with use_engine(request.param):
        yield str(request.param)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "rules_engine" in metafunc.fixturenames:
        v3_only = metafunc.definition.get_closest_marker("rules_v3_only") is not None
        metafunc.parametrize("rules_engine", ["v3"] if v3_only else ["v3", "v4"], indirect=True)
