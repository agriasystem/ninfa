"""How the OpenAI semantic layer is switched on, and that it is OFF unless it is.

`SMART_IMPORT_AI_MODE` is the one switch: `off` (the default) builds a resolver with nothing in it
and loads no vendor SDK; `shadow` and `assist` need `OPENAI_API_KEY` - and without one Smart Import
runs exactly as with `off` instead of breaking. The key is a secret wherever it could be printed.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.ai.gateway import factory
from app.modules.ai.gateway.factory import build_import_understanding_resolver
from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from app.modules.ai.import_understanding.types import AiMode

_REPO = Path(__file__).resolve().parents[3]
KEY = "sk-proj-REPLACE-ME-with-a-throwaway-test-value-0000"


def settings(**values: object) -> Settings:
    values.setdefault("anthropic_api_key", None)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_the_default_is_off_and_no_model_is_configured() -> None:
    base = settings()

    assert base.smart_import_ai_mode == "off"
    assert base.openai_api_key is None
    assert base.smart_import_openai_model == "gpt-6.1-sol"
    assert base.smart_import_openai_reasoning == "low"
    assert base.openai_base_url is None and base.openai_data_residency is None


def test_off_builds_a_resolver_with_nothing_inside_even_when_a_key_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_be_built(*_a: object, **_k: object) -> object:
        raise AssertionError("the OpenAI adapter was built although the mode is off")

    monkeypatch.setattr(OpenAIImportUnderstandingProvider, "__init__", must_not_be_built)

    resolver = build_import_understanding_resolver(
        settings(smart_import_ai_mode="off", openai_api_key=KEY)
    )

    assert resolver.enabled is False
    assert resolver._provider is None
    assert resolver.mode == AiMode.OFF


@pytest.mark.parametrize("mode", ["shadow", "assist"])
def test_a_mode_with_no_key_is_not_an_error_and_runs_without_a_model(
    mode: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)

    resolver = build_import_understanding_resolver(settings(smart_import_ai_mode=mode))

    assert resolver.enabled is False
    assert resolver._provider is None
    assert resolver.mode == AiMode(mode)
    assert any("OPENAI_API_KEY is not set" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_key_is_no_key(blank: str) -> None:
    resolver = build_import_understanding_resolver(
        settings(smart_import_ai_mode="assist", openai_api_key=blank)
    )

    assert resolver.enabled is False


@pytest.mark.parametrize("mode", ["shadow", "assist"])
def test_a_mode_with_a_key_builds_the_openai_semantic_layer(mode: str) -> None:
    resolver = build_import_understanding_resolver(
        settings(
            smart_import_ai_mode=mode,
            openai_api_key=KEY,
            smart_import_openai_model="a-model",
            smart_import_openai_reasoning="low",
        )
    )

    provider = resolver._provider
    assert isinstance(provider, OpenAIImportUnderstandingProvider)
    assert resolver.enabled is True
    assert resolver.mode == AiMode(mode)
    # the semantic layer asks about the columns the rules placed unsure, in either mode...
    assert resolver.reads_confirmations is True
    # ...but a model's reading is NEVER certain unless the switch is turned on (ADR 0052)
    assert resolver.corroborates is False
    assert provider.model == "a-model"
    assert provider.contract == "semantic-v1"
    assert provider._effort == "low"


def test_the_vocabulary_certainty_is_off_by_default() -> None:
    assert settings().smart_import_ai_vocabulary_certainty is False


@pytest.mark.parametrize(("mode", "certain"), [("shadow", False), ("assist", True)])
def test_turning_the_vocabulary_certainty_on_applies_in_assist_only(
    mode: str, certain: bool
) -> None:
    resolver = build_import_understanding_resolver(
        settings(
            smart_import_ai_mode=mode,
            openai_api_key=KEY,
            smart_import_ai_vocabulary_certainty=True,
        )
    )

    assert resolver.reads_confirmations is True
    assert resolver.corroborates is certain


def test_the_environment_example_leaves_the_vocabulary_certainty_off() -> None:
    example = (_REPO / ".env.example").read_text(encoding="utf-8")

    assert re.search(r"^SMART_IMPORT_AI_VOCABULARY_CERTAINTY=false$", example, re.MULTILINE)


def test_the_two_ways_of_selecting_a_model_for_smart_import_are_not_combined() -> None:
    with pytest.raises(ValidationError, match="set only one of them"):
        settings(
            smart_import_ai_mode="assist",
            import_understanding_provider="anthropic",
            anthropic_api_key="a-key-for-the-other-vendor",
        )


@pytest.mark.parametrize("mode", ["shadow", "assist"])
def test_both_selections_together_are_a_startup_error_that_names_both(mode: str) -> None:
    with pytest.raises(ValidationError) as raised:
        settings(
            smart_import_ai_mode=mode,
            import_understanding_provider="anthropic",
            anthropic_api_key="a-key-for-the-other-vendor",
        )

    message = str(raised.value)
    assert "SMART_IMPORT_AI_MODE" in message and "IMPORT_UNDERSTANDING_PROVIDER" in message
    assert "a-key-for-the-other-vendor" not in message


def test_each_selection_alone_is_fine_and_off_is_not_a_selection() -> None:
    settings(smart_import_ai_mode="assist", openai_api_key=KEY)
    settings(import_understanding_provider="anthropic", anthropic_api_key="a-key")
    # `off` selects nothing, so it can sit next to the original provider
    settings(
        smart_import_ai_mode="off", import_understanding_provider="anthropic", anthropic_api_key="k"
    )
    settings(smart_import_ai_mode="assist", import_understanding_provider="unconfigured")


def test_the_environment_example_says_the_two_selections_are_not_combined() -> None:
    example = (_REPO / ".env.example").read_text(encoding="utf-8")

    assert "STARTUP ERROR" in example
    assert "IMPORT_UNDERSTANDING_PROVIDER" in example


def test_the_original_provider_selection_is_untouched() -> None:
    legacy = Settings(
        _env_file=None,
        import_understanding_provider="anthropic",
        anthropic_api_key="a-key-for-the-other-vendor",
    )

    resolver = build_import_understanding_resolver(legacy)

    assert resolver.enabled is True
    assert resolver.corroborates is False  # the original assistant only ever suggests


def test_a_custom_endpoint_and_a_regional_one_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        settings(openai_base_url="https://gateway.example.test/v1", openai_data_residency="eu")


@pytest.mark.parametrize("url", ["http://gateway.example.test/v1", "ftp://x/v1", "gateway/v1"])
def test_a_custom_endpoint_must_be_https(url: str) -> None:
    with pytest.raises(ValidationError, match="https"):
        settings(openai_base_url=url)


@pytest.mark.parametrize("url", ["https://gateway.example.test/v1", "http://127.0.0.1:9000/v1"])
def test_https_or_a_loopback_endpoint_is_accepted(url: str) -> None:
    assert settings(openai_base_url=url).openai_base_url == url


def test_the_regional_endpoint_reaches_the_client_and_is_never_hard_coded() -> None:
    resolver = build_import_understanding_resolver(
        settings(smart_import_ai_mode="assist", openai_api_key=KEY, openai_data_residency="eu")
    )
    default = build_import_understanding_resolver(
        settings(smart_import_ai_mode="assist", openai_api_key=KEY)
    )

    assert isinstance(resolver._provider, OpenAIImportUnderstandingProvider)
    assert isinstance(default._provider, OpenAIImportUnderstandingProvider)
    assert str(resolver._provider._client.base_url).startswith("https://eu.api.openai.com")
    assert str(default._provider._client.base_url).startswith("https://api.openai.com")


def test_a_model_the_name_of_which_is_empty_is_refused() -> None:
    with pytest.raises(ValidationError):
        settings(smart_import_openai_model="")


def test_the_key_never_renders_in_a_repr_a_dump_or_an_error() -> None:
    configured = settings(smart_import_ai_mode="assist", openai_api_key=KEY)

    assert KEY not in repr(configured)
    assert KEY not in str(configured)
    assert KEY not in str(configured.model_dump())
    assert KEY not in configured.model_dump_json()
    with pytest.raises(ValidationError) as raised:
        settings(openai_api_key=KEY, smart_import_openai_timeout_seconds=0.0)
    assert KEY not in str(raised.value)


def test_the_factory_selects_nothing_by_itself_because_a_key_exists() -> None:
    # "an API key alone is never enough": mode off + key = nothing is built
    assert (
        factory.build_import_understanding_resolver(settings(openai_api_key=KEY))._provider is None
    )


def test_the_environment_example_documents_the_switches_with_placeholders_only() -> None:
    example = (_REPO / ".env.example").read_text(encoding="utf-8")

    for name in (
        "SMART_IMPORT_AI_MODE",
        "OPENAI_API_KEY",
        "SMART_IMPORT_OPENAI_MODEL",
        "SMART_IMPORT_OPENAI_REASONING",
        "OPENAI_BASE_URL",
        "OPENAI_DATA_RESIDENCY",
    ):
        assert re.search(rf"^#?\s*{name}=", example, re.MULTILINE), name
    assert re.search(r"^SMART_IMPORT_AI_MODE=off\s*$", example, re.MULTILINE)
    # a key is never in the example: the variable is there, empty
    assert re.search(r"^OPENAI_API_KEY=\s*$", example, re.MULTILINE)
    assert not re.search(r"sk-[A-Za-z0-9_-]{16,}", example)


def test_no_api_key_shaped_value_is_committed_outside_the_tests() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "."],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    pattern = re.compile(r"sk-(?:proj-|live-|svcacct-)?[A-Za-z0-9_-]{32,}")
    offenders = []
    for name in tracked:
        path = _REPO / name
        if (
            "tests" in path.parts
            or "node_modules" in path.parts
            or path.suffix in {".png", ".jpg", ".ico", ".woff", ".woff2", ".xlsx", ".lock"}
            or not path.is_file()
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if pattern.search(text):
            offenders.append(name)

    assert offenders == []


def test_a_process_that_never_selects_the_mode_never_loads_the_openai_sdk() -> None:
    code = (
        "import sys\n"
        "from app.core.config import Settings\n"
        "from app.modules.ai.gateway.factory import build_import_understanding_resolver\n"
        "s = Settings(_env_file=None, database_url='postgresql+psycopg://u:p@h/d')\n"
        "r = build_import_understanding_resolver(s)\n"
        "assert r.enabled is False\n"
        "assert 'openai' not in sys.modules, 'the OpenAI SDK was imported'\n"
        "print('ok')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        env={"PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )

    assert done.stdout.strip() == "ok", done.stderr[-400:]
