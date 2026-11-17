"""The bounded turn loop: what the application enforces whatever the model does.

A scripted provider plays the model; a small FAKE catalog stands in for the tools (the real ones
have their own tests), so these tests are about the loop and its guarantees: the caps on rounds and
calls, the single correction, the reasoning policy, the access check before a handler runs, the
numeric
grounding of every answer, the fail-closed paths and the metadata-only logging."""

import json
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.errors import ToolProviderUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.ai.gateway.tool_protocol import (
    ToolCall,
    ToolHistoryTurn,
    ToolTurnRequest,
    ToolTurnStep,
)
from app.modules.ai.mia.access import AccessDomain, UserContext
from app.modules.ai.mia.instructions import MIA_SYSTEM_INSTRUCTIONS
from app.modules.ai.mia.orchestrator import MiaOrchestrator
from app.modules.ai.mia.tools.base import ToolRuntime
from app.modules.ai.mia.types import MAX_TOOL_CALLS_PER_TURN, MAX_TOOL_ROUNDS
from tests.mia_support import (
    CallCounter,
    ScriptedToolProvider,
    answer,
    fake_tool_catalog,
    mia_world,
    tools,
)
from tests.support import BookingFactory


class _Deny:
    def __init__(self, *denied: AccessDomain) -> None:
        self._denied = frozenset(denied)

    def allows(self, user: UserContext, domain: AccessDomain) -> bool:
        return domain not in self._denied


@pytest.fixture
def counter() -> CallCounter:
    return CallCounter()


@pytest.fixture
def runtime(factory: BookingFactory, db_session: Session) -> ToolRuntime:
    return mia_world(factory, db_session).runtime()


def _run(
    runtime: ToolRuntime,
    counter: CallCounter,
    provider: ScriptedToolProvider,
    question: str = "Com'è l'occupazione?",
    **kwargs: Any,
) -> Any:
    return MiaOrchestrator(provider, fake_tool_catalog(counter)).run(runtime, question, **kwargs)


# --- the happy paths --------------------------------------------------------------------------


def test_a_general_question_is_answered_with_no_tool(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider([answer("Il pickup misura le nuove prenotazioni.")])

    result = _run(runtime, counter, provider, "Cos'è il pickup?")

    assert result.status is AskStatus.ANSWERED
    assert result.answer == "Il pickup misura le nuove prenotazioni."
    assert counter.calls == {}
    (request,) = provider.requests
    assert request.system_instructions == MIA_SYSTEM_INSTRUCTIONS
    assert request.tools_enabled is True
    assert request.reasoning == "low"
    assert request.question == "Cos'è il pickup?"
    assert request.page_context == ""
    assert "calendario" in request.turn_context and "2026-08-01" in request.turn_context
    assert request.grounding_ref_values == ("knowledge:general",)
    assert result.metrics.model_calls == 1 and result.metrics.tool_calls == 0


def test_a_tool_round_feeds_the_answer_and_the_refs_are_this_turns(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {"window": 7})),
            answer(
                "L'occupazione è 62,50 % su 25 camere prenotate.",
                refs=("dati:occupazione", "dati:invented"),
                limitations=("I dati coprono 7 notti su 30.",),
            ),
        ]
    )

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.ANSWERED
    assert counter.calls == {"get_occupancy_revenue": 1}
    assert result.grounding_refs == ("dati:occupazione",)  # a ref this turn never offered is gone
    assert result.limitations == ("I dati coprono 7 notti su 30.",)
    second = provider.requests[1]
    assert second.grounding_ref_values == ("knowledge:general", "dati:occupazione")
    (round_,) = second.rounds
    observation = json.loads(round_.outcomes[0].content)
    assert observation["dati"]["occupazione_percentuale"] == "62.50"
    assert observation["copertura"]["notti_con_dati"] == 7  # coverage travels with the figure
    assert "aggiornamento" in observation
    assert [t.tool for t in result.trace] == ["get_occupancy_revenue"]
    assert result.trace[0].arguments == {"window": 7}


