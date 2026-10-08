"""The ONE file in this codebase allowed to import `anthropic` (see
`test_anthropic_provider_isolation.py`, which enforces this by scanning every other module's own
imports). `AskNinfaService`, the context builder, and every domain type stay entirely unaware this
vendor - or any vendor - exists; this adapter's only job is translating `LanguageModelRequest` -> a
real Messages API call -> `LanguageModelAnswer`, never the other way around (see ADR 0025).

No streaming, no tools, no web search/fetch, no MCP, no retrieval - exactly one Messages API
request per `generate()` call. Structured Outputs (`output_config.format`, verified against the
real 1.8.0 SDK installed for this gate - see ADR 0025, "why structured outputs") constrain the
model to the closed shape Gate 18 already expects; this module still never trusts the response as
given (`_answer_from_message` re-validates it byte for byte) - Gate 18's own
`answer_validation.py` is the second, independent layer of distrust on top of this one.
"""

import copy
import json
import logging
import time
from typing import Any, Literal

import anthropic
from anthropic.types import (
    JSONOutputFormatParam,
    Message,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    ThinkingConfigAdaptiveParam,
)

from app.modules.ai.ask_ninfa.types import GroundingRef
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import (
    LanguageModelAnswer,
    LanguageModelRequest,
    ModelAnswerStatus,
)

logger = logging.getLogger(__name__)

# Fixed, not user-configurable - a model change is an architectural decision (its own future gate),
# never a runtime toggle. Verified against the real, installed SDK (Gate 19's own pre-gate check),
# never guessed from the prompt.
ANTHROPIC_MODEL = "claude-sonnet-5"

# Bounded, never indefinite (ADR 0025, "why one provider call, bounded and unretried").
_TIMEOUT_SECONDS = 15.0
_MAX_OUTPUT_TOKENS = 1024
_MAX_RETRIES = 0

# A request that allows a LONGER answer (Mia Home: up to 1800 characters of Italian, ~550 tokens,
# on top of the JSON envelope, the grounding refs, up to five limitations and the adaptive-thinking
# tokens, which count against `max_tokens`) needs a larger - still fixed, still bounded - output
# budget, or a perfectly good answer would be cut off by the vendor mid-JSON and fail closed as
# UNAVAILABLE. Requests at or below `_STANDARD_ANSWER_CHARS` (every Decision Ask request) keep
# `_MAX_OUTPUT_TOKENS` exactly as before.
_STANDARD_ANSWER_CHARS = 1200
_MAX_OUTPUT_TOKENS_LONG_ANSWER = 2048

# Ask NINFA is explanation, not frontier reasoning (ADR 0025, "why low effort, why no sampling
# params") - Claude Sonnet 5's Messages API exposes no temperature/top_p/top_k at all in this SDK
# version; `effort` is the one inference-shape knob `output_config` offers.
_EFFORT: Literal["low"] = "low"

# The SAME closed vocabulary Gate 18 already defined (`app.modules.ai.ask_ninfa.types`) - never a
# second, adapter-local list that could drift from it.
_STATUS_VALUES = [status.value for status in ModelAnswerStatus]
_GROUNDING_REF_VALUES = [ref.value for ref in GroundingRef]

# Verified against https://platform.claude.com/docs/en/build-with-claude/structured-outputs
# (Gate 19's own pre-gate check): `enum`/`required`/`additionalProperties` are supported;
# `maxLength` and similar string/numeric constraints are NOT - those stay Gate 18's own
# `answer_validation.py` job, never duplicated here (provider schema is shape/type/enum only).
_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": _STATUS_VALUES},
        "answer": {"type": "string"},
        "grounding_refs": {
            "type": "array",
            "items": {"type": "string", "enum": _GROUNDING_REF_VALUES},
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "answer", "grounding_refs", "limitations"],
    "additionalProperties": False,
}

_EXPECTED_KEYS = frozenset(_OUTPUT_SCHEMA["required"])


def _output_schema_for(request: LanguageModelRequest) -> dict[str, Any]:
    """The default Decision Ask schema itself (the SAME object, so nothing about that path
    changes) unless the request names its own closed `grounding_refs` vocabulary - then a deep
    copy whose `items.enum` is exactly that vocabulary, never a mutation of the shared constant."""
    if request.grounding_ref_values is None:
        return _OUTPUT_SCHEMA
    schema = copy.deepcopy(_OUTPUT_SCHEMA)
    schema["properties"]["grounding_refs"]["items"]["enum"] = list(request.grounding_ref_values)
    return schema


def _max_tokens_for(request: LanguageModelRequest) -> int:
    if request.max_answer_chars > _STANDARD_ANSWER_CHARS:
        return _MAX_OUTPUT_TOKENS_LONG_ANSWER
    return _MAX_OUTPUT_TOKENS


