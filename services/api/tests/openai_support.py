"""Test support for the OpenAI semantic layer: a real `openai` SDK client wired to a fake transport.

Nothing here reaches the network and no key is real. The SDK is the real one (installed for the
gate), so what a test inspects is the HTTP request the SDK would really send and what it does with
a response or an error the real way. Free functions only, like every support module of NINFA.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

from app.modules.ai.gateway.openai_provider import OpenAIImportUnderstandingProvider
from app.modules.ai.import_understanding.prompt import SEMANTIC_INSTRUCTIONS, evidence_json
from app.modules.ai.import_understanding.types import (
    ColumnEvidence,
    ImportUnderstandingRequest,
    UnderstandingEvidence,
)
from app.modules.data_sources.semantics_bookings import BOOKINGS
from app.modules.data_sources.semantics_costs import COSTS
from app.modules.data_sources.semantics_labor import LABOR

KEY = "sk-proj-THE-KEY-AND-A-GUEST-mario.rossi@example.com"
MODEL = "gpt-6.1-sol"
URL = httpx2.URL("https://api.openai.com/v1/responses")


def vocabulary() -> dict[str, tuple[str, ...]]:
    """The kinds of data and fields NINFA really has (what `understanding.py` offers a model)."""
    return {
        "BOOKINGS": tuple(BOOKINGS.fields),
        "COSTS": tuple(COSTS.fields),
        "LABOR": tuple(LABOR.fields),
    }


def evidence(**overrides: Any) -> UnderstandingEvidence:
    base: dict[str, Any] = {
        "expected_domain": "LABOR",
        "fields": vocabulary(),
        "columns": (
            ColumnEvidence(0, "Giorno", "DATE", 10, 10),
            ColumnEvidence(1, "Servizio", "TEXT", 10, 3, samples=("Reception", "Cucina")),
            ColumnEvidence(2, "Nome", "TEXT", 10, 10, pii="PII_PERSON_NAME"),
            ColumnEvidence(
                3, "Ore", "NUMBER", 10, 4, number_range=("4", "8"), assigned="planned_hours"
            ),
        ),
    }
    base.update(overrides)
    return UnderstandingEvidence(**base)


def request(
    ev: UnderstandingEvidence | None = None,
    *,
    attempt: int = 1,
    hints: Sequence[str] = (),
) -> ImportUnderstandingRequest:
    return ImportUnderstandingRequest(
        SEMANTIC_INSTRUCTIONS,
        evidence_json(ev or evidence()),
        {},
        attempt=attempt,
        retry_hints=tuple(hints),
        contract="semantic-v1",
    )


def interpretation(**overrides: Any) -> dict[str, Any]:
    """A well-formed `semantic-v1` answer for the default evidence (the department column read)."""
    base: dict[str, Any] = {
        "status": "INTERPRETED",
        "domain": "LABOR",
        "domain_confidence": "MEDIUM",
        "overall_confidence": "MEDIUM",
        "header": "PLAUSIBLE",
        "columns": [
            {"index": 1, "field": "role", "confidence": "MEDIUM", "reason": "HEADER_SYNONYM"}
        ],
        "unknown_columns": [],
        "ambiguities": [],
        "answers": [],
        "warnings": [],
        "questions_required": False,
    }
    base.update(overrides)
    return base


def body(
    text: str | None,
    *,
    status: str = "completed",
    refusal: str | None = None,
    incomplete: str | None = None,
    usage: tuple[int, int] = (123, 45),
    model: str = MODEL,
) -> dict[str, Any]:
    """A Responses API response, as the API would send it."""
    content: list[dict[str, Any]] = []
    if text is not None:
        content.append({"type": "output_text", "text": text, "annotations": []})
    if refusal is not None:
        content.append({"type": "refusal", "refusal": refusal})
    return {
        "id": "resp_test_1",
        "object": "response",
        "created_at": 1_760_000_000,
        "status": status,
        "model": model,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {
                "type": "message",
                "id": "msg_test_1",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": usage[0],
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": usage[1],
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": usage[0] + usage[1],
        },
    }


def ok(answer: Mapping[str, Any] | None = None, **kwargs: Any) -> httpx2.Response:
    return httpx2.Response(
        200,
        json=body(json.dumps(answer if answer is not None else interpretation()), **kwargs),
        headers={"x-request-id": "req_test_123"},
    )


def error(status: int, code: str | None = None, message: str = KEY) -> httpx2.Response:
    """An error response; its message carries a secret on purpose (it must go nowhere)."""
    payload = {"error": {"message": message, "type": "error", "code": code}}
    return httpx2.Response(status, json=payload, headers={"x-request-id": "req_err_456"})


@dataclass
class Exchange:
    """What a provider sent and what it was answered, in order."""

    handler: Callable[[httpx2.Request], httpx2.Response]
    requests: list[httpx2.Request] = field(default_factory=list)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def provider_with(
    handler: Callable[[httpx2.Request], httpx2.Response] | Exchange,
    **kwargs: Any,
) -> tuple[OpenAIImportUnderstandingProvider, Exchange]:
    exchange = handler if isinstance(handler, Exchange) else Exchange(handler)
    sleeps: list[float] = kwargs.pop("sleeps", [])
    provider = OpenAIImportUnderstandingProvider(
        KEY,
        model=kwargs.pop("model", MODEL),
        http_client=httpx2.Client(transport=httpx2.MockTransport(exchange)),
        sleep=sleeps.append,
        **kwargs,
    )
    return provider, exchange


__all__ = [
    "KEY",
    "MODEL",
    "URL",
    "Exchange",
    "body",
    "error",
    "evidence",
    "interpretation",
    "ok",
    "provider_with",
    "request",
    "vocabulary",
]
