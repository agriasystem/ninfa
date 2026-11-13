"""The ONE file in this codebase allowed to import `openai` (see `test_ai_boundary.py`, which
enforces it by scanning every other module's own imports). The resolver, the egress gate, the
validator and everything that reads a file stay entirely unaware that this vendor - or any vendor -
exists: this adapter translates one `ImportUnderstandingRequest` into one OpenAI **Responses API**
call and its answer into a typed `SemanticInterpretation`, never the other way around.

What is asked of the API, and why (all verified against the real `openai` SDK installed for this
gate, never guessed):

* `responses.create(text={"format": {"type": "json_schema", "strict": True, ...}})` - Structured
  Outputs: the model is constrained to the closed `semantic-v1` shape, in which `domain` and
  `field` are enums of what NINFA really has. The Pydantic model is built per request from the
  vocabulary the evidence itself carries, its strict schema comes from the SDK's public
  `pydantic_function_tool`, and the answer is validated by the SAME Pydantic model here. (`parse`
  would do the same but raises before the status, the refusal and the usage of a bad answer can
  be read - and those are what the audit and the fallback need.)
* `store=False` - the request and the answer are not kept by the vendor for later retrieval.
* `reasoning={"effort": ...}` - `medium` for the first reading; ONE second, targeted reading (after
  an answer that broke the shape) may use a higher effort. No loop: the resolver makes at most two
  calls.
* No tools, no web search, no retrieval, no streaming, no `previous_response_id`, no `user` or
  `safety_identifier`: nothing that identifies the hotel or the person goes out with the document.
* The model's reasoning is neither asked for (`summary` is not set) nor read nor kept.

Failure policy: every error of the SDK becomes `ImportUnderstandingUnavailableError` carrying ONE
stable `FailureKind` word - the vendor's message (which can hold anything, a key included) goes
nowhere. The SDK's own retries are OFF; the adapter itself repeats a request at most
`max_transport_retries` times after a transient failure (429, 5xx, a dropped connection - never a
timeout, never an exhausted quota, never a refusal), inside a total time budget.
"""

import json
import logging
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

import httpx2
import openai
import pydantic
from openai import OpenAI

from app.modules.ai.import_understanding.interpretation import (
    SemanticInterpretation,
    contract_model,
)
from app.modules.ai.import_understanding.resolver import ImportUnderstandingUnavailableError
from app.modules.ai.import_understanding.types import (
    FailureKind,
    ImportUnderstandingRequest,
    ProviderAnswer,
    ProviderUsage,
)

logger = logging.getLogger(__name__)
# The SDK logs the options of every request at DEBUG - that is, the cleaned evidence of a hotel's
# file. Whatever the application's log level, the vendor's own logger stays at WARNING.
for _name in ("openai",):
    logging.getLogger(_name).setLevel(logging.WARNING)

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
DataResidency = Literal["global", "us", "eu", "ae", "au", "in", "jp"]

# The reasoning tokens of a reasoning model count against this limit, so it is generous: an answer
# is a few hundred tokens, a cut-off one is a failure (INCOMPLETE), never a partial reading.
_MAX_OUTPUT_TOKENS = 6000
_TIMEOUT_SECONDS = 25.0
_MAX_TRANSPORT_RETRIES = 1
_RETRY_BACKOFF_SECONDS = 0.5
# After this long, nothing is repeated: a slow provider is a failing one.
_TOTAL_BUDGET_SECONDS = 30.0

_QUOTA_CODES = frozenset({"insufficient_quota", "billing_hard_limit_reached"})
_TOO_LARGE_CODES = frozenset({"context_length_exceeded", "request_too_large"})
_MODEL_CODES = frozenset({"model_not_found", "model_not_available", "unsupported_model"})


def _code_of(error: openai.APIError) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else ""