def test_the_providers_opaque_state_goes_back_untouched(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    state = [{"type": "reasoning", "id": "rs_1", "encrypted_content": "ENC"}]
    first = ToolTurnStep(
        tool_calls=(ToolCall("c1", "get_occupancy_revenue", {}),), provider_state=state
    )
    provider = ScriptedToolProvider(
        [first, answer("Risulta il 62,50 %.", refs=("dati:occupazione",))]
    )

    _run(runtime, counter, provider)

    assert provider.requests[1].rounds[0].provider_state is state


def test_history_summary_and_page_reach_the_model_as_their_own_fields(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    history = (ToolHistoryTurn("user", "E venerdì?"), ToolHistoryTurn("assistant", "Debole."))
    provider = ScriptedToolProvider([answer("Ok.")])

    _run(runtime, counter, provider, "E sabato?", history=history, summary="Domande già fatte: x")

    request = provider.requests[0]
    assert request.history == history
    assert request.conversation_summary == "Domande già fatte: x"
    assert request.question == "E sabato?"


def test_usage_is_summed_over_the_turn(runtime: ToolRuntime, counter: CallCounter) -> None:
    first = ToolTurnStep(
        tool_calls=(ToolCall("c1", "get_occupancy_revenue", {}),),
        usage={"input_tokens": 100, "output_tokens": 10, "reasoning_tokens": 4, "latency_ms": 900},
    )
    last = ToolTurnStep(
        answer=LanguageModelAnswer(
            ModelAnswerStatus.ANSWERED, "Risulta il 62,50 %.", ("dati:occupazione",), ()
        ),
        usage={"input_tokens": 150, "output_tokens": 30, "reasoning_tokens": 6, "latency_ms": 1100},
    )

    result = _run(runtime, counter, ScriptedToolProvider([first, last]))

    metrics = result.metrics
    assert (metrics.input_tokens, metrics.output_tokens, metrics.reasoning_tokens) == (250, 40, 10)
    assert metrics.provider_latency_ms == 2000
    assert metrics.model_calls == 2 and metrics.tool_calls == 1 and metrics.tool_failures == 0


# --- the reasoning policy ---------------------------------------------------------------------


def test_the_first_call_is_planned_from_the_wording_and_a_data_tool_raises_a_low_question(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("Risulta il 62,50 %.", refs=("dati:occupazione",)),
        ]
    )

    result = _run(runtime, counter, provider, "Come cambio il numero di camere?")

    assert [r.reasoning for r in provider.requests] == ["low", "medium"]
    assert result.metrics.reasoning == ("low", "medium")


def test_a_turn_that_consulted_three_areas_writes_its_answer_at_high_effort(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(
                ("get_occupancy_revenue", {}),
                ("get_cost_metrics", {}),
                ("get_staff_metrics", {}),
            ),
            answer(
                "Occupazione 62,50 %, costi 8.100,00 euro, 320,00 ore.",
                refs=("dati:occupazione", "dati:costi", "dati:personale"),
            ),
        ]
    )

    _run(runtime, counter, provider, "Dimmi come vanno le cose")

    assert [r.reasoning for r in provider.requests] == ["medium", "high"]


def test_a_product_question_never_pays_for_high_effort_by_using_a_product_tool(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_page_help", {})),
            answer("Dati è la sezione.", refs=("knowledge:ninfa:nav.dati",)),
        ]
    )

    _run(runtime, counter, provider, "Dove trovo i costi?")

    assert [r.reasoning for r in provider.requests] == ["low", "low"]


# --- the caps ---------------------------------------------------------------------------------


