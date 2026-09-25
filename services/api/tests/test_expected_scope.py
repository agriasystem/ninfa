"""Gate 4 scope guards: Expected is a historical level, and nothing beyond it exists.

No forecast, pickup, alert, decision, AI, public API, worker task or scheduler; no dependency on
the web framework; no float; no new third-party dependency.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.modules.intelligence.expected as expected_package
from app.db.base import Base

PACKAGE_DIR = Path(expected_package.__file__).parent
WORKER_DIR = Path(__file__).resolve().parents[2] / "worker" / "worker"
PYPROJECTS = [
    Path(__file__).resolve().parents[3] / "pyproject.toml",
    Path(__file__).resolve().parents[1] / "pyproject.toml",
    Path(__file__).resolve().parents[2] / "worker" / "pyproject.toml",
]
FORBIDDEN_WORDS = (
    "pickup",
    "velocity",
    "forecast",
    "trend",
    "alert",
    "decision",
    "recommendation",
    "priority",
    "impact",
    "narrative",
    "remaining",
    "llm",
    "openai",
    "anthropic",
    "prompt",
    "weather",
    "competitor",
)


def identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.arg):
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


# --- M. nothing beyond Expected ---------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_forecast_pickup_alert_decision_or_ai_vocabulary_in_the_code(path: Path) -> None:
    used = {name.lower() for name in identifiers(path)}
    used |= {value.lower() for value in string_constants(path)}

    found = {word for word in FORBIDDEN_WORDS if any(word in name for name in used)}

    assert found == set(), found


def test_the_schema_has_no_forecast_pickup_alert_or_decision_table() -> None:
    # "decision" is excluded on purpose: Gate 11 legitimately adds `decisions`/`decision_runs`/
    # `decision_observations` elsewhere - the invariant this test still protects is that the
    # EXPECTED ENGINE ITSELF never grows a forecast/pickup/alert/priority/impact table.
    names = " ".join(sorted(Base.metadata.tables))

    for word in ("forecast", "pickup", "alert", "recommendation", "priority", "impact"):
        assert word not in names, word
    assert {t for t in Base.metadata.tables if "expected" in t} == {
        "booking_expected_baselines",
        "booking_expected_comparables",
    }


def test_an_expected_baseline_has_no_forecast_shaped_column() -> None:
    from app.modules.intelligence.expected.models import BookingExpectedBaseline

    columns = set(BookingExpectedBaseline.__table__.columns.keys())

    assert not {
        c for c in columns if any(w in c for w in ("final", "remaining", "forecast", "pickup"))
    }
    assert {"expected_rooms_on_books", "expected_lower", "expected_upper", "iqr"} <= columns


def test_the_range_is_named_and_documented_as_a_historical_quartile_range_not_an_interval() -> None:
    from app.modules.intelligence.expected import statistics

    source = (PACKAGE_DIR / "statistics.py").read_text(encoding="utf-8")

    assert "NOT a confidence or" in source and "prediction interval" in source
    assert statistics.P25 < statistics.P75
    for path in PACKAGE_DIR.glob("*.py"):
        assert "95%" not in path.read_text(encoding="utf-8"), path.name


# --- no API, no worker, no framework ----------------------------------------------------------


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])

    assert paths == ["/api/v1/health"]
    for word in ("expected", "baseline", "comparable", "snapshot"):
        assert not [p for p in paths if word in p]


def test_no_worker_task_and_no_scheduler_was_added() -> None:
    assert not any(
        "expected" in path.read_text(encoding="utf-8").lower() for path in WORKER_DIR.glob("*.py")
    )
    tasks = (WORKER_DIR / "tasks.py").read_text(encoding="utf-8")
    assert tasks.count("@app.task") == 1  # still only the Gate 0 heartbeat


def test_the_expected_service_does_not_depend_on_the_web_framework() -> None:
    code = (
        "import sys, app.modules.intelligence.expected.service; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )

    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert output.stdout.strip() == "[]"


def test_no_dependency_was_added_for_gate_4() -> None:
    """Only the standard library, SQLAlchemy and the app itself are imported: no numpy, pandas,
    scipy or scikit-learn for a median and two quartiles."""
    allowed_roots = {"app", "sqlalchemy", "__future__"}
    stdlib = set(sys.stdlib_module_names)
    for path in PACKAGE_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] in stdlib | allowed_roots, (path.name, module)


def test_the_dependency_manifests_do_not_mention_scientific_libraries() -> None:
    for manifest in PYPROJECTS:
        text = manifest.read_text(encoding="utf-8").lower()
        for library in ("numpy", "pandas", "scipy", "scikit", "sklearn", "statsmodels"):
            assert library not in text, (manifest.name, library)


def test_the_engine_reads_no_clock_and_takes_no_time_input() -> None:
    """Expected is a function of stored snapshots: no `now`; the same input, the same result."""
    for path in PACKAGE_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert (
            "datetime.now" not in source and "utcnow" not in source and "date.today" not in source
        )