def classify(error: Exception) -> FailureKind:
    """The stable kind of an SDK failure: from the exception's class and the vendor's error CODE,
    never from its message."""
    if isinstance(error, openai.APITimeoutError):
        return FailureKind.TIMEOUT
    if isinstance(error, openai.APIConnectionError):
        return FailureKind.CONNECTION
    if isinstance(error, openai.RateLimitError):
        return FailureKind.QUOTA if _code_of(error) in _QUOTA_CODES else FailureKind.RATE_LIMIT
    if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return FailureKind.AUTH
    if isinstance(error, openai.NotFoundError):
        return FailureKind.MODEL_UNAVAILABLE
    if isinstance(error, openai.LengthFinishReasonError):
        return FailureKind.INCOMPLETE
    if isinstance(error, openai.ContentFilterFinishReasonError):
        return FailureKind.REFUSAL
    if isinstance(error, openai.BadRequestError):
        code = _code_of(error)
        if code in _TOO_LARGE_CODES:
            return FailureKind.REQUEST_TOO_LARGE
        if code in _MODEL_CODES:
            return FailureKind.MODEL_UNAVAILABLE
        return FailureKind.PROVIDER_ERROR
    if isinstance(error, openai.APIStatusError):
        if error.status_code == 413:
            return FailureKind.REQUEST_TOO_LARGE
        return FailureKind.SERVER if error.status_code >= 500 else FailureKind.PROVIDER_ERROR
    return FailureKind.PROVIDER_ERROR


# A failure that can pass by itself: worth one more try. (Not a timeout: waiting twice is worse than
# the fallback; not a quota, a key or a model: nothing a second request changes.)
_TRANSIENT = frozenset({FailureKind.RATE_LIMIT, FailureKind.SERVER, FailureKind.CONNECTION})


def _vocabulary(request: ImportUnderstandingRequest) -> dict[str, list[str]]:
    """The kinds of data and fields NINFA offered, read back from the evidence the request carries
    (it is NINFA's own JSON, built a moment ago: `allowed.fields`)."""
    document = json.loads(request.evidence_json)
    fields = document["allowed"]["fields"]
    return {str(domain): [str(name) for name in names] for domain, names in fields.items()}


def _input_of(request: ImportUnderstandingRequest) -> list[Any]:
    """The evidence (DATA) and, on the repeat, the rules the previous answer broke as stable codes
    (never the previous answer): separate blocks, never concatenated into the instructions."""
    blocks: list[dict[str, str]] = [
        {"type": "input_text", "text": f"<evidence>\n{request.evidence_json}\n</evidence>"}
    ]
    if request.retry_hints:
        codes = ", ".join(request.retry_hints)
        blocks.append(
            {
                "type": "input_text",
                "text": f"<previous_answer_broke_rules>{codes}</previous_answer_broke_rules>",
            }
        )
    return [{"role": "user", "content": blocks}]


@lru_cache(maxsize=8)
def _strict_schema(contract: type[SemanticInterpretation]) -> dict[str, Any]:
    """The Structured Outputs schema of a contract: every property required, every object closed -
    what the SDK's own helper builds for a Pydantic model."""
    tool = openai.pydantic_function_tool(contract)
    return dict(tool["function"].get("parameters", {}))


def _refused(response: Any) -> bool:
    for item in response.output or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in item.content or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False


