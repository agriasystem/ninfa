"""Missing data and data quality / freshness scenarios.

What these worlds have in common is that the honest answer is NOT a number: the inventory is not
configured, the analysis has not run, the bookings cover 7 nights of 30, the last import is three
days
old, the bookings by channel do not add up. A good answer says what is missing or doubtful, says
what
NINFA does have, and never fills the hole (no estimate, no "probably", no zero in place of unknown).
"""

from typing import Any

from tests.benchmarks.mia_openai_v1.dsl import C, S, T, numbered
from tests.benchmarks.mia_openai_v1.model import Scenario

_PRODUCT = ({"get_feature_explanation"}, {"search_ninfa_knowledge"}, {"get_page_help"})


def _missing(
    world: str,
    question: str,
    calls: list[Any],
    answer: str,
    mention: list[Any],
    **rubric: Any,
) -> tuple[str, str, object]:
    if "tool_failure" in rubric and "expect" not in rubric:
        # a read that fails may end as an answer or as "nothing useful to say": both are honest
        rubric["expect"] = ["ANSWERED", "INSUFFICIENT_CONTEXT"]
    return (
        world,
        "missing_data",
        T(question, calls, answer, mention=mention, must_state_missing=True, **rubric),
    )


MISSING = (
    _missing(
        "no_inventory",
        "Qual è l'occupazione?",
        [C("get_occupancy_revenue")],
        "NINFA non può calcolare l'occupazione perché manca l'inventario camere: senza il numero "
        "di "
        "camere vendibili non si sa quante siano occupate. Restano disponibili le prenotazioni, i "
        "ricavi camera ({truth.rev30} euro sulle prenotazioni attuali) e l'ADR.",
        [["inventario"], ["{truth.rev30}"]],
    ),
    _missing(
        "no_inventory",
        "Perché non vedo l'occupazione?",
        [C("get_occupancy_revenue"), C("get_room_inventory")],
        "L'occupazione non è disponibile perché l'inventario camere non è ancora configurato in "
        "Struttura: NINFA non deduce il numero di camere dalle prenotazioni.",
        [["inventario"], ["struttura"]],
    ),
    _missing(
        "no_inventory",
        "Quanto siamo pieni venerdì?",
        [C("get_occupancy_revenue", night={"kind": "weekday", "weekday": "venerdi"})],
        "Venerdì 7 agosto ci sono {truth.rooms_fri} camere prenotate, ma non posso dirti la "
        "percentuale di occupazione perché manca l'inventario camere.",
        [["{truth.rooms_fri}"], ["inventario"]],
    ),
    _missing(
        "no_inventory",
        "Come faccio a far comparire l'occupazione?",
        [C("get_feature_explanation", entry_id="workflow.change_room_count")],
        "Manca l'inventario camere: devi configurarlo in Struttura, nel blocco Inventario camere, "
        "scrivendo il numero di camere vendibili e da quando vale. Poi l'occupazione non è più "
        "mancante.",
        [["struttura"], ["inventario"]],
        tools=[{"get_feature_explanation"}, {"get_room_inventory"}, {"search_ninfa_knowledge"}],
    ),
    _missing(
        "no_analysis",
        "Quali sono le decisioni di oggi?",
        [C("get_today_summary")],
        "L'analisi di oggi non è ancora disponibile: l'ultima analisi completata è del 30 luglio. "
        "Per oggi non posso mostrarti decisioni.",
        [["non è ancora disponibile", "non ancora disponibile"], ["30 luglio"]],
    ),
    _missing(
        "no_analysis",
        "Com'è l'occupazione di oggi?",
        [C("get_occupancy_revenue")],
        "Per oggi l'analisi non è ancora disponibile, quindi l'occupazione non è disponibile.",
        [["non è ancora disponibile", "non ancora disponibile", "non è disponibile"]],
    ),
    _missing(
        "no_analysis",
        "Perché oggi non ho Decision?",
        [C("get_today_summary"), C("get_data_status")],
        "L'analisi di oggi non è ancora disponibile; l'ultima completata è del 30 luglio. Non "
        "posso "
        "dirti il perché con certezza, ma per oggi NINFA non ha decisioni da mostrare.",
        [["non ancora disponibile", "non è ancora disponibile"], ["30 luglio"]],
        tools=[{"get_today_summary"}, {"get_data_status"}],
    ),
    _missing(
        "never_analysed",
        "Com'è la mia struttura?",
        [C("get_today_summary"), C("get_data_status")],
        "NINFA non ha ancora analizzato questa struttura: non ci sono analisi, quindi non posso "
        "dirti come sta andando.",
        [["non ha ancora analizzato", "non ancora", "nessuna analisi"]],
        tools=[{"get_today_summary"}, {"get_data_status"}],
    ),
    _missing(
        "never_analysed",
        "Quanto dipendo dalle OTA?",
        [C("get_distribution")],
        "Non posso dirlo: l'analisi non è ancora disponibile e NINFA non ha dati di distribuzione.",
        # every honest way of saying "not yet": the first live run answered "non è ancora
        # valutabile" and was marked wrong for not using the oracle's own words
        [
            [
                "non è ancora disponibile",
                "non ancora disponibile",
                "non ha dati",
                "non è ancora valutabile",
                "non è valutabile",
                "non sono disponibili",
                "non risulta",
            ]
        ],
    ),
    _missing(
        "never_analysed",
        "Quanto ho speso a luglio?",
        [C("get_cost_metrics")],
        "Non ci sono dati sufficienti: NINFA non ha costi per luglio.",
        [
            [
                "non ci sono dati",
                "non ha costi",
                "nessun costo",
                "non risultano costi",
                "non è disponibile",
                "non sono registrati",
            ]
        ],
    ),
    _missing(
        "partial",
        "Perché il costo per camera non è disponibile?",
        [C("get_cpor")],
        "Il costo per camera occupata non è calcolabile perché le prenotazioni importate non "
        "coprono "
        "i giorni di luglio: per quei giorni NINFA non sa quante camere fossero occupate.",
        [
            ["non coprono", "non è calcolabile", "non è disponibile", "manca", "non c'è"],
            ["occupat"],
        ],
    ),
    _missing(
        "partial",
        "Qual è l'occupazione del mese?",
        [C("get_occupancy_revenue")],
        "I dati non coprono tutto il periodo: ci sono prenotazioni registrate solo per "
        "{truth.nights_data30} notti su 30. Su quelle notti l'occupazione sulle prenotazioni "
        "attuali "
        "è del {truth.occ30} %.",
        [["{truth.occ30}"], ["solo 7", "7 notti", "7 di 30", "7 su 30"]],
    ),
    _missing(
        "partial",
        "Quante ore di personale ho?",
        [C("get_staff_metrics")],
        "Non è disponibile: NINFA non ha un piano del personale, nessuna origine dati per il "
        "personale.",
        [["non è disponibile", "non ha un piano", "nessuna origine"]],
    ),
    _missing(
        "partial",
        "Quanto pesa Booking.com?",
        [C("get_channel_breakdown")],
        "Non posso dirlo: NINFA non ha prenotazioni certe da cui ricavare la composizione dei "
        "canali.",
        [["non ha prenotazioni", "non posso dirlo", "non è disponibile"]],
    ),
    _missing(
        "partial",
        "Qual è la quota OTA?",
        [C("get_distribution")],
        "La quota OTA non è disponibile: i dati sono insufficienti per valutare la dipendenza "
        "dalle "
        "OTA.",
        [["non è disponibile", "insufficient"]],
    ),
    _missing(
        "ota_insufficient",
        "Com'è il pickup?",
        [C("get_pickup")],
        "Il pickup non è calcolabile: serve il dato di una settimana fa per ogni notte. Non è "
        "zero, "
        "semplicemente non è noto.",
        [["non è calcolabile", "non è noto"], ["non è zero"]],
    ),
    _missing(
        "ota_insufficient",
        "Perché non ho una valutazione sulle OTA?",
        [C("get_distribution")],
        "NINFA non ha ancora un giudizio sulla dipendenza OTA: lo storico non è sufficiente per "
        "stabilire un livello atteso. La quota OTA attuale è del {truth.ota_share} %.",
        [["storico", "confront"], ["{truth.ota_share}"]],
    ),
    _missing(
        "stale",
        "Qual è il pickup?",
        [C("get_pickup")],
        "Il pickup non è noto: non è calcolabile e non è zero, perché non ci sono nuovi dati di "
        "prenotazione.",
        [["non è noto", "non è calcolabile"]],
    ),
    _missing(
        "never_analysed",
        "Quali dati ti mancano?",
        [C("get_data_status")],
        "Mancano tutti i dati analizzati: l'analisi non è ancora disponibile e NINFA non ha ancora "
        "importato dati sufficienti.",
        [["mancano", "non ancora"]],
    ),
    _missing(
        "partial",
        "Quali dati ti mancano?",
        [C("get_data_status")],
        "Per ora manca il piano del personale: nessuna origine dati per il personale.",
        [["personale"]],
    ),
    _missing(
        "full",
        "Qual è l'occupazione?",
        [C("get_occupancy_revenue")],
        "Al momento non riesco a leggere questo dato: l'occupazione non è disponibile. Riprova tra "
        "poco: i dati di NINFA restano disponibili.",
        [["non è disponibile", "non riesco"]],
        tool_failure=frozenset({"get_occupancy_revenue"}),
    ),
    _missing(
        "full",
        "Quanto ho speso a luglio?",
        [C("get_cost_metrics")],
        "Non riesco a leggere i costi in questo momento: il dato non è disponibile, quindi non ti "
        "do una cifra.",
        [["non è disponibile", "non riesco"]],
        tool_failure=frozenset({"get_cost_metrics"}),
    ),
    _missing(
        "full",
        "Quante decisioni ho oggi?",
        [C("get_today_summary")],
        "Al momento non riesco a leggere le decisioni di oggi: non posso dirti quante siano.",
        [["non riesco", "non posso"]],
        tool_failure=frozenset({"get_today_summary"}),
    ),
    _missing(
        "full",
        "Quanto dipendo dalle OTA?",
        [C("get_distribution")],
        "Non riesco a leggere i dati di distribuzione adesso: la quota OTA non è disponibile.",
        [["non è disponibile", "non riesco"]],
        tool_failure=frozenset({"get_distribution"}),
    ),
    _missing(
        "full",
        "Quante ore di personale ho pianificato?",
        [C("get_staff_metrics")],
        "Non riesco a leggere il piano del personale in questo momento: il dato non è disponibile.",
        [["non è disponibile", "non riesco"]],
        tool_failure=frozenset({"get_staff_metrics"}),
    ),
    _missing(
        "full",
        "Fammi un riepilogo della situazione dell'hotel.",
        [[C("get_today_summary"), C("get_occupancy_revenue"), C("get_distribution")]],
        "Oggi NINFA ha {truth.decision_count} decisioni che richiedono attenzione. Al momento non "
        "riesco a leggere occupazione e distribuzione: quei dati non sono disponibili.",
        [["{truth.decision_count}"], ["non riesco", "non sono disponibili"]],
        tools=[{"get_today_summary"}, {"get_occupancy_revenue"}],
        tool_failure=frozenset({"get_occupancy_revenue", "get_distribution"}),
        max_calls=6,
    ),
)

