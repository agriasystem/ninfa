"""Authentication & Session V1: exact OpenAPI surface (review items 103-111).

Gate 18 adds exactly one further path, `.../decisions/{decision_id}/ask`, and Home UI V1 (Mia
Home, ADR 0028) exactly one more, `.../properties/{property_id}/ask` - the only two POSTs among the
`/api/v1/properties/` routes (see `test_decision_api_scope.py` for the route/method assertions).
"""

from fastapi.testclient import TestClient

_ASK_PATH = "/api/v1/properties/{property_id}/decisions/{decision_id}/ask"
_HOME_ASK_PATH = "/api/v1/properties/{property_id}/ask"

_EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/session",
    "/api/v1/properties/{property_id}/decision-feed",
    "/api/v1/properties/{property_id}/decisions",
    "/api/v1/properties/{property_id}/decisions/{decision_id}",
    "/api/v1/properties/{property_id}/decisions/{decision_id}/history",
    _ASK_PATH,
    _HOME_ASK_PATH,
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


def test_decision_routes_remain_get_only_except_the_two_ask_posts(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1/properties/"):
            continue
        if path in (_ASK_PATH, _HOME_ASK_PATH):
            assert set(methods) == {"post"}, path
        else:
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
