"""The vocabulary of Mia's evaluation: a scenario, its turns, the rubric a turn is judged by and the
oracle that proves the rubric can be met.

A SCENARIO is a conversation about one WORLD (a synthetic hotel in a given state). Each TURN is a
message the person types (with, optionally, the validated screen hint the browser would send) and
carries:

* a RUBRIC - deterministic checks, no model-as-judge: which status is acceptable, which tools a
  competent answer must (or must never) use, what the answer must say and must not say, whether it
  must admit what is missing or hedge about freshness;
* an ORACLE - the tool calls and the answer a competent model would give, written with placeholders
  that resolve against the world's `truth` (numbers computed from the SAME services the tools use,
  never typed here). The oracle powers the offline mode: it plays the model through the REAL
  orchestrator, tools, worlds and scorer, so every rubric is proven satisfiable and every layer
  other than the model is exercised on the whole corpus.

Placeholders: `{truth.<key>}` in a `must_mention` alternative expands into every way a model may
write
the value (`62,50`, `62,5`, `62.50`, ...); in an oracle answer it renders the Italian form.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# The categories of the corpus and the minimum number of scenarios of each (the spec's).
CATEGORY_MINIMUMS: dict[str, int] = {
    "product_knowledge": 50,
    "how_to": 30,
    "data_interpretation": 50,
    "decision_explanation": 30,
    "multi_domain": 25,
    "missing_data": 20,
    "data_quality_stale": 20,
    "import_smart_import": 30,
    "security_adversarial": 20,
    "conversation_follow_up": 20,
}

# A tool call as an oracle (or a test) writes it: (tool name, arguments). Arguments may hold
# `"$decision:<TYPE>"` / `"$import:<n>"` placeholders that the runner resolves against the world.
Call = tuple[str, Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class Rubric:
    """What a good turn looks like. Every field has a neutral default: a rubric states only what the
    turn is about."""

    # statuses a good answer may have (a refusal scenario says {"REFUSED"})
    expect_status: frozenset[str] = frozenset({"ANSWERED"})
    # alternative SETS of tools: a good answer called every tool of at least one of them
    expected_tools_any: tuple[frozenset[str], ...] = ()
    forbidden_tools: frozenset[str] = frozenset()
    # the answer comes from product knowledge, general knowledge or a clarification: no tool at all
    no_tool: bool = False
    # a question this simple (or this broad) needs at most this many tool calls
    max_tool_calls: int = 4
    # each group: at least one alternative must appear (accent/case-insensitive); an alternative may
    # carry `{truth.key}` placeholders
    must_mention: tuple[tuple[str, ...], ...] = ()
    # regular expressions the answer must not match (case-insensitive)
    must_not_mention: tuple[str, ...] = ()
    # the answer has to say that something is not available / not known, and not guess it
    must_state_missing: bool = False
    # the data is not from today: the answer says "the last available data", never "today"
    freshness_hedge: bool = False
    # a decision is named or counted: it must match what the world's feed really holds
    decision_claims: bool = False
    # a general-knowledge turn: no property fact may be stated (no tools, no figures)
    general_knowledge: bool = False
    # these tools fail (a read error) during the turn: the answer must say the data is unavailable
    tool_failure: frozenset[str] = frozenset()
    # a later turn that depends on an earlier one: scored as multi-turn reference accuracy
    follow_up: bool = False
    # the turn tries something hostile: prompt injection success etc. are watched by the zero
    # counters on EVERY turn, this flag only marks it for the report
    adversarial: bool = False


@dataclass(frozen=True, slots=True)
class Oracle:
    """What a competent model does: rounds of tool calls, then the answer (a template)."""

    rounds: tuple[tuple[Call, ...], ...] = ()
    answer: str = ""
    status: str = "ANSWERED"
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Turn:
    message: str
    rubric: Rubric
    oracle: Oracle
    # what the browser would send about the screen (validated by the server like in production)
    ui_context: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    category: str
    world: str
    turns: tuple[Turn, ...]
    # tags used by the report (family of cost: simple product / data-aware / multi-tool)
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def family(self) -> str:
        """The cost family of a scenario: the product question, the data-aware one, the multi-
        tool."""
        calls = max(
            (sum(len(r) for r in turn.oracle.rounds) for turn in self.turns),
            default=0,
        )
        if self.category in ("product_knowledge", "how_to"):
            return "simple_product"
        if calls >= 3:
            return "multi_tool"
        return "data_aware"


def rubric(**kwargs: Any) -> Rubric:
    """`rubric(tools={"a"}, ...)`-style construction with the common shorthands."""
    if "tools" in kwargs:
        sets = kwargs.pop("tools")
        kwargs["expected_tools_any"] = tuple(frozenset(s) for s in sets)
    for name in ("expect_status", "forbidden_tools", "tool_failure"):
        if name in kwargs:
            kwargs[name] = frozenset(kwargs[name])
    if "must_mention" in kwargs:
        kwargs["must_mention"] = tuple(tuple(g) for g in kwargs["must_mention"])
    if "must_not_mention" in kwargs:
        kwargs["must_not_mention"] = tuple(kwargs["must_not_mention"])
    return Rubric(**kwargs)


__all__ = [
    "CATEGORY_MINIMUMS",
    "Call",
    "Oracle",
    "Rubric",
    "Scenario",
    "Turn",
    "rubric",
]
