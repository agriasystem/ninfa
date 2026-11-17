"""Cases that `test_environment_isolation.py` runs in a CHILD pytest, with an environment that
imitates a developer's machine (a fake `OPENAI_API_KEY`, `SMART_IMPORT_AI_MODE` of assist or
shadow).

This file is named so that a normal run does not collect it: it only means something under that
environment, and some of its cases FAIL on purpose (`swallowed`). It holds no key and sends nothing.
"""

import contextlib
import os
import socket
from typing import Any

import pytest

from app.core.config import Settings, get_settings
from app.modules.ai.gateway.factory import build_import_understanding_resolver
from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from tests import offline_guard

MACHINES_KEY = "sk-test-the-machines-key-0000000000"
SOMEWHERE_ELSE = ("203.0.113.1", 443)  # TEST-NET-3: never routable, and never reached


def test_ordinary_environment_is_offline(settings: Settings, app: Any) -> None:
    assert os.environ["SMART_IMPORT_AI_MODE"] == "off"
    assert os.environ["IMPORT_UNDERSTANDING_PROVIDER"] == "unconfigured"
    for name in ("OPENAI_API_KEY", "SMART_IMPORT_AI_VOCABULARY_CERTAINTY", "OPENAI_BASE_URL"):
        assert name not in os.environ, name
    assert get_settings().smart_import_ai_mode == "off"
    assert settings.smart_import_ai_mode == "off" and settings.openai_api_key is None

    resolver = build_import_understanding_resolver(settings)
    assert resolver.enabled is False and resolver._provider is None
    assert app.state.import_understanding_resolver.enabled is False
    assert app.state.import_understanding_resolver._provider is None


def test_ordinary_tripwire_refuses_and_records_a_connection_that_leaves_the_machine() -> None:
    with pytest.raises(offline_guard.ExternalNetworkError):
        socket.create_connection(SOMEWHERE_ELSE, timeout=0.2)

    assert offline_guard.GUARD.attempts == ["203.0.113.1:443"]
    offline_guard.GUARD.attempts.clear()  # forgiven: THIS test is about the tripwire itself


def test_swallowed_attempt_still_fails_the_test() -> None:
    # what the provider adapters do: a failed call is "the model was down", and nothing more
    with contextlib.suppress(Exception):
        socket.create_connection(SOMEWHERE_ELSE, timeout=0.2)


@pytest.mark.live_openai
def test_live_gets_the_machines_environment_and_can_build_a_provider() -> None:
    assert os.environ["OPENAI_API_KEY"] == MACHINES_KEY
    assert offline_guard.GUARD.active is False

    live = build_import_understanding_resolver(Settings(_env_file=None))

    assert live.enabled is True
    assert isinstance(live._provider, OpenAIImportUnderstandingProvider)  # built; nothing is sent


def test_ordinary_after_a_live_test_is_isolated_again() -> None:
    assert os.environ["SMART_IMPORT_AI_MODE"] == "off"
    assert "OPENAI_API_KEY" not in os.environ
    assert offline_guard.GUARD.active is True
