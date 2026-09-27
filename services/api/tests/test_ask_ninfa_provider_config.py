"""Gate 19 review items 1-8: `Settings`' own Ask NINFA provider configuration - explicit selection,
fail-closed on a missing key, and a secret that never renders anywhere.

Mirrors `test_api_config.py`'s own `make_settings()`/`pytest.raises(ValidationError, ...)` pattern
exactly - a Gate 19-specific file, never edits to the Gate 12/13 file itself.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.ai.gateway.anthropic_provider import ANTHROPIC_MODEL
from app.modules.ai.gateway.factory import build_language_model_provider
from app.modules.ai.gateway.unconfigured import UnconfiguredLanguageModelProvider

VALID_URL = "postgresql+psycopg://user:pw@db.example:5432/ninfa"
FAKE_KEY = "sk-ant-test-not-a-real-key"


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url=VALID_URL, **overrides)  # type: ignore[arg-type]


# --- 1: default is unconfigured -------------------------------------------------------------------


def test_1_default_provider_is_unconfigured() -> None:
    settings = make_settings()
    assert settings.ask_ninfa_provider == "unconfigured"
    assert settings.anthropic_api_key is None
    assert isinstance(build_language_model_provider(settings), UnconfiguredLanguageModelProvider)


# --- 2: explicit Anthropic selection -----------------------------------------------------------


def test_2_anthropic_explicit_selection_is_accepted() -> None:
    settings = make_settings(ask_ninfa_provider="anthropic", anthropic_api_key=FAKE_KEY)
    assert settings.ask_ninfa_provider == "anthropic"


# --- 3: Anthropic selected + key missing -> fail closed at Settings construction time -----------


def test_3_anthropic_without_a_key_fails_closed_at_startup() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        make_settings(ask_ninfa_provider="anthropic")


def test_3_anthropic_with_a_blank_key_also_fails_closed() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        make_settings(ask_ninfa_provider="anthropic", anthropic_api_key="   ")


# --- 4: unknown provider rejected -----------------------------------------------------------------


def test_4_unknown_provider_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(ask_ninfa_provider="openai")


# --- 5-6: secret never in repr or logs (str()) ----------------------------------------------------


def test_5_6_api_key_never_appears_in_repr_or_str() -> None:
    settings = make_settings(ask_ninfa_provider="anthropic", anthropic_api_key=FAKE_KEY)
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings)
    assert FAKE_KEY not in repr(settings.anthropic_api_key)


# --- 7: model is exactly claude-sonnet-5, never configurable ------------------------------------


def test_7_model_constant_is_exactly_claude_sonnet_5() -> None:
    assert ANTHROPIC_MODEL == "claude-sonnet-5"


def test_7_settings_has_no_model_field_at_all() -> None:
    # The model id lives in the provider adapter's own configuration (ADR 0025, "why the model id
    # lives in the adapter") - never a Settings field a deployment could silently override.
    assert "anthropic_model" not in Settings.model_fields
    assert "ask_ninfa_model" not in Settings.model_fields


# --- 8: no silent provider auto-selection ---------------------------------------------------------


def test_8_a_configured_key_alone_never_auto_selects_anthropic() -> None:
    """Setting ONLY `ANTHROPIC_API_KEY`, without `ASK_NINFA_PROVIDER=anthropic`, must NOT flip the
    provider - selection is explicit, never inferred from "a key happens to exist" (ADR 0025,
    "why provider selection is explicit")."""
    settings = make_settings(anthropic_api_key=FAKE_KEY)
    assert settings.ask_ninfa_provider == "unconfigured"
    assert isinstance(build_language_model_provider(settings), UnconfiguredLanguageModelProvider)
