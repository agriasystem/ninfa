"""Mia's context tools: `get_current_property_context` and `get_data_status`.

Every world is real (a persisted run read back through the real services). What is pinned here:
the facts each tool states, that "no decision" is never turned into "all fine" or into an invented
cause, that coverage and freshness are facts and never a verdict, that hidden areas leave no trace
in a count, and that nothing a tool returns can trip the technical-leak check or write a row.
"""

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.modules.ai.ask_ninfa.semantic_labels import cost_category_label_of
from app.modules.ai.ask_ninfa.technical_leak import contains_technical_leak
from app.modules.ai.mia.access import AccessDomain, UserContext
from app.modules.ai.mia.grounding import split_observation_numbers, ungrounded_numbers
from app.modules.ai.mia.tools.base import observation_to_json
from app.modules.ai.mia.tools.decisions import ref_token
from app.modules.ai.mia.types import MAX_OBSERVATION_CHARS
from app.modules.ai.mia.ui_context import DecisionHint, ImportHint, PageContext
from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance
from app.modules.ingestion.models import DataSourceDomain
from app.modules.invoices.cost_categories import CostCategory
from app.modules.snapshots.repository import RoomInventoryRepository
from app.modules.tenancy.models import MembershipRole
from tests.ask_home_support import booking_only_coverage, provenance_for, sync_feed
from tests.data_overview_support import IMPORT_FINISHED_AT, seed_run, succeeded_import, utc
from tests.decision_api_support import decision_table_counts
from tests.mia_decision_support import (
    AS_OF,
    HideAreas,
    clear_evaluations,
    insufficient_evaluations,
    json_text,
    seed_five_decisions,
    spoken_text,
    world_for,
)
from tests.mia_support import MiaWorld
from tests.support import BookingFactory, Tenant


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


@pytest.fixture
def world(factory: BookingFactory, db_session: Session, tenant: Tenant) -> MiaWorld:
    return world_for(factory, db_session, tenant)


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = payload["dati"]
    return data


def _areas(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["area"]: row for row in _data(payload)["aree"]}


# --- registration


def test_the_context_tools_are_in_the_catalog_and_filter_their_own_areas(world: MiaWorld) -> None:
    context = world.catalog.get("get_current_property_context")
    status = world.catalog.get("get_data_status")
    assert context is not None and status is not None
    assert context.domain is AccessDomain.COMPANY
    # the status filters the areas itself: it must be callable with ANY area hidden
    assert status.domain is None
    for definition in (context, status):
        assert definition.spec().input_schema["properties"] == {}


@pytest.mark.parametrize("tool", ["get_current_property_context", "get_data_status"])
def test_the_context_tools_refuse_an_argument_they_do_not_have(world: MiaWorld, tool: str) -> None:
    assert world.call(tool, {"anything": 1}).outcome.is_error


# --- get_current_property_context


def test_the_property_context_states_the_structure_the_date_and_who_asks(
    world: MiaWorld, tenant: Tenant
) -> None:
    payload = world.ok("get_current_property_context")
    data = _data(payload)

    assert payload["strumento"] == "get_current_property_context"
    assert data["struttura"] == tenant.property.name
    assert data["fuso orario"] == "Europe/Rome"
    assert data["valuta"] == "EUR"
    assert data["data di riferimento"] == "2026-08-01, sabato"
    assert data["utente"] == {"nome": "Luisa", "ruolo": "membro del team"}
    assert "contesto:struttura" in payload["riferimenti"]


def test_a_missing_room_inventory_is_unknown_never_zero(world: MiaWorld) -> None:
    payload = world.ok("get_current_property_context")

    assert _data(payload)["camere vendibili nella data di riferimento"] is None
    assert any("inventario camere" in line for line in payload["non disponibile"])


def test_a_known_room_inventory_is_stated_as_it_is_stored(
    world: MiaWorld, db_session: Session, tenant: Tenant
) -> None:
    RoomInventoryRepository(db_session, tenant.context).set_for_date(
        tenant.property.id, AS_OF, rooms_available=40, rooms_out_of_order=2
    )

    payload = world.ok("get_current_property_context")
    data = _data(payload)

    assert data["camere vendibili nella data di riferimento"] == 40
    assert data["camere fuori servizio (solo informativo)"] == 2
    assert payload["non disponibile"] == []


def test_the_user_is_a_first_name_and_a_role_never_an_address(
    factory: BookingFactory, db_session: Session, tenant: Tenant
) -> None:
    world = world_for(factory, db_session, tenant)
    runtime = world.runtime()
    runtime.user = UserContext(world.at.user.id, MembershipRole.OWNER, "mario.rossi@example.com")

    payload = world.ok("get_current_property_context", runtime=runtime)

    assert _data(payload)["utente"] == {"nome": None, "ruolo": "titolare dell'account"}
    text = json_text(payload)
    assert "@" not in text
    assert world.at.user.email not in text


