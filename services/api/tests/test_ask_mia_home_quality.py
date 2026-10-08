"""Mia Home response quality (`ask-mia-home-v2`): context sufficiency for rich, grounded answers.

WHAT THIS FILE PROVES, AND WHAT IT DOES NOT. A deterministic test cannot prove that a language model
writes a good answer. What it CAN prove - and what this codebase owns - is that (1) the context the
model is handed contains every piece of information a rich, concrete, grounded answer needs for each
of the Home's questions and feed states, (2) a rich answer of the length the instructions ask for
travels the whole pipeline intact (validated, never truncated, line breaks preserved), and (3) the
Decision Ask's own limits did not move. `ContextReadingProvider` (`tests/ask_home_answers.py`)
composes each answer by reading ONLY the context string a real provider would receive: if the
context lacked a needed field, composing would fail and so would the test. It says nothing about
whether the real model follows the instructions - that needs the real Anthropic smoke test.
"""

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.ai.ask_ninfa.answer_validation import (
    validate_model_answer,
    validate_model_answer_core,
)
from app.modules.ai.ask_ninfa.home_types import MAX_HOME_ANSWER_CHARS
from app.modules.ai.ask_ninfa.types import MAX_ANSWER_CHARS, AskStatus
from app.modules.ai.gateway.anthropic_provider import (
    _MAX_OUTPUT_TOKENS,
    _MAX_OUTPUT_TOKENS_LONG_ANSWER,
    _max_tokens_for,
)
from app.modules.ai.gateway.protocol import (
    LanguageModelAnswer,
    LanguageModelRequest,
    ModelAnswerStatus,
)
from app.modules.intelligence.revenue.types import RevenueDecisionType
from tests.ask_home_answers import ContextReadingProvider, italian_date, ungrounded_numbers
from tests.ask_home_support import (
    D1,
    STAY,
    answered_provider,
    ask_home_url,
    booking_only_coverage,
    five_triggered_evaluations,
    full_coverage,
    known_provenance,
    sync_feed,
    utc,
)
from tests.ask_ninfa_support import with_fake_provider
from tests.decision_api_support import AuthedTenant, authed_tenant
from tests.decision_support import CLEAR, INSUFFICIENT, ota_evaluation, revenue_evaluation
from tests.support import BookingFactory

Q_OTHER = "Ci sono altri problemi oltre a questo?"
Q_PRIORITY = "Qual è la priorità più urgente oggi?"
Q_IMPACT = "Quale decisione ha l'impatto economico più alto?"
Q_DATA = "Quali dati ha usato NINFA oggi?"
Q_COSTS = "Come stanno andando i costi?"
Q_DISTRIBUTION = "E la distribuzione, come va?"
Q_WHY = "Perché?"

_Seeder = Callable[..., AuthedTenant]


def _revenue(at: AuthedTenant, **kwargs: Any) -> Any:
    tenant = at.tenant
    return revenue_evaluation(
        workspace_id=tenant.workspace.id,
        property_id=tenant.property.id,
        data_source_id=tenant.data_source.id,
        snapshot_local_date=D1,
        **kwargs,
    )


def _seed_three(
    factory: BookingFactory, authenticated_as: Callable[[UUID], None], db_session: Session
) -> AuthedTenant:
    """Two Revenue decisions + one Distribution one, Revenue+Distribution analysed only."""
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    sync_feed(
        db_session,
        tenant,
        [
            _revenue(at, stay_date=STAY),
            _revenue(
                at,
                stay_date=STAY.replace(day=22),
                decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
            ),
            ota_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                booking_data_source_id=tenant.data_source.id,
                as_of_local_date=D1,
            ),
        ],
        coverage=booking_only_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),  # 09:31 in Europe/Rome
    )
    return at


def _seed_five(
    factory: BookingFactory, authenticated_as: Callable[[UUID], None], db_session: Session
) -> AuthedTenant:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        five_triggered_evaluations(factory, at.tenant),
        coverage=full_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),
    )
    return at


def _seed_single(
    factory: BookingFactory, authenticated_as: Callable[[UUID], None], db_session: Session
) -> AuthedTenant:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        [_revenue(at, stay_date=STAY)],
        coverage=booking_only_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),
    )
    return at


