"""Every way the real adapter can fail, through the whole understanding: the rules' own answer.

`test_openai_provider` drives the adapter alone; here the REAL adapter (the real SDK, a fake
transport) sits inside the real Smart Import, on a file the model could help with. A timeout, a 429,
a 5xx, a refusal, an answer that is not the closed shape, an answer that names a field nobody
offered: each one must leave EXACTLY the reading the rules alone give - and a file that is not READY
without the model must not be READY because of its failure.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.modules.ai.import_understanding.resolver import ImportUnderstandingResolver
from app.modules.ai.import_understanding.types import AiMode, AiTrace
from app.modules.ingestion.models import DataSourceDomain
from tests import understanding_support as corpus
from tests.openai_support import body, error, interpretation, ok, provider_with
from tests.semantic_support import outline, semantic_service
from tests.test_smart_import_ai_pipeline import bookings, without_a_model

STATUS_UNKNOWN = bookings(status="Condizione")


def run(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[dict[str, Any], list[AiTrace], int]:
    provider, exchange = provider_with(handler)
    traces: list[AiTrace] = []
    resolver = ImportUnderstandingResolver(
        provider, AiMode.ASSIST, corroborate=True, observer=traces.append
    )
    service = semantic_service(None)
    service._resolver = resolver
    from app.modules.data_sources.understanding import UnderstandAnswers

    inspection = service.understand(
        DataSourceDomain.BOOKINGS,
        "f.xlsx",
        STATUS_UNKNOWN,
        UnderstandAnswers(),
        False,
        None,
        False,
        currency="EUR",
    )
    return outline(inspection), traces, len(exchange.requests)


def reading(index: int, name: str, reason: str) -> dict[str, Any]:
    return {"index": index, "field": name, "confidence": "MEDIUM", "reason": reason}


def a_valid_reading(_request: httpx2.Request) -> httpx2.Response:
    answer = interpretation(
        domain="BOOKINGS",
        columns=[reading(4, "status", "HEADER_SYNONYM")],
        unknown_columns=[],
    )
    return ok(answer)


FAILURES: list[tuple[str, Callable[[httpx2.Request], httpx2.Response], str]] = [
    ("timeout", lambda r: (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=r)), "TIMEOUT"),
    ("429 rate limited", lambda _r: error(429, "rate_limit_exceeded"), "RATE_LIMIT"),
    ("429 quota", lambda _r: error(429, "insufficient_quota"), "QUOTA"),
    ("500", lambda _r: error(500), "SERVER"),
    ("503", lambda _r: error(503), "SERVER"),
    ("401", lambda _r: error(401, "invalid_api_key"), "AUTH"),
    ("404 model", lambda _r: error(404, "model_not_found"), "MODEL_UNAVAILABLE"),
    (
        "refusal",
        lambda _r: httpx2.Response(200, json=body(None, refusal="I cannot help with that.")),
        "REFUSAL",
    ),
    (
        "cut short",
        lambda _r: httpx2.Response(
            200, json=body('{"status": "INTER', status="incomplete", incomplete="max_output_tokens")
        ),
        "INCOMPLETE",
    ),
    (
        "not json",
        lambda _r: httpx2.Response(200, json=body("this is not json at all")),
        "SCHEMA",
    ),
    (
        "no answer",
        lambda _r: httpx2.Response(200, json=body(None)),
        "SCHEMA",
    ),
    (
        "a field nobody offered",
        lambda _r: ok(
            interpretation(domain="BOOKINGS", columns=[reading(4, "ADMIN_MODE", "VALUE_SHAPE")])
        ),
        "SCHEMA",
    ),
    (
        "a claim of certainty",
        lambda _r: ok(interpretation(overall_confidence="HIGH")),
        "SCHEMA",
    ),
]


@pytest.mark.parametrize(("label", "handler", "kind"), FAILURES, ids=[f[0] for f in FAILURES])
def test_a_failure_of_the_real_adapter_leaves_the_rules_own_answer(
    label: str, handler: Callable[[httpx2.Request], httpx2.Response], kind: str
) -> None:
    result, traces, _ = run(handler)

    assert result == without_a_model(STATUS_UNKNOWN), label
    assert result["level"] != "READY"
    (trace,) = traces
    assert trace.fallback_reason == kind, (label, trace.fallback_reason)
    assert trace.promoted == 0 and trace.suggested == 0


def test_a_good_answer_through_the_same_path_does_help() -> None:
    """The control: the harness is not simply making everything fall back."""
    result, traces, calls = run(a_valid_reading)

    assert calls == 1
    assert result["level"] == "READY"
    assert traces[0].promoted == 1 and traces[0].fallback_reason is None


def test_a_rate_limit_costs_two_requests_and_a_timeout_one() -> None:
    _, _, limited = run(lambda _r: error(429, "rate_limit_exceeded"))
    _, _, slow = run(lambda r: (_ for _ in ()).throw(httpx2.ReadTimeout("slow", request=r)))

    assert limited == 2  # the request and ONE more
    assert slow == 1


def test_an_answer_that_is_not_the_shape_gets_one_more_try_and_then_the_rules() -> None:
    seen: list[httpx2.Request] = []

    def first_bad_then_good(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx2.Response(200, json=body("nonsense"))
        return a_valid_reading(request)

    result, traces, calls = run(first_bad_then_good)

    # the resolver asks ONCE more (a higher effort, the codes of what broke) and the second answer
    # is used: the answer that was void is never half-used
    assert calls == 2
    assert [json.loads(r.content)["reasoning"]["effort"] for r in seen] == ["medium", "high"]
    assert result["level"] == "READY" and traces[0].calls == 2


def test_nothing_in_a_failure_reaches_the_answer_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    secret = "sk-proj-A-SECRET-AND-mario.rossi@example.com"

    result, _, _ = run(lambda _r: error(500, message=secret))

    text = json.dumps(result, default=str) + "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in text and "mario.rossi" not in text
    assert corpus  # (the corpus module is only imported for the fixtures it shares)