def test_the_page_is_a_labelled_hint_with_a_token_for_the_decision_and_no_raw_ids(
    world: MiaWorld,
) -> None:
    decision_id, import_id = uuid4(), uuid4()
    page = PageContext(
        route="/dati",
        page_title="Dati",
        section="labor",
        section_title="Personale",
        period_days=7,
        metric_title="Costo del personale",
        decision=DecisionHint(
            str(decision_id), "Pickup sotto le attese", "Aperta", "2026-07-30", "2026-08-01"
        ),
        import_hint=ImportHint(str(import_id), "completato", "prenotazioni", None),
        entity_kind="cost_category",
        entity_id="FOOD",
    )

    payload = world.ok("get_current_property_context", runtime=world.runtime(page=page))
    data = _data(payload)

    (key,) = [k for k in data if k.startswith("cosa sta guardando l'utente")]
    assert "solo un suggerimento" in key
    hint = data[key]
    assert hint["pagina"] == "Dati"
    assert hint["sezione"] == "Personale"
    assert hint["decisione selezionata"]["riferimento"] == ref_token(decision_id)
    assert set(hint["import selezionato"]) == {"stato", "tipo di dati", "terminato"}
    # a category code is the product's own word, not something to hand to the model raw
    assert hint["elemento selezionato"]["identificativo"] == cost_category_label_of(
        CostCategory.FOOD
    )
    assert "contesto:pagina" in payload["riferimenti"]
    text = json_text(payload)
    assert str(decision_id) not in text and str(import_id) not in text
    assert not contains_technical_leak(spoken_text(payload))


def test_with_no_page_there_is_no_hint(world: MiaWorld) -> None:
    payload = world.ok("get_current_property_context")

    assert not [k for k in _data(payload) if k.startswith("cosa sta guardando")]
    assert "contesto:pagina" not in payload["riferimenti"]


# --- get_data_status: the state of the analysis


def test_a_property_never_analysed_says_so_and_nothing_more(world: MiaWorld) -> None:
    payload = world.ok("get_data_status")
    data = _data(payload)

    assert "prima analisi" in data["stato dell'analisi"]
    assert "ultima analisi completata" not in data
    assert payload["copertura"]["copertura dell'analisi"] == "nessuna analisi disponibile"
    assert all(row["stato"] == "non disponibile" for row in data["aree"])
    assert any(
        "analisi del giorno non è ancora disponibile" in x for x in payload["non disponibile"]
    )
    assert "controlli rimasti senza conclusione per dati insufficienti" not in data


def test_no_analysis_today_but_an_earlier_one_names_its_date(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, as_of=AS_OF - timedelta(days=3))

    payload = world.ok("get_data_status")
    data = _data(payload)

    assert data["ultima analisi completata"] == "2026-07-29"
    assert "2026-07-29" in data["stato dell'analisi"]
    assert "non è ancora disponibile" in data["stato dell'analisi"]


def test_nothing_to_act_on_is_stated_for_what_was_analysed_not_as_all_fine(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, evaluations=clear_evaluations(tenant), coverage=None)

    payload = world.ok("get_data_status")
    data = _data(payload)

    assert "per quanto analizzato oggi" in data["stato dell'analisi"]
    assert data["controlli rimasti senza conclusione per dati insufficienti"] == 0
    # the default coverage skips costs and labor: they are NOT "under control", just unseen
    areas = _areas(payload)
    assert areas["Costi"]["stato"] == "non analizzata"
    assert "non può dire che vada tutto bene" in areas["Costi"]["esito"]
    assert payload["copertura"]["copertura dell'analisi"] == "parziale"
    assert payload["copertura"]["aree non analizzate"] == ["Costi", "Personale"]
    assert payload["copertura"]["aree analizzate"] == ["Ricavi", "Distribuzione"]


def test_checks_without_enough_data_are_counted_and_never_explained_away(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, evaluations=insufficient_evaluations(tenant))

    payload = world.ok("get_data_status")
    data = _data(payload)

    assert "Nessuna decisione affidabile oggi" in data["stato dell'analisi"]
    assert "Non vuol dire che vada tutto bene" in data["stato dell'analisi"]
    assert data["controlli rimasti senza conclusione per dati insufficienti"] == 1
    assert _areas(payload)["Ricavi"]["stato"] == "analisi parziale"
    # NINFA does not record why: the tool says so instead of offering a cause
    assert any("non ipotizzarne uno" in note for note in payload["note"])
    text = json_text(payload).lower()
    for invented_cause in ("storico ancora", "nessuna nuova prenotazione", "bassa affidabilit"):
        assert invented_cause not in text


