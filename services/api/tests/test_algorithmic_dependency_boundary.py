"""Smart Import V4.1: ONE new library, and the four that were measured and left out (ADR 0056).

The earlier scope guards forbid fuzzy-matching and scientific libraries in the manifests. V4.1 makes
one exception on purpose - RapidFuzz, at run time, in one module - and this file is the precise
guard of it. SciPy (global assignment), DuckDB and CleverCSV (CSV dialect sniffers) and fsspec (what
DuckDB needs to read from memory) were built, measured over 1,026 documents and removed because they
bought nothing the default engine needs; they are declared nowhere and imported by nothing, so that
running NINFA never depends on them and nobody re-adds them by accident without reading the report.
"""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

API = Path(__file__).resolve().parents[1]
APP = API / "app"
PACKAGE = APP / "modules" / "data_sources" / "algorithmic"
PYPROJECT = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))

# the one library V4 adds, and the one module that imports it (at module level)
RUNTIME = "rapidfuzz"
HOME = "header.py"
# measured, not adopted
EVALUATED_AND_LEFT_OUT = {"scipy", "numpy", "duckdb", "clevercsv", "fsspec"}


def _names(entries: list[str]) -> set[str]:
    out = set()
    for entry in entries:
        name = entry.split(";")[0]
        for separator in ("[", ">", "<", "=", "~", " "):
            name = name.split(separator)[0]
        out.add(name.lower())
    return out


def _declared() -> set[str]:
    declared = _names(PYPROJECT["project"]["dependencies"])
    for entries in PYPROJECT.get("dependency-groups", {}).values():
        declared |= _names([e for e in entries if isinstance(e, str)])
    for entries in PYPROJECT["project"].get("optional-dependencies", {}).values():
        declared |= _names(entries)
    return declared


def test_rapidfuzz_is_the_runtime_dependency_v4_adds() -> None:
    assert RUNTIME in _names(PYPROJECT["project"]["dependencies"])


def test_the_libraries_that_were_measured_and_left_out_are_declared_nowhere() -> None:
    assert not EVALUATED_AND_LEFT_OUT & _declared()


def _imports(path: Path) -> list[tuple[str, bool]]:
    """(root module, at module level) of every import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {id(node) for node in tree.body}
    found: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name.split(".")[0], id(node) in top) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.module.split(".")[0], id(node) in top))
    return found


def test_rapidfuzz_is_imported_by_exactly_one_module() -> None:
    importers = [
        path
        for path in sorted(APP.rglob("*.py"))
        if any(root == RUNTIME for root, _top in _imports(path))
    ]

    assert importers == [PACKAGE / HOME]


def test_no_module_of_the_app_imports_a_library_that_was_left_out() -> None:
    for path in sorted(APP.rglob("*.py")):
        for root, _top in _imports(path):
            assert root not in EVALUATED_AND_LEFT_OUT, f"{root} imported by {path}"


def test_the_production_process_loads_none_of_them() -> None:
    """Importing the app (its routes, its understanding, its V4 engine) loads none of the libraries
    that were left out, whatever happens to be installed on the machine."""
    script = (
        "import sys\n"
        "import app.main\n"
        "from app.modules.data_sources.algorithmic import selector\n"
        "with selector.use_engine('v4'):\n"
        "    import app.modules.data_sources.understanding\n"
        "watched = ('scipy', 'duckdb', 'fsspec', 'clevercsv')\n"
        "loaded = sorted(m for m in watched if m in sys.modules)\n"
        "print('LOADED', loaded)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=API, capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "LOADED []" in result.stdout, result.stdout


def test_the_dialect_hook_and_the_assignment_are_gone_from_the_production_code() -> None:
    """The second opinion on a CSV delimiter and the global assignment were removed: V3's reader is
    the only one, and the selection is V3's greedy pick over V4's evidence."""
    from app.modules.document_understanding import grid

    assert not hasattr(grid, "delimiter_refiner")
    assert not (PACKAGE / "assignment.py").exists()
    assert not (PACKAGE / "dialect.py").exists()
