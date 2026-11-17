"""Mia's decision tools: `get_today_summary`, `list_decisions`, `explain_decision`.

Every world is real: decisions persisted by `DecisionService.sync()` and read back through the real
feed. What is pinned here: the engine's order is never re-ranked, "no decision" is never "all fine"
and never an invented cause, an id that is not the user's own (missing, another workspace, another
property, a hidden area) is ONE and the same answer, a hidden area leaves no trace in a count or an
ordering word, a decision's explanation comes from the same whitelist as the Decision Ask, and no
observation can leak an internal word, a raw UUID, or write a row.
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.modules.ai.ask_ninfa.semantic_labels import (
    DECISION_TYPE_LABELS,
    decision_description_of,
)
from app.modules.ai.ask_ninfa.technical_leak import contains_technical_leak
from app.modules.ai.mia.access import AccessDomain
from app.modules.ai.mia.grounding import split_observation_numbers, ungrounded_numbers
from app.modules.ai.mia.tools.base import observation_to_json
from app.modules.ai.mia.tools.decisions import parse_ref, ref_token
from app.modules.ai.mia.types import MAX_OBSERVATION_CHARS
from app.modules.decisions.models import Decision, DecisionObservation
from app.modules.decisions.precision import canonical_text
from app.modules.intelligence.priority.types import PriorityDecisionType
from tests.ask_home_support import STAY
from tests.data_overview_support import seed_run
from tests.decision_api_support import decision_table_counts
from tests.decision_support import TRIGGERED, revenue_evaluation
from tests.mia_decision_support import (
    HideAreas,
    clear_evaluations,
    decision_of_type,
    decisions_of,
    insufficient_evaluations,
    json_text,
    other_property_of,
    seed_five_decisions,
    spoken_text,
    world_for,
)
from tests.mia_support import MiaWorld
from tests.support import BookingFactory, Tenant

PICKUP = PriorityDecisionType.REV_PICKUP_LOW
OCCUPANCY = PriorityDecisionType.REV_OCCUPANCY_RISK
OTA = PriorityDecisionType.REV_OTA_DEPENDENCY
COST = PriorityDecisionType.COST_CPOR_ANOMALY
LABOR = PriorityDecisionType.LABOR_OVERSTAFFING
# the order `five_triggered_evaluations` hands the engine: this is the feed's own order
ENGINE_ORDER = (PICKUP, OCCUPANCY, OTA, COST, LABOR)


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


@pytest.fixture
def world(factory: BookingFactory, db_session: Session, tenant: Tenant) -> MiaWorld:
    return world_for(factory, db_session, tenant)


@pytest.fixture
def five(factory: BookingFactory, db_session: Session, tenant: Tenant) -> None:
    seed_five_decisions(factory, db_session, tenant)


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = payload["dati"]
    return data


def _titles(payload: dict[str, Any]) -> list[str]:
    return [row["titolo"] for row in _data(payload)["decisioni"]]


def _label(decision_type: PriorityDecisionType) -> str:
    return DECISION_TYPE_LABELS[decision_type]


# --- ids


def test_a_decision_id_travels_as_letters_only_and_comes_back_as_the_same_uuid() -> None:
    decision_id = uuid4()

    token = ref_token(decision_id)

    assert token.isalpha() and token.islower()
    assert len(token) == 32
    assert parse_ref(token) == decision_id
    assert parse_ref(token.upper()) == decision_id
    # the id the page carries is the canonical UUID: both forms name the same decision
    assert parse_ref(str(decision_id)) == decision_id
    assert parse_ref(f"  {decision_id}  ") == decision_id


@pytest.mark.parametrize("garbage", ["", "abc", "x" * 32, "g" * 31, "not-a-uuid-at-all", "z" * 40])
def test_a_reference_that_is_not_one_is_not_parsed(garbage: str) -> None:
    assert parse_ref(garbage) is None


# --- registration


def test_the_decision_tools_are_in_the_catalog_with_closed_arguments(world: MiaWorld) -> None:
    for name in ("get_today_summary", "list_decisions", "explain_decision"):
        definition = world.catalog.get(name)
        assert definition is not None, name
        assert definition.domain is None  # they filter the areas themselves
        assert definition.spec().input_schema["additionalProperties"] is False
    explain = world.catalog.get("explain_decision")
    assert explain is not None
    assert explain.spec().input_schema["required"] == ["decision_id"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_today_summary", {"x": 1}),
        ("list_decisions", {"limit": 11}),
        ("list_decisions", {"limit": 0}),
        ("list_decisions", {"area": "marketing"}),
        ("list_decisions", {"status": "closed"}),
        ("list_decisions", {"day": "domani"}),
        ("list_decisions", {"surprise": True}),
        ("explain_decision", {}),
        ("explain_decision", {"decision_id": "short"}),
        ("explain_decision", {"decision_id": "x" * 65}),
        ("explain_decision", {"decision_id": "a" * 32, "extra": 1}),
    ],
)
def test_bad_arguments_run_nothing(world: MiaWorld, tool: str, arguments: dict[str, Any]) -> None:
    assert world.call(tool, arguments).outcome.is_error


# --- get_today_summary


@pytest.mark.usefixtures("five")
def test_the_summary_counts_the_decisions_and_names_the_one_the_engine_put_first(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    payload = world.ok("get_today_summary")
    data = _data(payload)

    assert data["giorno"] == "2026-08-01, sabato"
    assert data["decisioni che richiedono attenzione"] == 5
    assert data["prima decisione nell'ordine di NINFA"] == {
        "riferimento": ref_token(decision_of_type(db_session, tenant.property.id, PICKUP).id),
        "titolo": _label(PICKUP),
        "area": "Ricavi",
    }
    areas = {row["area"]: row for row in data["aree"]}
    assert {name: row["decisioni"] for name, row in areas.items()} == {
        "Ricavi": 2,
        "Distribuzione": 1,
        "Costi": 1,
        "Personale": 1,
    }
    assert payload["copertura"]["copertura dell'analisi"] == "completa"
    assert data["controlli rimasti senza conclusione per dati insufficienti"] == 0
    assert payload["riferimenti"] == ["decisioni:oggi"]


def test_a_run_with_nothing_to_act_on_is_not_all_fine_for_areas_it_did_not_analyse(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, evaluations=clear_evaluations(tenant))

    payload = world.ok("get_today_summary")
    data = _data(payload)
    areas = {row["area"]: row for row in data["aree"]}

    assert data["decisioni che richiedono attenzione"] == 0
    assert "prima decisione nell'ordine di NINFA" not in data
    assert "per quanto analizzato oggi" in data["stato dell'analisi"]
    assert areas["Ricavi"]["stato dell'analisi"] == "analizzata"
    assert "per quanto analizzato oggi" in areas["Ricavi"]["esito"]
    assert areas["Costi"]["stato dell'analisi"] == "non analizzata"
    assert "non può dire che vada tutto bene" in areas["Costi"]["esito"]
    assert payload["copertura"]["aree non analizzate"] == ["Costi", "Personale"]


def test_checks_that_could_not_conclude_are_reported_as_a_fact_and_never_explained(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, evaluations=insufficient_evaluations(tenant))

    payload = world.ok("get_today_summary")
    data = _data(payload)
    areas = {row["area"]: row for row in data["aree"]}

    assert "Nessuna decisione affidabile oggi" in data["stato dell'analisi"]
    assert "Non vuol dire che vada tutto bene" in data["stato dell'analisi"]
    assert data["controlli rimasti senza conclusione per dati insufficienti"] == 1
    assert areas["Ricavi"]["stato dell'analisi"] == "analisi parziale"
    assert "non si può escludere un problema non rilevato" in areas["Ricavi"]["esito"]
    assert any("non ipotizzarne uno" in note for note in payload["note"])


def test_no_analysis_yet_is_said_plainly(world: MiaWorld) -> None:
    payload = world.ok("get_today_summary")
    data = _data(payload)

    assert "prima analisi" in data["stato dell'analisi"]
    assert payload["aggiornamento"]["analisi del giorno presente"] is False
    assert all(row["stato dell'analisi"] == "non disponibile" for row in data["aree"])
    assert payload["copertura"]["copertura dell'analisi"] == "nessuna analisi disponibile"
    assert "controlli rimasti senza conclusione per dati insufficienti" not in data
    assert payload["non disponibile"]


def test_no_analysis_today_but_an_earlier_one_names_its_date(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, as_of=date(2026, 7, 29))

    payload = world.ok("get_today_summary")

    assert "2026-07-29" in _data(payload)["stato dell'analisi"]
    assert payload["aggiornamento"]["giorno dell'ultima analisi completata"] == "2026-07-29"
    assert payload["aggiornamento"]["analisi del giorno presente"] is False


@pytest.mark.usefixtures("five")
def test_hidden_areas_are_removed_before_anything_is_counted_or_named_first(
    world: MiaWorld,
) -> None:
    runtime = world.runtime(access=HideAreas(AccessDomain.REVENUE))

    payload = world.ok("get_today_summary", runtime=runtime)
    data = _data(payload)

    assert [row["area"] for row in data["aree"]] == ["Distribuzione", "Costi", "Personale"]
    assert data["decisioni che richiedono attenzione"] == 3
    # "the first decision" is the first VISIBLE one, not the engine's first overall
    assert data["prima decisione nell'ordine di NINFA"]["titolo"] == _label(OTA)
    # the run-level counts cannot be split by area: withheld
    assert "controlli rimasti senza conclusione per dati insufficienti" not in data
    assert "controlli non mostrati perché poco affidabili" not in data
    assert payload["copertura"]["aree analizzate"] == ["Distribuzione", "Costi", "Personale"]
    assert any("non sono consentite" in note for note in payload["note"])
    assert "Ricavi" not in json_text(payload)
    assert _label(PICKUP) not in json_text(payload)


@pytest.mark.usefixtures("five")
def test_with_every_area_hidden_nothing_is_said_to_need_attention(world: MiaWorld) -> None:
    runtime = world.runtime(
        access=HideAreas(
            AccessDomain.REVENUE,
            AccessDomain.DISTRIBUTION,
            AccessDomain.COSTS,
            AccessDomain.LABOR,
        )
    )

    data = _data(world.ok("get_today_summary", runtime=runtime))

    assert data["decisioni che richiedono attenzione"] == 0
    assert data["aree"] == []
    assert (
        "Nessuna decisione che richieda attenzione nelle aree che puoi vedere"
        in data["stato dell'analisi"]
    )


# --- list_decisions


@pytest.mark.usefixtures("five")
def test_the_decisions_come_in_the_engines_order_with_their_positions_and_never_re_ranked(
    world: MiaWorld,
) -> None:
    payload = world.ok("list_decisions", {"limit": 10})
    rows = _data(payload)["decisioni"]

    assert _titles(payload) == [_label(t) for t in ENGINE_ORDER]
    assert [row["posizione nell'ordine di NINFA"] for row in rows] == [1, 2, 3, 4, 5]
    assert "priorità di NINFA" in _data(payload)["origine dell'elenco"]
    assert [row["area"] for row in rows] == [
        "Ricavi",
        "Ricavi",
        "Distribuzione",
        "Costi",
        "Personale",
    ]
    assert _data(payload)["valuta"] == "EUR"
    assert any("non le crea né le modifica" in note for note in payload["note"])


@pytest.mark.usefixtures("five")
def test_each_decision_carries_a_reference_a_target_facts_and_an_indicative_impact(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    payload = world.ok("list_decisions", {"limit": 10})
    rows = {row["titolo"]: row for row in _data(payload)["decisioni"]}

    pickup = rows[_label(PICKUP)]
    assert pickup["riferimento"] == ref_token(
        decision_of_type(db_session, tenant.property.id, PICKUP).id
    )
    assert pickup["riguarda"] == {"notte di soggiorno": STAY.isoformat()}
    assert pickup["stato"] == "Aperta"
    assert pickup["vista la prima volta"] == "2026-08-01"
    assert pickup["dati principali"]
    assert {"etichetta", "valore"} <= set(pickup["dati principali"][0])
    # an impact, where the whitelist has one, is always worded as an indicative estimate
    impacts = [p for row in rows.values() for p in row.get("impatto stimato", [])]
    assert impacts
    assert all("stima indicativa" in p["etichetta"] for p in impacts)
    # a cost decision names its category in Italian, never the code
    assert "categoria di costo" in rows[_label(COST)]["riguarda"]
    assert "reparto" in rows[_label(LABOR)]["riguarda"]
    assert payload["riferimenti"][0] == "decisioni:elenco"
    assert f"decisione:{pickup['riferimento']}" in payload["riferimenti"]


@pytest.mark.usefixtures("five")
def test_an_area_and_a_limit_narrow_the_list_without_reordering_it(world: MiaWorld) -> None:
    revenue = world.ok("list_decisions", {"area": "ricavi", "limit": 10})
    assert _titles(revenue) == [_label(PICKUP), _label(OCCUPANCY)]

    first_only = world.ok("list_decisions", {"limit": 1})
    assert _titles(first_only) == [_label(PICKUP)]

    costs = world.ok("list_decisions", {"area": "costi"})
    assert _titles(costs) == [_label(COST)]
    assert _data(costs)["decisioni"][0]["posizione nell'ordine di NINFA"] == 1


def test_an_empty_day_says_why_and_never_that_all_is_fine(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, evaluations=insufficient_evaluations(tenant))

    payload = world.ok("list_decisions")

    assert _data(payload)["decisioni"] == []
    (reason,) = payload["non disponibile"]
    assert "nessuna decisione per questo giorno" in reason
    assert "Non vuol dire che vada tutto bene" in reason


def test_another_day_is_read_from_that_days_own_analysis(
    factory: BookingFactory, db_session: Session
) -> None:
    other = factory.tenant()
    world = world_for(factory, db_session, other)
    yesterday = date(2026, 7, 31)
    seed_run(
        db_session,
        other,
        as_of=yesterday,
        evaluations=[
            revenue_evaluation(
                workspace_id=other.workspace.id,
                property_id=other.property.id,
                data_source_id=other.data_source.id,
                stay_date=STAY,
                snapshot_local_date=yesterday,
                status=TRIGGERED,
            )
        ],
    )

    that_day = world.ok("list_decisions", {"day": "2026-07-31"})
    today = world.ok("list_decisions")

    assert _titles(that_day) == [_label(PICKUP)]
    assert _data(that_day)["giorno"] == "2026-07-31, venerdì"
    assert _data(today)["decisioni"] == []
    assert "2026-07-31" in today["non disponibile"][0]  # the last completed analysis, named


@pytest.mark.usefixtures("five")
@pytest.mark.parametrize("status", ["open", "all"])
def test_the_memory_of_decisions_is_not_presented_as_a_priority_order(
    world: MiaWorld, status: str
) -> None:
    payload = world.ok("list_decisions", {"status": status, "limit": 10})
    data = _data(payload)

    assert len(data["decisioni"]) == 5
    assert "non è l'ordine di priorità" in data["origine dell'elenco"]
    assert all("posizione nell'ordine di NINFA" not in row for row in data["decisioni"])
    assert "giorno" not in data
    assert {row["titolo"] for row in data["decisioni"]} == {_label(t) for t in ENGINE_ORDER}


@pytest.mark.usefixtures("five")
def test_hidden_areas_vanish_from_the_list_and_the_positions_count_only_what_is_visible(
    world: MiaWorld,
) -> None:
    runtime = world.runtime(access=HideAreas(AccessDomain.REVENUE))

    payload = world.ok("list_decisions", {"limit": 10}, runtime=runtime)
    rows = _data(payload)["decisioni"]

    assert [row["titolo"] for row in rows] == [_label(OTA), _label(COST), _label(LABOR)]
    # "the first" is the first VISIBLE decision
    assert [row["posizione nell'ordine di NINFA"] for row in rows] == [1, 2, 3]
    assert _label(PICKUP) not in json_text(payload)

    memory = world.ok("list_decisions", {"status": "all", "limit": 10}, runtime=runtime)
    assert {row["titolo"] for row in _data(memory)["decisioni"]} == {
        _label(OTA),
        _label(COST),
        _label(LABOR),
    }


@pytest.mark.usefixtures("five")
def test_asking_for_a_hidden_area_returns_nothing_and_says_it_is_not_allowed(
    world: MiaWorld,
) -> None:
    runtime = world.runtime(access=HideAreas(AccessDomain.COSTS))

    payload = world.ok("list_decisions", {"area": "costi"}, runtime=runtime)

    assert _data(payload)["decisioni"] == []
    assert payload["non disponibile"] == ["quest'area non è consentita a questo utente"]


# --- explain_decision


@pytest.mark.usefixtures("five")
@pytest.mark.parametrize("decision_type", ENGINE_ORDER, ids=lambda t: t.name)
def test_every_kind_of_decision_is_explained_from_the_same_whitelist_as_the_decision_ask(
    world: MiaWorld, db_session: Session, tenant: Tenant, decision_type: PriorityDecisionType
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, decision_type)
    latest = decision.id
    payload = world.ok("explain_decision", {"decision_id": ref_token(latest)})
    data = _data(payload)

    assert data["decisione trovata"] is True
    assert data["titolo"] == _label(decision_type)
    assert data["cosa ha controllato NINFA"] == decision_description_of(decision_type)
    assert data["stato"] == "Aperta"
    assert data["valori rilevati"], "expected / actual / delta come from the whitelisted facts"
    assert all({"etichetta", "valore"} <= set(point) for point in data["valori rilevati"])
    assert data["andamento nelle ultime valutazioni"], "the short history is part of the answer"
    assert data["tra le decisioni di oggi"] is True
    assert data["posizione nell'ordine di NINFA"] == ENGINE_ORDER.index(decision_type) + 1
    assert payload["riferimenti"] == [f"decisione:{ref_token(decision.id)}"]
    assert payload["aggiornamento"]["ultima valutazione"] == "2026-08-01"
    assert payload["aggiornamento"]["episodi"] == 1
    assert any("stime indicative" in note for note in payload["note"])


@pytest.mark.usefixtures("five")
def test_the_confidence_is_on_the_zero_to_hundred_scale_exactly_as_stored(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, PICKUP)
    stored = (
        db_session.query(DecisionObservation)
        .filter(DecisionObservation.decision_id == decision.id)
        .one()
    )

    data = _data(world.ok("explain_decision", {"decision_id": ref_token(decision.id)}))

    assert data["affidabilità (su cento)"] == canonical_text(stored.confidence_score)
    assert Decimal(data["affidabilità (su cento)"]) > 1  # never a 0..1 fraction


@pytest.mark.usefixtures("five")
def test_the_explanation_says_what_was_checked_in_words_and_exposes_no_implementation_detail(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, PICKUP)

    payload = world.ok("explain_decision", {"decision_id": ref_token(decision.id)})
    text = spoken_text(payload)

    assert not contains_technical_leak(text), text
    assert "REV_PICKUP_LOW" not in text
    assert "stay_date" not in text
    # the target is plain Italian, not the engine's own snake_case keys
    assert _data(payload)["riguarda"] == {"notte di soggiorno": STAY.isoformat()}


@pytest.mark.usefixtures("five")
def test_a_recommendation_is_offered_as_something_to_verify_never_as_a_new_decision(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, OTA)

    payload = world.ok("explain_decision", {"decision_id": ref_token(decision.id)})
    suggestion = _data(payload)["cosa suggerisce NINFA di verificare"]

    assert suggestion["azione"] == "Rivedi il mix distributivo"
    assert suggestion["controlli di supporto"]
    assert suggestion["avvertenze"]
    assert any("non la crea né la cambia" in note for note in payload["note"])
    assert payload["non disponibile"] == []


@pytest.mark.usefixtures("five")
def test_a_decision_with_no_suggested_action_says_so_instead_of_inventing_one(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, PICKUP)

    payload = world.ok("explain_decision", {"decision_id": ref_token(decision.id)})

    assert _data(payload)["cosa suggerisce NINFA di verificare"] is None
    assert payload["non disponibile"] == [
        "NINFA non ha un'azione da suggerire per questa decisione con i dati disponibili"
    ]


@pytest.mark.usefixtures("five")
def test_the_id_the_page_carries_works_like_the_token(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, OTA)

    from_page = world.ok("explain_decision", {"decision_id": str(decision.id)})
    from_list = world.ok("explain_decision", {"decision_id": ref_token(decision.id)})

    assert from_page["dati"] == from_list["dati"]
    assert str(decision.id) not in json_text(from_page)  # the answer never repeats the raw UUID


@pytest.mark.usefixtures("five")
def test_the_explanation_of_a_decision_outside_todays_feed_says_so(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, PICKUP)
    later = world.runtime(as_of=date(2026, 8, 5))  # a day with no analysis: not in ITS feed

    data = _data(
        world.ok("explain_decision", {"decision_id": ref_token(decision.id)}, runtime=later)
    )

    assert data["tra le decisioni di oggi"] is False
    assert "posizione nell'ordine di NINFA" not in data


# --- ids that are not the user's own: ONE answer


def _decision_ids_of(session: Session, tenant: Tenant) -> list[Decision]:
    return list(decisions_of(session, tenant.property.id))


@pytest.mark.usefixtures("five")
def test_a_missing_a_foreign_an_other_property_and_a_hidden_decision_are_one_and_the_same_answer(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    foreign = factory.tenant()
    seed_five_decisions(factory, db_session, foreign)
    sibling = other_property_of(factory, tenant)
    seed_five_decisions(factory, db_session, sibling)
    foreign_id = decision_of_type(db_session, foreign.property.id, PICKUP).id
    sibling_id = decision_of_type(db_session, sibling.property.id, PICKUP).id
    own_cost = decision_of_type(db_session, tenant.property.id, COST).id

    def answer(reference: str, **runtime_args: Any) -> dict[str, Any]:
        runtime = world.runtime(**runtime_args)
        execution = world.call("explain_decision", {"decision_id": reference}, runtime=runtime)
        assert not execution.outcome.is_error, execution.outcome.content
        payload: dict[str, Any] = json.loads(execution.outcome.content)
        return {k: payload[k] for k in ("dati", "non disponibile", "riferimenti", "note")}

    missing = answer(ref_token(uuid4()))
    assert missing["dati"] == {"decisione trovata": False}
    assert missing["riferimenti"] == []

    assert answer(ref_token(foreign_id)) == missing  # another workspace
    assert answer(str(foreign_id)) == missing
    assert answer(ref_token(sibling_id)) == missing  # same workspace, another property
    assert answer(str(sibling_id)) == missing
    assert answer("not a reference at all") == missing  # not even a reference
    assert answer(ref_token(own_cost), access=HideAreas(AccessDomain.COSTS)) == missing  # hidden
    # ...while the user's own decision of a visible area is found
    assert answer(ref_token(own_cost))["dati"]["decisione trovata"] is True


@pytest.mark.usefixtures("five")
def test_a_foreign_decision_leaves_no_trace_of_its_content(
    factory: BookingFactory, db_session: Session, world: MiaWorld
) -> None:
    foreign = factory.tenant()
    seed_five_decisions(factory, db_session, foreign)
    foreign_id = decision_of_type(db_session, foreign.property.id, COST).id

    execution = world.call("explain_decision", {"decision_id": ref_token(foreign_id)})

    assert str(foreign_id) not in execution.outcome.content
    assert _label(COST) not in execution.outcome.content


# --- safety nets


def _all_calls(db_session: Session, tenant: Tenant) -> list[tuple[str, dict[str, Any]]]:
    pickup = decision_of_type(db_session, tenant.property.id, PICKUP)
    return [
        ("get_today_summary", {}),
        ("list_decisions", {"limit": 10}),
        ("list_decisions", {"status": "all", "limit": 10}),
        ("explain_decision", {"decision_id": ref_token(pickup.id)}),
    ]


@pytest.mark.usefixtures("five")
def test_no_decision_tool_writes_a_row(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    before = decision_table_counts(db_session)

    for tool, arguments in _all_calls(db_session, tenant):
        assert not world.call(tool, arguments).outcome.is_error

    assert decision_table_counts(db_session) == before


@pytest.mark.usefixtures("five")
def test_no_decision_observation_leaks_an_internal_word_a_raw_uuid_or_exceeds_the_size(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    raw_ids = [str(d.id) for d in _decision_ids_of(db_session, tenant)] + [
        d.id.hex for d in _decision_ids_of(db_session, tenant)
    ]

    for tool, arguments in _all_calls(db_session, tenant):
        execution = world.call(tool, arguments)
        assert not execution.outcome.is_error, execution.outcome.content
        text = execution.outcome.content
        assert not contains_technical_leak(spoken_text(json.loads(text))), (tool, text)
        assert not any(raw in text for raw in raw_ids), tool
        assert len(text) < MAX_OBSERVATION_CHARS // 2, (tool, len(text))


@pytest.mark.usefixtures("five")
def test_a_restated_figure_is_grounded_and_an_invented_one_is_not(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    decision = decision_of_type(db_session, tenant.property.id, PICKUP)
    execution = world.call("explain_decision", {"decision_id": ref_token(decision.id)})
    assert execution.observation is not None
    figures, dates = split_observation_numbers([observation_to_json(execution.observation)])
    stored_confidence = _data(json.loads(execution.outcome.content))["affidabilità (su cento)"]

    restated = f"L'affidabilità è {Decimal(stored_confidence):.0f} su 100."
    assert ungrounded_numbers(restated, figures, dates) == []
    assert ungrounded_numbers("Mancano 93 camere.", figures, dates) == ["93"]


def test_a_decision_of_another_day_in_the_feed_is_never_taken_for_todays(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(
        db_session, tenant, as_of=date(2026, 7, 31), evaluations=insufficient_evaluations(tenant)
    )

    payload = world.ok("get_today_summary")

    assert _data(payload)["decisioni che richiedono attenzione"] == 0
    assert payload["aggiornamento"]["analisi del giorno presente"] is False
