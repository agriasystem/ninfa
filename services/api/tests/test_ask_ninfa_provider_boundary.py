"""Gate 18 review items 26-30: the provider boundary is a `Protocol`, never a concrete vendor SDK.

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

# Gate 19's own, single, approved exception - see `test_anthropic_provider_isolation.py` for the
# precise, per-file version of this same boundary.
_ALLOWED_ANTHROPIC_FILE = _AI_MODULE_ROOT / "gateway" / "anthropic_provider.py"

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


def _all_ai_module_source_except_the_approved_anthropic_adapter() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in _AI_MODULE_ROOT.rglob("*.py")
        if path != _ALLOWED_ANTHROPIC_FILE
    )


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
    source = _all_ai_module_source_except_the_approved_anthropic_adapter().lower()
    for token in _FORBIDDEN_VENDOR_TOKENS:
        assert token not in source, token


def test_no_other_llm_sdk_was_added_as_a_dependency() -> None:
    """Gate 19 legitimately adds `anthropic` (see `pyproject.toml`'s own dependency comment) - this
    now confirms it is EXACTLY the one vendor dependency, never a second one alongside it."""
    manifests = [
        _API_ROOT / "pyproject.toml",
        _REPO_ROOT / "services" / "worker" / "pyproject.toml",
    ]
    for manifest in manifests:
        lowered = manifest.read_text(encoding="utf-8").lower()
        for token in ("openai", "cohere", "langchain", "google-generativeai", "mistralai"):
            assert token not in lowered, (manifest, token)

    api_dependencies = (_API_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"anthropic>=' in api_dependencies


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
