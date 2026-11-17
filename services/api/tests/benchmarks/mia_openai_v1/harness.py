"""Runs a scenario the way the route does, against a world, with a provider of the caller's choice.

The path is the production one - validate the question, refuse what the guardrail refuses (before
any
model), validate the screen hint, build the runtime, read the conversation back, run the bounded
orchestrator over the closed catalog, record an answered exchange - with three additions that only a
measurement needs: a recorder on everything sent to the provider, a listener on every statement the
database receives (a write outside the person's own conversation is a finding), and the option to
make
chosen tools fail.
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection

from app.modules.ai.ask_ninfa.guardrails import REFUSAL_COPY, classify_refusal
from app.modules.ai.ask_ninfa.question import validate_question
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.tool_protocol import ToolCallingProvider
from app.modules.ai.mia.conversation import MiaConversationService
from app.modules.ai.mia.orchestrator import MiaOrchestrator
from app.modules.ai.mia.tools.base import ToolCatalog, ToolDefinition, ToolRuntime
from app.modules.ai.mia.types import MiaTurnResult, Observation, TurnMetrics
from app.modules.ai.mia.ui_context import UiContext, build_page_context
from tests.benchmarks.mia_openai_v1.model import Scenario, Turn
from tests.benchmarks.mia_openai_v1.providers import RecordingProvider, resolver_for
from tests.benchmarks.mia_openai_v1.scoring import TurnRun, TurnScore, score_turn
from tests.benchmarks.mia_openai_v1.worlds import World

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE")


@dataclass
class TurnOutcome:
    run: TurnRun
    score: TurnScore
    metrics: TurnMetrics
    refused: bool = False


@dataclass
class ScenarioOutcome:
    scenario: Scenario
    turns: list[TurnOutcome] = field(default_factory=list)


@contextmanager
def watch_writes(connection: Connection) -> Iterator[list[str]]:
    """Every INSERT / UPDATE / DELETE (and any DDL) the connection executes, by its first words."""
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        text = statement.lstrip()
        if text.split(None, 1)[0].upper() in _WRITE_VERBS if text else False:
            seen.append(" ".join(text.split())[:120])

    event.listen(connection, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", record)


def failing_catalog(base: ToolCatalog, names: frozenset[str]) -> ToolCatalog:
    """The same closed catalog in which the named tools fail when read (a database error)."""

    def broken(runtime: ToolRuntime, args: Any) -> Observation:
        raise RuntimeError("a read failed")

    return ToolCatalog(
        [
            ToolDefinition(t.name, t.description, t.domain, t.args_model, broken)
            if t.name in names
            else t
            for t in base
        ]
    )


ProviderFor = Callable[[Scenario, int, Turn, World], ToolCallingProvider]


def run_scenario(
    scenario: Scenario,
    world: World,
    provider_for: ProviderFor,
    *,
    stop: Callable[[], bool] | None = None,
) -> ScenarioOutcome:
    """One conversation, turn by turn, in one world. `stop()` is asked before every turn (a spent
    budget ends the run without starting a turn it cannot finish)."""
    outcome = ScenarioOutcome(scenario)
    tenant = world.mia.runtime().tenant
    session = world.session
    service = MiaConversationService(session, tenant)
    conversation = None
    with watch_writes(session.connection()) as writes:
        for index, turn in enumerate(scenario.turns):
            if stop is not None and stop():
                break
            written_before = len(writes)
            recorder, result, refused = _turn(
                scenario, index, turn, world, provider_for, service, conversation
            )
            if result.status in (AskStatus.ANSWERED, AskStatus.INSUFFICIENT_CONTEXT):
                if conversation is None:
                    conversation = service.create(
                        world.property_id, world.mia.at.user.id, turn.message
                    )
                service.record_exchange(conversation, question=turn.message, result=result)
            catalog = world.mia.catalog
            run = TurnRun(
                scenario_id=scenario.id,
                category=scenario.category,
                index=index,
                message=turn.message,
                rubric=turn.rubric,
                world=world,
                result=result,
                requests=tuple(recorder.requests),
                bodies=tuple(recorder.bodies),
                catalog_names=frozenset(catalog.names),
                writes=tuple(writes[written_before:]),
                called=tuple(trace.tool for trace in result.trace),
            )
            outcome.turns.append(TurnOutcome(run, score_turn(run), result.metrics, refused))
    return outcome


def _turn(
    scenario: Scenario,
    index: int,
    turn: Turn,
    world: World,
    provider_for: ProviderFor,
    service: MiaConversationService,
    conversation: Any,
) -> tuple[RecordingProvider, MiaTurnResult, bool]:
    question = validate_question(turn.message)
    refusal = classify_refusal(question)
    if refusal is not None:
        refused = MiaTurnResult(
            status=AskStatus.REFUSED,
            answer=None,
            grounding_refs=(),
            limitations=(REFUSAL_COPY[refusal],),
        )
        return RecordingProvider(_Never()), refused, True

    resolve = resolver_for(world)
    ui = UiContext.model_validate(resolve(dict(turn.ui_context))) if turn.ui_context else None
    page = build_page_context(
        world.session, world.mia.runtime().tenant, world.property_id, ui, world.mia.registry
    )
    runtime = world.runtime(page=page)
    context = service.model_context(conversation)
    recorder = RecordingProvider(provider_for(scenario, index, turn, world))
    catalog = world.mia.catalog
    if turn.rubric.tool_failure:
        catalog = failing_catalog(catalog, turn.rubric.tool_failure)
    result = MiaOrchestrator(recorder, catalog).run(
        runtime, question, history=context.history, summary=context.summary
    )
    return recorder, result, False


class _Never:
    def next_step(self, request: Any) -> Any:  # pragma: no cover - a refused turn never asks
        raise AssertionError("a refused message must never reach the model")


def run_all(
    scenarios: Sequence[Scenario],
    get_world: Callable[[str], World],
    provider_for: ProviderFor,
    *,
    stop: Callable[[], bool] | None = None,
) -> list[ScenarioOutcome]:
    outcomes: list[ScenarioOutcome] = []
    for scenario in scenarios:
        if stop is not None and stop():
            break
        outcomes.append(run_scenario(scenario, get_world(scenario.world), provider_for, stop=stop))
    return outcomes


__all__ = [
    "ProviderFor",
    "ScenarioOutcome",
    "TurnOutcome",
    "failing_catalog",
    "run_all",
    "run_scenario",
    "watch_writes",
]
