from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers every mapped class before the first query)
from app.core.config import get_settings


def create_db_engine(url: str, **kwargs: Any) -> Engine:
    """Engine whose sessions always run in UTC, whatever the server's TimeZone setting is."""
    return create_engine(
        url, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"}, **kwargs
    )


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings().sqlalchemy_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session
