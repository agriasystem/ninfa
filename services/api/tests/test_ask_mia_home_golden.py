"""Mia Home golden cases (Home UI V1, ADR 0028): the four suggested questions, end to end over HTTP,
against ONE fixed, real persisted feed - three triggered decisions (two Revenue, one Distribution),
a Revenue+Distribution-only analysis (Costi/Personale not requested) and a known booking import.

The fake provider cannot "understand" a question, so what is locked here is the part this codebase
owns: for each question, the context a real model would receive contains exactly what a grounded
answer needs - and nothing a grounded answer must not use - and the request/response contract
around it holds. A real model's own wording is exercised by the provider/instructions tests and by
manual acceptance with the real provider.
"""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.intelligence.revenue.types import RevenueDecisionType
from tests.ask_home_support import (
    D1,
    STAY,
    answered_provider,
    ask_home_url,
    booking_only_coverage,
    known_provenance,
    sync_feed,
    utc,
)
from tests.ask_ninfa_support import DeterministicFakeLanguageModelProvider, with_fake_provider
from tests.decision_api_support import AuthedTenant, authed_tenant
from tests.decision_support import ota_evaluation, revenue_evaluation
from tests.support import BookingFactory

Q1 = "Ci sono altri problemi oltre a questo?"
Q2 = "Qual è la priorità più urgente oggi?"
Q3 = "Quale decisione ha l'impatto economico più alto?"
Q4 = "Quali dati ha usato NINFA oggi?"

_TOP_LEVEL_KEYS = {
    "data di riferimento",
    "stato dell'analisi",
    "numero di decisioni che richiedono attenzione",
    "decisioni in ordine di priorità",
    "decisioni non mostrate",
    "controlli con dati insufficienti",
    "controlli con affidabilità troppo bassa",
    "copertura dell'analisi",
    "dati usati dall'analisi",
    "data dell'ultima analisi completata",
}


def _seed(
    factory: BookingFactory, authenticated_as: Callable[[UUID], None], db_session: Session
) -> AuthedTenant:
    at = authed_tenant(factory, authenticated_as)
    tenant = at.tenant
    sync_feed(
        db_session,
        tenant,
        [
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY,
                snapshot_local_date=D1,
            ),
            revenue_evaluation(
                workspace_id=tenant.workspace.id,
                property_id=tenant.property.id,
                data_source_id=tenant.data_source.id,
                stay_date=STAY.replace(day=22),
                snapshot_local_date=D1,
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
        provenance=known_provenance(utc(2026, 8, 1, 7, 31)),  # 09:31 in Europe/Rome (UTC+2)
    )
    return at


def _ask(
    api_client: TestClient,
    app: FastAPI,
    at: AuthedTenant,
    question: str,
    answer: str,
) -> tuple[dict[str, Any], DeterministicFakeLanguageModelProvider, dict[str, Any]]:
    provider = answered_provider(answer, refs=("DECISIONS", "COVERAGE"))
    with_fake_provider(app)(provider)
    response = api_client.post(
        ask_home_url(at.tenant.property.id),
        json={"question": question, "as_of_local_date": "2026-08-01"},
    )
    assert response.status_code == 200, response.text
    return response.json(), provider, json.loads(provider.last_request.context)


def test_the_context_has_exactly_the_documented_top_level_shape(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    _, _, context = _ask(api_client, app, at, Q1, "Sì, ce ne sono altre due.")
    assert set(context) == _TOP_LEVEL_KEYS


@pytest.mark.parametrize("question", [Q1, Q2, Q3, Q4])
def test_each_suggested_question_is_answered_not_refused_and_reaches_the_provider_verbatim(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
    question: str,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    body, provider, _ = _ask(api_client, app, at, question, "Risposta sintetica e fondata.")
    assert body["status"] == "ANSWERED"
    assert provider.last_request.question == question  # no guardrail false positive, no rewrite


def test_golden_1_other_problems_are_the_other_engine_decisions_plus_the_unanalysed_areas(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    _, _, context = _ask(api_client, app, at, Q1, "Oltre alla prima, NINFA ne ha rilevate due.")

    decisions = context["decisioni in ordine di priorità"]
    assert context["numero di decisioni che richiedono attenzione"] == 3
    assert len(decisions) == 3  # the "other" problems exist ONLY as engine decisions
    assert [item["posizione nell'ordine di NINFA"] for item in decisions] == [
        "prima",
        "seconda",
        "terza",
    ]
    assert {item["area"] for item in decisions} <= {"Ricavi", "Distribuzione"}
    coverage = context["copertura dell'analisi"]
    assert coverage["sintesi"] == "alcune aree non sono state analizzate"
    assert {(a["area"], a["stato"]) for a in coverage["aree"]} == {
        ("Ricavi", "analizzata"),
        ("Distribuzione", "analizzata"),
        ("Costi", "non analizzata"),
        ("Personale", "non analizzata"),
    }


def test_golden_2_the_most_urgent_priority_is_the_first_in_ninfas_own_order_in_words(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    _, _, context = _ask(api_client, app, at, Q2, "La più prioritaria per NINFA è la prima.")

    first = context["decisioni in ordine di priorità"][0]
    assert first["posizione nell'ordine di NINFA"] == "prima"
    serialized = json.dumps(context, ensure_ascii=False)
    for forbidden in ("priority_rank", "priority_score", "impact_score", "urgency_score", "rank"):
        assert forbidden not in serialized, forbidden


def test_golden_3_economic_impact_is_present_only_as_labelled_indicative_estimates(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    _, _, context = _ask(api_client, app, at, Q3, "Le stime non sono tutte confrontabili.")

    impacts = [
        point
        for item in context["decisioni in ordine di priorità"]
        for point in item["impatto economico"]
    ]
    assert impacts, "the seeded revenue decisions both carry an engine-recorded proxy"
    for point in impacts:
        assert "stima indicativa" in point["etichetta"]
        assert point["unità"] is None  # revenue proxies carry no currency - none is invented


def test_golden_4_data_used_today_is_coverage_plus_a_factual_import_in_property_time(
    api_client: TestClient,
    app: FastAPI,
    factory: BookingFactory,
    authenticated_as: Callable[[UUID], None],
    db_session: Session,
) -> None:
    at = _seed(factory, authenticated_as, db_session)
    _, _, context = _ask(api_client, app, at, Q4, "NINFA ha analizzato Ricavi e Distribuzione.")

    imported = context["dati usati dall'analisi"]["ultimo import prenotazioni"]
    assert imported == {
        "data": "2026-08-01",
        "ora locale della struttura": "09:31",
        "giorno rispetto alla data di riferimento": "oggi",
    }
    assert context["copertura dell'analisi"] is not None
    serialized = json.dumps(context, ensure_ascii=False).lower()
    for judgement in ("aggiornat", "obsolet", "stale", "current", "recente"):
        assert judgement not in serialized, judgement