class OpenAIImportUnderstandingProvider:
    """Implements `ImportUnderstandingProvider` with the `semantic-v1` contract."""

    contract = "semantic-v1"
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        reasoning_effort: ReasoningEffort = "medium",
        escalated_effort: ReasoningEffort = "high",
        base_url: str | None = None,
        data_residency: DataResidency | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_output_tokens: int = _MAX_OUTPUT_TOKENS,
        max_transport_retries: int = _MAX_TRANSPORT_RETRIES,
        client: OpenAI | None = None,
        http_client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self._effort = reasoning_effort
        self._escalated = escalated_effort
        self._max_output_tokens = max_output_tokens
        self._retries = max(0, max_transport_retries)
        self._sleep = sleep
        # `max_retries=0`: the SDK never repeats a request by itself, so every retry is counted here
        # (an endpoint argument is passed only when chosen: the SDK refuses `base_url=None`
        # next to a regional endpoint)
        endpoint: dict[str, Any] = {}
        if base_url is not None:
            endpoint["base_url"] = base_url
        if data_residency is not None:
            endpoint["data_residency"] = data_residency
        self._client = client or OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
            http_client=http_client,
            **endpoint,
        )

    # --- the one call --------------------------------------------------------------------------

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        started = time.monotonic()
        effort = self._escalated if request.attempt >= 2 else self._effort
        try:
            contract = contract_model(_vocabulary(request))
        except (ValueError, KeyError, TypeError) as exc:
            raise ImportUnderstandingUnavailableError(
                "the request could not be shaped", FailureKind.SCHEMA
            ) from exc
        retries = 0
        while True:
            try:
                return self._call(request, contract, effort, started, retries)
            except ImportUnderstandingUnavailableError:
                raise
            except Exception as exc:
                kind = classify(exc)
                elapsed = time.monotonic() - started
                if (
                    kind in _TRANSIENT
                    and retries < self._retries
                    and elapsed < _TOTAL_BUDGET_SECONDS
                ):
                    retries += 1
                    self._sleep(_RETRY_BACKOFF_SECONDS * retries)
                    continue
                usage = ProviderUsage(
                    model=self.model,
                    latency_ms=int(elapsed * 1000),
                    request_id=getattr(exc, "request_id", None),
                    reasoning_effort=effort,
                    retries=retries,
                )
                logger.warning(
                    "import_understanding provider=openai model=%s status=UNAVAILABLE kind=%s "
                    "attempt=%d retries=%d elapsed_ms=%d error_type=%s",
                    self.model,
                    kind.value,
                    request.attempt,
                    retries,
                    usage.latency_ms,
                    type(exc).__name__,
                )
                raise ImportUnderstandingUnavailableError(
                    "the provider request failed", kind, usage
                ) from exc

    def _call(
        self,
        request: ImportUnderstandingRequest,
        contract: type[SemanticInterpretation],
        effort: ReasoningEffort,
        started: float,
        retries: int,
    ) -> ProviderAnswer:
        reasoning: Any = {"effort": effort} if effort != "none" else openai.omit
        response = self._client.responses.create(
            model=self.model,
            instructions=request.system_instructions,
            input=_input_of(request),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "semantic_interpretation",
                    "strict": True,
                    "schema": _strict_schema(contract),
                }
            },
            reasoning=reasoning,
            store=False,
            max_output_tokens=self._max_output_tokens,
        )
        usage = self._usage(response, effort, started, retries)
        status = getattr(response, "status", None)
        if _refused(response):
            raise ImportUnderstandingUnavailableError(
                "the model declined to answer", FailureKind.REFUSAL, usage
            )
        if status == "incomplete":
            raise ImportUnderstandingUnavailableError(
                "the answer was cut short", FailureKind.INCOMPLETE, usage
            )
        if status in ("failed", "cancelled"):
            raise ImportUnderstandingUnavailableError(
                "the provider did not complete the answer", FailureKind.PROVIDER_ERROR, usage
            )
        answer = response.output_text
        if not answer:
            return ProviderAnswer(None, usage)
        try:
            parsed = contract.model_validate_json(answer)
        except pydantic.ValidationError:
            # Structured Outputs promise the shape, but an answer that does not parse is not one:
            # it goes back to the resolver as "not the closed shape" (which makes ONE more call)
            return ProviderAnswer(None, usage)
        logger.info(
            "import_understanding provider=openai model=%s attempt=%d effort=%s elapsed_ms=%d "
            "input_tokens=%s output_tokens=%s retries=%d",
            self.model,
            request.attempt,
            effort,
            usage.latency_ms,
            usage.input_tokens,
            usage.output_tokens,
            retries,
        )
        return ProviderAnswer(parsed, usage)

    def _usage(
        self, response: Any, effort: ReasoningEffort, started: float, retries: int
    ) -> ProviderUsage:
        counted = getattr(response, "usage", None)
        return ProviderUsage(
            model=str(getattr(response, "model", None) or self.model),
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=getattr(counted, "input_tokens", None),
            output_tokens=getattr(counted, "output_tokens", None),
            request_id=getattr(response, "_request_id", None),
            reasoning_effort=effort,
            retries=retries,
        )


__all__ = ["OpenAIImportUnderstandingProvider", "classify"]
