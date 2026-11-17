"""Mia's boundaries, enforced by reading the real source files (like `test_ai_boundary.py`).

* Mia's core and her tools can reach no network and no vendor: only the gateway adapter talks to a
  provider, and even it imports no SDK of its own - the client, the failure vocabulary and the retry
  rule come from the ONE file that imports `openai`, so the key, the endpoint, the data residency
  and the timeout are decided once for the whole account.
* Mia is read-only: nothing under `ai/mia` (besides the person's own conversation) imports a write
  path of NINFA - no Decision Engine `sync`, no `PriorityService`, no analysis run, no import - and
  no tool module calls anything that writes through a session.
* Smart Import and Mia stay separate: neither imports the other's business logic."""

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
_MODULES = _APP / "modules"
_MIA = _MODULES / "ai" / "mia"
_GATEWAY = _MODULES / "ai" / "gateway"
_SMART_IMPORT = [
    _MODULES / "ai" / "import_understanding",
    _MODULES / "data_sources",
    _MODULES / "document_understanding",
]

_NETWORK = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "mistralai",
        "cohere",
        "httpx",
        "httpx2",
        "requests",
        "urllib3",
        "aiohttp",
        "socket",
        "smtplib",
        "ftplib",
        "websockets",
        "http.client",
        "http.server",
        "urllib.request",
    }
)

# What would let Mia change NINFA: the Decision Engine's write path, the analysis run, an import.
_WRITE_PATHS = (
    "app.modules.decisions.service",
    "app.modules.intelligence.priority.service",
    "app.modules.analysis.run",
    "app.modules.analysis.service",
    "app.modules.ingestion.canonical_csv",
    "app.modules.snapshots.service",
    "app.worker",
)
# `DataSourcesService` is the service the Struttura screens read through; it also holds the import
# and the switch-off. Mia may call these methods of it and no other.
_READ_ONLY_DATA_SOURCES = frozenset({"overview", "remembered_answers", "saved_configuration"})
_WRITE_CALLS = frozenset(
    {"add", "add_all", "commit", "flush", "delete", "merge", "bulk_save_objects"}
)
# the ONE place that may write: the person's own conversation
_MAY_WRITE = frozenset({"conversation.py"})


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module)
            found.add(node.module.split(".")[0])
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _files(_MIA), ids=lambda p: str(p.relative_to(_MIA)))
def test_mia_imports_no_network_library_and_no_vendor_sdk(path: Path) -> None:
    assert _imports(path) & _NETWORK == set(), path.name


def test_the_mia_adapter_imports_no_sdk_of_its_own() -> None:
    adapter = _GATEWAY / "mia_openai_provider.py"

    imported = _imports(adapter)

    assert "openai" not in imported, "the SDK is imported by openai_provider.py alone"
    assert "anthropic" not in imported
    # what it does use of the account's shared plumbing
    assert "app.modules.ai.gateway.openai_provider" in imported


def test_the_neutral_tool_protocol_names_no_vendor() -> None:
    assert _imports(_GATEWAY / "tool_protocol.py") & _NETWORK == set()


def test_only_the_shared_openai_file_builds_the_client() -> None:
    sources = {p.name: p.read_text(encoding="utf-8") for p in _files(_GATEWAY)}

    holders = [name for name, text in sources.items() if "OpenAI(" in text]

    assert holders == ["openai_provider.py"]


@pytest.mark.parametrize("path", _files(_MIA), ids=lambda p: str(p.relative_to(_MIA)))
def test_mia_imports_no_write_path_of_ninfa(path: Path) -> None:
    imported = _imports(path)
    offending = {name for name in imported if name.startswith(_WRITE_PATHS)}

    assert not offending, (path.name, offending)


@pytest.mark.parametrize(
    "path",
    [p for p in _files(_MIA) if p.name not in _MAY_WRITE and p.name != "models.py"],
    ids=lambda p: str(p.relative_to(_MIA)),
)
def test_no_module_of_mia_writes_through_a_session_except_the_conversation(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    writes: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _WRITE_CALLS
        ):
            owner = ast.unparse(node.func.value)
            if "session" in owner.lower():
                writes.append(f"{owner}.{node.func.attr}")
    assert writes == [], (path.name, writes)


@pytest.mark.parametrize("path", _files(_MIA), ids=lambda p: str(p.relative_to(_MIA)))
def test_mia_does_not_import_a_smart_import_decision_path(path: Path) -> None:
    """Smart Import and Mia do not share business logic: Mia may read what an import left behind
    (through the repositories and the services that describe it), never reach into the layer that
    reads a file or talks to a model about one."""
    forbidden = (
        "app.modules.ai.import_understanding",
        "app.modules.document_understanding",
        "app.modules.data_sources.understanding",
        "app.modules.data_sources.smart_import",
    )
    # The deliberate exceptions, all pure and vendor-free: text hygiene that a file name, a source
    # name or a remembered word must go through before a model reads it (the SAME rules Smart Import
    # applies to a cell, so there are not two definitions of "personal data"), and the vocabulary
    # of the questions Smart Import asks (an enum Mia explains).
    shared = (
        "app.modules.ai.import_understanding.sanitize",
        "app.modules.document_understanding.personal_shapes",
        "app.modules.document_understanding.redaction",
        "app.modules.data_sources.understanding_types",
    )
    imported = _imports(path)

    offending = {
        name for name in imported if name.startswith(forbidden) and not name.startswith(shared)
    }

    assert not offending, (path.name, offending)


@pytest.mark.parametrize("directory", _SMART_IMPORT, ids=lambda d: d.name)
def test_smart_import_does_not_import_mia(directory: Path) -> None:
    for path in _files(directory):
        offending = {name for name in _imports(path) if name.startswith("app.modules.ai.mia")}
        assert not offending, (path.name, offending)


def test_the_two_model_layers_have_their_own_switches() -> None:
    from app.core.config import Settings

    fields = Settings.model_fields

    assert "mia_provider" in fields and "smart_import_ai_mode" in fields
    assert fields["mia_provider"].default == "unconfigured"
    assert fields["smart_import_ai_mode"].default == "off"
    # Mia's model and timeout are her own; the key, endpoint and residency are the account's
    assert "mia_openai_model" in fields and "smart_import_openai_model" in fields
    assert "openai_api_key" in fields and "mia_openai_api_key" not in fields


def test_the_only_data_sources_service_methods_mia_calls_are_reads() -> None:
    called: dict[str, set[str]] = {}
    for path in _files(_MIA):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            owner = ast.unparse(node.func.value)
            if owner == "service" or owner.startswith("DataSourcesService("):
                called.setdefault(path.name, set()).add(node.func.attr)

    for name, methods in called.items():
        assert methods <= _READ_ONLY_DATA_SOURCES, (name, methods - _READ_ONLY_DATA_SOURCES)
    assert called, "the scan found no use of DataSourcesService: the test is out of date"
