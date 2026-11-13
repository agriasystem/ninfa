"""The AI layer of Smart Import is a PORT, not a vendor.

`ImportUnderstandingProvider` is the one seam; the business logic around it - the resolver, the
egress gate, the validator, the evidence builder, and everything that reads a file - knows nothing
of any vendor and can reach no network by itself. Only the adapter file may import an SDK, and
nothing else under `app/modules` may import a library that talks to the network at all, so that "AI
off" is a property of the code and not only of a setting. Enforced by parsing the real source files.
"""

import ast
from pathlib import Path

import pytest

from app.core.config import Settings
from app.modules.ai.gateway.factory import build_import_understanding_resolver
from app.modules.ai.import_understanding.resolver import ImportUnderstandingProvider

_APP = Path(__file__).resolve().parents[1] / "app"
_MODULES = _APP / "modules"
_GATEWAY = _MODULES / "ai" / "gateway"
# Each adapter may import ITS OWN vendor SDK and no other: a second vendor never rides in through
# the adapter of the first.
_ADAPTERS = {
    _GATEWAY / "anthropic_provider.py": frozenset({"anthropic"}),
    _GATEWAY / "openai_provider.py": frozenset({"openai"}),
}
# Everything that can open a connection, directly or through a vendor SDK. (`http` itself holds
# status constants that are harmless: only its client and server modules count.)
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
_CORE = [
    _MODULES / "ai" / "import_understanding",
    _MODULES / "data_sources",
    _MODULES / "document_understanding",
]


def _imports(path: Path) -> set[str]:
    """Every module the file imports, by its full dotted name (and its top-level package)."""
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
    return sorted(directory.rglob("*.py"))


@pytest.mark.parametrize("directory", _CORE, ids=lambda d: d.name)
def test_the_core_of_smart_import_imports_no_library_that_can_reach_the_network(
    directory: Path,
) -> None:
    offenders = {
        str(path.relative_to(_APP)): sorted(_imports(path) & _NETWORK)
        for path in _files(directory)
        if _imports(path) & _NETWORK
    }

    assert offenders == {}


def test_only_the_adapter_files_import_a_vendor_sdk_anywhere_under_the_modules() -> None:
    vendors = {"anthropic", "openai", "mistralai", "cohere", "google"}
    offenders = [
        str(path.relative_to(_APP))
        for path in _files(_MODULES)
        if path not in _ADAPTERS and _imports(path) & vendors
    ]

    assert offenders == []


@pytest.mark.parametrize("adapter", sorted(_ADAPTERS), ids=lambda p: p.stem)
def test_an_adapter_imports_its_own_vendor_and_no_other(adapter: Path) -> None:
    vendors = {"anthropic", "openai", "mistralai", "cohere", "google"}

    assert adapter.exists()
    assert _imports(adapter) & vendors == _ADAPTERS[adapter]


def test_the_port_imports_no_vendor() -> None:
    port = _MODULES / "ai" / "import_understanding" / "resolver.py"

    assert ImportUnderstandingProvider.__module__.endswith("import_understanding.resolver")
    assert not _imports(port) & {"anthropic", "openai", "mistralai", "cohere", "google"}
    # ...and nothing of the egress gate or the evidence knows a vendor either
    for name in ("egress.py", "sanitize.py", "validator.py", "prompt.py", "types.py"):
        assert not _imports(port.with_name(name)) & _NETWORK, name


def test_an_unconfigured_provider_builds_a_resolver_with_nothing_inside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.ai.gateway import anthropic_provider

    def must_not_be_built(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a vendor client was built although no provider is selected")

    monkeypatch.setattr(
        anthropic_provider, "AnthropicImportUnderstandingProvider", must_not_be_built
    )
    monkeypatch.setattr(
        "app.modules.ai.gateway.factory.AnthropicImportUnderstandingProvider", must_not_be_built
    )
    settings = Settings(_env_file=None)

    resolver = build_import_understanding_resolver(settings)

    assert settings.import_understanding_provider == "unconfigured"
    assert resolver.enabled is False and resolver._provider is None


def test_the_default_provider_is_unconfigured() -> None:
    field = Settings.model_fields["import_understanding_provider"]

    assert field.default == "unconfigured"
