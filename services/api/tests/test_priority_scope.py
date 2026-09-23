"""Gate 10 boundary: no recommendation, no persistence, no UI, no scheduler, no AI, no API, no
migration, no new dependency (spec part U). AST-based, not substring-based, since this module's
own docstrings explain several of these exclusions in prose (a text search would false-positive
on the word "Decision" itself, used legitimately in `decision_type`/`PriorityDecisionType`)."""

import ast
from pathlib import Path

from fastapi.testclient import TestClient

import app.modules.intelligence.priority as priority_package

_PACKAGE_DIR = Path(priority_package.__file__).parent
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _module_trees() -> list[tuple[str, ast.Module]]:
    return [
        (source.name, ast.parse(source.read_text(encoding="utf-8")))
        for source in _PACKAGE_DIR.glob("*.py")
    ]


def test_no_recommendation_class_or_generated_action_text_function() -> None:
    forbidden_names = {"Recommendation", "RecommendationEngine", "generate_recommendation"}
    for name, tree in _module_trees():
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef | ast.FunctionDef)
        }
        assert not defined & forbidden_names, f"{name} defines {defined & forbidden_names}"


def test_no_decision_persistence_or_lifecycle_or_memory_class() -> None:
    forbidden_names = {
        "Decision",
        "DecisionFact",
        "DecisionEvent",
        "DecisionOutcome",
        "DecisionMemory",
        "DecisionLifecycle",
        "DecisionState",
    }
    for name, tree in _module_trees():
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        assert not defined & forbidden_names, f"{name} defines {defined & forbidden_names}"


def test_no_orm_model_base_is_used_anywhere_priority_stays_out_of_the_database() -> None:
    for name, tree in _module_trees():
        bases = {
            base.id
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for base in node.bases
            if isinstance(base, ast.Name)
        }
        assert "Base" not in bases, f"{name} defines an ORM model"


def test_no_ai_ml_or_ranking_model_identifier() -> None:
    forbidden_substrings = ("openai", "anthropic", "llm", "embedding", "mlmodel", "ranking_model")
    for name, tree in _module_trees():
        identifiers = {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for identifier in identifiers:
            assert not any(bad in identifier for bad in forbidden_substrings), (
                f"{name} references an AI/ML identifier: {identifier}"
            )


def test_no_fastapi_router_or_business_api_anywhere_in_the_module() -> None:
    for name, tree in _module_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "fastapi" in node.module:
                raise AssertionError(f"{name} imports fastapi")
            if isinstance(node, ast.Name) and node.id == "APIRouter":
                raise AssertionError(f"{name} references APIRouter")


def test_no_worker_task_or_scheduler_decorator() -> None:
    forbidden = {"task", "periodic", "defer", "schedule"}
    for name, tree in _module_trees():
        decorator_names = {
            decorator.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
        }
        assert not decorator_names & forbidden, f"{name} has a worker-task decorator"


def test_alembic_head_still_has_no_priority_migration() -> None:
    migrations_dir = _REPO_ROOT / "services" / "api" / "alembic" / "versions"
    filenames = [path.name for path in migrations_dir.glob("*.py")]
    assert filenames, "expected to find existing migration files"
    assert any("0008_labor_ingestion" in filename for filename in filenames), filenames
    assert not any("priority" in filename.lower() for filename in filenames)


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    # Priority adds no route: the API surface is exactly what it was before this gate.
    paths = list(client.get("/openapi.json").json()["paths"])
    assert paths == ["/api/v1/health"]
    for word in ("priority", "candidate", "ranking"):
        assert not [p for p in paths if word in p]
