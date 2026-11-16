"""Explicit provider selection - never "if a key happens to exist, silently choose a vendor" (see
ADR 0025, "why provider selection is explicit"). `Settings.ask_ninfa_provider` is the ONLY input;
`Settings`'s own validator (`app.core.config._check_ask_ninfa_provider_configuration`) already
guarantees `anthropic_api_key` is set whenever `ask_ninfa_provider == "anthropic"`, so this factory
never has to fail closed itself - by the time it runs, `Settings()` construction would already have
raised if the configuration were invalid.
"""

import logging
from typing import assert_never

from app.core.config import Settings
from app.modules.ai.gateway.anthropic_provider import (
    AnthropicImportUnderstandingProvider,
    AnthropicLanguageModelProvider,
)
from app.modules.ai.gateway.protocol import LanguageModelProvider
from app.modules.ai.gateway.unconfigured import UnconfiguredLanguageModelProvider
from app.modules.ai.import_understanding.resolver import (
    ImportUnderstandingProvider,
    ImportUnderstandingResolver,
)
from app.modules.ai.import_understanding.types import AiMode

logger = logging.getLogger(__name__)


def build_language_model_provider(settings: Settings) -> LanguageModelProvider:
    """Called ONCE, when the app is built (`create_app()`) - never per-request, so a real
    `AnthropicLanguageModelProvider` (and the `anthropic.Anthropic` HTTP client it owns) is
    constructed a single time per app instance, never leaked as a process-wide global either."""
    provider = settings.ask_ninfa_provider
    if provider == "unconfigured":
        return UnconfiguredLanguageModelProvider()
    if provider == "anthropic":
        assert settings.anthropic_api_key is not None  # guaranteed by Settings' own validator
        return AnthropicLanguageModelProvider(api_key=settings.anthropic_api_key.get_secret_value())
    assert_never(provider)


def build_import_understanding_resolver(settings: Settings) -> ImportUnderstandingResolver:
    """The optional assistant of Smart Import V3, built ONCE when the app is built. With the
    provider `unconfigured` - the default - the resolver has no provider at all: it asks nothing,
    sends nothing anywhere, and Smart Import reads files exactly as it does without it."""
    provider: ImportUnderstandingProvider | None = None
    selected = settings.import_understanding_provider
    if selected == "anthropic":
        assert settings.anthropic_api_key is not None  # guaranteed by Settings' own validator
        provider = AnthropicImportUnderstandingProvider(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
    elif selected != "unconfigured":
        assert_never(selected)
    if provider is not None:
        return ImportUnderstandingResolver(provider)
    return _build_semantic_resolver(settings)


def _build_semantic_resolver(settings: Settings) -> ImportUnderstandingResolver:
    """The OpenAI semantic layer, selected by `SMART_IMPORT_AI_MODE` alone. `off` builds a resolver
    with nothing inside (and imports nothing of the vendor). A mode that needs a key it does not
    have builds the same: Smart Import must never break because a model is unavailable."""
    mode = AiMode(settings.smart_import_ai_mode)
    if mode == AiMode.OFF:
        return ImportUnderstandingResolver(None, AiMode.OFF)
    key = settings.openai_api_key
    if key is None or not key.get_secret_value().strip():
        logger.warning(
            "SMART_IMPORT_AI_MODE=%s but OPENAI_API_KEY is not set: Smart Import runs without a "
            "model, exactly as with SMART_IMPORT_AI_MODE=off",
            mode.value,
        )
        return ImportUnderstandingResolver(None, mode)
    # imported here, not at the top: a process that never selects the mode never loads the SDK
    from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider

    provider = OpenAIImportUnderstandingProvider(
        key.get_secret_value(),
        model=settings.smart_import_openai_model,
        reasoning_effort=settings.smart_import_openai_reasoning,
        base_url=settings.openai_base_url,
        data_residency=settings.openai_data_residency,
        timeout_seconds=settings.smart_import_openai_timeout_seconds,
    )
    return ImportUnderstandingResolver(
        provider,
        mode,
        corroborate=True,  # the semantic layer (it also reads the columns the rules placed unsure)
        # ...but a model's reading is certain only if this is turned ON, and it is OFF by default:
        # the live benchmark found three unsafe READY with it on (ADR 0052)
        vocabulary_certainty=settings.smart_import_ai_vocabulary_certainty,
        provider_name="openai",
        model=settings.smart_import_openai_model,
    )


__all__ = ["build_import_understanding_resolver", "build_language_model_provider"]
