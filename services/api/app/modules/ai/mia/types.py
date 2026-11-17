"""Constants and value types shared across Mia. No behaviour, no I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.ai.ask_ninfa.types import AskStatus

# A wording change of the system policy bumps this string, never a silent edit
# (`test_mia_instructions.py` pins the invariants a future wording change must keep).
MIA_INSTRUCTIONS_VERSION = "mia-v1-6"

# --- bounds of ONE user turn --------------------------------------------------------------------
# A bounded, read-only assistant - never an autonomous agent. The model may ask for NINFA facts in
# at most `MAX_TOOL_ROUNDS` rounds (each round may hold several independent calls), at most
# `MAX_TOOL_CALLS_PER_TURN` calls in all, then it MUST answer: the model call after the last allowed
# round is made WITHOUT tools. A broad question ("com'è la situazione dell'hotel?") touches four
# areas plus the decisions and the data status, which is why the cap is eight and not four.
MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS_PER_TURN = 8
# ... plus AT MOST ONE correction: an answer whose figures the application could not ground (or
# that stops in the middle of a sentence) gets one more call, without tools, to be rewritten from
# the data already gathered. Never a second chance after that: the turn then fails closed.
MAX_CORRECTIONS_PER_TURN = 1
MAX_MODEL_CALLS_PER_TURN = MAX_TOOL_ROUNDS + 1 + MAX_CORRECTIONS_PER_TURN
# The whole turn (every model call and every tool) must finish within this budget, or it fails
# closed. Each provider call has its own, shorter timeout on top.
TURN_DEADLINE_SECONDS = 90.0
# One observation is a small semantic aggregate, never a table dump: a result larger than this is a
# bug in a tool (or an unbounded argument), reported to the model as an error instead of truncated.
MAX_OBSERVATION_CHARS = 12000
MAX_TOOL_ERROR_CHARS = 400

# A short answer for a simple question, an articulated one for an analysis: the ceiling is for the
# second. An answer above it is not cut (a cut answer is a wrong answer): it fails validation.
MAX_MIA_ANSWER_CHARS = 3200

# The ref a general-knowledge explanation carries ("Cos'è il RevPAR?"): an explicit, structured
# marker that the answer is NOT about the property's data. It also keeps the closed ref vocabulary
# of the structured output non-empty on a turn that called no tool.
GENERAL_KNOWLEDGE_REF = "knowledge:general"

JsonObject = Mapping[str, Any]

# What an observation IS, internally (the user never sees these words):
# fact a value NINFA stores or calculated deterministically (occupancy, a decision's numbers)
# product what NINFA itself is (a section, a feature, a term) - the Product Knowledge Registry
ObservationKind = Literal["fact", "product"]


@dataclass(frozen=True, slots=True)
class Gap:
    """A figure a tool is ABOUT and cannot (fully) give, and why - the structured form of "NINFA has
    only part of what this metric needs".

    `metric` names one of the metrics of `completeness.GAP_METRICS` (a closed table: the words a
    person uses to ask for it, the words an honest answer uses to say it cannot be given, and its
    label). `reason` is ONE clause, written by the tool from what it really read, that reads after a
    colon ("per quella notte NINFA non sa quante camere ci sono"). `partial` is False when the
    figure cannot be given at all and True when it is given but rests on only part of what was
    asked.

    It is evidence, not decoration: `completeness.undisclosed_gaps` checks, in code, that an answer
    to a person who ASKED for that metric says it, and the orchestrator adds the sentence itself
    when the answer did not (ADR 0055, "truthfulness closure")."""

    metric: str
    reason: str
    partial: bool = False


@dataclass(frozen=True, slots=True)
class Observation:
    """What a tool returns: a small, labelled, semantic aggregate - never a row, an id of a guest or
    SQL.

    `data` is a JSON-able mapping with plain-Italian keys, so a model that echoes a key produces
    natural Italian. `refs` are the grounding refs this observation offers: the answer's
    `grounding_refs` may name only refs of the observations of THIS turn.

    COVERAGE and FRESHNESS are first-class, not decoration: `coverage` says how much of what was
    asked the figures actually cover ("7 notti su 30"), `freshness` says how recent and what kind of
    data it is (last import, observed or reconstructed). A figure with no coverage statement is a
    figure that covers all it claims to. `not_available` lists, in plain Italian, what NINFA cannot
    determine for what was asked; `notes` say how to read the figures. `resolved` is the (validated,
    fully resolved) arguments the tool ran with - it feeds the conversation trace, never the
    user."""

    tool: str
    refs: tuple[str, ...]
    data: JsonObject
    coverage: JsonObject | None = None
    freshness: JsonObject | None = None
    not_available: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    resolved: JsonObject = field(default_factory=dict)
    kind: ObservationKind = "fact"
    gaps: tuple[Gap, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolTrace:
    """One executed (or refused) tool call of a turn, as the conversation remembers it: which tool,
    with which RESOLVED arguments, which refs it produced. Written by the server from validated
    values - never taken from the model's text or the client."""

    tool: str
    arguments: JsonObject
    refs: tuple[str, ...]
    failed: bool = False


@dataclass(frozen=True, slots=True)
class TurnMetrics:
    """What a turn cost and how it went, WITHOUT any content (the observability record): counts,
    names, durations, token usage, the failure kind. Never a question, an argument, a result, an
    answer or a chain of thought."""

    model_calls: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    corrected: bool = False
    reasoning: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    provider_latency_ms: int = 0
    elapsed_ms: int = 0
    failure_kind: str | None = None
    unavailable_reason: str | None = None
    # How many missing figures the application had to ADD to the answer (the model had not said
    # them), and whether the whole answer was the boundary of the open property. Counts only.
    gap_disclosures: int = 0
    boundary: bool = False


@dataclass(frozen=True, slots=True)
class MiaTurnResult:
    """The outcome of one user message. `answer` is `None` for REFUSED/UNAVAILABLE."""

    status: AskStatus
    answer: str | None
    grounding_refs: tuple[str, ...]
    limitations: tuple[str, ...]
    trace: tuple[ToolTrace, ...] = ()
    metrics: TurnMetrics = field(default_factory=TurnMetrics)

    @property
    def tool_calls(self) -> int:
        return self.metrics.tool_calls

    @property
    def model_calls(self) -> int:
        return self.metrics.model_calls


__all__ = [
    "GENERAL_KNOWLEDGE_REF",
    "MAX_CORRECTIONS_PER_TURN",
    "MAX_MIA_ANSWER_CHARS",
    "MAX_MODEL_CALLS_PER_TURN",
    "MAX_OBSERVATION_CHARS",
    "MAX_TOOL_CALLS_PER_TURN",
    "MAX_TOOL_ERROR_CHARS",
    "MAX_TOOL_ROUNDS",
    "MIA_INSTRUCTIONS_VERSION",
    "TURN_DEADLINE_SECONDS",
    "Gap",
    "JsonObject",
    "MiaTurnResult",
    "Observation",
    "ObservationKind",
    "ToolTrace",
    "TurnMetrics",
]