_STALE_NOTE = (
    "L'ultimo dato disponibile è l'import delle prenotazioni del 29 luglio; non ci sono nuovi dati "
    "di prenotazione dopo quella data."
)

QUALITY: tuple[Any, ...] = (
    (
        "stale",
        "Com'è l'occupazione oggi?",
        [[C("get_occupancy_revenue"), C("get_data_status")]],
        _STALE_NOTE + " Su quei dati l'occupazione dei prossimi 30 giorni è del {truth.occ30} %.",
        [["{truth.occ30}"]],
        [{"get_occupancy_revenue"}, {"get_data_status"}],
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Quante prenotazioni ho oggi?",
        [[C("get_occupancy_revenue"), C("get_data_status")]],
        _STALE_NOTE + " Sulle prenotazioni a sistema ci sono {truth.roomnights30} camere-notte "
        "prenotate nei prossimi 30 giorni.",
        [["{truth.roomnights30}"]],
        [{"get_occupancy_revenue"}],
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Perché non vedo nuove prenotazioni?",
        [[C("get_data_status")]],
        "Perché dall'ultimo import del 29 luglio non sono arrivati nuovi dati di prenotazione. "
        "Senza "
        "nuovi dati il pickup non è noto: non è zero.",
        [["29 luglio"], ["non è zero", "non è noto"]],
        None,
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Il pickup è zero?",
        [[C("get_pickup"), C("get_data_status")]],
        "No: senza nuovi dati di prenotazione dopo l'import del 29 luglio il pickup non è noto, "
        "non è "
        "zero.",
        [["non è zero", "non è noto"]],
        [{"get_pickup"}],
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Da quanto non importo le prenotazioni?",
        [[C("get_data_status")]],
        "L'ultimo import delle prenotazioni è del 29 luglio.",
        [["29 luglio"]],
        None,
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Posso fidarmi dei dati di oggi?",
        [[C("get_data_status"), C("get_occupancy_revenue")]],
        _STALE_NOTE + " Le cifre che vedi sono quelle dell'ultimo import, non di oggi.",
        [["29 luglio"]],
        [{"get_data_status"}],
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "Quando è stata l'ultima analisi?",
        [[C("get_data_status")]],
        "L'ultima analisi è del 1 agosto, ma ha usato l'ultimo import delle prenotazioni, quello "
        "del "
        "29 luglio: non ci sono nuovi dati dopo quella data.",
        [["29 luglio"]],
        None,
        {"freshness_hedge": True},
    ),
    (
        "stale",
        "L'occupazione che vedo è aggiornata?",
        [[C("get_data_status"), C("get_occupancy_revenue")]],
        _STALE_NOTE + " L'occupazione è del {truth.occ30} % su quei dati.",
        # the question is about freshness, not about the figure: what matters is that the answer
        # names the date of the last import (the first live run answered exactly that, without
        # repeating the percentage, and was marked wrong for it)
        [["29 luglio"]],
        [{"get_data_status"}, {"get_occupancy_revenue"}],
        {"freshness_hedge": True},
    ),
    (
        "no_analysis",
        "I dati che vedo sono di oggi?",
        [[C("get_data_status")]],
        "No: per oggi l'analisi non è ancora disponibile; l'ultimo dato disponibile è l'analisi "
        "del "
        "30 luglio.",
        [["non è ancora disponibile", "non ancora disponibile"], ["30 luglio"]],
        None,
        {"freshness_hedge": True},
    ),
    (
        "over_capacity",
        "Perché l'occupazione è sopra il 100%?",
        [[C("get_occupancy_revenue"), C("get_room_inventory")]],
        "In {truth.over_capacity_nights} notti ci sono più camere prenotate di quelle "
        "dell'inventario. "
        "Può essere l'inventario troppo basso, un overbooking o una prenotazione sbagliata: NINFA "
        "non può dire quale.",
        [["{truth.over_capacity_nights}"], ["inventario"]],
        [{"get_occupancy_revenue"}, {"get_room_inventory"}],
        {},
    ),
    (
        "over_capacity",
        "Ho prenotazioni sopra il numero di camere?",
        [[C("get_room_inventory")]],
        "Sì, secondo i dati: in {truth.over_capacity_nights} notti le prenotazioni superano "
        "l'inventario. È una domanda sui dati, non un verdetto.",
        [["{truth.over_capacity_nights}"], ["inventario"]],
        [{"get_room_inventory"}, {"get_occupancy_revenue"}],
        {},
    ),
    (
        "over_capacity",
        "Come controllo le notti sopra l'inventario?",
        [[C("get_feature_explanation", entry_id="workflow.check_over_capacity")]],
        "Apri Dati e guarda le notti segnalate come sopra l'inventario: per ognuna controlla se "
        "l'inventario in Struttura è corretto.",
        [["inventario"]],
        [{"get_feature_explanation"}, {"search_ninfa_knowledge"}, {"get_room_inventory"}],
        {},
    ),
    (
        "over_capacity",
        "L'occupazione dei prossimi 30 giorni è affidabile?",
        [[C("get_occupancy_revenue"), C("get_room_inventory")]],
        "È del {truth.occ30} % sulle prenotazioni attuali, ma in {truth.over_capacity_nights} "
        "notti "
        "le prenotazioni superano l'inventario: controlla l'inventario prima di fidarti del dato.",
        [["{truth.occ30}"], ["{truth.over_capacity_nights}"]],
        [{"get_occupancy_revenue"}],
        {},
    ),
    (
        "ota_data_quality",
        "Perché non vedo la dipendenza OTA?",
        [[C("get_distribution")]],
        "NINFA non riesce a valutare la dipendenza OTA perché i dati non sono coerenti: la "
        "composizione per canale non coincide con le prenotazioni registrate.",
        [["coerent", "non coincid"]],
        None,
        {"must_state_missing": True},
    ),
    (
        "ota_data_quality",
        "Posso fidarmi del mix dei canali?",
        [[C("get_channel_breakdown")]],
        "Il mix dei canali è indicativo: la composizione per canale non coincide con le "
        "prenotazioni "
        "registrate, quindi non è un dato certo.",
        [["indicativ", "non coincid"]],
        None,
        {"must_state_missing": True},
    ),
    (
        "ota_insufficient",
        "Perché non ho il verdetto OTA?",
        [[C("get_distribution")]],
        "I dati attuali sono a posto: manca lo storico confrontabile per stabilire il livello "
        "atteso. "
        "Arriverà da solo, un'analisi alla volta. La quota OTA attuale è del {truth.ota_share} %.",
        # "why no verdict" is answered by the missing history; the current share is not needed
        [["storico"]],
        None,
        {},
    ),
    (
        "stale",
        "Posso usare questi numeri per decidere i prezzi di oggi?",
        [[C("get_data_status"), C("get_occupancy_revenue")]],
        _STALE_NOTE + " Sono numeri dell'ultimo import, non di oggi: valuta tu se bastano. Io non "
        "posso dirti quali prezzi usare.",
        [["29 luglio"]],
        [{"get_data_status"}],
        {"freshness_hedge": True},
    ),
    (
        "reconstructed_costs",
        "Il costo per camera si basa su dati osservati?",
        [[C("get_cpor")]],
        "Non del tutto: {truth.basis_reconstructed} giorni del mese sono ricostruiti a posteriori "
        "e "
        "non osservati, e un dato ricostruito non è ciò che NINFA sapeva quel giorno.",
        [["ricostruit"], ["{truth.basis_reconstructed}"]],
        None,
        {},
    ),
    (
        "reconstructed_costs",
        "Cosa significa dato ricostruito nel costo per camera?",
        [[C("get_cpor"), C("get_ninfa_glossary", term="ricostruito")]],
        "Un dato ricostruito è dedotto dopo, per un giorno passato, dalle prenotazioni come sono "
        "adesso: è approssimato. Nel costo per camera, {truth.basis_reconstructed} giorni sono "
        "ricostruiti.",
        [["ricostruit"], ["{truth.basis_reconstructed}"]],
        [{"get_cpor"}, {"get_ninfa_glossary"}],
        {},
    ),
    (
        "reconstructed_costs",
        "Quanti giorni del costo per camera sono ricostruiti?",
        [[C("get_cpor")]],
        "{truth.basis_reconstructed} giorni su {truth.basis_total} del mese sono ricostruiti, "
        "gli altri osservati; per due giorni NINFA non conosce l'occupazione.",
        [["{truth.basis_reconstructed}"]],
        None,
        {},
    ),
)


def build() -> list[Scenario]:
    scenarios: list[Scenario] = []
    next_missing = numbered("miss")
    for world, category, turn in MISSING:
        scenarios.append(S(next_missing(), category, world, turn))  # type: ignore[arg-type]
    next_quality = numbered("qual")
    for world, question, calls, answer, mention, tools, extra in QUALITY:
        scenarios.append(
            S(
                next_quality(),
                "data_quality_stale",
                world,
                T(question, calls, answer, mention=mention, tools=tools, max_calls=4, **extra),
            )
        )
    return scenarios


__all__ = ["MISSING", "QUALITY", "build"]
