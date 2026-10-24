"""Authentication & Session V1: exact OpenAPI surface (review items 103-111).

Gate 18 adds exactly one further path, `.../decisions/{decision_id}/ask`, and Home UI V1 (Mia
Home, ADR 0028) exactly one more, `.../properties/{property_id}/ask` - the only two POSTs among the
`/api/v1/properties/` routes (see `test_decision_api_scope.py` for the route/method assertions).
Dati UI V1 (ADR 0031) adds exactly one more, a GET: `.../properties/{property_id}/data/overview`.
Fonti dati V1 (docs/architecture/data-sources-v1.md) adds the `.../data-sources` family under
`/properties/{property_id}`, whose exact methods are pinned below and in `test_data_sources_api.py`.
Smart Import V2 (docs/architecture/smart-import-v2.md) adds to that family, all POST except the
saved configuration (GET / DELETE): read a file, check a matching, dry-run it, import with it.
"""

from fastapi.testclient import TestClient

_ASK_PATH = "/api/v1/properties/{property_id}/decisions/{decision_id}/ask"
_HOME_ASK_PATH = "/api/v1/properties/{property_id}/ask"
_DATA_OVERVIEW_PATH = "/api/v1/properties/{property_id}/data/overview"
_SOURCES = "/api/v1/properties/{property_id}/data-sources"
# The data-source family, with the EXACT methods each path may answer.
_SOURCES_METHODS = {
    _SOURCES: {"get"},  # NO POST: a source is never created on its own, only by a successful import
    f"{_SOURCES}/{{data_source_id}}": {"delete"},
    f"{_SOURCES}/import-preview": {"post"},
    f"{_SOURCES}/imports": {"post"},
    f"{_SOURCES}/imports/mapped": {"post"},
    f"{_SOURCES}/import-inspection": {"post"},
    f"{_SOURCES}/import-mapping-check": {"post"},
    f"{_SOURCES}/import-validation": {"post"},
    f"{_SOURCES}/{{data_source_id}}/import-configuration": {"get", "delete"},
    f"{_SOURCES}/templates/{{domain}}": {"get"},
}

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
    _DATA_OVERVIEW_PATH,
    *_SOURCES_METHODS,
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
        if path in _SOURCES_METHODS:
            assert set(methods) == _SOURCES_METHODS[path], path
        elif path in (_ASK_PATH, _HOME_ASK_PATH):
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
