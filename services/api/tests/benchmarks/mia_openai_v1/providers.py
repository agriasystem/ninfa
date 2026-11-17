"""The providers the evaluation plays the model with, and the wrappers that watch them.

* `OracleProvider` - OFFLINE: plays what a competent model would do (rounds of tool calls, then an
  answer rendered from the world's truth) through the REAL orchestrator, so every layer except the
  model is exercised and every rubric is proven satisfiable.
* `RecordingProvider` - keeps every request exactly as the adapter would send it (the egress): the
PII
  scan and the cost estimate read it.
* `CachingProvider` - LIVE only: a reply is cached by the hash of the request, so a stopped run can
be
  resumed and a report regenerated without paying twice. The cache holds what a model said about
  SYNTHETIC hotels: keep it out of the repository.
* `CountingProvider` - LIVE only: a HARD budget of calls. A call over the budget never reaches the
  provider (it is refused with the stable kind `BUDGET_EXHAUSTED`).
"""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.ai.gateway.errors import ToolProviderUnavailableError
from app.modules.ai.gateway.mia_openai_provider import _tools_param, answer_schema, input_items
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.ai.gateway.tool_protocol import (
    ToolCall,
    ToolCallingProvider,
    ToolTurnRequest,
    ToolTurnStep,
)
from app.modules.ai.mia.types import GENERAL_KNOWLEDGE_REF
from tests.benchmarks.mia_openai_v1.model import Oracle
from tests.benchmarks.mia_openai_v1.scoring import render


def egress_body(request: ToolTurnRequest) -> str:
    """Everything the OpenAI adapter would put in the HTTP body for this request, as one text (the
    helpers are the adapter's own: what is scanned is what is sent)."""
    return json.dumps(
        {
            "instructions": request.system_instructions,
            "input": input_items(request),
            "tools": _tools_param(request),
            "answer_schema": answer_schema(request.grounding_ref_values),
            "reasoning": request.reasoning,
            "tool_choice": "auto" if request.tools_enabled else "none",
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


_ORACLE_USAGE_CHARS_PER_TOKEN = 3.2


class OracleProvider:
    """A competent model, scripted from the scenario's oracle."""

    def __init__(
        self,
        oracle: Oracle,
        truth: Mapping[str, Any],
        resolve: Callable[[Any], Any],
    ) -> None:
        self._oracle = oracle
        self._truth = truth
        self._resolve = resolve
        self._round = 0

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        usage = {
            "input_tokens": int(len(egress_body(request)) / _ORACLE_USAGE_CHARS_PER_TOKEN),
            "output_tokens": 150,
            "reasoning_tokens": 0,
            "latency_ms": 0,
        }
        if request.tools_enabled and self._round < len(self._oracle.rounds):
            calls = tuple(
                ToolCall(
                    call_id=f"call_{self._round}_{index}",
                    name=name,
                    arguments=self._resolve(dict(arguments)),
                )
                for index, (name, arguments) in enumerate(self._oracle.rounds[self._round])
            )
            self._round += 1
            return ToolTurnStep(tool_calls=calls, usage=usage)
        refs = self._refs(request)
        answer = LanguageModelAnswer(
            status=ModelAnswerStatus(self._oracle.status),
            answer=render(self._oracle.answer, self._truth),
            grounding_refs=refs,
            limitations=tuple(render(text, self._truth) for text in self._oracle.limitations),
        )
        return ToolTurnStep(answer=answer, usage=usage)

    @staticmethod
    def _refs(request: ToolTurnRequest) -> tuple[str, ...]:
        found: list[str] = []
        for round_ in request.rounds:
            for outcome in round_.outcomes:
                if outcome.is_error:
                    continue
                try:
                    refs = json.loads(outcome.content).get("riferimenti", [])
                except (ValueError, AttributeError):
                    continue
                found.extend(str(ref) for ref in refs)
        allowed = set(request.grounding_ref_values)
        chosen = tuple(dict.fromkeys(ref for ref in found if ref in allowed))
        return chosen or (GENERAL_KNOWLEDGE_REF,)


@dataclass
class RecordingProvider:
    inner: ToolCallingProvider
    requests: list[ToolTurnRequest] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        self.requests.append(request)
        self.bodies.append(egress_body(request))
        return self.inner.next_step(request)


@dataclass
class CountingProvider:
    """A hard budget: the (max_calls + 1)-th call that would reach the provider is refused."""

    inner: ToolCallingProvider
    max_calls: int | None = None
    calls: int = 0
    refused: int = 0

    @property
    def exhausted(self) -> bool:
        return self.max_calls is not None and self.calls >= self.max_calls

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        if self.max_calls is not None and self.calls >= self.max_calls:
            self.refused += 1
            raise ToolProviderUnavailableError("the call budget is spent", "BUDGET_EXHAUSTED")
        self.calls += 1
        return self.inner.next_step(request)


def _step_to_json(step: ToolTurnStep) -> dict[str, Any]:
    return {
        "tool_calls": [
            {"call_id": c.call_id, "name": c.name, "arguments": dict(c.arguments)}
            for c in step.tool_calls
        ],
        "answer": None
        if step.answer is None
        else {
            "status": step.answer.status.value,
            "answer": step.answer.answer,
            "grounding_refs": list(step.answer.grounding_refs),
            "limitations": list(step.answer.limitations),
        },
        "usage": dict(step.usage),
        "provider_state": step.provider_state,
    }


def _step_from_json(raw: Mapping[str, Any]) -> ToolTurnStep:
    answer = raw["answer"]
    return ToolTurnStep(
        tool_calls=tuple(
            ToolCall(c["call_id"], c["name"], c["arguments"]) for c in raw["tool_calls"]
        ),
        answer=None
        if answer is None
        else LanguageModelAnswer(
            ModelAnswerStatus(answer["status"]),
            answer["answer"],
            tuple(answer["grounding_refs"]),
            tuple(answer["limitations"]),
        ),
        usage={**raw["usage"], "cached": 1},
        provider_state=raw["provider_state"],
    )


@dataclass
class CachingProvider:
    """Replays a reply the cache already holds (no call, no cost); stores every fresh one."""

    inner: ToolCallingProvider
    directory: Path
    model: str
    hits: int = 0

    def __post_init__(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, request: ToolTurnRequest) -> Path:
        digest = hashlib.sha256((self.model + "\n" + egress_body(request)).encode()).hexdigest()
        return self.directory / f"{digest}.json"

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        path = self._path(request)
        if path.exists():
            self.hits += 1
            return _step_from_json(json.loads(path.read_text(encoding="utf-8")))
        step = self.inner.next_step(request)
        path.write_text(json.dumps(_step_to_json(step), ensure_ascii=False), encoding="utf-8")
        return step


_PLACEHOLDER = re.compile(r"^\$(decision|import):(.+)$")


def resolver_for(world: Any) -> Callable[[Any], Any]:
    """Arguments of an oracle call: `"$decision:<TYPE>"` and `"$import:<name>"` become the real ids
    of the world (a model reads them from a tool; the oracle knows them)."""

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, str):
            match = _PLACEHOLDER.match(value)
            if match:
                kind, name = match.groups()
                if kind == "decision":
                    return world.truth["decision_ids"][name]
                return str(world.imports[name])
        return value

    return resolve


__all__ = [
    "CachingProvider",
    "CountingProvider",
    "OracleProvider",
    "RecordingProvider",
    "egress_body",
    "resolver_for",
]