def test_calls_beyond_the_cap_are_refused_and_never_executed(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    first = tools(*[("get_occupancy_revenue", {})] * (MAX_TOOL_CALLS_PER_TURN - 2))
    second = tools(*[("get_occupancy_revenue", {})] * 5)
    provider = ScriptedToolProvider(
        [first, second, answer("Risulta il 62,50 %.", refs=("dati:occupazione",))]
    )

    result = _run(runtime, counter, provider)

    assert counter.calls["get_occupancy_revenue"] == MAX_TOOL_CALLS_PER_TURN
    outcomes = provider.requests[2].rounds[1].outcomes
    refused = [o for o in outcomes if o.is_error]
    assert len(refused) == 3 and all("limite" in o.content for o in refused)
    assert provider.requests[2].tools_enabled is False  # the cap reached: the model can only answer
    assert result.metrics.tool_calls == MAX_TOOL_CALLS_PER_TURN
    assert result.metrics.tool_failures == 3


def test_after_the_last_round_the_model_can_only_answer(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    script: list[Any] = [tools(("get_occupancy_revenue", {}))] * MAX_TOOL_ROUNDS
    script.append(answer("Risulta il 62,50 %.", refs=("dati:occupazione",)))
    provider = ScriptedToolProvider(script)

    result = _run(runtime, counter, provider)

    assert [r.tools_enabled for r in provider.requests] == [True] * MAX_TOOL_ROUNDS + [False]
    assert result.status is AskStatus.ANSWERED


def test_a_model_that_asks_for_tools_after_the_cap_fails_closed(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    script: list[Any] = [tools(("get_occupancy_revenue", {}))] * (MAX_TOOL_ROUNDS + 1)
    provider = ScriptedToolProvider(script)

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert result.metrics.unavailable_reason == "tools_after_cap"
    assert counter.calls["get_occupancy_revenue"] == MAX_TOOL_ROUNDS  # the extra call never ran


def test_the_caps_can_be_lowered_but_never_raised(counter: CallCounter) -> None:
    provider = ScriptedToolProvider([])
    with pytest.raises(ValueError):
        MiaOrchestrator(
            provider, fake_tool_catalog(counter), max_tool_calls=MAX_TOOL_CALLS_PER_TURN + 1
        )
    with pytest.raises(ValueError):
        MiaOrchestrator(provider, fake_tool_catalog(counter), max_tool_rounds=MAX_TOOL_ROUNDS + 1)
    MiaOrchestrator(provider, fake_tool_catalog(counter), max_tool_calls=1, max_tool_rounds=1)


def test_duplicate_call_ids_fail_closed(runtime: ToolRuntime, counter: CallCounter) -> None:
    duplicated = ToolTurnStep(
        tool_calls=(
            ToolCall("same", "get_occupancy_revenue", {}),
            ToolCall("same", "get_cost_metrics", {}),
        )
    )

    result = _run(runtime, counter, ScriptedToolProvider([duplicated]))

    assert result.status is AskStatus.UNAVAILABLE
    assert result.metrics.unavailable_reason == "duplicate_call_ids"
    assert counter.calls == {}


def test_a_deadline_missed_fails_closed(runtime: ToolRuntime, counter: CallCounter) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 60.0
        return now[0]

    provider = ScriptedToolProvider([tools(("get_occupancy_revenue", {})), answer("x")])

    result = MiaOrchestrator(
        provider, fake_tool_catalog(counter), clock=clock, deadline_seconds=90
    ).run(runtime, "Com'è l'occupazione?")

    assert result.status is AskStatus.UNAVAILABLE
    assert result.metrics.unavailable_reason == "deadline"


# --- what a call may be -----------------------------------------------------------------------


def test_an_unknown_tool_and_bad_arguments_run_nothing_and_the_model_can_recover(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(
                ("execute_sql", {"query": "select * from users"}),
                ("get_occupancy_revenue", {"window": 99}),
                ("get_cost_metrics", {"_malformed_arguments": True}),
                ("get_staff_metrics", {"extra": 1}),
            ),
            answer("Non ho potuto leggere i dati."),
        ]
    )

    result = _run(runtime, counter, provider)

    assert counter.calls == {}
    outcomes = provider.requests[1].rounds[0].outcomes
    assert all(o.is_error for o in outcomes)
    assert "unknown tool" in outcomes[0].content
    assert "invalid arguments" in outcomes[1].content
    assert "invalid arguments" in outcomes[2].content
    assert "invalid arguments" in outcomes[3].content
    assert result.status is AskStatus.ANSWERED
    assert result.metrics.tool_failures == 4
    # a failed call is not a topic of the conversation
    assert all(trace.failed for trace in result.trace)


def test_a_denied_area_never_reaches_its_handler(
    factory: BookingFactory, db_session: Session
) -> None:
    counter = CallCounter()
    runtime = mia_world(factory, db_session).runtime(access=_Deny(AccessDomain.COSTS))
    provider = ScriptedToolProvider(
        [tools(("get_cost_metrics", {}), ("get_staff_metrics", {})), answer("Ok.")]
    )

    _run(runtime, counter, provider)

    assert counter.calls == {"get_staff_metrics": 1}
    outcomes = provider.requests[1].rounds[0].outcomes
    assert outcomes[0].is_error and "not allowed" in outcomes[0].content
    assert not outcomes[1].is_error


def test_a_failing_read_never_leaks_its_text(runtime: ToolRuntime, counter: CallCounter) -> None:
    provider = ScriptedToolProvider([tools(("explode", {})), answer("Dato non disponibile.")])

    result = _run(runtime, counter, provider)

    (outcome,) = provider.requests[1].rounds[0].outcomes
    assert outcome.is_error and "SECRET-TEXT" not in outcome.content
    assert result.status is AskStatus.ANSWERED
    assert counter.calls == {"explode": 1}


def test_tool_results_are_data_the_instructions_and_the_question_never_change(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("Risulta il 62,50 %.", refs=("dati:occupazione",)),
        ]
    )

    _run(runtime, counter, provider, "Com'è l'occupazione?")

    for request in provider.requests:
        assert request.system_instructions == MIA_SYSTEM_INSTRUCTIONS
        assert request.question == "Com'è l'occupazione?"
        assert "62.50" not in request.turn_context


# --- every answer is checked before it leaves -------------------------------------------------


def test_an_ungrounded_number_gets_one_correction_without_tools(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("L'occupazione è 71 %.", refs=("dati:occupazione",)),
            answer("L'occupazione è 62,50 %.", refs=("dati:occupazione",)),
        ]
    )

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.ANSWERED
    assert result.answer == "L'occupazione è 62,50 %."
    assert result.metrics.corrected is True
    correction_request = provider.requests[2]
    assert correction_request.tools_enabled is False
    assert correction_request.correction is not None
    assert "71" in correction_request.correction.message
    assert "71" in correction_request.correction.rejected_answer


