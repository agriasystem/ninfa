"""A provider that fails must never stop, slow or spoil an import.

Smart Import reads files without any model. When one is configured and it times out, is rate
limited (429), returns a server error (500, 529), refuses, runs out of quota, answers with something
that is not JSON or is cut short, the person must get EXACTLY the answer they would have got with no
model - the same screen, the same questions, a normal 200 - and the vendor's message (which can hold
anything, a key included) must go nowhere. These tests drive the real vendor adapter with the real
SDK exceptions (no network: the client is replaced) and the whole API route with a provider that
fails in every way.
"""

import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.modules.ai.gateway import anthropic_provider as vendor
from app.modules.ai.import_understanding.prompt import (
    SYSTEM_INSTRUCTIONS,
    evidence_json,
    output_schema,
)
from app.modules.ai.import_understanding.resolver import (
    ImportUnderstandingResolver,
    ImportUnderstandingUnavailableError,
)
from app.modules.ai.import_understanding.types import (
    ColumnEvidence,
    ImportUnderstandingRequest,
    ResolutionReason,
    UnderstandingEvidence,
)
from tests import understanding_support as corpus
from tests.data_sources_support import SourcesEnv, sources_env
from tests.import_ai_support import Scenario, ScenarioProvider
from tests.smart_import_support import understand, validation
from tests.support import BookingFactory

SECRET = "sk-ant-api03-THE-KEY-AND-A-GUEST-mario.rossi@example.com"
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(error: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=_REQUEST, json={"error": {"message": SECRET}})
    return error(SECRET, response=response, body={"error": {"message": SECRET}})


SDK_FAILURES: dict[str, Callable[[], Exception]] = {
    "timeout": lambda: anthropic.APITimeoutError(request=_REQUEST),
    "connection refused": lambda: anthropic.APIConnectionError(message=SECRET, request=_REQUEST),
    "429 rate limited": lambda: _status(anthropic.RateLimitError, 429),
    "500 server error": lambda: _status(anthropic.InternalServerError, 500),
    "529 overloaded": lambda: _status(anthropic.APIStatusError, 529),
    "400 credit balance too low": lambda: _status(anthropic.BadRequestError, 400),
    "401 bad key": lambda: _status(anthropic.AuthenticationError, 401),
    "403 forbidden": lambda: _status(anthropic.PermissionDeniedError, 403),
    "404 unknown model": lambda: _status(anthropic.NotFoundError, 404),
    "a bare exception": lambda: RuntimeError(SECRET),
    "keyboard-style base exception subclass": lambda: OSError(SECRET),
}


class _Messages:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls = 0

    def create(self, **_kwargs: Any) -> object:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _adapter(
    monkeypatch: pytest.MonkeyPatch, outcome: object
) -> tuple[vendor.AnthropicImportUnderstandingProvider, _Messages]:
    messages = _Messages(outcome)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: SimpleNamespace(messages=messages))
    return vendor.AnthropicImportUnderstandingProvider(api_key="sk-test"), messages


def _evidence() -> UnderstandingEvidence:
    return UnderstandingEvidence(
        expected_domain="LABOR",
        fields={"LABOR": ("work_date", "role")},
        columns=(ColumnEvidence(0, "Gruppo", "TEXT", 10, 3, samples=("Reception", "Cucina")),),
    )


def _request() -> ImportUnderstandingRequest:
    evidence = _evidence()
    return ImportUnderstandingRequest(
        SYSTEM_INSTRUCTIONS, evidence_json(evidence), output_schema(evidence.fields)
    )


def _fit(_domain: str, _index: int, _field: str) -> float | None:
    return 1.0


def _message(*texts: str, stop_reason: str = "end_turn") -> object:
    blocks = [SimpleNamespace(type="text", text=text) for text in texts]
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=500, output_tokens=40),
    )


# --- the vendor adapter ---


@pytest.mark.parametrize("failure", list(SDK_FAILURES))
def test_every_vendor_failure_becomes_one_static_unavailable_with_nothing_of_the_vendor(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    provider, messages = _adapter(monkeypatch, SDK_FAILURES[failure]())

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(ImportUnderstandingUnavailableError) as caught,
    ):
        provider.suggest(_request())

    assert str(caught.value) == "the provider request failed"  # a static word
    assert messages.calls == 1  # the adapter itself never retries
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert SECRET not in logged and "mario.rossi" not in logged and "Reception" not in logged


