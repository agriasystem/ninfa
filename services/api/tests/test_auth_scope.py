"""Authentication & Session V1: exact OpenAPI surface (review items 103-111)."""

from fastapi.testclient import TestClient

_EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/session",
    "/api/v1/properties/{property_id}/decision-feed",
    "/api/v1/properties/{property_id}/decisions",
    "/api/v1/properties/{property_id}/decisions/{decision_id}",
    "/api/v1/properties/{property_id}/decisions/{decision_id}/history",
}


def test_openapi_exposes_exactly_the_expected_paths(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == _EXPECTED_PATHS


def test_login_is_post_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/v1/auth/login"]) == {"post"}


def test_logout_is_post_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/v1/auth/logout"]) == {"post"}


def test_session_is_get_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/v1/auth/session"]) == {"get"}


def test_decision_routes_remain_get_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if path.startswith("/api/v1/properties/"):
            assert set(methods) == {"get"}, path


def test_no_signup_reset_oauth_or_debug_auth_route_exists(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = [p.lower() for p in schema["paths"]]
    forbidden_words = (
        "signup",
        "register",
        "reset-password",
        "reset_password",
        "forgot-password",
        "change-password",
        "change_password",
        "oauth",
        "callback",
        "sso",
        "mfa",
        "debug",
    )
    for word in forbidden_words:
        assert not [p for p in paths if word in p], word
