from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    # raise_server_exceptions=False lets us assert on the 500 error envelope.
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client
