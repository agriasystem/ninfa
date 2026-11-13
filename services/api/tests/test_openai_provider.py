"""The OpenAI adapter, driven through the REAL `openai` SDK with a fake transport (no network).

What matters here is what the SDK would really put on the wire and what it really raises: the
request is a Responses API call with Structured Outputs over the closed `semantic-v1` shape, with
`store=false`, no tools and nothing that identifies a hotel or a person; every failure of the SDK
becomes one stable word and never the vendor's message (which can hold a key); a transient failure
is repeated a bounded number of times, a timeout or an exhausted quota never.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from app.modules.ai.import_understanding.interpretation import SemanticInterpretation
from app.modules.ai.import_understanding.prompt import SEMANTIC_INSTRUCTIONS
from app.modules.ai.import_understanding.resolver import ImportUnderstandingUnavailableError
from app.modules.ai.import_understanding.types import FailureKind, ProviderAnswer
from tests.openai_support import (
    KEY,
    MODEL,
    Exchange,
    body,
    error,
    interpretation,
    ok,
    provider_with,
    request,
    vocabulary,
)


def _answered(provider: OpenAIImportUnderstandingProvider, **kwargs: Any) -> ProviderAnswer:
    answer = provider.suggest(request(**kwargs))
    assert isinstance(answer, ProviderAnswer)
    return answer


def _failure(
    provider: OpenAIImportUnderstandingProvider, **kwargs: Any
) -> ImportUnderstandingUnavailableError:
    with pytest.raises(ImportUnderstandingUnavailableError) as raised:
        provider.suggest(request(**kwargs))
    return raised.value


# --- what goes on the wire -----------------------------------------------------------------------


def test_the_call_is_a_responses_api_request_with_structured_output_and_nothing_stored() -> None:
    provider, exchange = provider_with(lambda _r: ok())

    _answered(provider)

    sent = exchange.requests[0]
    assert sent.method == "POST"
    assert sent.url.path == "/v1/responses"
    payload = exchange.bodies[0]
    assert payload["model"] == MODEL
    assert payload["store"] is False
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["instructions"] == SEMANTIC_INSTRUCTIONS
    structured = payload["text"]["format"]
    assert structured["type"] == "json_schema"
    assert structured["strict"] is True
    assert structured["schema"]["additionalProperties"] is False


def test_the_evidence_travels_as_data_in_its_own_block_never_in_the_instructions() -> None:
    provider, exchange = provider_with(lambda _r: ok())
    asked = request()

    provider.suggest(asked)

    payload = exchange.bodies[0]
    assert asked.evidence_json not in payload["instructions"]
    blocks = payload["input"][0]["content"]
    assert [b["type"] for b in blocks] == ["input_text"]
    assert blocks[0]["text"] == f"<evidence>\n{asked.evidence_json}\n</evidence>"


def test_nothing_that_identifies_the_hotel_or_keeps_state_is_sent() -> None:
    provider, exchange = provider_with(lambda _r: ok())

    _answered(provider)

    payload = exchange.bodies[0]
    for forbidden in (
        "tools",
        "tool_choice",
        "previous_response_id",
        "conversation",
        "user",
        "safety_identifier",
        "metadata",
        "background",
        "prompt_cache_key",
    ):
        assert forbidden not in payload, forbidden
    assert "stream" not in payload or payload["stream"] is False
    # the key is a header, never part of the document
    assert KEY not in json.dumps(payload)


def test_the_schema_offers_only_the_domains_and_fields_ninfa_really_has() -> None:
    provider, exchange = provider_with(lambda _r: ok())

    _answered(provider)

    schema = exchange.bodies[0]["text"]["format"]["schema"]
    text = json.dumps(schema)
    offered = vocabulary()
    domain_enum = schema["properties"]["domain"]["enum"]
    assert set(domain_enum) == {*offered, "UNKNOWN"}
    every_field = {f for names in offered.values() for f in names}
    column = schema["$defs"]["ColumnReading"] if "$defs" in schema else None
    assert column is not None
    assert set(column["properties"]["field"]["enum"]) == {*every_field, "NONE"}
    # a confidence a model may claim is LOW or MEDIUM: there is no HIGH to choose
    assert schema["$defs"]["Confidence"]["enum"] == ["LOW", "MEDIUM"]
    # every property of every object is required and objects are closed
    assert "additionalProperties" in text
    assert set(schema["required"]) == set(schema["properties"])


def test_the_vendor_sdk_is_told_the_closed_shape_has_no_room_for_a_value_of_the_file() -> None:
    provider, exchange = provider_with(lambda _r: ok())

    _answered(provider)

    schema = exchange.bodies[0]["text"]["format"]["schema"]

    def types_of(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            if isinstance(node.get("type"), str):
                found.add(node["type"])
            for value in node.values():
                found |= types_of(value)
        elif isinstance(node, list):
            for item in node:
                found |= types_of(item)
        return found

    # strings only where a choice is made (an enum) or an opaque question id / choice;
    # the schema has no number or date type at all other than a column index
    assert types_of(schema) <= {"object", "array", "string", "integer", "boolean"}


# --- what comes back -----------------------------------------------------------------------------


def test_a_valid_answer_is_a_typed_interpretation_with_what_the_call_cost() -> None:
    provider, _ = provider_with(lambda _r: ok(usage=(321, 54)))

    answer = _answered(provider)

    assert isinstance(answer.payload, SemanticInterpretation)
    assert answer.payload.domain == "LABOR"
    assert answer.payload.columns[0].field == "role"
    usage = answer.usage
    assert (usage.model, usage.input_tokens, usage.output_tokens) == (MODEL, 321, 54)
    assert usage.request_id == "req_test_123"
    assert usage.reasoning_effort == "medium"
    assert usage.retries == 0
    assert usage.latency_ms >= 0


def test_the_first_reading_is_medium_effort_and_the_one_repeat_is_higher() -> None:
    provider, exchange = provider_with(lambda _r: ok())

    _answered(provider, attempt=1)
    _answered(provider, attempt=2, hints=("UNKNOWN_FIELD", "SHAPE"))

    first, second = exchange.bodies
    assert first["reasoning"] == {"effort": "medium"}
    assert second["reasoning"] == {"effort": "high"}
    blocks = second["input"][0]["content"]
    assert blocks[1]["text"] == (
        "<previous_answer_broke_rules>UNKNOWN_FIELD, SHAPE</previous_answer_broke_rules>"
    )


def test_a_model_without_reasoning_is_sent_no_reasoning_parameter() -> None:
    provider, exchange = provider_with(
        lambda _r: ok(), reasoning_effort="none", escalated_effort="none"
    )

    _answered(provider)

    assert "reasoning" not in exchange.bodies[0]


def test_an_answer_that_is_not_the_closed_shape_goes_back_as_nothing_to_be_asked_again() -> None:
    provider, _ = provider_with(lambda _r: httpx2.Response(200, json=body("this is not json")))

    answer = _answered(provider)

    assert (
        answer.payload is None
    )  # the resolver reads this as "not the shape" and may ask once more
    assert answer.usage.input_tokens == 123


def test_an_answer_naming_a_field_nobody_offered_is_not_a_shape_either() -> None:
    wrong = interpretation(
        columns=[
            {"index": 1, "field": "ADMIN_MODE", "confidence": "MEDIUM", "reason": "VALUE_SHAPE"}
        ]
    )
    provider, _ = provider_with(lambda _r: ok(wrong))

    assert _answered(provider).payload is None


def test_a_claim_of_certainty_is_not_a_shape() -> None:
    sure = interpretation(overall_confidence="HIGH")
    provider, _ = provider_with(lambda _r: ok(sure))

    assert _answered(provider).payload is None


def test_no_answer_at_all_is_nothing() -> None:
    provider, _ = provider_with(lambda _r: httpx2.Response(200, json=body(None)))

    assert _answered(provider).payload is None


def test_a_refusal_is_a_stable_failure() -> None:
    provider, _ = provider_with(
        lambda _r: httpx2.Response(200, json=body(None, refusal="I cannot help with that."))
    )

    failed = _failure(provider)

    assert failed.kind == FailureKind.REFUSAL
    assert failed.usage is not None and failed.usage.input_tokens == 123


def test_an_answer_cut_short_is_a_stable_failure() -> None:
    provider, _ = provider_with(
        lambda _r: httpx2.Response(
            200, json=body('{"status": "INTER', status="incomplete", incomplete="max_output_tokens")
        )
    )

    assert _failure(provider).kind == FailureKind.INCOMPLETE


# --- failures ------------------------------------------------------------------------------------

_FAILURES: list[tuple[str, Callable[[httpx2.Request], httpx2.Response], FailureKind]] = [
    ("429 rate limited", lambda _r: error(429, "rate_limit_exceeded"), FailureKind.RATE_LIMIT),
    ("429 quota exhausted", lambda _r: error(429, "insufficient_quota"), FailureKind.QUOTA),
    ("500", lambda _r: error(500), FailureKind.SERVER),
    ("503", lambda _r: error(503), FailureKind.SERVER),
    ("401 bad key", lambda _r: error(401, "invalid_api_key"), FailureKind.AUTH),
    ("403", lambda _r: error(403), FailureKind.AUTH),
    ("404 unknown model", lambda _r: error(404, "model_not_found"), FailureKind.MODEL_UNAVAILABLE),
    (
        "400 request too large",
        lambda _r: error(400, "context_length_exceeded"),
        FailureKind.REQUEST_TOO_LARGE,
    ),
    ("413", lambda _r: error(413), FailureKind.REQUEST_TOO_LARGE),
    ("400 something else", lambda _r: error(400, "invalid_prompt"), FailureKind.PROVIDER_ERROR),
    ("418", lambda _r: error(418), FailureKind.PROVIDER_ERROR),
]


@pytest.mark.parametrize(("label", "handler", "kind"), _FAILURES, ids=[f[0] for f in _FAILURES])
def test_every_failure_of_the_sdk_is_one_stable_kind(
    label: str, handler: Callable[[httpx2.Request], httpx2.Response], kind: FailureKind
) -> None:
    provider, _ = provider_with(handler)

    failed = _failure(provider)

    assert failed.kind == kind, label
    assert str(failed) == "the provider request failed"


def test_a_timeout_is_a_stable_failure_and_is_never_repeated() -> None:
    def hang(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=_request)

    exchange = Exchange(hang)
    provider, _ = provider_with(exchange)

    failed = _failure(provider)

    assert failed.kind == FailureKind.TIMEOUT
    assert len(exchange.requests) == 1


def test_a_dropped_connection_is_repeated_once_and_then_is_the_fallback() -> None:
    def refuse(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=_request)

    exchange = Exchange(refuse)
    sleeps: list[float] = []
    provider, _ = provider_with(exchange, sleeps=sleeps)

    failed = _failure(provider)

    assert failed.kind == FailureKind.CONNECTION
    assert len(exchange.requests) == 2  # the first try and ONE more
    assert failed.usage is not None and failed.usage.retries == 1
    assert len(sleeps) == 1 and sleeps[0] <= 1.0


def test_a_rate_limit_that_passes_is_answered_and_the_repeat_is_counted() -> None:
    calls = {"n": 0}

    def once_limited(_request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return error(429, "rate_limit_exceeded") if calls["n"] == 1 else ok()

    provider, exchange = provider_with(once_limited)

    answer = _answered(provider)

    assert len(exchange.requests) == 2
    assert answer.usage.retries == 1
    assert isinstance(answer.payload, SemanticInterpretation)


def test_a_rate_limit_that_does_not_pass_is_repeated_at_most_once() -> None:
    exchange = Exchange(lambda _r: error(429, "rate_limit_exceeded"))
    provider, _ = provider_with(exchange)

    failed = _failure(provider)

    assert failed.kind == FailureKind.RATE_LIMIT
    assert len(exchange.requests) == 2


@pytest.mark.parametrize("code", ["insufficient_quota", "billing_hard_limit_reached"])
def test_an_exhausted_quota_is_never_repeated(code: str) -> None:
    exchange = Exchange(lambda _r: error(429, code))
    provider, _ = provider_with(exchange)

    assert _failure(provider).kind == FailureKind.QUOTA
    assert len(exchange.requests) == 1


def test_a_server_error_is_repeated_once() -> None:
    exchange = Exchange(lambda _r: error(500))
    provider, _ = provider_with(exchange)

    assert _failure(provider).kind == FailureKind.SERVER
    assert len(exchange.requests) == 2


def test_with_no_retries_allowed_nothing_is_repeated() -> None:
    exchange = Exchange(lambda _r: error(500))
    provider, _ = provider_with(exchange, max_transport_retries=0)

    _failure(provider)

    assert len(exchange.requests) == 1


def test_the_sdk_never_repeats_a_request_by_itself() -> None:
    # a 500 followed by a success: with the SDK's own retries on it would be answered by the second
    # request without the adapter ever knowing; here the adapter counts every request
    provider, exchange = provider_with(lambda _r: error(500), max_transport_retries=0)

    _failure(provider)

    assert len(exchange.requests) == 1


def test_a_vendor_message_carrying_a_secret_goes_nowhere(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    provider, _ = provider_with(lambda _r: error(500, message=KEY))

    failed = _failure(provider)

    assert KEY not in str(failed)
    assert "mario.rossi" not in str(failed)
    assert failed.__cause__ is not None  # kept for a debugger, never for a log line
    everything = "\n".join(record.getMessage() for record in caplog.records)
    assert KEY not in everything
    assert "mario.rossi" not in everything
    assert "sk-proj" not in everything


def test_the_cleaned_evidence_is_never_logged_even_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    provider, _ = provider_with(lambda _r: ok())
    asked = request()

    provider.suggest(asked)

    everything = "\n".join(record.getMessage() for record in caplog.records)
    assert "Servizio" not in everything
    assert "<evidence>" not in everything
    assert "Reception" not in everything


def test_a_success_logs_counts_and_words_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    provider, _ = provider_with(lambda _r: ok(usage=(77, 11)))

    _answered(provider)

    line = next(r.getMessage() for r in caplog.records if "provider=openai" in r.getMessage())
    assert f"model={MODEL}" in line
    assert "input_tokens=77" in line and "output_tokens=11" in line


# --- configuration of the client -----------------------------------------------------------------


def test_a_regional_endpoint_is_used_only_when_selected() -> None:
    seen: list[str] = []

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen.append(r.url.host)
        return ok()

    default, _ = provider_with(handler)
    regional, _ = provider_with(handler, data_residency="eu")

    _answered(default)
    _answered(regional)

    assert seen == ["api.openai.com", "eu.api.openai.com"]


def test_a_custom_endpoint_is_honoured() -> None:
    seen: list[str] = []

    def handler(r: httpx2.Request) -> httpx2.Response:
        seen.append(str(r.url))
        return ok()

    provider, _ = provider_with(handler, base_url="https://gateway.example.test/openai/v1")

    _answered(provider)

    assert seen == ["https://gateway.example.test/openai/v1/responses"]


def test_the_model_is_whatever_is_configured() -> None:
    provider, exchange = provider_with(lambda _r: ok(model="another-model"), model="another-model")

    answer = _answered(provider)

    assert exchange.bodies[0]["model"] == "another-model"
    assert answer.usage.model == "another-model"
