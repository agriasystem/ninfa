"""Gate 21B requirement: the pilot CLI's production orchestration must never import a test
module - test helpers may exercise the path, but must never BE the path (see
docs/architecture/pilot-readiness-v1.md, "Production path only")."""

from pathlib import Path

import pytest

_CLI_MODULES = ["_support.py", "pilot.py", "imports.py", "analysis.py"]
_CLI_DIR = Path(__file__).resolve().parents[1] / "app" / "cli"


@pytest.mark.parametrize("filename", _CLI_MODULES)
def test_pilot_cli_module_never_imports_from_tests(filename: str) -> None:
    source = (_CLI_DIR / filename).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import tests") or stripped.startswith("from tests"):
            pytest.fail(f"{filename} imports a test module: {stripped!r}")
