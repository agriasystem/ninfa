"""Database foundation checks. They run against TEST_DATABASE_URL (never the dev database)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="module")
def engine(test_database_url: str) -> Iterator[Engine]:
    test_engine = create_engine(test_database_url)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def alembic_config(test_database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = test_database_url
    config.attributes["configure_logging"] = False
    return config


def test_test_suite_uses_the_test_database(test_database_url: str) -> None:
    assert get_settings().sqlalchemy_url == test_database_url


def test_can_connect(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_application_role_is_not_superuser(engine: Engine) -> None:
    with engine.connect() as connection:
        is_super = connection.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()

    assert is_super is False


def test_migrations_upgrade_to_head(engine: Engine, alembic_config: Config) -> None:
    head = ScriptDirectory.from_config(alembic_config).get_current_head()

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        queue_table = connection.execute(
            text("SELECT to_regclass('public.procrastinate_jobs')")
        ).scalar_one()

    assert current == head
    assert queue_table == "procrastinate_jobs"


def test_migrations_are_idempotent_at_head(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")


def test_migrations_can_be_downgraded_and_reapplied(engine: Engine, alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    with engine.connect() as connection:
        queue_table = connection.execute(
            text("SELECT to_regclass('public.procrastinate_jobs')")
        ).scalar_one()
    assert queue_table is None

    command.upgrade(alembic_config, "head")
