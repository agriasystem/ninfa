"""Part V: scope guards - what Gate 9 deliberately does NOT build.

Checked on the AST's own IDENTIFIER nodes (a name being defined or referenced), never a text
search of the source: every module here explains in PROSE what it deliberately excludes
("never a commission cost", "no persisted Decision"), and a naive substring search would trip on
that very prose. An identifier is different: if `commission`, `priority` or `recommend` were
ever an actual variable, function, class or keyword argument name, that would be the real
violation this test exists to catch.
"""

import ast
import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from app.modules.intelligence import distribution as distribution_package

_DISTRIBUTION_DIR = Path(inspect.getfile(distribution_package)).parent

_FORBIDDEN_SUBSTRINGS = (
    "commission",
    "netrevenuegain",
    "economicloss",
    "conversion",
    "cac",
    "roas",
    "cancellationrate",
    "channelprofitability",
    "rateparity",
    "adrbychannel",
    # NOT "decision": `OtaDecisionType`/`decision_type` are the SAME naming convention Gate
    # 5/7/8 already use for "which detector answered" (never a persisted Decision table -
    # `test_no_decision_table_or_persistence_class` below checks THAT specifically).
    "priority",
    "urgency",
    "actionability",
    "ranking",
    "recommend",
    "llm",
    "embedding",
    "sklearn",
    "torch",
    "tensorflow",
)


def _identifiers_of(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            names.add(node.arg)
    return names


def _all_identifiers() -> set[str]:
    identifiers: set[str] = set()
    for path in _DISTRIBUTION_DIR.glob("*.py"):
        identifiers |= _identifiers_of(path.read_text(encoding="utf-8"))
    return identifiers


def test_no_forbidden_identifier_appears_anywhere_in_the_module() -> None:
    """One sweep covering commission/channel-performance/pricing, decision/priority/
    recommendation machinery, and AI/ML dependencies: none is an actual identifier."""
    identifiers = {name.lower().replace("_", "") for name in _all_identifiers()}
    hits = {forbidden for forbidden in _FORBIDDEN_SUBSTRINGS if forbidden in identifiers}
    assert not hits, hits


def test_no_decision_table_or_persistence_class() -> None:
    tree = ast.parse(
        "\n".join(path.read_text(encoding="utf-8") for path in _DISTRIBUTION_DIR.glob("*.py"))
    )
    class_names = {node.name.lower() for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert not (class_names & {"decision", "decisionfact", "decisionevent", "decisionoutcome"})


def test_openapi_still_exposes_only_the_health_endpoint(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert sorted(response.json()["paths"].keys()) == ["/api/v1/health"]


def test_no_ota_dependency_business_endpoint_exists(client: TestClient) -> None:
    for path in ("/api/v1/ota-dependency", "/api/v1/rev-ota-dependency", "/api/v1/distribution"):
        response = client.get(path)
        assert response.status_code == 404


def test_no_migration_was_added() -> None:
    versions_dir = _DISTRIBUTION_DIR.parents[3] / "alembic" / "versions"
    heads = [
        path.stem for path in versions_dir.glob("*.py") if path.stem.startswith(("0008", "0009"))
    ]
    assert heads == ["0008_labor_ingestion"]