def test_decisions_are_counted_per_area_when_there_are_some(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_five_decisions(factory, db_session, tenant)

    payload = world.ok("get_data_status")
    areas = _areas(payload)

    assert "richiedono attenzione" in _data(payload)["stato dell'analisi"]
    assert areas["Ricavi"]["decisioni"] == 2
    assert areas["Distribuzione"]["decisioni"] == 1
    assert areas["Costi"]["decisioni"] == 1
    assert areas["Personale"]["decisioni"] == 1
    assert payload["copertura"]["copertura dell'analisi"] == "completa"


def test_an_unrecorded_coverage_is_said_to_be_unrecorded(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, unknown_coverage=True)

    payload = world.ok("get_data_status")

    assert payload["copertura"]["copertura dell'analisi"] == "non registrata per questa analisi"
    assert all(row["stato"] == "non disponibile" for row in _data(payload)["aree"])


# --- get_data_status: where the data come from


def test_the_last_booking_import_is_a_dated_fact_in_the_property_time_zone(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, finished_at=IMPORT_FINISHED_AT)  # 07:15 UTC = 09:15 in Rome

    freshness = world.ok("get_data_status")["aggiornamento"]

    assert freshness["prenotazioni"] == {
        "ultimo import": "oggi alle 09:15",
        "giorni dall'ultimo import": 0,
    }


def test_an_older_import_is_dated_never_called_stale(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, finished_at=utc(2026, 7, 30, 7, 15))

    payload = world.ok("get_data_status")

    assert payload["aggiornamento"]["prenotazioni"] == {
        "ultimo import": "il 2026-07-30 alle 09:15",
        "giorni dall'ultimo import": 2,
    }
    verdict_free = json_text({"dati": payload["dati"], "aggiornamento": payload["aggiornamento"]})
    for verdict in ("stale", "obsolet", "vecchio", "aggiornato"):
        assert verdict not in verdict_free.lower()


def test_costs_and_labor_freshness_come_from_their_own_single_source(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)
    costs_source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    succeeded_import(factory, costs_source, utc(2026, 7, 31, 10, 0))

    freshness = world.ok("get_data_status")["aggiornamento"]

    assert freshness["costi"] == {
        "ultimo import": "ieri alle 12:00",
        "giorni dall'ultimo import": 1,
    }
    assert freshness["personale"] == {
        "ultimo import": None,
        "motivo": "nessuna origine dati configurata",
    }


def test_a_source_with_no_completed_import_says_so(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    sync_feed(db_session, tenant, [], coverage=booking_only_coverage(), provenance=None)

    freshness = world.ok("get_data_status")["aggiornamento"]

    assert freshness["prenotazioni"]["ultimo import"] is None
    assert freshness["prenotazioni"]["motivo"]


def test_the_blocks_say_why_a_block_has_no_figures(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant)  # a run, but no snapshot for any night

    payload = world.ok("get_data_status")
    blocks = {row["blocco"]: row for row in _data(payload)["blocchi di dati"]}

    occupancy = blocks["Prenotazioni e occupazione"]
    assert occupancy["disponibile"] is False
    assert occupancy["motivo"] == "Non ci sono prenotazioni registrate per questo periodo."
    assert any("Prenotazioni e occupazione" in line for line in payload["non disponibile"])


# --- get_data_status: was the latest delivery new (ADR 0045)


def _provenance_of(tenant: Tenant, import_job_id: Any) -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=tenant.data_source.id,
            import_job_id=import_job_id,
            last_successful_import_finished_at=IMPORT_FINISHED_AT,
        )
    )


