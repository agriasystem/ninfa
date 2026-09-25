"""Gate 11 boundary: no recommendation, no generated prose, no AI, no business API, no UI, no
notification, no scheduler, no detector/Priority-formula change, no new dependency (tests 146-156).

AST-based, not substring-based, for the same reason `test_priority_scope.py` gives: this module's
own docstrings explain several of these exclusions in prose.
"""

import ast
import tomllib
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

import app.modules.decision_memory as decision_memory_package
import app.modules.decisions as decisions_package
from app.modules.intelligence.costs.types import COST_RULES_VERSION
from app.modules.intelligence.distribution.types import OTA_DEPENDENCY_RULES_VERSION
from app.modules.intelligence.labor.types import LABOR_RULES_VERSION
from app.modules.intelligence.priority.types import (
    ACTIONABILITY_WEIGHT,
    CONFIDENCE_WEIGHT,
    IMPACT_WEIGHT,
    PRIORITY_RULES_VERSION,
    URGENCY_WEIGHT,
)
from app.modules.intelligence.revenue.types import RULES_VERSION as REVENUE_RULES_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_DIRS = [
    Path(decisions_package.__file__).parent,
    Path(decision_memory_package.__file__).parent,
]


def _module_trees() -> list[tuple[str, ast.Module]]:
    return [
        (source.name, ast.parse(source.read_text(encoding="utf-8")))
        for package_dir in _PACKAGE_DIRS
        for source in package_dir.glob("*.py")
    ]


def test_no_recommendation_class_or_generated_action_text_function() -> None:
    forbidden_names = {
        "Recommendation",
        "RecommendationEngine",
        "generate_recommendation",
        "generate_summary",
        "explain",
    }
    for name, tree in _module_trees():
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef | ast.FunctionDef)
        }
        assert not defined & forbidden_names, f"{name} defines {defined & forbidden_names}"


def test_no_generated_natural_language_prose_function() -> None:
    forbidden_substrings = ("narrative", "generatetext", "naturallanguage", "summarize")
    for name, tree in _module_trees():
        identifiers = {
            node.name.lower().replace("_", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.ClassDef)
        }
        for identifier in identifiers:
            assert not any(bad in identifier for bad in forbidden_substrings), (
                f"{name} defines {identifier}"
            )


def test_no_ai_ml_identifier_anywhere() -> None:
    forbidden_substrings = ("openai", "anthropic", "llm", "embedding", "mlmodel", "vectordb")
    for name, tree in _module_trees():
        identifiers = {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        for identifier in identifiers:
            assert not any(bad in identifier for bad in forbidden_substrings), (
                f"{name} references an AI/ML identifier: {identifier}"
            )


def test_no_fastapi_router_anywhere_in_the_decision_modules() -> None:
    for name, tree in _module_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "fastapi" in node.module:
                raise AssertionError(f"{name} imports fastapi")
            if isinstance(node, ast.Name) and node.id == "APIRouter":
                raise AssertionError(f"{name} references APIRouter")


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])
    assert paths == ["/api/v1/health"]
    for word in ("decision", "priority", "candidate"):
        assert not [p for p in paths if word in p]


def test_no_notification_identifier() -> None:
    forbidden_substrings = ("sendemail", "sendsms", "pushnotification", "webhook", "slackalert")
    for name, tree in _module_trees():
        identifiers = {
            node.name.lower().replace("_", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.ClassDef)
        }
        for identifier in identifiers:
            assert not any(bad in identifier for bad in forbidden_substrings), (
                f"{name} defines {identifier}"
            )


def test_no_worker_task_or_scheduler_decorator_or_import() -> None:
    forbidden_decorators = {"task", "periodic", "defer", "schedule"}
    for name, tree in _module_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "procrastinate" in node.module:
                raise AssertionError(f"{name} imports the worker/scheduler framework")
        decorator_names = {
            decorator.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
        }
        assert not decorator_names & forbidden_decorators, f"{name} has a scheduler decorator"


def test_detector_rule_versions_are_unchanged_by_this_gate() -> None:
    """A proxy for "no detector change": Gates 5/7/8/9's own rules versions are literal, hand-
    written constants - if this gate had touched a detector's calculation, the version would have
    had to change with it (every gate in this codebase bumps its own version on a rule change)."""
    assert REVENUE_RULES_VERSION == "revenue-decisions-v1"
    assert COST_RULES_VERSION == "cost-cpor-anomaly-v1"
    assert LABOR_RULES_VERSION == "labor-overstaffing-v1"
    assert OTA_DEPENDENCY_RULES_VERSION == "ota-dependency-v1"


def test_priority_formula_and_weights_are_unchanged_by_this_gate() -> None:
    assert PRIORITY_RULES_VERSION == "priority-engine-v1"
    assert (
        Decimal("0.40"),
        Decimal("0.25"),
        Decimal("0.20"),
    ) == (IMPACT_WEIGHT, URGENCY_WEIGHT, CONFIDENCE_WEIGHT)
    assert Decimal("0.15") == ACTIONABILITY_WEIGHT


def test_no_new_runtime_dependency_was_added() -> None:
    pyproject = tomllib.loads((_REPO_ROOT / "services" / "api" / "pyproject.toml").read_text())
    dependencies = {
        entry.split()[0].split("[")[0].split(">=")[0].split("==")[0].split("~=")[0].lower()
        for entry in pyproject["project"]["dependencies"]
    }
    # exactly the dependency set the codebase already had before this gate: the Decision Layer
    # needed nothing new (no rule DSL library, no event-sourcing framework, no AI/ML package).
    known = {
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic-settings",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "tzdata",
        "openpyxl",
    }
    unexpected = dependencies - known
    assert unexpected == set(), f"unexpected new dependency: {unexpected}"
