"""Smart Import V4.1: the new dependencies are few, isolated, and mostly not shipped (ADR 0056).

The earlier scope guards forbid fuzzy-matching and scientific libraries in the manifests. V4.1 adds
exceptions on purpose - RapidFuzz at run time; SciPy (with NumPy), DuckDB, CleverCSV and fsspec for
development only, because the benchmark measured them as worth nothing the default engine needs -
and
this file is the precise guard of those exceptions: which manifest section holds each, which ONE
module imports each, and that the production process never loads the development ones.
"""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

API = Path(__file__).resolve().parents[1]
PACKAGE = API / "app" / "modules" / "data_sources" / "algorithmic"
APP = API / "app"
PYPROJECT = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))

RUNTIME = {"rapidfuzz"}
DEVELOPMENT = {"scipy", "duckdb", "clevercsv", "fsspec"}
# the one module that may import each, and whether the import must sit inside a function
HOME = {
    "rapidfuzz": ("header.py", False),
    "scipy": ("assignment.py", True),
    "numpy": ("assignment.py", True),
    "duckdb": ("dialect.py", True),
    "fsspec": ("dialect.py", True),
    "clevercsv": ("dialect.py", True),
}


def _names(entries: list[str]) -> set[str]:
    out = set()
    for entry in entries:
        name = entry.split(";")[0]
        for separator in ("[", ">", "<", "=", "~", " "):
            name = name.split(separator)[0]
        out.add(name.lower())
    return out


def test_only_rapidfuzz_is_a_runtime_dependency_of_v4() -> None:
    runtime = _names(PYPROJECT["project"]["dependencies"])

    assert runtime >= RUNTIME
    assert not (DEVELOPMENT | {"numpy"}) & runtime  # none of the development ones ships


def test_the_development_ones_are_in_the_development_group() -> None:
    development = _names(PYPROJECT["dependency-groups"]["dev"])

    assert development >= DEVELOPMENT


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


def test_each_library_is_imported_by_exactly_one_module_and_the_lazy_ones_inside_a_function() -> (
    None
):
    for path in sorted(APP.rglob("*.py")):
        for root, at_top in _imports(path):
            if root not in HOME:
                continue
            home, lazy = HOME[root]
            assert path.name == home and path.parent == PACKAGE, f"{root} imported by {path}"
            assert not (lazy and at_top), f"{root} must be imported inside a function in {path}"


def test_every_library_is_still_imported_where_it_belongs() -> None:
    seen = {root for path in PACKAGE.glob("*.py") for root, _top in _imports(path)}

    assert set(HOME) <= seen


def test_the_production_process_loads_no_development_library() -> None:
    """Importing the app (its routes, its understanding, its V4 engine) must not load SciPy, DuckDB,
    fsspec or CleverCSV: they are not installed in production, and the code that wants them asks for
    them only when a configuration that needs them is selected. (NumPy is not checked: RapidFuzz
    uses it when it happens to be installed, which is a fact about the machine, not about NINFA.)"""
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


def test_the_default_engine_never_needs_a_development_library() -> None:
    from app.modules.data_sources.algorithmic.engine import DEFAULT

    assert DEFAULT.assignment is False  # greedy over V4's evidence: no SciPy