# Fixed, deterministic: adaptive thinking (Sonnet 5's own default reasoning mode), but never
# exposed - `display: "omitted"` redacts the content itself at the API level, so there is nothing
# for `_answer_from_message` to filter out even before its own defensive text-block scan runs (see
# ADR 0025, "why thinking is ignored, not merely unrequested").
_THINKING: ThinkingConfigAdaptiveParam = {"type": "adaptive", "display": "omitted"}


def _content_blocks(request: LanguageModelRequest) -> list[TextBlockParam]:
    """Context and question as two SEPARATE, deterministically-ordered content blocks - never
    concatenated into one string, never interpolated into `system`. The XML-ish tags are plain
    structural labels, not instructions - see ADR 0025, "why content blocks, not string
    concatenation"."""
    return [
        {"type": "text", "text": f"<context>\n{request.context}\n</context>"},
        {"type": "text", "text": f"<question>\n{request.question}\n</question>"},
    ]


def _answer_from_message(message: Message) -> LanguageModelAnswer:
    text_blocks = [block.text for block in message.content if block.type == "text"]
    if len(text_blocks) != 1:
        raise LanguageModelUnavailableError(
            "Anthropic response did not contain exactly one structured text block"
        )

    try:
        payload = json.loads(text_blocks[0])
    except (json.JSONDecodeError, TypeError) as exc:
        raise LanguageModelUnavailableError("Anthropic response was not valid JSON") from exc

    if not isinstance(payload, dict) or set(payload.keys()) != _EXPECTED_KEYS:
        # Covers BOTH a missing required field and an unexpected extra one - the schema's own
        # `additionalProperties: false` should already prevent the latter from a well-behaved
        # response, but this is re-checked here too, never assumed.
        raise LanguageModelUnavailableError("Anthropic response did not match the expected schema")

    try:
        status = ModelAnswerStatus(payload["status"])
        answer = payload["answer"]
        grounding_refs = tuple(payload["grounding_refs"])
        limitations = tuple(payload["limitations"])
        if not isinstance(answer, str):
            raise TypeError("answer must be a string")
        if not all(isinstance(ref, str) for ref in grounding_refs):
            raise TypeError("grounding_refs must be strings")
        if not all(isinstance(item, str) for item in limitations):
            raise TypeError("limitations must be strings")
    except (KeyError, ValueError, TypeError) as exc:
        raise LanguageModelUnavailableError(
            "Anthropic response did not match the expected schema"
        ) from exc

    return LanguageModelAnswer(
        status=status, answer=answer, grounding_refs=grounding_refs, limitations=limitations
    )


class AnthropicLanguageModelProvider:
    """Implements Gate 18's `LanguageModelProvider` Protocol - `AskNinfaService` never knows this
    class exists, only that something satisfies `.generate()`."""

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES
        )

    def generate(self, request: LanguageModelRequest) -> LanguageModelAnswer:
        started = time.monotonic()
        output_format: JSONOutputFormatParam = {
            "type": "json_schema",
            "schema": _output_schema_for(request),
        }
        output_config: OutputConfigParam = {"effort": _EFFORT, "format": output_format}
        messages: list[MessageParam] = [{"role": "user", "content": _content_blocks(request)}]
        try:
            message = self._client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=_max_tokens_for(request),
                system=request.system_instructions,
                messages=messages,
                thinking=_THINKING,
                output_config=output_config,
            )
        except Exception as exc:
            # Every SDK-raised failure (auth, timeout, connection, rate limit, 4xx/5xx status) -
            # and, as defense in depth, anything else unexpected - fails closed. The vendor's own
            # exception message/body is NEVER included: `type(exc).__name__` is a safe, static
            # category label, never the exception's own `str()` (which can embed request/response
            # detail, and for `AuthenticationError` specifically, part of the request).
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "ask_ninfa provider=anthropic model=%s status=UNAVAILABLE elapsed_ms=%d"
                " error_type=%s",
                ANTHROPIC_MODEL,
                elapsed_ms,
                type(exc).__name__,
            )
            raise LanguageModelUnavailableError("Anthropic provider request failed") from exc

        answer = _answer_from_message(message)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "ask_ninfa provider=anthropic model=%s status=%s elapsed_ms=%d"
            " input_tokens=%d output_tokens=%d",
            ANTHROPIC_MODEL,
            answer.status.value,
            elapsed_ms,
            message.usage.input_tokens,
            message.usage.output_tokens,
        )
        return answer


__all__ = ["ANTHROPIC_MODEL", "AnthropicLanguageModelProvider"]
