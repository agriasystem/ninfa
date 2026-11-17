"""The provider-agnostic boundary for a BOUNDED, read-only tool-calling turn of Mia.

`LanguageModelProvider.generate` (protocol.py) is one request, one answer. Mia needs one more thing
from a provider: to let the model ask for NINFA facts through a CLOSED catalog of read-only tools,
and to answer once it has them. This module defines that exchange in neutral terms - no vendor SDK
type appears anywhere here, exactly like `protocol.py` - and nothing more:

    ToolTurnRequest   instructions + trusted turn context + page context + conversation summary
                      + history + question + the tool rounds of this turn so far + the catalog
    ToolTurnStep      what the model did next: ask for tools, OR give the final answer

The ORCHESTRATOR (`app.modules.ai.mia.orchestrator`) owns the loop, the cap on tool calls, the
reasoning policy and the deadline; a provider only translates ONE request into ONE vendor call and
the reply back. A provider never executes a tool, never loops, never decides how many calls are
allowed (ADR 0055, "why the loop is not in the adapter").

Separate inputs, never concatenated: instructions are trusted and static; `turn_context` is trusted
application facts (date, calendar, role) handed over as DATA; `page_context` is the screen the
person is looking at (a HINT, never a source of facts); `conversation_summary` and `history` are the
earlier conversation (untrusted text, never a source of facts); `question` is untrusted input. Tool
results travel as `ToolOutcome`s, also DATA.

`provider_state` is the one opaque thing: whatever a vendor needs handed back with the next request
of the SAME turn (OpenAI's encrypted reasoning items, with `store=False`). The orchestrator keeps it
in memory for the turn and returns it untouched; it is never persisted and never inspected.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.modules.ai.gateway.protocol import LanguageModelAnswer

ReasoningLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool of the closed catalog, as the model sees it. `input_schema` is a closed JSON schema
    (`additionalProperties: false`), generated from the same typed model that validates the call."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A request of the model, exactly as it produced it - still UNVALIDATED. `arguments` is never
    trusted: the executor validates it against the tool's typed model before anything runs."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What the application answers a `ToolCall` with: canonical JSON text (an observation, or a
    short error the model can act on). Data, never an instruction."""

    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolRound:
    """One model step that asked for tools, with the outcomes it received (same order, same ids)."""

    calls: tuple[ToolCall, ...]
    outcomes: tuple[ToolOutcome, ...]
    provider_state: object | None = None


@dataclass(frozen=True, slots=True)
class ToolHistoryTurn:
    """One earlier message of the conversation. `tools_used` is the server-written trace of what an
    assistant message drew on (tool names and RESOLVED arguments): it lets "e il giorno dopo?" be
    resolved against the date that was really discussed. Referential context, never business
    truth."""

    role: str
    content: str
    tools_used: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCorrection:
    """A one-shot, server-written request to REWRITE an answer the application rejected: the model's
    own rejected answer (as the JSON text it produced) followed by `message`, trusted text written
    by the application (never by the user or the model). The provider appends the two to the end of
    the transcript, in that order; it does not interpret either."""

    rejected_answer: str
    message: str


@dataclass(frozen=True, slots=True)
class ToolTurnRequest:
    """`tools_enabled=False` is the final-answer step: the catalog is still described (a transcript
    that contains tool rounds must) but the model may not call any tool and must answer.
    `grounding_ref_values` is the closed set of refs the structured answer may name: the refs of the
    observations of THIS turn, plus the general-knowledge marker. `correction`, when set, is the
    rewrite request described above (always with `tools_enabled=False`). `reasoning` is the effort
    the application chose for THIS call (`ai.mia.policy`)."""

    system_instructions: str
    turn_context: str
    question: str
    max_answer_chars: int
    grounding_ref_values: tuple[str, ...]
    tools: tuple[ToolSpec, ...]
    tools_enabled: bool
    reasoning: ReasoningLevel = "medium"
    page_context: str = ""
    conversation_summary: str = ""
    history: tuple[ToolHistoryTurn, ...] = ()
    rounds: tuple[ToolRound, ...] = ()
    correction: ToolCorrection | None = None


@dataclass(frozen=True, slots=True)
class ToolTurnStep:
    """Exactly one of the two is set: the model asked for `tool_calls`, or gave its `answer`.
    `usage` is content-free metadata (token counts, latency), never text."""

    tool_calls: tuple[ToolCall, ...] = ()
    answer: LanguageModelAnswer | None = None
    usage: Mapping[str, int] = field(default_factory=dict)
    provider_state: object | None = None


class ToolCallingProvider(Protocol):
    """The seam the Mia orchestrator depends on. A real implementation MUST bound each call with
    its own timeout and raise `LanguageModelUnavailableError` - never a raw vendor exception - on
    any failure, and MUST NEVER log the request or any tool argument/result (only safe metadata)."""

    def next_step(self, request: ToolTurnRequest) -> ToolTurnStep: ...


__all__ = [
    "ReasoningLevel",
    "ToolCall",
    "ToolCallingProvider",
    "ToolCorrection",
    "ToolHistoryTurn",
    "ToolOutcome",
    "ToolRound",
    "ToolSpec",
    "ToolTurnRequest",
    "ToolTurnStep",
]
