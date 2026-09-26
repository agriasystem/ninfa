"""Recommendation Engine V1 boundary (review items 18-23, plus the AI/mutation/UI scope this
gate's own spec rules out entirely). AST-based, not substring-based - the module's own docstrings
explain several of these exclusions in prose, which a plain grep would otherwise false-positive
on (see every other gate's own `test_*_scope.py` for the same reasoning).
"""

import ast
from pathlib import Path

import pytest

import app.modules.recommendations as recommendations_package

PACKAGE_DIR = Path(recommendations_package.__file__).parent
SOURCES = sorted(PACKAGE_DIR.glob("*.py"))

# --- 18-20: no raw operational row dependency ----------------------------------------------------

FORBIDDEN_MODELS = {
    "Booking",
    "BookingImportRow",
    "Invoice",
    "InvoiceLine",
    "InvoiceImportRow",
    "LaborEntry",
    "LaborImportRow",
    "LaborSnapshot",
    "BookingSnapshot",
    "RoomInventoryDaily",
}

# --- 21-23: no detector/PriorityService/Expected service import ----------------------------------

FORBIDDEN_SERVICES = {
    "RevenueDecisionService",
    "CostDecisionService",
    "LaborDecisionService",
    "OtaDependencyService",
    "DemandForecastService",
    "PriorityService",
    "BookingExpectedService",
}

FORBIDDEN_AI = {
    "openai",
    "anthropic",
    "langchain",
    "llm",
    "embedding",
    "vectordb",
}


def _identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.rsplit(".", 1)[-1])
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return names


def _module_names(path: Path) -> set[str]:
    """Every dotted module path this file imports FROM, in full (not just the last segment) -
    used to catch `app.modules.bookings.models`/`app.modules.invoices.models`/etc. regardless of
    which specific names were imported from them."""
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


FORBIDDEN_ROW_MODULES = {
    "app.modules.bookings.models",
    "app.modules.invoices.models",
    "app.modules.labor.models",
    "app.modules.snapshots.models",
}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_raw_operational_row_dependency(path: Path) -> None:
    assert not (_identifiers(path) & FORBIDDEN_MODELS), path.name
    assert not (_module_names(path) & FORBIDDEN_ROW_MODULES), path.name


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_detector_priority_or_expected_service_import(path: Path) -> None:
    assert not (_identifiers(path) & FORBIDDEN_SERVICES), path.name


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_ai_ml_dependency(path: Path) -> None:
    lowered = {name.lower() for name in _identifiers(path)}
    assert not (lowered & FORBIDDEN_AI), path.name


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_database_session_import_or_type_anywhere(path: Path) -> None:
    """Pure/testable, no DB session in the engine (AST-based: a docstring merely EXPLAINING the
    absence of a session, in prose, must never fail this)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            imported_names.update(alias.asname or alias.name for alias in node.names)
    assert "Session" not in imported_names, path.name


def test_no_mutation_or_execution_vocabulary_anywhere() -> None:
    """Structural scope guard: no code in this package ever names an autonomous-execution
    concept, even as an identifier - not just absent from the API surface."""
    forbidden = {
        "acknowledge",
        "dismiss",
        "snooze",
        "assign",
        "autoapply",
        "execute",
        "approvedbydefault",
    }
    for path in SOURCES:
        identifiers = {name.lower().replace("_", "") for name in _identifiers(path)}
        assert not (identifiers & forbidden), path.name
