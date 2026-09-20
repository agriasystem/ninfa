"""Alembic environment.

The database URL comes from `app.core.config.Settings` (DATABASE_URL), unless a caller
overrides it programmatically with `config.attributes["database_url"]` (used by the tests).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

import app.models  # noqa: F401  (registers models on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.migration_filters import include_object
from app.db.session import create_db_engine

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    override = config.attributes.get("database_url")
    return str(override) if override else get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