def _seed_revenue_only_pair(
    factory: BookingFactory, authenticated_as: Callable[[UUID], None], db_session: Session
) -> AuthedTenant:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        [
            _revenue(at, stay_date=STAY),
            _revenue(
                at,
                stay_date=STAY.replace(day=22),
                decision_type=RevenueDecisionType.REV_OCCUPANCY_RISK,
            ),
        ],
        coverage=booking_only_coverage(),
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),
    )
    return at


def _ask(
    api_client: TestClient,
    app: FastAPI,
    at: AuthedTenant,
    question: str,
    *,
    as_of: str = "2026-08-01",
) -> tuple[dict[str, Any], ContextReadingProvider, dict[str, Any]]:
    """Asks through the real route with the context-reading stand-in, and checks the invariants
    every answer must satisfy regardless of scenario: it was accepted by the real validation (not
    UNAVAILABLE), fits the Home ceiling, and every figure in it occurs in the context."""
    provider = ContextReadingProvider()
    with_fake_provider(app)(provider)
    response = api_client.post(
        ask_home_url(at.tenant.property.id),
        json={"question": question, "as_of_local_date": as_of},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"ANSWERED", "INSUFFICIENT_CONTEXT"}, body
    assert len(body["answer"]) <= MAX_HOME_ANSWER_CHARS
    assert ungrounded_numbers(body["answer"], provider.last_request.context) == []
    return body, provider, json.loads(provider.last_request.context)


# --- 1. "Ci sono altri problemi oltre a questo?" -------------------------------------------


def test_1_other_problems_answers_yes_and_lists_every_other_decision_with_details(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_OTHER)

    decisions = context["decisioni in ordine di priorità"]
    primary, others = decisions[0], decisions[1:]
    assert len(others) == 2
    answer = body["answer"]
    assert answer.startswith("Sì")
    for other in others:  # ALL the others, each with its area and what it is about
        assert other["decisione"] in answer
        assert other["area"] in answer
        for value in other["riguarda"].values():
            assert italian_date(value) in answer
    assert "stima indicativa" in answer  # the estimate, labelled as such
    assert f"({primary['area']})" not in answer.split("\n", 1)[0]  # the primary is not re-listed
    # the areas NINFA did not analyse are named: never an implied "all fine"
    assert "Costi" in answer and "Personale" in answer


