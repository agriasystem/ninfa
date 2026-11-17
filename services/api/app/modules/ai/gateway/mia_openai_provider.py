"""Mia's OpenAI adapter: ONE `ToolTurnRequest` -> ONE Responses API call -> one `ToolTurnStep`.

It imports no SDK of its own: the client, the retry classification and the "send nothing" marker
come from `openai_provider` (the one file that imports `openai`), so the key, the endpoint, the
regional data residency, the timeout and the failure vocabulary are decided ONCE for the whole
account and a second adapter never keeps a copy. What is Mia's own is only the shape of the request.

What is asked of the API (shapes verified against the installed SDK, never guessed):

* `responses.create(tools=[function...], tool_choice="auto"|"none", parallel_tool_calls=True)` - the
  model asks for NINFA facts through a closed catalog (`strict` is off: the arguments are validated
  by NINFA's own typed models, which also say WHICH argument is wrong, instead of the API refusing
  the whole request).
* `text={"format": {"type": "json_schema", "strict": True, ...}}` - the FINAL answer is the closed
  shape `{status, answer, grounding_refs, limitations}`, where `grounding_refs` is an enum of the
  refs of THIS turn's observations.
* `reasoning={"effort": ...}` - chosen per call by the application (`ai.mia.policy`), never by the
  model. `include=["reasoning.encrypted_content"]` + `store=False`: the request and the answer are
  not kept by the vendor, and the reasoning of the turn travels back to the next call of the SAME
  turn as an encrypted item the application only passes along (`ToolTurnStep.provider_state`). The
  reasoning is neither read nor stored by NINFA.
* No web search, no retrieval, no state (`previous_response_id`), no `user` / `safety_identifier`:
  nothing that identifies the hotel or the person goes out with the question.

Failure policy: every error of the SDK becomes `ToolProviderUnavailableError` carrying ONE stable
`FailureKind` word - the vendor's message goes nowhere. The adapter repeats a request at most
`max_transport_retries` times after a transient failure (429, 5xx, a dropped connection - never a
timeout, never an exhausted quota, never a refusal), inside a total time budget. Logging is metadata
only: model, effort, latency, token counts, tool NAMES - never the question, an argument, a result
or the answer.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx2

from app.modules.ai.gateway.errors import ToolProviderUnavailableError
from app.modules.ai.gateway.openai_provider import (
    OMIT,
    TRANSIENT_FAILURES,
    DataResidency,
    FailureKind,
    build_openai_client,
    classify,
)
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.ai.gateway.tool_protocol import (
    ToolCall,
    ToolHistoryTurn,
    ToolRound,
    ToolTurnRequest,
    ToolTurnStep,
)

logger = logging.getLogger(__name__)

# Reasoning tokens count against this limit, so it is generous; a cut-off answer is a failure
# (INCOMPLETE), never a partial reply.
_MAX_OUTPUT_TOKENS = 12000
_TIMEOUT_SECONDS = 40.0
_MAX_TRANSPORT_RETRIES = 1
_RETRY_BACKOFF_SECONDS = 0.5
# After this long nothing is repeated: a slow provider is a failing one.
_TOTAL_BUDGET_SECONDS = 50.0

# The tags of the blocks this adapter builds. Untrusted text (the question, the history, a tool
# result) that contains one of them is defanged, so it can never close a block and start another.
_BLOCK_TAGS = (
    "turn_context",
    "page_context",
    "conversation_summary",
    "conversation_history",
    "question",
)
_TAG = re.compile(r"<\s*(/?)\s*(" + "|".join(_BLOCK_TAGS) + r")\b", re.IGNORECASE)


def defang(text: str) -> str:
    """`</question>` inside a user's text becomes `‹/question>`: still readable, no longer a tag."""
    return _TAG.sub(lambda match: f"‹{match.group(1)}{match.group(2)}", text)


def _history_text(history: tuple[ToolHistoryTurn, ...]) -> str:
    lines: list[str] = []
    for turn in history:
        speaker = "utente" if turn.role == "user" else "mia"
        lines.append(f"[{speaker}] {defang(turn.content)}")
        if turn.tools_used:
            lines.append(
                "[strumenti usati dalla risposta precedente] "
                + defang(json.dumps(list(turn.tools_used), ensure_ascii=False, sort_keys=True))
            )
    return "\n".join(lines)


