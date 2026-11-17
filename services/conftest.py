"""Shared pytest setup for the backend (api + worker).

Settings are read from the environment when the application modules are imported, so the test
environment must be prepared here, before any `app` / `worker` import.

The ordinary suite is OFFLINE whatever the developer's machine holds (`tests/offline_guard.py`):
the AI switches are forced off in THIS process' environment, and a tripwire refuses and records
any connection that leaves the machine. A test that is meant to reach the real API is marked
`@pytest.mark.live_openai` (skipped unless the machine says `RUN_LIVE_OPENAI=1`).
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values

# stdlib only: safe to import before the application (`pythonpath` puts services/api first)
from tests import offline_guard

_ROOT = Path(__file__).resolve().parents[1]

# Real values come from the environment (CI) or from the developer's gitignored root .env.
_dotenv = dotenv_values(_ROOT / ".env")

TEST_DATABASE_URL: str | None = os.environ.get("TEST_DATABASE_URL") or _dotenv.get(
    "TEST_DATABASE_URL"
)

os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
os.environ["LOG_LEVEL"] = "INFO"
# Tests never touch the development database. Tests that do not need a database still need a
# syntactically valid URL; this placeholder is never connected to.
os.environ["DATABASE_URL"] = (
    TEST_DATABASE_URL or "postgresql+psycopg://placeholder:placeholder@127.0.0.1:1/placeholder"
)
os.environ.pop("CORS_ORIGINS", None)

# What the machine held, for the one kind of test that asks for it back.
_MACHINE_ENVIRONMENT = dict(os.environ)
_ISOLATED = offline_guard.isolate(os.environ)
offline_guard.GUARD.allowed = offline_guard.hosts_of(os.environ["DATABASE_URL"])


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_openai: reaches the REAL OpenAI API. Skipped unless the machine sets "
        "RUN_LIVE_OPENAI=1; while it runs the machine environment is back and the offline "
        "tripwire is off.",
    )
    offline_guard.GUARD.install()


def pytest_unconfigure(config: pytest.Config) -> None:
    offline_guard.GUARD.uninstall()
    offline_guard.restore(os.environ, _ISOLATED)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _MACHINE_ENVIRONMENT.get("RUN_LIVE_OPENAI") == "1":
        return
    skip = pytest.mark.skip(reason="a live OpenAI test: set RUN_LIVE_OPENAI=1 to run it")
    for item in items:
        if item.get_closest_marker("live_openai") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _ordinary_tests_are_offline(request: pytest.FixtureRequest) -> Iterator[None]:
    """An ordinary test that tried to leave this machine FAILS, even if the code under test caught
    the refusal (the provider adapters do, by design: Smart Import must never break)."""
    if request.node.get_closest_marker("live_openai") is not None:
        names = (*offline_guard.FORCED, *offline_guard.REMOVED)
        offline_guard.restore(os.environ, {n: _MACHINE_ENVIRONMENT.get(n) for n in names})
        try:
            with offline_guard.GUARD.lifted():
                yield
        finally:
            offline_guard.isolate(os.environ)
        return
    offline_guard.GUARD.attempts.clear()
    yield
    attempts = list(offline_guard.GUARD.attempts)
    offline_guard.GUARD.attempts.clear()
    if attempts:
        where = ", ".join(sorted(set(attempts)))
        pytest.fail(
            f"an ordinary test tried to leave this machine ({where}): the suite is offline. "
            "A test that must reach the real API is marked live_openai.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of the dedicated test database; fails loudly instead of silently skipping."""
    if not TEST_DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Configure it in .env (see .env.example) and create "
            "the test database (see docs/development/local-development.md)."
        )
    return TEST_DATABASE_URL
