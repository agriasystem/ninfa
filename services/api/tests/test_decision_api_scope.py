"""Decision API V1: OpenAPI now exposes exactly health + the five Decision API routes (four GET,
plus Gate 18's one POST `/ask`), no OTHER write operation, no debug endpoint, and every one of the
five (never health) sits behind `get_current_principal` in its own dependency graph - a central,
strong guard so a future route can never be registered "by accident" without authentication.
"""

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.v1.decisions.router import (
    ask_mia_home,
    ask_ninfa,
    get_decision_detail,
    get_decision_feed,
    get_decision_history,
    list_decisions,
)
from app.api.v1.health import health
from app.core.auth import get_current_principal

_ASK_PATH = "/api/v1/properties/{property_id}/decisions/{decision_id}/ask"
_HOME_ASK_PATH = "/api/v1/properties/{property_id}/ask"

_GET_ONLY_DECISION_PATHS = {
    "/api/v1/properties/{property_id}/decision-feed",
    "/api/v1/properties/{property_id}/decisions",
    "/api/v1/properties/{property_id}/decisions/{decision_id}",
    "/api/v1/properties/{property_id}/decisions/{decision_id}/history",
}

_DECISION_PATHS = _GET_ONLY_DECISION_PATHS | {_ASK_PATH, _HOME_ASK_PATH}


def test_openapi_exposes_the_decision_routes_and_the_two_ask_posts(client: TestClient) -> None:
    """The EXACT full-surface guard (health + auth + decisions, nothing else) now lives in
    `test_auth_scope.py`, which supersedes this one now that Gate 13 legitimately adds three
    `/auth/*` routes - this file keeps the narrower, still-true claim that is actually its own
    scope: the decision routes are exactly these six (four GET, plus the Decision Ask POST and the
    property-level Mia Home POST)."""
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"])
    assert paths >= _DECISION_PATHS
    assert {p for p in paths if p.startswith("/api/v1/properties/")} == _DECISION_PATHS


def test_health_route_methods_are_unchanged_from_its_own_real_contract(client: TestClient) -> None:
    """`health.py` itself only ever defined one `@router.get(...)` - this asserts the GENERATED
    schema still matches that real, pre-existing contract, not a hand-picked expectation."""
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/v1/health"]) == {"get"}


def test_every_decision_route_is_get_only_except_the_one_ask_post(client: TestClient) -> None:
    """Gate 18's own `/ask` is the SOLE, deliberate exception - a POST because it carries a
    `question` body and calls an external provider, never because it mutates business state (see
    ADR 0024, "why POST despite read-only business state"). Every other decision route stays
    GET-only, exactly as Gate 12 defined it."""
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1/properties/"):
            continue
        if path in (_ASK_PATH, _HOME_ASK_PATH):
            assert set(methods) == {"post"}, path
            for forbidden in ("get", "put", "patch", "delete"):
                assert forbidden not in methods, (path, forbidden)
        else:
            assert set(methods) == {"get"}, path
            for forbidden in ("post", "put", "patch", "delete"):
                assert forbidden not in methods, (path, forbidden)


def test_no_debug_or_analyze_or_sync_endpoint_exists(client: TestClient) -> None:
    """ "ask" is deliberately NOT in this forbidden list (unlike before Gate 18): the one, exact,
    read-only `/ask` route is a reviewed, intentional addition - see `_ASK_PATH`'s own dedicated
    method/auth/mutation assertions elsewhere in this file. Every OTHER autonomous-action or
    debug-style word stays forbidden, unchanged."""
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
        "execute",
        "approve",
        "apply",
        "auto",
    )
    for word in forbidden_words:
        assert not [p for p in paths if word in p.lower()], word


# --- Gate 16 (Recommendation Engine V1, review items 67-71): additive-only, never a new route ---
# --- Gate 18 (Ask NINFA Core V1, review items 64-69): exactly ONE new route, POST, read-only -----


def test_decision_paths_are_exactly_the_historical_four_plus_the_two_ask_routes(
    client: TestClient,
) -> None:
    """Supersedes the old Gate-16-era claim ("still exactly the same four") now that Gate 18
    legitimately adds a fifth path: the exact 4-GET-route set Gate 12 defined is still intact
    (`_GET_ONLY_DECISION_PATHS`), plus exactly one more, `_ASK_PATH` - never a sixth, never a
    GET-history-of-conversations, never a conversation-management route of any kind."""
    schema = client.get("/openapi.json").json()
    paths = {p for p in schema["paths"] if p.startswith("/api/v1/properties/")}
    assert paths == _GET_ONLY_DECISION_PATHS | {_ASK_PATH, _HOME_ASK_PATH}
    assert _ASK_PATH in paths
    assert _HOME_ASK_PATH in paths
    for forbidden_conversation_path in (
        "/api/v1/properties/{property_id}/decisions/{decision_id}/conversations",
        "/api/v1/properties/{property_id}/decisions/{decision_id}/messages",
        "/api/v1/properties/{property_id}/decisions/{decision_id}/chat",
        "/api/v1/ask",
    ):
        assert forbidden_conversation_path not in paths


def test_decision_detail_schema_additively_includes_recommendation(client: TestClient) -> None:
    """The OpenAPI-level proof of the additive design: `DecisionDetailResponse`'s own schema now
    has a `recommendation` property, with no route, method, or path added to reach it."""
    schema = client.get("/openapi.json").json()
    detail_schema = schema["components"]["schemas"]["DecisionDetailResponse"]
    assert "recommendation" in detail_schema["properties"]


def test_decision_detail_route_parameters_unchanged_by_recommendation(client: TestClient) -> None:
    """No new query parameter (`apply`, `execute`, `include_recommendation`, ...) was added to
    reach or control the recommendation - it is unconditional, computed fresh every time."""
    schema = client.get("/openapi.json").json()
    detail_operation = schema["paths"]["/api/v1/properties/{property_id}/decisions/{decision_id}"][
        "get"
    ]
    parameter_names = {parameter["name"] for parameter in detail_operation.get("parameters", [])}
    assert parameter_names == {"property_id", "decision_id"}


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
    behavioural 401 check that a developer might forget to write. Includes Gate 18's `ask_ninfa` -
    it authenticates and authorizes exactly like every other decision route, never a lesser bar
    because it happens to call an external provider."""
    decision_endpoints = {
        get_decision_feed,
        list_decisions,
        get_decision_detail,
        get_decision_history,
        ask_ninfa,
        ask_mia_home,
    }
    decision_routes = [
        route for route in _all_api_routes(app.routes) if route.endpoint in decision_endpoints
    ]
    assert len(decision_routes) == 6
    for route in decision_routes:
        closure = _dependency_closure(route.dependant)
        assert get_current_principal in closure, route.path


def test_health_route_does_not_depend_on_get_current_principal(app: FastAPI) -> None:
    """The inverse check: health must stay public - it never gained the auth dependency."""
    [health_route] = [route for route in _all_api_routes(app.routes) if route.endpoint is health]
    closure = _dependency_closure(health_route.dependant)
    assert get_current_principal not in closure