def user_message_text(request: ToolTurnRequest) -> str:
    """The ONE user message of a turn: separate, labelled blocks. Only the question and the earlier
    conversation are untrusted, and both are defanged."""
    blocks = [f"<turn_context>\n{request.turn_context}\n</turn_context>"]
    if request.page_context:
        blocks.append(f"<page_context>\n{request.page_context}\n</page_context>")
    if request.conversation_summary:
        blocks.append(
            "<conversation_summary>\n"
            f"{defang(request.conversation_summary)}\n</conversation_summary>"
        )
    if request.history:
        blocks.append(
            f"<conversation_history>\n{_history_text(request.history)}\n</conversation_history>"
        )
    blocks.append(f"<question>\n{defang(request.question)}\n</question>")
    return "\n\n".join(blocks)


def answer_schema(refs: tuple[str, ...]) -> dict[str, Any]:
    """The strict shape of the final answer; `grounding_refs` may only name this turn's refs."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "answer", "grounding_refs", "limitations"],
        "properties": {
            "status": {"type": "string", "enum": [s.value for s in ModelAnswerStatus]},
            "answer": {"type": "string"},
            "grounding_refs": {
                "type": "array",
                "items": {"type": "string", "enum": list(refs)},
            },
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
    }


def _tools_param(request: ToolTurnRequest) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": spec.name,
            "description": spec.description,
            "parameters": dict(spec.input_schema),
            "strict": False,
        }
        for spec in request.tools
    ]


def _round_items(round_: ToolRound) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    state = round_.provider_state
    if isinstance(state, list):
        items.extend(item for item in state if isinstance(item, dict))
    for call in round_.calls:
        items.append(
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": json.dumps(dict(call.arguments), ensure_ascii=False),
            }
        )
    for outcome in round_.outcomes:
        items.append(
            {"type": "function_call_output", "call_id": outcome.call_id, "output": outcome.content}
        )
    return items


def input_items(request: ToolTurnRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "input_text", "text": user_message_text(request)}]}
    ]
    for round_ in request.rounds:
        items.extend(_round_items(round_))
    if request.correction is not None:
        items.append(
            {
                "role": "assistant",
                "content": [{"type": "output_text", "text": request.correction.rejected_answer}],
            }
        )
        items.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": request.correction.message}],
            }
        )
    return items


def _parse_arguments(raw: object) -> Mapping[str, Any]:
    """The model's arguments as an object. Anything that is not one is NOT repaired or guessed: it
    becomes a marker the executor's typed validation rejects with a message the model can act on."""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"_malformed_arguments": True}
        return parsed if isinstance(parsed, dict) else {"_malformed_arguments": True}
    return {"_malformed_arguments": True}


def _refused(response: Any) -> bool:
    for item in response.output or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in item.content or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False


