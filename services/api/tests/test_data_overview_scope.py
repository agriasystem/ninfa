"""Dati overview: architectural guards, enforced on the source (AST), not by convention.

Dati is a deterministic, read-only projection. These tests keep it that way: no language-model
code, no float arithmetic on a business figure, no write, no clock. They scan the whole Dati
module tree and its API package, so a future edit that breaks a rule fails here rather than in
production.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
DATI_FILES = sorted(
    [*(APP / "modules" / "data_overview").glob("*.py"), *(APP / "api" / "v1" / "data").glob("*.py")]
)

FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "openai",
    "httpx",
    "requests",
    "urllib3",
    "app.modules.ai",
    "app.api.v1.mia",
}
WRITE_CALLS = {
    "add",
    "add_all",
    "commit",
    "rollback",
    "flush",
    "delete",
    "merge",
    "execute",
    "begin",
}
CLOCK_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("date", "today"), ("time", "time")}


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_the_dati_sources_are_found() -> None:
    names = {path.name for path in DATI_FILES}
    assert {
        "service.py",
        "metrics.py",
        "distribution.py",
        "costs.py",
        "labor.py",
        "router.py",
    } <= names


@pytest.mark.parametrize("path", DATI_FILES, ids=lambda path: path.name)
def test_no_language_model_or_network_import(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        for module in modules:
            assert not any(
                module == root or module.startswith(f"{root}.") for root in FORBIDDEN_IMPORT_ROOTS
            ), f"{path.name} imports {module}: Dati is deterministic and never calls a model or Mia"


@pytest.mark.parametrize("path", DATI_FILES, ids=lambda path: path.name)
def test_no_float_anywhere(path: Path) -> None:
    """A business figure is a `Decimal` (or an int): never a float, not even as an annotation."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Name) and node.id == "float":
            pytest.fail(f"{path.name}:{node.lineno} uses float")
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"{path.name}:{node.lineno} has a float literal")


@pytest.mark.parametrize("path", DATI_FILES, ids=lambda path: path.name)
def test_no_write_call(path: Path) -> None:
    """The projection reads through repositories: it never adds, flushes, commits or executes."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in WRITE_CALLS, (
                f"{path.name}:{node.lineno} calls .{node.func.attr}(): Dati is read-only"
            )


@pytest.mark.parametrize("path", DATI_FILES, ids=lambda path: path.name)
def test_no_clock_is_read(path: Path) -> None:
    """The analysis day is passed explicitly: 'today' is the property's, never the server's."""
    for node in ast.walk(_tree(path)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and (node.func.value.id, node.func.attr) in CLOCK_CALLS
        ):
            pytest.fail(f"{path.name}:{node.lineno} reads the clock")


def test_the_router_resolves_the_property_scope_dependency() -> None:
    """Authorization is the shared dependency, never re-implemented by a route."""
    source = (APP / "api" / "v1" / "data" / "router.py").read_text(encoding="utf-8")
    assert "resolve_property_scope" in source
    assert "get_language_model_provider" not in source
