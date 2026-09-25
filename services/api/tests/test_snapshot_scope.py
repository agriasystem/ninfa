"""Gate 3 scope guards: what must NOT exist, and the observation/reconstruction separation in code.

No public API, no scheduler, no worker task, no dependency on the web framework, no analytics
vocabulary (pickup, forecast, expected, alert, ...), and no way for one origin's code path to
produce the other origin's rows.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.modules.snapshots as snapshots_package
from app.modules.snapshots.models import SnapshotOrigin

PACKAGE_DIR = Path(snapshots_package.__file__).parent
WORKER_DIR = Path(__file__).resolve().parents[2] / "worker" / "worker"
FORBIDDEN_WORDS = (
    "pickup",
    "velocity",
    "trend",
    "forecast",
    "expected",
    "alert",
    "impact",
    "priority",
    "recommendation",
    "decision",
    "narrative",
)


def identifiers(path: Path) -> set[str]:
    """Names a module defines or uses (functions, classes, arguments, variables, attributes)."""
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
    """String literals that are not docstrings."""
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


# --- no API, no worker, no framework ------------------------------------------------------------


def test_the_only_public_endpoint_is_still_the_health_check(client: TestClient) -> None:
    paths = list(client.get("/openapi.json").json()["paths"])

    assert "/api/v1/health" in paths
    for word in ("snapshot", "inventory", "metric", "curve"):
        assert not [p for p in paths if word in p]


def test_no_worker_task_and_no_scheduler_was_added() -> None:
    assert not any(
        "snapshot" in path.read_text(encoding="utf-8").lower() for path in WORKER_DIR.glob("*.py")
    )
    tasks = (WORKER_DIR / "tasks.py").read_text(encoding="utf-8")
    assert tasks.count("@app.task") == 1  # still only the Gate 0 heartbeat
    for name in ("periodic", "cron", "schedule"):
        assert name not in identifiers(WORKER_DIR / "tasks.py")


def test_the_snapshot_services_do_not_depend_on_the_web_framework() -> None:
    code = (
        "import sys, app.modules.snapshots.observed, app.modules.snapshots.reconstruction; "
        "print(sorted(m for m in ('fastapi', 'starlette') if m in sys.modules))"
    )

    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert output.stdout.strip() == "[]"


def test_no_dependency_was_added_for_gate_3() -> None:
    """Only the standard library, Decimal, zoneinfo, SQLAlchemy and the app itself are imported."""
    allowed_roots = {"app", "sqlalchemy", "__future__"}
    stdlib = set(sys.stdlib_module_names)
    for path in PACKAGE_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                root = module.split(".")[0]
                assert root in stdlib | allowed_roots, (path.name, module)


# --- vocabulary ---------------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_analytics_vocabulary_in_the_snapshot_code(path: Path) -> None:
    """Snapshots are BOOKINGS + INVENTORY -> facts. Pickup, forecast, alerts ... are later gates."""
    used = {name.lower() for name in identifiers(path)}
    used |= {value.lower() for value in string_constants(path)}

    found = {word for word in FORBIDDEN_WORDS if any(word in name for name in used)}

    assert found == set(), found


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_a_reconstruction_is_never_called_exact_or_historical_truth(path: Path) -> None:
    tokens = identifiers(path) | string_constants(path)

    assert not {"EXACT", "HISTORICAL_TRUTH", "HISTORICAL", "TRUTH"} & tokens


def test_the_origin_enum_has_exactly_two_values() -> None:
    assert {o.value for o in SnapshotOrigin} == {"OBSERVED", "RECONSTRUCTED_APPROXIMATE"}


# --- observation and reconstruction are separate code paths -------------------------------------


def origin_members(path: Path) -> set[str]:
    return {
        node.attr
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "SnapshotOrigin"
    }


def test_the_observed_service_can_only_produce_observed_rows() -> None:
    assert origin_members(PACKAGE_DIR / "observed.py") == {"OBSERVED"}


def test_the_reconstruction_service_can_only_produce_approximate_rows() -> None:
    assert origin_members(PACKAGE_DIR / "reconstruction.py") == {"RECONSTRUCTED_APPROXIMATE"}
    assert "OBSERVED" not in identifiers(PACKAGE_DIR / "aggregate.py") - {"OBSERVED_STATUSES"}


def test_the_two_services_are_distinct_classes_sharing_only_plumbing() -> None:
    from app.modules.snapshots.common import SnapshotServiceBase
    from app.modules.snapshots.observed import ObservedSnapshotService
    from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService

    assert not issubclass(ObservedSnapshotService, BookingSnapshotReconstructionService)
    assert not issubclass(BookingSnapshotReconstructionService, ObservedSnapshotService)
    assert {name for name in vars(ObservedSnapshotService) if not name.startswith("_")} == {
        "take_snapshot"
    }
    assert {
        name for name in vars(BookingSnapshotReconstructionService) if not name.startswith("_")
    } == {"reconstruct"}
    assert issubclass(ObservedSnapshotService, SnapshotServiceBase)


def test_room_inventory_was_not_added_to_the_property_model() -> None:
    from app.modules.properties.models import Property

    assert "rooms_total" not in Property.__table__.columns
    assert not [c for c in Property.__table__.columns if "room" in c.name]
