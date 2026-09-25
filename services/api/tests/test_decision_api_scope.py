"""Decision API V1: OpenAPI now exposes exactly health + the four Decision API routes, GET only,
no write operations, no debug endpoint, and every one of the four (never health) sits behind
`get_current_principal` in its own dependency graph - a central, strong guard so a future route
can never be registered "by accident" without authentication.
"""

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.v1.decisions.router import (
    get_decision_detail,
    get_decision_feed,
    get_decision_history,
    list_decisions,
)
from app.api.v1.health import health
from app.core.auth import get_current_principal

_EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/properties/{property_id}/decision-feed",
    "/api/v1/properties/{property_id}/decisions",
    "/api/v1/properties/{property_id}/decisions/{decision_id}",
    "/api/v1/properties/{property_id}/decisions/{decision_id}/history",
}


def test_openapi_exposes_exactly_health_and_the_four_decision_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == _EXPECTED_PATHS


def test_health_route_methods_are_unchanged_from_its_own_real_contract(client: TestClient) -> None:
    """`health.py` itself only ever defined one `@router.get(...)` - this asserts the GENERATED
    schema still matches that real, pre-existing contract, not a hand-picked expectation."""
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/v1/health"]) == {"get"}


def test_every_decision_route_is_get_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if path == "/api/v1/health":
            continue
        assert set(methods) == {"get"}, path
        for forbidden in ("post", "put", "patch", "delete"):
            assert forbidden not in methods, (path, forbidden)


def test_no_debug_or_analyze_or_sync_endpoint_exists(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = list(schema["paths"])
    forbidden_words = (
        "debug",
        "analyze",
        "run",
        "scan",
        "detect",
        "sync",
        "resolve",
        "reopen",
        "dismiss",
        "snooze",
        "acknowledge",
        "recommend",
        "ask",
    )
    for word in forbidden_words:
        assert not [p for p in paths if word in p.lower()], word


# --- structural auth coverage: every Decision route's OWN dependency graph, not just its HTTP
# behaviour (see test_decision_api_auth.py for the behavioural 401 proof of the same fact) ------


def _dependency_closure(dependant: Dependant) -> set[object]:
    calls: set[object] = {dependant.call} if dependant.call is not None else set()
    for sub in dependant.dependencies:
        calls |= _dependency_closure(sub)
    return calls


def _all_api_routes(routes: Iterable[Any]) -> list[APIRoute]:
    """Recursively flattens every `APIRoute` out of the app's route tree. This FastAPI version
    nests `include_router()` as `_IncludedRouter` proxies (their own real routes live under
    `.original_router.routes`), so `APIRoute.path` alone is only the LOCAL, unprefixed path
    (`/health`, not `/api/v1/health`) - routes are matched by ENDPOINT FUNCTION identity instead,
    which is unambiguous regardless of how many prefixes wrap it."""
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_all_api_routes(route.original_router.routes))
        elif hasattr(route, "routes"):
            found.extend(_all_api_routes(route.routes))
    return found


def test_every_decision_route_depends_on_get_current_principal(app: FastAPI) -> None:
    """Walks the REAL FastAPI dependency graph (not the source text): a future route added to
    `app/api/v1/decisions/router.py` without a path (directly or via `resolve_property_scope`,
    which itself depends on it) to `get_current_principal` would fail this test, not just a
    behavioural 401 check that a developer might forget to write."""
    decision_endpoints = {
        get_decision_feed,
        list_decisions,
        get_decision_detail,
        get_decision_history,
    }
    decision_routes = [
        route for route in _all_api_routes(app.routes) if route.endpoint in decision_endpoints
    ]
    assert len(decision_routes) == 4
    for route in decision_routes:
        closure = _dependency_closure(route.dependant)
        assert get_current_principal in closure, route.path


def test_health_route_does_not_depend_on_get_current_principal(app: FastAPI) -> None:
    """The inverse check: health must stay public - it never gained the auth dependency."""
    [health_route] = [route for route in _all_api_routes(app.routes) if route.endpoint is health]
    closure = _dependency_closure(health_route.dependant)
    assert get_current_principal not in closure