def test_1_other_problems_in_the_full_feed_enumerates_all_four_others(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_five(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_OTHER)

    decisions = context["decisioni in ordine di priorità"]
    assert len(decisions) == 5
    listed = [line for line in body["answer"].splitlines() if line.startswith("- ")]
    assert len(listed) == 4  # every other decision, one line each, none dropped
    for other in decisions[1:]:
        assert any(other["decisione"] in line and other["area"] in line for line in listed)
    assert len(body["answer"].split()) <= 220


def test_1_a_single_decision_means_no_other_actionable_decisions(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_single(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_OTHER)

    assert context["numero di decisioni che richiedono attenzione"] == 1
    assert body["answer"].startswith("No")
    assert "non ha rilevato altre decisioni" in body["answer"]
    assert "- " not in body["answer"].split("\n\n")[0]  # nothing invented to fill a list
    assert "Costi" in body["answer"]  # an unanalysed area is still not "all clear"


# --- 2. "Qual è la priorità più urgente oggi?" ---------------------------------------------------


def test_2_priority_names_the_first_decision_and_explains_it_with_its_own_data(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_PRIORITY)

    first = context["decisioni in ordine di priorità"][0]
    assert first["posizione nell'ordine di NINFA"] == "prima"
    answer = body["answer"]
    assert first["decisione"] in answer and first["area"] in answer
    assert first["descrizione"] in answer  # what NINFA checked, in plain Italian
    assert first["dati"], "the first decision carries its own facts"
    assert first["dati"][0]["valore"] in answer  # a concrete figure from the decision itself
    assert "su 100" in answer  # reliability on its 0-100 scale
    assert "stima indicativa" in answer
    assert "più prioritaria per NINFA" in answer  # in words - never a position number or a score


# --- 3. "Quale decisione ha l'impatto economico più alto?" -------------------------------------


def test_3_estimates_of_different_kinds_are_called_not_directly_comparable(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_five(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_IMPACT)

    kinds = {
        item["tipo di impatto economico"]
        for item in context["decisioni in ordine di priorità"]
        if item["impatto economico"]
    }
    assert kinds == {"ricavi", "costi"}  # revenue and cost estimates are NOT the same kind
    answer = body["answer"]
    assert "non sono direttamente confrontabili" in answer
    assert "ricavi" in answer and "costi" in answer
    assert "euro" in answer  # the cost estimate carries the currency the engine recorded
    assert "stime indicative, non perdite certe" in answer
    # compared, never summed: 500.00 + 500.00 + 275.00 appears nowhere
    assert "1275" not in answer and "1000" not in answer


def test_3_estimates_of_one_kind_are_compared_and_the_highest_is_named(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_revenue_only_pair(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_IMPACT)

    kinds = {
        item["tipo di impatto economico"] for item in context["decisioni in ordine di priorità"]
    }
    assert kinds == {"ricavi"}
    assert "non sono direttamente confrontabili" not in body["answer"]
    assert "stima indicativa più alta" in body["answer"]
    assert "500" in body["answer"]  # the engine's own recorded figure, as recorded
    assert "euro" not in body["answer"]  # revenue estimates carry no currency - none is invented


def test_3_without_any_recorded_estimate_the_status_is_insufficient_context(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    sync_feed(
        db_session,
        tenant,
        [
            ota_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                booking_data_source_id=tenant.data_source.id,
                as_of_local_date=D1,
            )
        ],
        coverage=booking_only_coverage(),
    )
    body, _, context = _ask(api_client, app, at, Q_IMPACT)

    assert all(not item["impatto economico"] for item in context["decisioni in ordine di priorità"])
    assert body["status"] == "INSUFFICIENT_CONTEXT"
    assert "non ha registrato stime" in body["answer"]


# --- 4. "Quali dati ha usato NINFA oggi?" ------------------------------------------------------


def test_4_data_used_reports_coverage_the_import_fact_and_never_a_freshness_judgement(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    body, _, _ = _ask(api_client, app, at, Q_DATA)

    answer = body["answer"]
    assert "Ricavi" in answer and "Distribuzione" in answer  # analysed
    assert "Non sono state analizzate: Costi, Personale" in answer
    assert "ultimo import delle prenotazioni è di oggi, alle 09:31" in answer
    for judgement in ("aggiornat", "obsolet", "recente", "attual"):
        assert judgement not in answer.lower(), judgement


# --- 5-7. the feed states ----------------------------------------------------------------------


def test_5_no_action_required_says_so_and_still_names_the_unanalysed_areas(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        [_revenue(at, stay_date=STAY, status=CLEAR)],
        coverage=booking_only_coverage(),
    )
    body, _, context = _ask(api_client, app, at, Q_OTHER)

    assert (
        context["stato dell'analisi"] == "Nessuna decisione richiede attenzione in questo momento"
    )
    assert "Oggi nessuna decisione richiede attenzione" in body["answer"]
    assert "Costi, Personale" in body["answer"]  # not analysed: never an implied "all fine"


def test_6_data_quality_limited_reports_the_missing_checks_and_never_says_all_is_well(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = authed_tenant(factory, authenticated_as)
    sync_feed(
        db_session,
        at.tenant,
        [_revenue(at, stay_date=STAY, status=INSUFFICIENT)],
        coverage=booking_only_coverage(),
    )
    body, _, context = _ask(api_client, app, at, Q_PRIORITY)

    assert context["stato dell'analisi"].startswith("Analisi parziale")
    assert context["controlli con dati insufficienti"] == 1
    assert "parziale" in body["answer"]
    assert "1 controlli senza dati sufficienti" in body["answer"]
    assert "va tutto bene" not in body["answer"]
    assert "Nessuna decisione richiede" not in body["answer"]


def test_7_not_processed_says_so_and_names_the_last_completed_analysis(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_single(factory, authenticated_as, db_session)  # a run for 1 August only
    body, _, context = _ask(api_client, app, at, Q_PRIORITY, as_of="2026-08-03")

    assert context["decisioni in ordine di priorità"] == []
    assert context["copertura dell'analisi"] is None and context["dati usati dall'analisi"] is None
    assert body["status"] == "INSUFFICIENT_CONTEXT"  # there is no decision to explain today
    assert "non è ancora disponibile" in body["answer"]
    assert italian_date(context["data dell'ultima analisi completata"]) in body["answer"]


def test_7_not_processed_never_invents_data_for_the_data_question(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
) -> None:
    at = authed_tenant(factory, authenticated_as)  # no run at all
    body, _, context = _ask(api_client, app, at, Q_DATA)

    assert context["data dell'ultima analisi completata"] is None
    assert "non è ancora disponibile" in body["answer"]
    assert "import" not in body["answer"].lower()  # no import time is made up


# --- 8-9. free text -------------------------------------------------------------------------------


def test_8_a_free_question_about_an_area_with_decisions_is_answered_with_them(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_five(factory, authenticated_as, db_session)
    body, _, context = _ask(api_client, app, at, Q_COSTS)

    [cost] = [
        item for item in context["decisioni in ordine di priorità"] if item["area"] == "Costi"
    ]
    assert body["status"] == "ANSWERED"
    assert cost["decisione"] in body["answer"]
    assert "Lavanderia" in body["answer"]  # the cost category it is about
    assert "euro" in body["answer"]


def test_8_no_decision_in_an_analysed_area_is_said_but_an_unanalysed_area_is_never_all_clear(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_revenue_only_pair(factory, authenticated_as, db_session)

    analysed, _, _ = _ask(api_client, app, at, Q_DISTRIBUTION)
    assert analysed["status"] == "ANSWERED"
    assert "non ha rilevato nessuna decisione" in analysed["answer"]  # Distribuzione WAS analysed

    unanalysed, _, _ = _ask(api_client, app, at, Q_COSTS)
    assert unanalysed["status"] == "INSUFFICIENT_CONTEXT"  # Costi was NOT analysed
    assert "non è stata analizzata" in unanalysed["answer"]
    assert "nessuna decisione" not in unanalysed["answer"]


def test_9_a_bare_why_without_history_is_flagged_as_needing_a_clearer_question(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    body, provider, context = _ask(api_client, app, at, Q_WHY)

    # No history was sent, so nothing is remembered server-side: the request holds ONLY this
    # question, and the context itself says the follow-up cannot be resolved.
    request = provider.last_request
    assert request.question == Q_WHY
    assert request.history == ()
    assert context["numero di decisioni che richiedono attenzione"] == 3
    operational = context["dati operativi richiesti"]
    assert any(
        "richiama una conversazione precedente" in n
        for n in operational["cosa NINFA non può determinare"]
    )
    assert operational["argomento ripreso dalla domanda precedente"] is False
    assert body["status"] == "INSUFFICIENT_CONTEXT"
    assert "Non ho memoria delle domande precedenti" in body["answer"]
    assert "riformularla" in body["answer"]


def test_9_a_bare_why_with_the_previous_exchange_is_resolved_from_the_users_own_question(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    provider = ContextReadingProvider()
    with_fake_provider(app)(provider)
    response = api_client.post(
        ask_home_url(at.tenant.property.id),
        json={
            "question": Q_WHY,
            "as_of_local_date": "2026-08-01",
            "history": [
                {"role": "user", "content": Q_PRIORITY},
                {"role": "assistant", "content": "La più prioritaria per NINFA è la prima."},
            ],
        },
    )

    assert response.status_code == 200, response.text
    request = provider.last_request
    assert [turn.role for turn in request.history] == ["user", "assistant"]
    assert request.history[0].content == Q_PRIORITY
    context = json.loads(request.context)
    assert context["dati operativi richiesti"]["argomento ripreso dalla domanda precedente"] is True
    # the history text itself is NOT part of the fact context: facts are always rebuilt fresh
    assert Q_PRIORITY not in request.context
    assert "La più prioritaria per NINFA è la prima." not in request.context


# --- a rich answer travels the whole pipeline intact ---------------------------------------------


def _rich_answer(words: int) -> str:
    """A multi-paragraph answer with a bullet list and a literal Italian vocabulary of about
    `words` words (no snake_case, no technical token)."""
    bullet = "- Pickup sotto le attese (Ricavi), data del soggiorno 15 agosto"
    filler = "prenotazioni arrivano sotto il ritmo atteso per questa data " * 40
    body = " ".join(filler.split()[: max(words - 20, 1)])
    return f"Sì, ce ne sono altre.\n\n{bullet}\n- {bullet[2:]}\n\n{body}."


def test_a_rich_220_word_answer_is_accepted_whole_with_its_line_breaks(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    rich = _rich_answer(220)
    assert len(rich.split()) >= 200
    assert MAX_ANSWER_CHARS < len(rich) <= MAX_HOME_ANSWER_CHARS  # too long for the Decision Ask

    with_fake_provider(app)(answered_provider(rich))
    body = api_client.post(
        ask_home_url(at.tenant.property.id),
        json={"question": Q_OTHER, "as_of_local_date": "2026-08-01"},
    ).json()

    assert body["status"] == "ANSWERED"
    assert body["answer"] == rich  # not truncated, not reflowed, newlines and bullets intact
    assert "\n\n" in body["answer"] and "\n- " in body["answer"]


def test_an_answer_over_the_home_ceiling_still_fails_closed_never_truncated(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_three(factory, authenticated_as, db_session)
    with_fake_provider(app)(answered_provider("parola " * 300))  # 2100 characters
    body = api_client.post(
        ask_home_url(at.tenant.property.id),
        json={"question": Q_OTHER, "as_of_local_date": "2026-08-01"},
    ).json()
    assert body["status"] == "UNAVAILABLE" and body["answer"] is None


# --- the Decision Ask's limits did not move ----------------------------------------------


def _raw(answer: str) -> LanguageModelAnswer:
    return LanguageModelAnswer(
        status=ModelAnswerStatus.ANSWERED, answer=answer, grounding_refs=(), limitations=()
    )


def test_the_decision_ask_ceiling_is_still_700_characters() -> None:
    assert MAX_ANSWER_CHARS == 700
    assert validate_model_answer(_raw("a" * 700)) is not None
    assert validate_model_answer(_raw("a" * 701)) is None  # fails closed, never truncated
    # ...while the shared core accepts the Home's longer answer only when the caller says so
    vocabulary = frozenset({"DECISIONS"})
    long_answer = _raw("parola " * 150)  # 1050 characters
    assert validate_model_answer_core(long_answer, vocabulary) is None
    core = validate_model_answer_core(long_answer, vocabulary, MAX_HOME_ANSWER_CHARS)
    assert core is not None and core.status is AskStatus.ANSWERED


def test_the_home_ceiling_is_a_hard_limit_of_its_own() -> None:
    vocabulary = frozenset({"DECISIONS"})
    assert validate_model_answer_core(_raw("a" * 1800), vocabulary, 1800) is not None
    assert validate_model_answer_core(_raw("a" * 1801), vocabulary, 1800) is None
    assert MAX_HOME_ANSWER_CHARS == 1800


# --- the provider's output budget grows only for the longer Home answer -------------------------


def _request(max_answer_chars: int) -> LanguageModelRequest:
    return LanguageModelRequest(
        system_instructions="I", context="{}", question="?", max_answer_chars=max_answer_chars
    )


def test_the_output_budget_is_larger_only_for_the_home_sized_answer() -> None:
    assert _max_tokens_for(_request(700)) == _MAX_OUTPUT_TOKENS  # Decision Ask: unchanged
    assert _max_tokens_for(_request(1200)) == _MAX_OUTPUT_TOKENS
    assert _max_tokens_for(_request(MAX_HOME_ANSWER_CHARS)) == _MAX_OUTPUT_TOKENS_LONG_ANSWER
    assert _MAX_OUTPUT_TOKENS < _MAX_OUTPUT_TOKENS_LONG_ANSWER <= 4096  # bounded, never unlimited


# --- the richer context stays private and technical-free -------------------------------------


def test_the_richer_context_still_carries_no_identifier_and_no_technical_token(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed_five(factory, authenticated_as, db_session)
    _, provider, context = _ask(api_client, app, at, Q_PRIORITY)

    serialized = provider.last_request.context
    assert str(at.tenant.property.id) not in serialized
    assert str(at.tenant.workspace.id) not in serialized
    for token in ("REV_PICKUP_LOW", "COST_CPOR_ANOMALY", "data_source_id", "decision_id", "rank"):
        assert token not in serialized, token
    for decision in context["decisioni in ordine di priorità"]:
        assert "_" not in decision["descrizione"]
        assert "_" not in (decision["tipo di impatto economico"] or "")
    assert date.fromisoformat(context["data di riferimento"]) == D1