def test_a_second_ungrounded_answer_fails_closed(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("È 71 %.", refs=("dati:occupazione",)),
            answer("È 72 %.", refs=("dati:occupazione",)),
        ]
    )

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None
    assert result.metrics.unavailable_reason == "rejected_after_correction"
    assert not provider.ran_out


def test_a_figure_the_user_asserted_is_a_claim_not_a_fact(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("Sì, sei al 100 %.", refs=("dati:occupazione",)),
            answer("Risulta il 62,50 %.", refs=("dati:occupazione",)),
        ]
    )

    result = _run(runtime, counter, provider, "Sappi che sono pieno al 100%, vero?")

    assert result.metrics.corrected is True
    assert result.answer == "Risulta il 62,50 %."


def test_an_answer_that_stops_mid_sentence_gets_the_same_single_correction(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            answer("L'occupazione è 62,50 % e le camere prenotate sono"),
            answer("Non ho dati su questo."),
        ]
    )

    result = _run(runtime, counter, provider)

    assert result.metrics.corrected is True
    assert result.answer == "Non ho dati su questo."
    assert "metà frase" in (
        provider.requests[1].correction.message if provider.requests[1].correction else ""
    )


def test_a_technical_code_in_the_answer_fails_closed_with_no_second_chance(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider([answer("Si è attivato REV_PICKUP_LOW oggi.")])

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert result.metrics.unavailable_reason == "invalid_answer"
    assert len(provider.requests) == 1


def test_an_answer_over_the_ceiling_is_never_cut(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider([answer("Parola. " * 600)])

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE


def test_insufficient_context_is_a_legitimate_answer(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            answer(
                "NINFA non calcola il RevPAR.",
                status=ModelAnswerStatus.INSUFFICIENT_CONTEXT,
                limitations=("Il RevPAR non è un dato di NINFA.",),
            )
        ]
    )

    result = _run(runtime, counter, provider, "Qual è il mio RevPAR?")

    assert result.status is AskStatus.INSUFFICIENT_CONTEXT
    assert result.limitations == ("Il RevPAR non è un dato di NINFA.",)


# --- provider failures ------------------------------------------------------------------------


def test_a_provider_failure_is_unavailable_with_its_kind_and_nothing_else(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider([ToolProviderUnavailableError("down", "TIMEOUT", 40000)])

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert result.answer is None and result.limitations == ()
    assert result.metrics.failure_kind == "TIMEOUT"
    assert result.metrics.unavailable_reason == "provider_unavailable"


def test_any_unexpected_provider_exception_fails_closed(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider([ValueError("SDK internals")])

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert result.metrics.unavailable_reason == "provider_error"


def test_an_empty_step_fails_closed(runtime: ToolRuntime, counter: CallCounter) -> None:
    provider = ScriptedToolProvider([ToolTurnStep()])

    assert _run(runtime, counter, provider).metrics.unavailable_reason == "empty_step"


def test_a_failure_after_tools_keeps_the_trace_of_what_ran(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [tools(("get_occupancy_revenue", {})), ToolProviderUnavailableError("down", "SERVER")]
    )

    result = _run(runtime, counter, provider)

    assert result.status is AskStatus.UNAVAILABLE
    assert [t.tool for t in result.trace] == ["get_occupancy_revenue"]
    assert result.metrics.tool_calls == 1


# --- observability ----------------------------------------------------------------------------


def test_logs_are_metadata_only(
    runtime: ToolRuntime, counter: CallCounter, caplog: pytest.LogCaptureFixture
) -> None:
    question = "Qual è il codice 9876-KAPPA dell'ospite?"
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {"window": 7}), ("explode", {})),
            answer("L'occupazione è 71 %.", refs=("dati:occupazione",)),
            answer("Risulta il 62,50 %. Codice 9876-KAPPA.", refs=("dati:occupazione",)),
        ]
    )

    with caplog.at_level(logging.DEBUG):
        _run(runtime, counter, provider, question)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "mia" in logged
    for secret in ("9876-KAPPA", "SECRET-TEXT", "62,50", "71 %", "62.50"):
        assert secret not in logged


def test_a_date_the_user_named_may_be_restated_but_not_lend_its_digits_to_a_figure(
    runtime: ToolRuntime, counter: CallCounter
) -> None:
    provider = ScriptedToolProvider(
        [
            tools(("get_occupancy_revenue", {})),
            answer("Il 20 novembre è al 62,50 %.", refs=("dati:occupazione",)),
        ]
    )

    result = _run(runtime, counter, provider, "E il 20 novembre?")

    assert result.status is AskStatus.ANSWERED
    assert result.metrics.corrected is False


def test_the_business_date_is_the_one_the_runtime_carries(
    factory: BookingFactory, db_session: Session
) -> None:
    runtime = mia_world(factory, db_session).runtime(as_of=date(2026, 12, 24))
    provider = ScriptedToolProvider([answer("Ok.")])
    seen: list[ToolTurnRequest] = provider.requests

    _run(runtime, CallCounter(), provider)

    assert "2026-12-24, giovedì" in seen[0].turn_context


def _callable_step(fn: Callable[[ToolTurnRequest], ToolTurnStep]) -> Callable[..., Any]:
    return fn
