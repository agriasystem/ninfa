"""Gate 18 review items 26-30: the provider boundary is a `Protocol`, never a concrete vendor SDK.

**Update (Smart Import OpenAI Intelligence V1):** a SECOND vendor, `openai`, is now a deliberate
dependency of Smart Import's semantic layer, isolated the same way - to exactly ONE adapter file
(`app/modules/ai/gateway/openai_provider.py`), named only by the composition root (`factory.py`),
which has to name it and read its settings. Everything below still holds for every OTHER vendor and
for every other file: the scans exclude the two adapters, let `factory.py` say `openai`, and still
refuse any third vendor anywhere. `test_ai_boundary.py` is the per-file, per-import version.

Mirrors `test_recommendation_scope.py`'s own philosophy (Gate 16: "not by convention, by
construction") - a source scan of every real file under `app/modules/ai/`, not a naming convention
a future contributor could quietly violate.

**Update (Gate 19):** `anthropic` is now a real, deliberate dependency, isolated to exactly ONE
file (`app/modules/ai/gateway/anthropic_provider.py`) - the scans below exclude that one file (and
now confirm the SDK IS declared, exactly once) rather than asserting zero mention of any vendor at
all. `test_anthropic_provider_isolation.py` is the precise, per-file version of the same claim;
this file keeps the narrower, still-true one that predates it (the same "superseded but not wrong"
relationship `test_decision_api_scope.py` already has with `test_auth_scope.py`).
"""

import dataclasses
import inspect
from pathlib import Path

from app.modules.ai.ask_ninfa.service import AskNinfaService
from app.modules.ai.ask_ninfa.types import AskDecisionContext, AskResult
from app.modules.ai.gateway.protocol import LanguageModelProvider
from app.modules.ai.gateway.unconfigured import UnconfiguredLanguageModelProvider
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider

# services/api/tests/test_ask_ninfa_provider_boundary.py -> services/api/ -> app/modules/ai
_API_ROOT = Path(__file__).resolve().parents[1]
_AI_MODULE_ROOT = _API_ROOT / "app" / "modules" / "ai"
_REPO_ROOT = _API_ROOT.parents[1]

# The two approved adapters (Gate 19's anthropic, and the OpenAI semantic layer's openai) - see
# `test_ai_boundary.py` for the precise, per-file version of this same boundary.
_ALLOWED_ANTHROPIC_FILE = _AI_MODULE_ROOT / "gateway" / "anthropic_provider.py"
_ALLOWED_OPENAI_FILE = _AI_MODULE_ROOT / "gateway" / "openai_provider.py"
# The composition root names the adapters it builds and reads their settings: it, and only it, may
# say `openai` (it already names `AnthropicLanguageModelProvider`).
_COMPOSITION_ROOT = _AI_MODULE_ROOT / "gateway" / "factory.py"

_FORBIDDEN_VENDOR_TOKENS = (
    "openai",
    "gpt-",
    "cohere",
    "mistralai",
    "google.generativeai",
    "genai",
    "vertexai",
    "bedrock",
    "huggingface",
    "langchain",
    "llama_index",
)


def _forbidden_in(path: Path) -> tuple[str, ...]:
    if path == _COMPOSITION_ROOT:
        return tuple(token for token in _FORBIDDEN_VENDOR_TOKENS if token != "openai")
    return _FORBIDDEN_VENDOR_TOKENS


# --- 26: AskNinfaService depends on the protocol, structurally -----------------------------------


def test_26_ask_ninfa_service_is_typed_against_the_protocol_not_a_concrete_sdk() -> None:
    signature = inspect.signature(AskNinfaService.__init__)
    annotation = signature.parameters["provider"].annotation
    assert annotation is LanguageModelProvider


def test_26_both_the_production_and_fake_provider_satisfy_the_same_protocol() -> None:
    real: LanguageModelProvider = UnconfiguredLanguageModelProvider()
    fake: LanguageModelProvider = DeterministicFakeLanguageModelProvider()
    assert hasattr(real, "generate")
    assert hasattr(fake, "generate")


# --- 27-29: no vendor SDK import, no vendor identifier, anywhere under app/modules/ai -------------


def test_27_28_29_no_vendor_sdk_import_or_identifier_anywhere_under_ai_module() -> None:
    """No OTHER vendor SDK/identifier exists anywhere under `app/modules/ai/` (`openai`, `cohere`,
    etc.). Whether `anthropic` ITSELF is imported only from the one approved adapter file is
    checked precisely, per real `ast`-parsed import (never a brittle text scan that a legitimate
    cross-reference - e.g. `factory.py` naming the `AnthropicLanguageModelProvider` class, or a
    docstring discussing the `ask_ninfa_provider == "anthropic"` config value - could trip), by
    `test_anthropic_provider_isolation.py` instead."""
    for path in _AI_MODULE_ROOT.rglob("*.py"):
        if path in (_ALLOWED_ANTHROPIC_FILE, _ALLOWED_OPENAI_FILE):
            continue
        source = path.read_text(encoding="utf-8").lower()
        for token in _forbidden_in(path):
            assert token not in source, (path.name, token)


def test_no_other_llm_sdk_was_added_as_a_dependency() -> None:
    """Gate 19 legitimately adds `anthropic` and the semantic layer `openai`: these are
    EXACTLY the two vendor dependencies of the API (the worker has none), never a third."""
    worker = _REPO_ROOT / "services" / "worker" / "pyproject.toml"
    assert "openai" not in worker.read_text(encoding="utf-8").lower()
    for manifest in (_API_ROOT / "pyproject.toml", worker):
        lowered = manifest.read_text(encoding="utf-8").lower()
        for token in ("cohere", "langchain", "google-generativeai", "mistralai"):
            assert token not in lowered, (manifest, token)

    api_dependencies = (_API_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"anthropic>=' in api_dependencies
    assert '"openai>=' in api_dependencies


# --- 30: no provider-specific type leaks into the domain shape -----------------------------------


def test_30_domain_types_never_reference_the_provider_wire_shape() -> None:
    """`AskDecisionContext`/`AskResult` are the domain's OWN vocabulary - neither one is, or
    contains, a `LanguageModelRequest`/`LanguageModelAnswer` (the gateway's wire shape). The
    boundary between "what Ask NINFA is about" and "what a provider call looks like" is real, not
    just naming."""
    domain_field_types = {f.type for f in dataclasses.fields(AskDecisionContext)} | {
        f.type for f in dataclasses.fields(AskResult)
    }
    for field_type in domain_field_types:
        text = str(field_type)
        assert "LanguageModel" not in text