def test_the_same_import_as_the_previous_day_is_not_new_data(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    previous = AS_OF - timedelta(days=1)
    sync_feed(
        db_session,
        tenant,
        [],
        as_of=previous,
        provenance=provenance_for(tenant, IMPORT_FINISHED_AT),
    )
    sync_feed(db_session, tenant, [], provenance=provenance_for(tenant, IMPORT_FINISHED_AT))

    payload = world.ok("get_data_status")

    assert _data(payload)["nuovi dati di prenotazione rispetto all'analisi precedente"] is False
    note = " ".join(payload["note"])
    assert "il pickup non è noto, non è zero" in note


def test_another_import_than_the_previous_day_is_new_data(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    previous = AS_OF - timedelta(days=1)
    sync_feed(
        db_session,
        tenant,
        [],
        as_of=previous,
        provenance=provenance_for(tenant, IMPORT_FINISHED_AT),
    )
    newer = succeeded_import(factory, tenant.data_source, IMPORT_FINISHED_AT + timedelta(hours=3))
    sync_feed(db_session, tenant, [], provenance=_provenance_of(tenant, newer.id))

    payload = world.ok("get_data_status")

    assert _data(payload)["nuovi dati di prenotazione rispetto all'analisi precedente"] is True


def test_a_run_that_does_not_say_enough_leaves_the_delivery_unknown_not_guessed(
    db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_run(db_session, tenant, with_provenance=False)

    payload = world.ok("get_data_status")

    assert _data(payload)["nuovi dati di prenotazione rispetto all'analisi precedente"] is None
    assert any("dati nuovi" in line for line in payload["non disponibile"])


# --- hidden areas


def test_a_hidden_area_leaves_no_trace_in_rows_coverage_freshness_or_totals(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_five_decisions(factory, db_session, tenant)
    costs_source = factory.data_source(tenant.property, DataSourceDomain.COSTS)
    succeeded_import(factory, costs_source, utc(2026, 7, 31, 10, 0))
    runtime = world.runtime(access=HideAreas(AccessDomain.COSTS))

    payload = world.ok("get_data_status", runtime=runtime)
    data = _data(payload)

    assert set(_areas(payload)) == {"Ricavi", "Distribuzione", "Personale"}
    assert "costi" not in payload["aggiornamento"]
    assert "Costi" not in payload["copertura"]["aree analizzate"]
    assert all(row["blocco"] != "Costi" for row in data["blocchi di dati"])
    # the two run-level counts cannot be split by area: they are withheld, not guessed
    assert "controlli rimasti senza conclusione per dati insufficienti" not in data
    assert "controlli non mostrati perché poco affidabili" not in data
    assert any("non sono consentite" in note for note in payload["note"])
    assert "Costi" not in json_text(payload).replace("Costi e personale", "")


def test_with_every_booking_area_hidden_the_booking_delivery_is_not_reported(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_five_decisions(factory, db_session, tenant)
    runtime = world.runtime(access=HideAreas(AccessDomain.REVENUE, AccessDomain.DISTRIBUTION))

    payload = world.ok("get_data_status", runtime=runtime)

    assert "prenotazioni" not in payload["aggiornamento"]
    assert _data(payload)["nuovi dati di prenotazione rispetto all'analisi precedente"] is None


# --- safety nets


def test_the_state_of_a_run_with_decisions_is_hidden_when_all_its_decisions_are(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    """The engine's state is domain-blind: with every decision's area hidden the tool must not say
    that something requires attention."""
    seed_five_decisions(factory, db_session, tenant)
    runtime = world.runtime(access=HideAreas(*AccessDomain.__members__.values()))

    # COMPANY/PRODUCT are not analysis areas, but hiding them is harmless to this tool
    payload = world.ok("get_data_status", runtime=runtime)

    assert "Nessuna decisione che richieda attenzione" in _data(payload)["stato dell'analisi"]
    assert _data(payload)["aree"] == []


@pytest.mark.parametrize("tool", ["get_current_property_context", "get_data_status"])
def test_no_observation_leaks_a_technical_word_exceeds_the_size_or_writes(
    factory: BookingFactory,
    db_session: Session,
    world: MiaWorld,
    tenant: Tenant,
    tool: str,
) -> None:
    seed_five_decisions(factory, db_session, tenant)
    before = decision_table_counts(db_session)
    page = PageContext(route="/oggi", page_title="Oggi", section="overview")

    execution = world.call(tool, runtime=world.runtime(page=page))

    assert not execution.outcome.is_error, execution.outcome.content
    text = execution.outcome.content
    assert not contains_technical_leak(spoken_text(json.loads(text))), text
    assert len(text) < MAX_OBSERVATION_CHARS // 3
    assert decision_table_counts(db_session) == before


def test_every_figure_of_the_status_can_be_restated_and_an_invented_one_cannot(
    factory: BookingFactory, db_session: Session, world: MiaWorld, tenant: Tenant
) -> None:
    seed_five_decisions(factory, db_session, tenant)
    execution = world.call("get_data_status")
    assert execution.observation is not None
    figures, dates = split_observation_numbers([observation_to_json(execution.observation)])

    assert ungrounded_numbers("Ci sono 2 decisioni sui ricavi.", figures, dates) == []
    assert ungrounded_numbers("Ci sono 17 decisioni sui ricavi.", figures, dates) == ["17"]


def test_an_unknown_category_code_is_dropped_not_passed_on_raw(world: MiaWorld) -> None:
    page = PageContext(entity_kind="labor_category", entity_id="SOMETHING_NEW")

    payload = world.ok("get_current_property_context", runtime=world.runtime(page=page))
    (hint,) = [v for k, v in _data(payload).items() if k.startswith("cosa sta guardando")]

    assert hint["elemento selezionato"] == {"tipo": "labor category", "identificativo": None}
    assert "SOMETHING" not in json_text(payload)