@pytest.mark.parametrize(
    "message",
    [
        _message("not json at all"),
        _message('{"domain": "LABOR", "columns": [{"index": 0, "fie'),  # cut short at max_tokens
        _message("{}", "{}"),
        _message(),
        _message(""),
    ],
    ids=["prose", "truncated", "two blocks", "no block", "empty"],
)
def test_a_response_that_is_not_one_json_object_is_unavailable_not_trusted(
    monkeypatch: pytest.MonkeyPatch, message: object
) -> None:
    provider, _ = _adapter(monkeypatch, message)

    with pytest.raises(ImportUnderstandingUnavailableError):
        provider.suggest(_request())


def test_the_adapter_bounds_the_answer_and_the_wait() -> None:
    assert vendor._IMPORT_MAX_OUTPUT_TOKENS <= 1500
    assert vendor._IMPORT_TIMEOUT_SECONDS <= 20.0
    assert vendor._MAX_RETRIES == 0


@pytest.mark.parametrize("failure", list(SDK_FAILURES))
def test_through_the_resolver_a_vendor_failure_is_unavailable_after_exactly_one_call(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    provider, messages = _adapter(monkeypatch, SDK_FAILURES[failure]())

    result = ImportUnderstandingResolver(provider).resolve(_evidence(), _fit)

    assert result.reason == ResolutionReason.UNAVAILABLE and not result.used
    assert result.calls == 1 and messages.calls == 1


# --- the whole route ---


@pytest.fixture
def env(factory: BookingFactory, authenticated_as: Callable[[UUID], None]) -> SourcesEnv:
    return sources_env(factory, authenticated_as)


def _unplaced_department_file() -> bytes:
    rows: list[list[object]] = [["Giorno", "Gruppo di lavoro", "Ore previste"]]
    from datetime import datetime

    for offset in range(3):
        for _name, department, *_rest in corpus.PEOPLE[:6]:
            rows.append([datetime(2026, 10, 26 + offset), department, 8])
    return corpus.csv_of(rows)


def _with(api_client: TestClient, provider: object | None) -> None:
    api_client.app.state.import_understanding_resolver = ImportUnderstandingResolver(provider)  # type: ignore[attr-defined,arg-type]


FAILING = [
    Scenario.TIMEOUT,
    Scenario.RATE_LIMITED,
    Scenario.SERVER_ERROR,
    Scenario.RAW_EXCEPTION,
    Scenario.NOT_JSON,
    Scenario.MALFORMED,
    Scenario.EMPTY,
    Scenario.HEAVY,
]


@pytest.mark.parametrize("scenario", FAILING, ids=lambda s: s.value)
def test_the_route_answers_a_failing_provider_exactly_as_it_answers_no_provider(
    api_client: TestClient, env: SourcesEnv, scenario: Scenario
) -> None:
    content = _unplaced_department_file()
    _with(api_client, None)
    without = understand(api_client, env, "LABOR", "turni.csv", content, {"date_order": "DMY"})
    model = ScenarioProvider(scenario)
    _with(api_client, model)

    with_model = understand(api_client, env, "LABOR", "turni.csv", content, {"date_order": "DMY"})

    assert with_model == without  # the same screen, the same questions, a normal 200
    assert 1 <= model.calls <= 2 and model.violations == []


@pytest.mark.parametrize("scenario", FAILING, ids=lambda s: s.value)
def test_a_file_the_engine_can_import_is_imported_even_when_the_provider_is_down(
    api_client: TestClient, env: SourcesEnv, scenario: Scenario
) -> None:
    content = _unplaced_department_file()
    answers = {"date_order": "DMY", "department_value": "FRONT_OFFICE"}
    _with(api_client, ScenarioProvider(scenario))

    body = understand(api_client, env, "LABOR", "turni.csv", content, answers)

    assert body["understanding"]["level"] == "READY"
    assert validation(api_client, env, "LABOR", content, body["proposal"], name="t.csv")[
        "can_import"
    ]


def test_a_provider_failure_is_never_reported_to_the_person_as_an_error(
    api_client: TestClient, env: SourcesEnv
) -> None:
    content = _unplaced_department_file()
    _with(api_client, ScenarioProvider(Scenario.RAW_EXCEPTION))

    body = understand(api_client, env, "LABOR", "turni.csv", content, {"date_order": "DMY"})

    text = json.dumps(body)
    for word in ("sk-ant", "secret", "RuntimeError", "unavailable", "provider", "Traceback"):
        assert word.lower() not in text.lower()
