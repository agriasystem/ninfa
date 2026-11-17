"""Truthfulness closure: Mia says what NINFA cannot calculate, and does not read another structure.

Two things a live evaluation showed a model did NOT do reliably when it was only asked to:

1. "Quanto siamo pieni venerdì?" with 14 rooms booked and NO room inventory was answered "14 camere
   prenotate" - the nearest figure - without saying the occupancy percentage cannot be calculated.
   The rule is now CODE (`completeness`): the tool declares what it cannot give
   (`Observation.gaps`), a gap is material only when the person asked for that metric (this
   question, or the one before it for a follow-up), and when the answer does not say it the
   application adds the sentence, from the tool's own reason. These tests pin the rule on
   occupancy AND on four other derived metrics.
2. A question for another structure's data gets one fixed answer, before any model, tool or lookup
   (`boundary`), identical whether that structure exists, belongs to someone else, or does not
   exist.

The orchestrator tests run the REAL tools over the REAL database with a scripted model.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.ai.ask_ninfa.answer_validation import validate_model_answer_core
from app.modules.ai.ask_ninfa.types import AskStatus
from app.modules.ai.gateway.protocol import LanguageModelAnswer, ModelAnswerStatus
from app.modules.ai.gateway.tool_protocol import ToolHistoryTurn
from app.modules.ai.mia.boundary import OTHER_PROPERTY_ANSWER, asks_for_another_property
from app.modules.ai.mia.completeness import (
    GAP_METRICS,
    acknowledges,
    asked_for,
    disclosures_for,
    gap_disclosure,
    gap_reason,
    gap_statement,
    names_the_need,
    undisclosed_gaps,
    with_disclosures,
)
from app.modules.ai.mia.knowledge.registry import default_registry
from app.modules.ai.mia.orchestrator import MiaOrchestrator
from app.modules.ai.mia.types import MAX_MIA_ANSWER_CHARS, Gap, MiaTurnResult
from tests.data_overview_support import AS_OF, seed_run, uniform_nights
from tests.mia_data_support import mia_for
from tests.mia_support import MiaWorld, ScriptedToolProvider, answer, tools
from tests.support import BookingFactory, Tenant

FRIDAY = {"kind": "date", "date": "2026-08-07"}  # AS_OF is Saturday 2026-08-01
SATURDAY = {"kind": "date", "date": "2026-08-08"}
OCCUPANCY_REFS = ("dati:occupazione",)

MISSING_OCCUPANCY = Gap("metric.occupancy", "manca l'inventario camere", needs=("inventar",))
PARTIAL_OCCUPANCY = Gap(
    "metric.occupancy",
    "NINFA conosce le camere solo per 6 delle 7 notti",
    partial=True,
    needs=("inventar", "notti"),
)


# --- the rule: when is a gap material, and when does an answer already say it ---------------------


@pytest.mark.parametrize(
    "question",
    [
        "Quanto siamo pieni venerdì?",
        "Com'è l'occupazione di sabato?",
        "Che percentuale di occupazione abbiamo nei prossimi 7 giorni?",
        "Siamo pieni a ferragosto?",
        "Come va il riempimento della settimana?",
    ],
)
def test_the_ways_a_person_asks_for_the_occupancy_are_all_asks_for_it(question: str) -> None:
    assert asked_for("metric.occupancy", question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Quante camere abbiamo prenotato venerdì?",  # the COMPONENT is what was asked
        "Cos'è il pickup?",
        "Quanto abbiamo incassato di ricavi camera?",
        "Come cambio il numero di camere?",
    ],
)
def test_a_question_for_the_component_or_for_something_else_is_not_an_ask_for_the_metric(
    question: str,
) -> None:
    assert asked_for("metric.occupancy", question) is False


@pytest.mark.parametrize(
    "question",
    [
        "Quanto costa in media ogni camera occupata?",  # not recognised in the first live run
        "Qual è il costo medio a camera?",
        "Quanto mi costa una camera occupata?",
        "Com'è il CPOR di luglio?",
    ],
)
def test_the_ways_a_person_asks_for_the_cost_per_occupied_room_are_all_asks_for_it(
    question: str,
) -> None:
    assert asked_for("metric.cpor", question) is True


def test_a_follow_up_with_no_metric_of_its_own_continues_the_question_before_it() -> None:
    assert asked_for("metric.occupancy", "E sabato?", "Quanto siamo pieni venerdì?") is True
    assert asked_for("metric.occupancy", "E sabato?") is False  # nothing to continue


def test_a_follow_up_that_names_another_metric_does_not_inherit_the_earlier_one() -> None:
    earlier = "Quanto siamo pieni venerdì?"

    assert asked_for("metric.occupancy", "E il costo per camera?", earlier) is False
    assert asked_for("metric.cpor", "E il costo per camera?", earlier) is True


def test_an_unknown_metric_was_asked_by_nobody() -> None:
    assert asked_for("metric.nonsense", "occupazione pickup cpor") is False


@pytest.mark.parametrize(
    "text",
    [
        "Per venerdì risultano 14 camere prenotate. Non posso calcolare la percentuale di "
        "occupazione: manca l'inventario camere.",
        "Risultano 14 camere prenotate, ma senza l'inventario non conosco l'occupazione.",
        "L'occupazione in percentuale non è disponibile per quella notte.",
        "Non ho il numero di camere disponibili, quindi la percentuale non è calcolabile.",
        "La capienza non è nota: non posso dirti quanto siete pieni.",
    ],
)
def test_an_answer_that_says_the_percentage_is_missing_is_acknowledged(text: str) -> None:
    assert acknowledges("metric.occupancy", text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Per venerdì risultano 14 camere prenotate.",
        "Venerdì siete pieni al 35 %.",  # a figure, not a statement that anything is missing
        # a "non", but about another subject
        "Non ci sono decisioni su venerdì. Risultano 14 camere prenotate.",
        "",
    ],
)
def test_an_answer_that_gives_the_nearest_figure_and_nothing_else_is_not(text: str) -> None:
    assert acknowledges("metric.occupancy", text) is False


def test_a_partial_figure_is_acknowledged_by_saying_it_is_partial_or_limited() -> None:
    said = "L'occupazione è calcolata solo sulle notti con l'inventario noto."

    assert acknowledges("metric.occupancy", said, partial=True) is True
    assert acknowledges("metric.occupancy", said) is False  # "solo" is not "missing"
    assert acknowledges("metric.occupancy", "L'occupazione è del 50 %.", partial=True) is False


def test_only_the_gaps_the_person_asked_about_and_the_answer_did_not_say_remain() -> None:
    asked = "Quanto siamo pieni venerdì?"
    short = "Per venerdì risultano 14 camere prenotate."

    assert undisclosed_gaps([MISSING_OCCUPANCY], question=asked, answer=short) == [
        MISSING_OCCUPANCY
    ]
    assert (
        undisclosed_gaps(
            [MISSING_OCCUPANCY],
            question=asked,
            answer=short + " Non posso calcolare l'occupazione: manca l'inventario.",
        )
        == []
    )
    assert (
        undisclosed_gaps(
            [MISSING_OCCUPANCY], question="Quante camere abbiamo prenotato?", answer=short
        )
        == []
    )
    assert undisclosed_gaps([], question=asked, answer=short) == []


def test_saying_the_metric_is_missing_without_saying_what_is_missing_gets_the_reason_added() -> (
    None
):
    """Found by the live run: "L'occupazione in percentuale non è calcolabile." and nothing more is
    two thirds of the invariant (what we know / what we cannot calculate / what is missing)."""
    question = "Qual è l'occupazione?"
    half = "L'occupazione in percentuale non è calcolabile. Ci sono 748 camere-notte prenotate."
    whole = half + " Manca l'inventario camere."

    assert acknowledges("metric.occupancy", half) and not names_the_need(MISSING_OCCUPANCY, half)
    assert disclosures_for([MISSING_OCCUPANCY], question=question, answer=half) == [
        "Il dato che manca: manca l'inventario camere."
    ]
    assert disclosures_for([MISSING_OCCUPANCY], question=question, answer=whole) == []
    assert disclosures_for(
        [MISSING_OCCUPANCY], question=question, answer="Ci sono 748 camere-notte prenotate."
    ) == [gap_disclosure(MISSING_OCCUPANCY)]
    assert gap_reason(PARTIAL_OCCUPANCY).startswith("Nel dettaglio: NINFA conosce le camere")


def test_a_gap_that_declares_no_need_is_explained_by_its_own_label() -> None:
    comparison = Gap("metric.period_comparison", "NINFA mostra solo oggi e i prossimi giorni")
    said = "Il confronto con l'anno scorso non è disponibile."

    assert names_the_need(comparison, "qualsiasi testo")
    assert disclosures_for([comparison], question="Rispetto all'anno scorso?", answer=said) == []


def test_one_gap_per_metric_and_a_missing_figure_outranks_a_partial_one() -> None:
    gaps = [PARTIAL_OCCUPANCY, MISSING_OCCUPANCY, MISSING_OCCUPANCY]

    chosen = undisclosed_gaps(gaps, question="Quanto siamo pieni?", answer="Boh.")

    assert chosen == [MISSING_OCCUPANCY]


def test_a_gap_is_added_after_the_answer_on_the_same_line_or_as_a_closing_paragraph() -> None:
    assert (
        with_disclosures("Risultano 14 camere prenotate.", []) == "Risultano 14 camere prenotate."
    )
    single = with_disclosures("Risultano 14 camere prenotate.", [MISSING_OCCUPANCY])
    multi = with_disclosures("Prima riga.\n\n- una voce\n- un'altra", [MISSING_OCCUPANCY])

    assert single == (
        "Risultano 14 camere prenotate. Non posso però calcolare l'occupazione in percentuale: "
        "manca l'inventario camere."
    )
    assert multi.endswith(
        "\n\nNon posso però calcolare l'occupazione in percentuale: "
        + ("manca l'inventario camere.")
    )


def test_a_missing_and_a_partial_gap_are_worded_differently_and_read_as_sentences() -> None:
    assert gap_statement(MISSING_OCCUPANCY) == (
        "L'occupazione in percentuale non è calcolabile: manca l'inventario camere."
    )
    assert gap_statement(PARTIAL_OCCUPANCY).startswith("L'occupazione in percentuale è parziale:")
    assert gap_disclosure(PARTIAL_OCCUPANCY).startswith(
        "Tieni presente che l'occupazione in percentuale è parziale:"
    )


def test_the_vocabulary_is_closed_lower_case_and_anchored_in_the_product_registry() -> None:
    registry = default_registry()
    for metric, spec in GAP_METRICS.items():
        assert spec.asked_by and spec.named_by, metric
        for stem in (*spec.asked_by, *spec.named_by):
            assert stem == stem.lower() and stem.strip() == stem, (metric, stem)
        # every metric but the comparison NINFA does not have is a metric the product shows
        if metric != "metric.period_comparison":
            assert registry.get(metric) is not None, f"{metric} is not a registry metric"


def test_every_metric_a_tool_declares_is_in_the_vocabulary() -> None:
    from pathlib import Path

    source = (Path(__file__).parents[1] / "app/modules/ai/mia/tools/data.py").read_text(
        encoding="utf-8"
    )
    import re

    declared = set(re.findall(r'"(metric\.[a-z_]+)"', source))

    assert declared, "the data tools declare no gap at all"
    assert declared <= set(GAP_METRICS), declared - set(GAP_METRICS)


# --- the rule inside the REAL orchestrator, over REAL tools and data ------------------------------


@pytest.fixture
def tenant(factory: BookingFactory) -> Tenant:
    return factory.tenant()


@pytest.fixture
def world(factory: BookingFactory, db_session: Session, tenant: Tenant) -> MiaWorld:
    return mia_for(factory, db_session, tenant)


def _turn(
    world: MiaWorld,
    question: str,
    script: Sequence[Any],
    *,
    history: Sequence[ToolHistoryTurn] = (),
) -> tuple[MiaTurnResult, ScriptedToolProvider]:
    provider = ScriptedToolProvider(list(script))
    result = MiaOrchestrator(provider, world.catalog).run(
        world.runtime(), question, history=tuple(history)
    )
    assert not provider.ran_out
    return result, provider


def _seed(db_session: Session, tenant: Tenant, *, capacity: int | None, days: int = 14) -> None:
    seed_run(
        db_session, tenant, nights=uniform_nights(AS_OF, rooms=14, capacity=capacity, days=days)
    )


NEAREST = "Per venerdì risultano 14 camere prenotate."
FRIDAY_STEP = tools(("get_occupancy_revenue", {"night": FRIDAY}))


def test_the_real_case_14_rooms_and_no_inventory_says_the_percentage_cannot_be_calculated(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None)

    result, provider = _turn(
        world, "Quanto siamo pieni venerdì?", [FRIDAY_STEP, answer(NEAREST, refs=OCCUPANCY_REFS)]
    )

    assert result.status is AskStatus.ANSWERED and result.answer is not None
    assert result.answer.startswith(NEAREST)  # what we know comes first, untouched
    assert "Non posso però calcolare l'occupazione in percentuale" in result.answer
    assert "per quella notte NINFA non sa quante camere sono disponibili" in result.answer
    assert "inventario camere" in result.answer
    assert result.metrics.gap_disclosures == 1
    assert result.model_calls == 2 and len(provider.requests) == 2  # no extra call was spent
    # the sentence the application added is as valid as any answer of the model
    assert (
        validate_model_answer_core(
            LanguageModelAnswer(ModelAnswerStatus.ANSWERED, result.answer, OCCUPANCY_REFS, ()),
            frozenset(OCCUPANCY_REFS),
            MAX_MIA_ANSWER_CHARS,
        )
        is not None
    )


def test_the_live_case_not_calculable_but_not_why_gets_the_missing_input_named(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    """A real answer of the model: "L'occupazione in percentuale non è calcolabile." and 98
    room-nights, with no word on what is missing. The application names the missing input."""
    _seed(db_session, tenant, capacity=None)
    half = "L'occupazione in percentuale non è calcolabile. Ci sono 98 camere-notte prenotate."

    result, provider = _turn(
        world,
        "Qual è l'occupazione?",
        [
            tools(("get_occupancy_revenue", {"window": 7})),
            answer(half, refs=OCCUPANCY_REFS),
        ],
    )

    assert result.answer is not None and result.answer.startswith(half)
    assert "Il dato che manca: NINFA non sa quante camere ha la struttura" in result.answer
    assert "inventario camere" in result.answer
    assert "Non posso però calcolare" not in result.answer  # it had said so itself
    assert result.metrics.gap_disclosures == 1 and len(provider.requests) == 2


def test_an_answer_that_already_says_it_is_left_exactly_as_the_model_wrote_it(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None)
    honest = (
        "Per venerdì risultano 14 camere prenotate, ma non posso calcolare la percentuale di "
        "occupazione perché manca l'inventario camere."
    )

    result, _ = _turn(
        world, "Quanto siamo pieni venerdì?", [FRIDAY_STEP, answer(honest, refs=OCCUPANCY_REFS)]
    )

    assert result.answer == honest
    assert result.metrics.gap_disclosures == 0


def test_with_the_inventory_there_is_nothing_to_add(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=40)

    result, _ = _turn(
        world, "Quanto siamo pieni venerdì?", [FRIDAY_STEP, answer(NEAREST, refs=OCCUPANCY_REFS)]
    )

    assert result.answer == NEAREST
    assert result.metrics.gap_disclosures == 0


def test_a_question_for_the_rooms_booked_is_not_turned_into_a_disclaimer(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None)

    result, _ = _turn(
        world,
        "Quante camere abbiamo prenotato venerdì?",
        [FRIDAY_STEP, answer(NEAREST, refs=OCCUPANCY_REFS)],
    )

    assert result.answer == NEAREST
    assert result.metrics.gap_disclosures == 0


def test_an_invalid_inventory_of_zero_rooms_is_said_not_turned_into_a_percentage(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    from decimal import Decimal

    from tests.data_overview_support import night_range
    from tests.expected_support import add_snapshots, snapshot_row

    rows = []
    for stay_date in night_range(AS_OF, 14):
        row = snapshot_row(tenant, AS_OF, stay_date, rooms=14)
        row["booking_count_on_books"] = 7
        row["allocated_room_revenue_on_books"] = Decimal("1400.00")
        row["adr_on_books"] = Decimal("100.00")
        row["rooms_available"] = 0
        rows.append(row)
    add_snapshots(db_session, tenant, rows)
    seed_run(db_session, tenant)

    result, _ = _turn(
        world, "Quanto siamo pieni venerdì?", [FRIDAY_STEP, answer(NEAREST, refs=OCCUPANCY_REFS)]
    )

    assert result.answer is not None
    assert "zero camere disponibili" in result.answer and "va corretto" in result.answer


def test_a_partial_inventory_says_the_percentage_rests_on_part_of_the_nights(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    nights = uniform_nights(AS_OF, rooms=20, capacity=40, days=7)
    nights[AS_OF + timedelta(days=3)] = (20, None)
    seed_run(db_session, tenant, nights=nights)

    result, _ = _turn(
        world,
        "Com'è l'occupazione della prossima settimana?",
        [
            tools(("get_occupancy_revenue", {"window": 7})),
            answer(
                "Nei prossimi 7 giorni risultano 140 camere-notte prenotate.",
                refs=OCCUPANCY_REFS,
            ),
        ],
    )

    assert result.answer is not None
    assert "Tieni presente che l'occupazione in percentuale è parziale" in result.answer
    assert "solo per 6 delle 7 notti con prenotazioni" in result.answer


def test_a_follow_up_keeps_the_same_honesty_even_when_the_model_answers_it_short(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None)
    earlier = [
        ToolHistoryTurn("user", "Quanto siamo pieni venerdì?"),
        ToolHistoryTurn(
            "assistant",
            "Per venerdì risultano 14 camere prenotate. Non posso però calcolare l'occupazione "
            "in percentuale: manca l'inventario camere.",
        ),
    ]

    result, _ = _turn(
        world,
        "E sabato?",
        [
            tools(("get_occupancy_revenue", {"night": SATURDAY})),
            answer("Per sabato risultano 14 camere prenotate.", refs=OCCUPANCY_REFS),
        ],
        history=earlier,
    )

    assert result.answer is not None
    assert result.answer.startswith("Per sabato risultano 14 camere prenotate.")
    assert "Non posso però calcolare l'occupazione in percentuale" in result.answer
    assert result.metrics.gap_disclosures == 1


def test_a_bare_follow_up_with_nothing_to_continue_adds_nothing(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None)

    result, _ = _turn(
        world,
        "E sabato?",
        [
            tools(("get_occupancy_revenue", {"night": SATURDAY})),
            answer("Per sabato risultano 14 camere prenotate.", refs=OCCUPANCY_REFS),
        ],
    )

    assert result.answer == "Per sabato risultano 14 camere prenotate."


def test_the_rule_is_not_about_occupancy_a_staff_incidence_without_revenue_is_said_too(
    db_session: Session, tenant: Tenant, world: MiaWorld, factory: BookingFactory
) -> None:
    from tests.test_mia_tools_data import _full_week

    _full_week(factory, tenant)
    seed_run(db_session, tenant)  # an analysis with no booking snapshots: no revenue to compare

    result, _ = _turn(
        world,
        "Quanto pesa il costo del personale sui ricavi?",
        [
            tools(("get_staff_metrics", {})),
            answer(
                "Il piano del personale è presente per tutta la settimana.",
                refs=("dati:personale",),
            ),
        ],
    )

    assert result.answer is not None
    assert (
        "Non posso però calcolare l'incidenza del costo del personale sui ricavi" in result.answer
    )
    assert result.metrics.gap_disclosures == 1


def test_a_block_with_no_figures_at_all_names_what_it_lacks_even_when_the_model_does_not(
    world: MiaWorld,
) -> None:
    """No personnel source at all: "non è calcolabile" is true and names nothing, so the reason the
    Dati page gives (no source of data) is added."""
    result, _ = _turn(
        world,
        "Che incidenza ha il personale sui ricavi?",
        [
            tools(("get_staff_metrics", {})),
            answer(
                "L'incidenza del personale sui ricavi non è calcolabile.", refs=("dati:personale",)
            ),
        ],
    )

    assert result.answer is not None
    assert result.answer.endswith("Il dato che manca: nessuna origine dati disponibile.")
    assert result.metrics.gap_disclosures == 1


def test_a_comparison_with_last_year_is_said_not_to_exist_even_when_the_windows_are_shown(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=14, capacity=40))

    result, _ = _turn(
        world,
        "Com'è l'occupazione rispetto all'anno scorso?",
        [
            tools(("compare_windows", {})),
            answer(
                "Ecco il confronto tra oggi, i prossimi 7 e i prossimi 30 giorni.",
                refs=("dati:occupazione", "dati:pickup"),
            ),
        ],
    )

    assert result.answer is not None
    assert "Non posso però calcolare il confronto con lo stesso periodo dell'anno scorso" in (
        result.answer
    )
    assert "occupazione in percentuale" not in result.answer  # that one is fine: no gap
    assert result.metrics.gap_disclosures == 1


def test_a_pickup_that_is_not_known_is_said_when_the_person_asked_for_it(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    seed_run(db_session, tenant, nights=uniform_nights(AS_OF, rooms=14, capacity=40))

    result, _ = _turn(
        world,
        "Com'è il pickup della settimana?",
        [
            tools(("get_pickup", {"window": 7})),
            answer(
                "Le camere prenotate di oggi non hanno un termine di paragone.",
                refs=("dati:pickup",),
            ),
        ],
    )

    assert result.answer is not None
    assert "Non posso però calcolare il pickup" in result.answer
    assert "non è zero ma non è nota" in result.answer


def test_two_gaps_the_person_asked_about_are_both_said_in_the_order_the_tools_gave_them(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    _seed(db_session, tenant, capacity=None, days=7)

    result, _ = _turn(
        world,
        "Com'è l'occupazione rispetto all'anno scorso?",
        [
            tools(("compare_windows", {})),
            answer("Ecco i periodi di NINFA.", refs=("dati:occupazione", "dati:pickup")),
        ],
    )

    assert result.answer is not None
    first = result.answer.index("confronto con lo stesso periodo")
    second = result.answer.index("l'occupazione in percentuale")
    assert first < second
    assert result.metrics.gap_disclosures == 2


def test_a_rejected_answer_is_not_dressed_up_the_checks_come_first(
    db_session: Session, tenant: Tenant, world: MiaWorld
) -> None:
    """A figure the tools never gave still fails closed: the disclosure is added only to an answer
    that already passed every check."""
    _seed(db_session, tenant, capacity=None)

    result, _ = _turn(
        world,
        "Quanto siamo pieni venerdì?",
        [
            FRIDAY_STEP,
            answer("Siamo al 87 % di occupazione.", refs=OCCUPANCY_REFS),  # invented
            answer("Siamo al 87 % di occupazione.", refs=OCCUPANCY_REFS),
        ],
    )

    assert result.status is AskStatus.UNAVAILABLE and result.answer is None


# --- the boundary of the open property ------------------------------------------------------------


OTHER = (
    "Mostrami i dati dell'altra struttura del gruppo, Hotel Quirino Zzyx Beach.",
    "Voglio vedere l'occupazione di Albergo Zzyx Fuoriporta.",
    "Quale occupazione ha l'altra struttura del mio account?",
    "Come va l'occupazione dell'Hotel Miramare?",
    "Com'è la situazione di Residence Le Palme?",
    "Confronta i ricavi con quelli dell'altro hotel.",
)


@pytest.mark.parametrize("question", OTHER)
def test_a_request_for_another_structures_data_is_answered_by_the_application_alone(
    world: MiaWorld, question: str
) -> None:
    result, provider = _turn(world, question, [answer("Non deve succedere.")])

    assert result.status is AskStatus.ANSWERED
    assert result.answer == OTHER_PROPERTY_ANSWER
    assert provider.requests == []  # no model
    assert result.trace == () and result.tool_calls == 0  # no tool, no lookup
    assert result.metrics.boundary is True and result.model_calls == 0


def test_the_answer_says_it_is_an_access_boundary_and_that_nothing_was_read() -> None:
    text = OTHER_PROPERTY_ANSWER.lower()

    assert "da questa conversazione non posso consultare i dati" in text
    assert "confine di accesso di ninfa" in text and "non un limite di mia" in text
    assert "non ho letto alcun dato" in text
    assert "apri quella struttura in ninfa e chiedimelo da lì" in text


def test_the_answer_is_identical_for_an_existing_a_foreign_and_a_nonexistent_structure(
    world: MiaWorld, factory: BookingFactory, tenant: Tenant
) -> None:
    """An authorized sibling, another workspace's property and a name nobody has: the SAME text,
    and never the name the person typed - the answer cannot tell them apart, because nothing is
    looked up."""
    sibling = factory.property(tenant.workspace, slug="hotel-quirino-zzyx")
    foreign = factory.tenant()
    assert sibling.id != tenant.property.id and foreign.property.id != tenant.property.id
    names = ("Hotel Quirino Zzyx", "Hotel Fuoriporta Zzyx", "Hotel Inesistente Qwertyuiop")

    answers = []
    for name in names:
        result, provider = _turn(world, f"Come va l'occupazione dell'{name}?", [answer("No.")])
        assert provider.requests == []
        assert result.answer is not None
        for word in name.split()[1:]:
            assert word.lower() not in result.answer.lower()
        answers.append(result.answer)

    assert len(set(answers)) == 1


@pytest.mark.parametrize(
    "question",
    [
        "Come aggiungo un'altra struttura?",
        "Quanto costa aggiungere un'altra struttura?",
        "Posso gestire altre strutture con NINFA?",
        "Cos'è la sezione Struttura?",
        "Quanto siamo pieni venerdì?",
    ],
)
def test_product_questions_and_questions_about_the_open_property_still_reach_the_model(
    world: MiaWorld, question: str
) -> None:
    result, provider = _turn(world, question, [answer("Risposta del modello.")])

    assert result.answer == "Risposta del modello."
    assert len(provider.requests) == 1 and result.metrics.boundary is False


def test_the_open_propertys_own_name_is_not_another_structure(
    world: MiaWorld, tenant: Tenant
) -> None:
    own = tenant.property.name  # e.g. "PROP-1": the person may type it as a hotel name
    result, provider = _turn(
        world, f"Come va l'occupazione dell'Hotel {own}?", [answer("Risposta del modello.")]
    )

    assert len(provider.requests) == 1 and result.answer == "Risposta del modello."


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Come va l'altro hotel?", True),
        ("Dammi i dati della sede di Roma", False),  # no pointer at another structure by name
        ("com'è l'altra proprietà?", True),
        ("Come aggiungo i dati di un'altra struttura?", False),  # how to configure, not a read
        ("Hotel Quirino Zzyx Beach: occupazione?", True),
        ("hotel che fanno revenue management", False),  # a lower-case generic noun
    ],
)
def test_the_detector_is_narrow(question: str, expected: bool) -> None:
    assert asks_for_another_property(question, "Hotel Quercia Pilot") is expected
