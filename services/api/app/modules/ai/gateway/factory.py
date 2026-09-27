"""Explicit provider selection - never "if a key happens to exist, silently choose a vendor" (see
ADR 0025, "why provider selection is explicit"). `Settings.ask_ninfa_provider` is the ONLY input;
`Settings`'s own validator (`app.core.config._check_ask_ninfa_provider_configuration`) already
guarantees `anthropic_api_key` is set whenever `ask_ninfa_provider == "anthropic"`, so this factory
never has to fail closed itself - by the time it runs, `Settings()` construction would already have
raised if the configuration were invalid.
"""

from typing import assert_never

from app.core.config import Settings
from app.modules.ai.gateway.anthropic_provider import AnthropicLanguageModelProvider
from app.modules.ai.gateway.protocol import LanguageModelProvider
from app.modules.ai.gateway.unconfigured import UnconfiguredLanguageModelProvider


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


__all__ = ["build_language_model_provider"]
