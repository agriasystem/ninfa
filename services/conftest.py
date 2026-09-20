"""Shared pytest setup for the backend (api + worker).

Settings are read from the environment when the application modules are imported, so the test
environment must be prepared here, before any `app` / `worker` import.
"""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

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


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of the dedicated test database; fails loudly instead of silently skipping."""
    if not TEST_DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL is not set. Configure it in .env (see .env.example) and create "
            "the test database (see docs/development/local-development.md)."
        )
    return TEST_DATABASE_URL
