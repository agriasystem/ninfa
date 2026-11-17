"""How Mia is switched on, and that she is OFF unless she is.

`MIA_PROVIDER` is her own switch, separate from Smart Import's layer: `unconfigured` (the default)
builds a provider that only says "unavailable" and loads no vendor SDK; `openai` needs the account's
key - and without one Mia is unavailable instead of stopping the application. The key, the endpoint
and the data residency are the account's (`OPENAI_*`), shared with Smart Import; the model and the
timeout are Mia's own. The key is a secret wherever it could be printed."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from app.modules.ai.gateway.errors import ToolProviderUnavailableError
from app.modules.ai.gateway.factory import build_mia_provider
from app.modules.ai.gateway.mia_openai_provider import OpenAIMiaProvider
from app.modules.ai.gateway.tool_protocol import ToolTurnRequest
from app.modules.ai.gateway.unconfigured import UnconfiguredToolProvider

_REPO = Path(__file__).resolve().parents[3]
KEY = "sk-proj-REPLACE-ME-with-a-throwaway-test-value-0000"


def settings(**values: object) -> Settings:
    values.setdefault("anthropic_api_key", None)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _request() -> ToolTurnRequest:
    return ToolTurnRequest(
        system_instructions="x",
        turn_context="{}",
        question="q",
        max_answer_chars=100,
        grounding_ref_values=("knowledge:general",),
        tools=(),
        tools_enabled=False,
    )


def test_the_default_is_unconfigured_with_gpt_6_1_sol_as_her_model() -> None:
    base = settings()

    assert base.mia_provider == "unconfigured"
    assert base.mia_openai_model == "gpt-6.1-sol"
    assert base.mia_openai_timeout_seconds == 40.0
    assert base.openai_api_key is None


def test_the_test_process_forces_mia_off_whatever_the_machine_holds() -> None:
    assert os.environ["MIA_PROVIDER"] == "unconfigured"
    assert "MIA_OPENAI_MODEL" not in os.environ
    assert settings().mia_provider == "unconfigured"


def test_unconfigured_builds_a_provider_that_says_unavailable_and_loads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_be_built(*_a: object, **_k: object) -> object:
        raise AssertionError("the OpenAI adapter was built although Mia is unconfigured")

    monkeypatch.setattr(OpenAIMiaProvider, "__init__", must_not_be_built)

    provider = build_mia_provider(settings(mia_provider="unconfigured", openai_api_key=KEY))

    assert isinstance(provider, UnconfiguredToolProvider)
    with pytest.raises(ToolProviderUnavailableError) as raised:
        provider.next_step(_request())
    assert raised.value.kind == "NOT_CONFIGURED"


def test_a_key_alone_never_turns_mia_on() -> None:
    provider = build_mia_provider(settings(openai_api_key=KEY))

    assert isinstance(provider, UnconfiguredToolProvider)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_openai_without_a_key_is_unavailable_with_one_warning_not_a_startup_error(
    key: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        provider = build_mia_provider(settings(mia_provider="openai", openai_api_key=key))

    assert isinstance(provider, UnconfiguredToolProvider)
    warnings = [r.getMessage() for r in caplog.records if "MIA_PROVIDER=openai" in r.getMessage()]
    assert len(warnings) == 1 and "OPENAI_API_KEY" in warnings[0]


def test_openai_with_a_key_builds_the_adapter_with_her_own_model_and_the_accounts_residency() -> (
    None
):
    provider = build_mia_provider(
        settings(
            mia_provider="openai",
            openai_api_key=KEY,
            mia_openai_model="gpt-6.1-sol",
            openai_data_residency="eu",
        )
    )

    assert isinstance(provider, OpenAIMiaProvider)
    assert provider.model == "gpt-6.1-sol"
    assert "eu" in str(provider._client.base_url)


def test_her_model_is_not_smart_imports_model() -> None:
    provider = build_mia_provider(
        settings(
            mia_provider="openai",
            openai_api_key=KEY,
            mia_openai_model="gpt-6.1-terra",
            smart_import_openai_model="gpt-6.1-sol",
        )
    )

    assert isinstance(provider, OpenAIMiaProvider) and provider.model == "gpt-6.1-terra"


def test_the_key_never_renders() -> None:
    configured = settings(mia_provider="openai", openai_api_key=KEY)
    provider = build_mia_provider(configured)

    assert KEY not in repr(configured) and KEY not in str(configured)
    assert KEY not in repr(provider) and KEY not in repr(vars(provider).keys())


def test_a_process_that_never_selects_mia_never_imports_the_vendor_sdk() -> None:
    code = (
        "import sys\n"
        "from app.core.config import Settings\n"
        "from app.modules.ai.gateway.factory import build_mia_provider\n"
        "p = build_mia_provider(Settings(_env_file=None, mia_provider='unconfigured'))\n"
        "assert type(p).__name__ == 'UnconfiguredToolProvider'\n"
        "assert 'app.modules.ai.gateway.mia_openai_provider' not in sys.modules\n"
        "print('ok')\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO / "services" / "api"),
        "MIA_PROVIDER": "unconfigured",
    }

    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO / "services" / "api"),
        check=False,
    )

    assert done.stdout.strip() == "ok", done.stderr[-400:]
