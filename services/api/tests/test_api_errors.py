from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app


def _app_with_probe_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/probe/validated/{item_id}")
    def validated(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/probe/app-error")
    def app_error() -> None:
        raise AppError("thing_missing", "The thing is missing", status_code=404, details={"id": 7})

    @app.get("/probe/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    return app


def _assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"]
    return error


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = _assert_envelope(response.json(), "not_found")
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_uses_envelope_without_echoing_input(settings: Settings) -> None:
    with TestClient(_app_with_probe_routes(settings)) as client:
        response = client.get("/probe/validated/not-a-number")

    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    assert isinstance(error["details"], list)
    assert error["details"][0]["loc"] == ["path", "item_id"]
    assert "not-a-number" not in response.text


def test_app_error_uses_declared_status_and_details(settings: Settings) -> None:
    with TestClient(_app_with_probe_routes(settings)) as client:
        response = client.get("/probe/app-error")

    assert response.status_code == 404
    error = _assert_envelope(response.json(), "thing_missing")
    assert error["message"] == "The thing is missing"
    assert error["details"] == {"id": 7}


def test_unhandled_exception_is_hidden_behind_generic_envelope(settings: Settings) -> None:
    with TestClient(_app_with_probe_routes(settings), raise_server_exceptions=False) as client:
        response = client.get("/probe/boom")

    assert response.status_code == 500
    error = _assert_envelope(response.json(), "internal_error")
    assert error["message"] == "Internal server error"
    assert "secret internal detail" not in response.text
    assert response.headers["X-Request-ID"] == error["request_id"]