def _usage_of(response: Any, started: float, retries: int) -> dict[str, int]:
    counted = getattr(response, "usage", None)
    details = getattr(counted, "output_tokens_details", None)
    usage = {
        "input_tokens": getattr(counted, "input_tokens", None),
        "output_tokens": getattr(counted, "output_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "retries": retries,
    }
    return {key: int(value) for key, value in usage.items() if isinstance(value, int)}


class OpenAIMiaProvider:
    """Implements `ToolCallingProvider` on the OpenAI Responses API."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        base_url: str | None = None,
        data_residency: DataResidency | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_output_tokens: int = _MAX_OUTPUT_TOKENS,
        max_transport_retries: int = _MAX_TRANSPORT_RETRIES,
        client: Any = None,
        http_client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self._max_output_tokens = max_output_tokens
        self._retries = max(0, max_transport_retries)
        self._sleep = sleep
        # `Any`: the SDK's overloaded `create` is checked by the tests against the real SDK
        self._client: Any = client or build_openai_client(
            api_key,
            timeout_seconds=timeout_seconds,
            base_url=base_url,
            data_residency=data_residency,
            http_client=http_client,
        )

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep:
        started = time.monotonic()
        retries = 0
        while True:
            try:
                return self._call(request, started, retries)
            except ToolProviderUnavailableError:
                raise
            except Exception as exc:  # the SDK's own classes are told apart by `classify`
                kind = classify(exc)
                elapsed = time.monotonic() - started
                if (
                    kind in TRANSIENT_FAILURES
                    and retries < self._retries
                    and elapsed < _TOTAL_BUDGET_SECONDS
                ):
                    retries += 1
                    self._sleep(_RETRY_BACKOFF_SECONDS * retries)
                    continue
                logger.warning(
                    "mia provider=openai model=%s status=UNAVAILABLE kind=%s effort=%s retries=%d "
                    "elapsed_ms=%d error_type=%s",
                    self.model,
                    kind.value,
                    request.reasoning,
                    retries,
                    int(elapsed * 1000),
                    type(exc).__name__,
                )
                raise ToolProviderUnavailableError(
                    "the provider request failed", kind.value, int(elapsed * 1000)
                ) from exc

    def _call(self, request: ToolTurnRequest, started: float, retries: int) -> ToolTurnStep:
        response = self._client.responses.create(
            model=self.model,
            instructions=request.system_instructions,
            input=input_items(request),
            tools=_tools_param(request) or OMIT,
            tool_choice=("auto" if request.tools_enabled else "none") if request.tools else OMIT,
            parallel_tool_calls=True if request.tools else OMIT,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "mia_answer",
                    "strict": True,
                    "schema": answer_schema(request.grounding_ref_values),
                }
            },
            reasoning={"effort": request.reasoning},
            include=["reasoning.encrypted_content"],
            store=False,
            max_output_tokens=self._max_output_tokens,
        )
        usage = _usage_of(response, started, retries)
        latency = usage.get("latency_ms", 0)
        status = getattr(response, "status", None)
        if _refused(response):
            raise ToolProviderUnavailableError(
                "the model declined to answer", FailureKind.REFUSAL.value, latency
            )
        if status == "incomplete":
            raise ToolProviderUnavailableError(
                "the answer was cut short", FailureKind.INCOMPLETE.value, latency
            )
        if status in ("failed", "cancelled"):
            raise ToolProviderUnavailableError(
                "the provider did not complete the answer",
                FailureKind.PROVIDER_ERROR.value,
                latency,
            )

        calls: list[ToolCall] = []
        reasoning_items: list[dict[str, Any]] = []
        for item in response.output or []:
            kind = getattr(item, "type", None)
            if kind == "function_call":
                calls.append(
                    ToolCall(
                        call_id=str(item.call_id),
                        name=str(item.name),
                        arguments=_parse_arguments(item.arguments),
                    )
                )
            elif kind == "reasoning":
                dumped = item.model_dump(exclude_none=True)
                reasoning_items.append(
                    {
                        key: dumped[key]
                        for key in ("type", "id", "summary", "encrypted_content")
                        if key in dumped
                    }
                )
        if calls and request.tools_enabled:
            logger.info(
                "mia provider=openai model=%s effort=%s tools=%s elapsed_ms=%d input_tokens=%s "
                "output_tokens=%s",
                self.model,
                request.reasoning,
                ",".join(call.name for call in calls),
                latency,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
            )
            return ToolTurnStep(
                tool_calls=tuple(calls), usage=usage, provider_state=reasoning_items or None
            )
        return self._answer(response, usage, request)

    def _answer(
        self, response: Any, usage: dict[str, int], request: ToolTurnRequest
    ) -> ToolTurnStep:
        latency = usage.get("latency_ms", 0)
        text = response.output_text
        if not text:
            raise ToolProviderUnavailableError("no answer", FailureKind.EMPTY.value, latency)
        try:
            raw = json.loads(text)
            status = ModelAnswerStatus(raw["status"])
            answer = raw["answer"]
            refs = raw["grounding_refs"]
            limitations = raw["limitations"]
            if (
                not isinstance(answer, str)
                or not isinstance(refs, list)
                or not isinstance(limitations, list)
                or not all(isinstance(x, str) for x in (*refs, *limitations))
            ):
                raise ValueError("shape")
        except (ValueError, KeyError, TypeError) as exc:
            raise ToolProviderUnavailableError(
                "the answer is not the closed shape", FailureKind.SCHEMA.value, latency
            ) from exc
        logger.info(
            "mia provider=openai model=%s effort=%s answer elapsed_ms=%d input_tokens=%s "
            "output_tokens=%s",
            self.model,
            request.reasoning,
            latency,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
        )
        return ToolTurnStep(
            answer=LanguageModelAnswer(
                status=status,
                answer=answer,
                grounding_refs=tuple(refs),
                limitations=tuple(limitations),
            ),
            usage=usage,
        )


__all__ = [
    "OpenAIMiaProvider",
    "answer_schema",
    "defang",
    "input_items",
    "user_message_text",
]
