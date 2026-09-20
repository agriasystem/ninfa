import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]


def test_health_returns_structured_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ninfa-api"
    assert set(body) == {"status", "service", "version"}


def test_health_version_comes_from_pyproject(client: TestClient) -> None:
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert client.get("/api/v1/health").json()["version"] == pyproject["project"]["version"]


def test_health_sets_generated_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert len(response.headers["X-Request-ID"]) >= 8


def test_health_echoes_valid_incoming_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-1234-abcd"})

    assert response.headers["X-Request-ID"] == "trace-1234-abcd"


def test_health_replaces_unsafe_incoming_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["X-Request-ID"] != "bad id\twith spaces"
    assert " " not in response.headers["X-Request-ID"]


def test_only_the_health_endpoint_is_public_until_authentication_exists(
    client: TestClient,
) -> None:
    """Gate 1 adds tenant data but deliberately no API for it (see architecture-v1.md)."""
    paths = client.get("/openapi.json").json()["paths"]

    assert list(paths) == ["/api/v1/health"]
