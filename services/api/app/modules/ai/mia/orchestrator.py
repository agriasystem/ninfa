"""The bounded turn loop of Mia: model step -> tool calls -> model step -> ... -> the answer.

    MiaOrchestrator(provider, catalog).run(runtime, question, history, summary) -> MiaTurnResult

NOT an autonomous agent, and the properties below are enforced HERE, in code, not requested of the
model:

* AT MOST `MAX_TOOL_ROUNDS` rounds of tool calls (each round may hold several independent calls) and
  AT MOST `MAX_TOOL_CALLS_PER_TURN` calls in all. A call beyond the cap is answered with a refusal
  outcome and NEVER executed; the model call after the last allowed round is made with tools
  disabled, so the model can only answer. At most ONE correction (below), and a wall-clock deadline
  for the whole turn. There is no loop the model can extend: every iteration either spends a tool
  round, spends the single correction, or ends.
* The model reaches NINFA only through `ToolExecutor` and the closed catalog: unknown tools, bad
  arguments and denied areas never run anything (`tools.base`).
* HOW HARD the model thinks is the application's call (`policy`): decided from the wording before
  the first call and raised from what the turn really consulted, never "high for every message".
* The final answer is never trusted as given. It goes through the same shape / length /
  technical-leak validation as every earlier Ask (`validate_model_answer_core`), its
  `grounding_refs` are narrowed to the refs the observations of THIS turn offered, and every number
  it states must be one the observations returned (`grounding.ungrounded_numbers`). Anything that
  fails - a provider error, a malformed step, an invalid answer, a missed deadline - fails closed to
  `UNAVAILABLE`: never a guess, never a partial answer.
* ONE exception, for two failures only: an answer with UNGROUNDED NUMBERS (typically a figure
carried
  over from an earlier message) or one that stops in the MIDDLE OF A SENTENCE gets a single
  correction - the model sees its own rejected answer and what failed, WITHOUT tools, and rewrites
  from the data already gathered. The rewrite goes through exactly the same validation.
* Observability is metadata only (`TurnMetrics`): counts, tool names, durations, token usage, the
  failure kind. Never the question, an argument, an observation, the answer or a chain of thought.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer_core
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer
from app.modules.ai.gateway.tool_protocol import (
    ReasoningLevel,
    ToolCallingProvider,
    ToolCorrection,
    ToolHistoryTurn,
    ToolOutcome,
    ToolRound,
    ToolTurnRequest,
    ToolTurnStep,
)
from app.modules.ai.mia import policy
from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.completeness import looks_truncated
from app.modules.ai.mia.grounding import (
    observation_numbers,
    split_observation_numbers,
    ungrounded_numbers,
    user_date_numbers,
)
from app.modules.ai.mia.instructions import MIA_SYSTEM_INSTRUCTIONS, correction_message
from app.modules.ai.mia.tools.base import (
    ToolCatalog,
    ToolExecutor,
    ToolRuntime,
    observation_to_json,
)
from app.modules.ai.mia.turn_context import build_turn_context
from app.modules.ai.mia.types import (
    GENERAL_KNOWLEDGE_REF,
    MAX_CORRECTIONS_PER_TURN,
    MAX_MIA_ANSWER_CHARS,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_TOOL_ROUNDS,
    TURN_DEADLINE_SECONDS,
    MiaTurnResult,
    Observation,
    ToolTrace,
    TurnMetrics,
)

logger = logging.getLogger(__name__)

_CAP_REACHED = (
    '{"errore": "limite di chiamate agli strumenti raggiunto per questa domanda: rispondi con '
    'i dati che hai"}'
)


@dataclass(frozen=True, slots=True)
class _Rejected:
    """A final answer that failed ONLY a check a rewrite can fix - figures the observations do not
    contain, or a text that stops mid-sentence - with the answer as the model wrote it."""

    figures: list[str]
    incomplete: bool
    answer: LanguageModelAnswer


@dataclass
class _Turn:
    """Everything one turn accumulates. Only ever written by the orchestrator, never the model."""

    question: str
    turn_context: str
    page_context: str
    summary: str
    started: float
    reasoning: ReasoningLevel
    rounds: list[ToolRound] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    traces: list[ToolTrace] = field(default_factory=list)
    data_domains: set[str] = field(default_factory=set)
    tool_rounds: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    model_calls: int = 0
    correction: ToolCorrection | None = None
    levels: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    provider_latency_ms: int = 0

    def vocabulary(self) -> tuple[str, ...]:
        """The closed set of refs an answer may name: the general-knowledge marker and exactly the
        refs the observations of THIS turn offered."""
        return tuple(
            dict.fromkeys(
                [GENERAL_KNOWLEDGE_REF, *(ref for item in self.observations for ref in item.refs)]
            )
        )

    def add_usage(self, step: ToolTurnStep) -> None:
        self.input_tokens += step.usage.get("input_tokens", 0)
        self.output_tokens += step.usage.get("output_tokens", 0)
        self.reasoning_tokens += step.usage.get("reasoning_tokens", 0)
        self.provider_latency_ms += step.usage.get("latency_ms", 0)

    def metrics(
        self,
        now: float,
        *,
        failure_kind: str | None = None,
        reason: str | None = None,
    ) -> TurnMetrics:
        return TurnMetrics(
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            tool_failures=self.tool_failures,
            corrected=self.correction is not None,
            reasoning=tuple(self.levels),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
            provider_latency_ms=self.provider_latency_ms,
            elapsed_ms=int((now - self.started) * 1000),
            failure_kind=failure_kind,
            unavailable_reason=reason,
        )


class MiaOrchestrator:
    def __init__(
        self,
        provider: ToolCallingProvider,
        catalog: ToolCatalog,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tool_calls: int = MAX_TOOL_CALLS_PER_TURN,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        deadline_seconds: float = TURN_DEADLINE_SECONDS,
    ) -> None:
        if max_tool_calls > MAX_TOOL_CALLS_PER_TURN or max_tool_rounds > MAX_TOOL_ROUNDS:
            raise ValueError("the tool caps can be lowered, never raised")
        self._provider = provider
        self._catalog = catalog
        self._clock = clock
        self._max_tool_calls = max_tool_calls
        self._max_tool_rounds = max_tool_rounds
        self._deadline = deadline_seconds

    def run(
        self,
        runtime: ToolRuntime,
        question: str,
        history: Sequence[ToolHistoryTurn] = (),
        summary: str = "",
    ) -> MiaTurnResult:
        page = runtime.page
        turn = _Turn(
            question=question,
            turn_context=build_turn_context(runtime),
            page_context="" if page.is_empty else page.to_json(),
            summary=summary,
            started=self._clock(),
            reasoning=policy.initial(question),
        )
        executor = ToolExecutor(self._catalog, runtime)
        specs = self._catalog.specs()
        # Tool rounds + the final answer; one more call is added when the correction is spent.
        max_model_calls = self._max_tool_rounds + 1

        while True:
            if self._clock() - turn.started > self._deadline:
                return self._unavailable(turn, "deadline")
            if turn.model_calls >= max_model_calls + (turn.correction is not None):
                return self._unavailable(turn, "model_call_cap")

            # A correction is a rewrite from the data already gathered: never another tool call.
            tools_enabled = (
                turn.correction is None
                and turn.tool_rounds < self._max_tool_rounds
                and turn.tool_calls < self._max_tool_calls
            )
            request = ToolTurnRequest(
                system_instructions=MIA_SYSTEM_INSTRUCTIONS,
                turn_context=turn.turn_context,
                question=question,
                max_answer_chars=MAX_MIA_ANSWER_CHARS,
                grounding_ref_values=turn.vocabulary(),
                tools=specs,
                tools_enabled=tools_enabled,
                reasoning=turn.reasoning,
                page_context=turn.page_context,
                conversation_summary=turn.summary,
                history=tuple(history),
                rounds=tuple(turn.rounds),
                correction=turn.correction,
            )
            try:
                step = self._provider.next_step(request)
            except LanguageModelUnavailableError as error:
                kind = getattr(error, "kind", None)
                return self._unavailable(turn, "provider_unavailable", failure_kind=kind)
            except Exception:  # defense in depth: ANY unexpected provider failure fails closed
                return self._unavailable(turn, "provider_error")
            turn.model_calls += 1
            turn.levels.append(turn.reasoning)
            turn.add_usage(step)

            if step.tool_calls:
                if not tools_enabled or step.answer is not None:
                    return self._unavailable(turn, "tools_after_cap")
                call_ids = [call.call_id for call in step.tool_calls]
                if len(set(call_ids)) != len(call_ids):
                    return self._unavailable(turn, "duplicate_call_ids")
                outcomes: list[ToolOutcome] = []
                for call in step.tool_calls:
                    if turn.tool_calls >= self._max_tool_calls:
                        # Beyond the cap: refused, never executed.
                        turn.traces.append(ToolTrace(call.name, {}, (), failed=True))
                        turn.tool_failures += 1
                        outcomes.append(ToolOutcome(call.call_id, _CAP_REACHED, is_error=True))
                        continue
                    turn.tool_calls += 1
                    execution = executor.execute(call)
                    turn.traces.append(execution.trace)
                    outcomes.append(execution.outcome)
                    if execution.outcome.is_error:
                        turn.tool_failures += 1
                    if execution.observation is not None:
                        turn.observations.append(execution.observation)
                        self._note_domain(turn, call.name)
                turn.tool_rounds += 1
                turn.rounds.append(
                    ToolRound(
                        calls=step.tool_calls,
                        outcomes=tuple(outcomes),
                        provider_state=step.provider_state,
                    )
                )
                turn.reasoning = policy.after_tools(
                    turn.reasoning,
                    data_domains=len(turn.data_domains),
                    used_data_tool=bool(turn.data_domains),
                )
                continue

            if step.answer is None:
                return self._unavailable(turn, "empty_step")
            verdict = self._finalize(turn, step.answer)
            if not isinstance(verdict, _Rejected):
                return verdict
            if turn.correction is not None:
                return self._unavailable(turn, "rejected_after_correction")
            if MAX_CORRECTIONS_PER_TURN < 1:  # pragma: no cover - the cap is a constant
                return self._unavailable(turn, "rejected")
            turn.correction = ToolCorrection(
                rejected_answer=json.dumps(
                    {
                        "status": verdict.answer.status.value,
                        "answer": verdict.answer.answer,
                        "grounding_refs": list(verdict.answer.grounding_refs),
                        "limitations": list(verdict.answer.limitations),
                    },
                    ensure_ascii=False,
                ),
                message=correction_message(verdict.figures, incomplete=verdict.incomplete),
            )

    # --- internals ---------------------------------------------------------------------------

    def _note_domain(self, turn: _Turn, tool_name: str) -> None:
        """What area of NINFA a tool read, for the reasoning policy: a product-knowledge tool is not
        a data area; a tool that spans areas (decisions, status) counts as one of its own."""
        definition = self._catalog.get(tool_name)
        if definition is None:
            return
        if definition.domain is AccessDomain.PRODUCT:
            return
        turn.data_domains.add(
            "trasversale" if definition.domain is None else definition.domain.value
        )

    def _unavailable(
        self, turn: _Turn, reason: str, *, failure_kind: str | None = None
    ) -> MiaTurnResult:
        logger.warning(
            "mia turn status=UNAVAILABLE reason=%s kind=%s model_calls=%d tool_calls=%d",
            reason,
            failure_kind or "-",
            turn.model_calls,
            turn.tool_calls,
        )
        return MiaTurnResult(
            status=AskStatus.UNAVAILABLE,
            answer=None,
            grounding_refs=(),
            limitations=(),
            trace=tuple(turn.traces),
            metrics=turn.metrics(self._clock(), failure_kind=failure_kind, reason=reason),
        )

    def _finalize(self, turn: _Turn, raw: LanguageModelAnswer) -> MiaTurnResult | _Rejected:
        validated = validate_model_answer_core(
            raw, frozenset(turn.vocabulary()), MAX_MIA_ANSWER_CHARS
        )
        if validated is None:
            return self._unavailable(turn, "invalid_answer")

        # What a figure may be grounded in: the FIGURES of this turn's observations (never the
        # digits of a date or a time they mention) and the dates/durations the user named. The
        # calendar of the turn context and the observations' own dates may ground a number ONLY
        # inside a date or a time expression ("10 ottobre", "9:31"): they must never lend their
        # day numbers to a figure.
        texts = [observation_to_json(item) for item in turn.observations]
        figures, observed_dates = split_observation_numbers(texts)
        allowed = figures | user_date_numbers(turn.question)
        calendar = observation_numbers([turn.turn_context]) | observed_dates
        stated = " ".join((validated.answer, *validated.limitations))
        offending = ungrounded_numbers(stated, allowed, calendar)
        incomplete = looks_truncated(validated.answer)
        if offending or incomplete:
            # Counts only: never the figures or the text (they may be exactly the wrong data).
            logger.warning(
                "mia rejected ungrounded_numbers=%d incomplete=%s corrected=%s",
                len(offending),
                incomplete,
                turn.correction is not None,
            )
            return _Rejected(offending, incomplete, raw)

        metrics = turn.metrics(self._clock())
        logger.info(
            "mia turn status=%s model_calls=%d tool_calls=%d tool_failures=%d corrected=%s "
            "tools=%s reasoning=%s input_tokens=%d output_tokens=%d elapsed_ms=%d",
            validated.status.value,
            metrics.model_calls,
            metrics.tool_calls,
            metrics.tool_failures,
            metrics.corrected,
            ",".join(trace.tool for trace in turn.traces) or "-",
            ",".join(metrics.reasoning),
            metrics.input_tokens,
            metrics.output_tokens,
            metrics.elapsed_ms,
        )
        return MiaTurnResult(
            status=validated.status,
            answer=validated.answer,
            grounding_refs=validated.grounding_refs,
            limitations=validated.limitations,
            trace=tuple(turn.traces),
            metrics=metrics,
        )


__all__ = ["MiaOrchestrator"]
