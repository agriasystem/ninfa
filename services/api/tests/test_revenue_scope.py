"""Gate 5 scope guards: two explicit detectors and their evaluations, nothing beyond them.

No persisted Decision, no generic rule engine, no pricing, recommendation, priority, AI, OTA,
cost or labor detector, no public API, worker task or scheduler, no migration, no float, no clock,
no writer, no new third-party dependency.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

import app as app_root
import app.modules.intelligence.revenue as revenue_package
from app.db.base import Base
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    ReasonCode,
    RevenueDecisionType,
)
from tests.support import alembic_config

PACKAGE_DIR = Path(revenue_package.__file__).parent
APP_DIR = Path(app_root.__file__).parent
WORKER_DIR = Path(__file__).resolve().parents[2] / "worker" / "worker"
PYPROJECTS = [
    Path(__file__).resolve().parents[3] / "pyproject.toml",
    Path(__file__).resolve().parents[1] / "pyproject.toml",
    Path(__file__).resolve().parents[2] / "worker" / "pyproject.toml",
]
MODULES = {
    "__init__",
    "types",
    "errors",
    "pairing",
    "statistics",
    "confidence",
    "impact",
    "pattern",
    "precision",
    "pickup",
    "occupancy",
    "fingerprint",
    "service",
}
# Whole words (identifiers are split on snake_case and CamelCase before comparing).
FORBIDDEN_TOKENS = {
    "recommendation",
    "recommend",
    "priority",
    "pricing",
    "price",
    "llm",
    "openai",
    "anthropic",
    "prompt",
    "narrative",
    "weather",
    "competitor",
    "alert",
    "outcome",
    "memory",
    "engine",
    "framework",
    "plugin",
    "registry",
    "dsl",
    "generic",
    "supplier",
    "invoice",
    "labor",
    "labour",
    "cost",
    "ota",
    "loss",
    "lost",
    "impact",
    "float",
}
FORBIDDEN_TABLE_WORDS = ("decision", "recommendation", "priority", "alert", "outcome", "memory")
FORBIDDEN_CLASSES = {
    "Decision",
    "DecisionFact",
    "DecisionEvent",
    "DecisionOutcome",
    "DecisionMemory",
    "GenericDecisionEngine",
}
WRITER_ATTRIBUTES = {
    "commit",
    "rollback",
    "flush",
    "add_all",
    "delete",
    "merge",
    "execute",
    "insert_baselines",
    "insert_comparables",
    "insert_if_absent",
    "set_for_date",
    "lock_data_source",
}


def source_files() -> list[Path]:
    return sorted(PACKAGE_DIR.glob("*.py"))


def tokens(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {part for part in spaced.lower().split("_") if part}


def identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg | ast.keyword) and node.arg is not None:
            names.add(node.arg)
    return names


def string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


# --- S: exactly two detectors, nothing generic ------------------------------------------------


def test_only_the_two_revenue_decision_types_exist() -> None:
    assert {t.value for t in RevenueDecisionType} == {"REV_PICKUP_LOW", "REV_OCCUPANCY_RISK"}


def test_the_five_statuses_are_distinct_and_complete() -> None:
    assert {s.value for s in EvaluationStatus} == {
        "TRIGGERED",
        "CLEAR",
        "INSUFFICIENT_DATA",
        "NOT_APPLICABLE",
        "SUPPRESSED_LOW_CONFIDENCE",
    }


def test_the_reason_codes_are_stable() -> None:
    assert {c.value for c in ReasonCode} >= {
        "TRIGGER_PICKUP_SHORTFALL",
        "TRIGGER_OCCUPANCY_GAP",
        "TRIGGER_ROOM_SHORTFALL",
        "TRIGGER_OCCUPANCY_AND_ROOM_SHORTFALL",
        "CLEAR_WITHIN_EXPECTED_RANGE",
        "EXPECTED_BASELINE_INSUFFICIENT",
        "PAIR_SAMPLE_INSUFFICIENT",
        "PICKUP_PRIOR_OBSERVATION_MISSING",
        "PICKUP_EXPECTATION_NON_POSITIVE",
        "PICKUP_NEAR_SOLD_OUT",
        "OCCUPANCY_INVENTORY_UNKNOWN",
        "OCCUPANCY_ALREADY_SOLD_OUT",
        "PROPERTY_CLOSED_FOR_STAY_DATE",
        "LOW_CONFIDENCE",
    }


def test_the_package_is_the_explicit_set_of_modules() -> None:
    assert {path.stem for path in source_files()} == MODULES


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_no_pricing_recommendation_priority_ai_or_generic_engine_vocabulary(path: Path) -> None:
    used = identifiers(path) | string_constants(path)
    found = {word for name in used for word in tokens(name) if word in FORBIDDEN_TOKENS}
    assert found == set(), found


def test_no_persisted_decision_model_exists_anywhere() -> None:
    classes = {
        node.name
        for path in APP_DIR.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }
    assert classes & FORBIDDEN_CLASSES == set()


def test_the_schema_gained_no_decision_table() -> None:
    names = " ".join(sorted(Base.metadata.tables))
    for word in FORBIDDEN_TABLE_WORDS:
        assert word not in names, word
    assert {t for t in Base.metadata.tables if "revenue" in t or "evaluation" in t} == set()


def test_there_is_no_migration_for_gate_5() -> None:
    script = ScriptDirectory.from_config(alembic_config("postgresql+psycopg://unused/unused"))
    assert script.get_heads() == ["0006_expected_engine"]
    assert len(list(script.walk_revisions())) == 6


# --- read-only, no clock, no float ------------------------------------------------------------


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_the_revenue_code_writes_nothing_and_takes_no_lock(path: Path) -> None:
    assert identifiers(path) & WRITER_ATTRIBUTES == set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("sqlalchemy")
        ):
            assert {alias.name for alias in node.names} <= {"Session"}, (path.name, node.module)


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_the_revenue_code_reads_no_clock(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    for needle in (
        "datetime.now",
        "utcnow",
        "date.today",
        "time.time",
        "perf_counter",
        "monotonic",
    ):
        assert needle not in source, (path.name, needle)


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_the_revenue_code_uses_no_float(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        assert not (isinstance(node, ast.Name) and node.id == "float"), path.name
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path.name


def test_the_service_has_no_web_framework_dependency() -> None:
    code = (
        "import sys, app.modules.intelligence.revenue.service; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "[]"


# --- no API, no worker, no dependency ---------------------------------------------------------


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])
    assert paths == ["/api/v1/health"]
    for word in ("revenue", "decision", "pickup", "occupancy", "evaluation"):
        assert not [p for p in paths if word in p]


def test_no_worker_task_and_no_scheduler_was_added() -> None:
    for word in ("revenue", "pickup", "occupancy", "decision"):
        assert not any(
            word in path.read_text(encoding="utf-8").lower() for path in WORKER_DIR.glob("*.py")
        ), word
    tasks = (WORKER_DIR / "tasks.py").read_text(encoding="utf-8")
    assert tasks.count("@app.task") == 1  # still only the Gate 0 heartbeat


def test_only_the_standard_library_sqlalchemy_and_the_app_are_imported() -> None:
    allowed_roots = {"app", "sqlalchemy", "__future__"}
    stdlib = set(sys.stdlib_module_names)
    for path in source_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] in stdlib | allowed_roots, (path.name, module)


def test_the_dependency_manifests_do_not_mention_scientific_or_ai_libraries() -> None:
    for manifest in PYPROJECTS:
        text = manifest.read_text(encoding="utf-8").lower()
        for library in (
            "numpy",
            "pandas",
            "scipy",
            "scikit",
            "sklearn",
            "statsmodels",
            "openai",
            "anthropic",
            "langchain",
        ):
            assert library not in text, (manifest.name, library)


# --- the documentation states the decisions --------------------------------------------------

DOCS = Path(__file__).resolve().parents[3] / "docs" / "architecture"


def test_the_documentation_records_the_gate_5_decisions() -> None:
    adr = " ".join(
        (DOCS / "adr" / "0011-revenue-decision-detection-v1.md").read_text("utf-8").split()
    )
    for phrase in (
        "No persisted Decision yet",
        "7-day pickup window",
        "Curve pairs, not an on-the-books gap",
        "remaining net pickup",
        "Cancellations are embedded in the net movement",
        "Final confidence is the MINIMUM",
        "Near sold out silences the pickup",
        "There is no loss probability",
        "It is **not** lost revenue",
        "Thresholds compare the full-precision values, never the rounded ones",
    ):
        assert phrase in adr, phrase
    guide = " ".join((DOCS / "revenue-decisions-v1.md").read_text("utf-8").split())
    for phrase in (
        "revenue-decisions-v1",
        "revenue-curve-pattern-v1",
        "SUPPRESSED_LOW_CONFIDENCE",
        "gross exposure proxy",
        "Expected is not a forecast",
        "seven statements",
        "Decision values and displayed values",
        "delta_percent_exact",
        "non-lossily",
    ):
        assert phrase in guide, phrase
