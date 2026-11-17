"""Data interpretation, decision explanation and multi-domain scenarios (the FULL hotel).

A figure is never typed here: `{truth.x}` resolves against the world's truth, computed by the same
services the tools read. A good answer states the figure AND what it is a figure of ("sulle
prenotazioni attuali", "pianificate", "indicativo"): the rubric asks for the figure, the guard
checks that it is the tool's.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from tests.benchmarks.mia_openai_v1.dsl import C, S, T, numbered
from tests.benchmarks.mia_openai_v1.model import Scenario

_NOT_CODES = (r"rev_pickup_low|rev_occupancy_risk|rev_ota_dependency|cost_cpor|labor_overstaffing",)

# (questions, calls, answer, mention, extra rubric). One scenario per question.
FACTS: Sequence[tuple[Sequence[str], list[Any], str, Sequence[Sequence[str]], dict[str, Any]]] = (
    (
        ("Com'è l'occupazione dei prossimi 30 giorni?", "Quanto siamo pieni nel prossimo mese?"),
        [C("get_occupancy_revenue")],
        "L'occupazione sulle prenotazioni attuali dei prossimi 30 giorni è del {truth.occ30} %, "
        "con "
        "{truth.roomnights30} camere-notte prenotate su {truth.avail30} disponibili.",
        [["{truth.occ30}"]],
        {},
    ),
    (
        (
            "Qual è l'occupazione della prossima settimana?",
            "Quanto siamo pieni nei prossimi sette giorni?",
        ),
        [C("get_occupancy_revenue", window=7)],
        "Nei prossimi 7 giorni l'occupazione sulle prenotazioni attuali è del {truth.occ7} %.",
        [["{truth.occ7}"]],
        {},
    ),
    (
        ("Qual è l'ADR?", "A quanto vendiamo in media una camera?"),
        [C("get_occupancy_revenue")],
        "La tariffa media (ADR) sulle prenotazioni attuali dei prossimi 30 giorni è di "
        "{truth.adr30} euro.",
        [["{truth.adr30}"]],
        {},
    ),
    (
        (
            "Quanti ricavi camera ho sulle prenotazioni?",
            "Quanto valgono le prenotazioni dei prossimi 30 giorni?",
        ),
        [C("get_occupancy_revenue")],
        "I ricavi camera sulle prenotazioni attuali dei prossimi 30 giorni sono {truth.rev30} "
        "euro: "
        "non sono fatturato né incassi.",
        [["{truth.rev30}"]],
        {},
    ),
    (
        ("Quanto siamo pieni venerdì?", "Com'è la situazione di venerdì?"),
        [C("get_occupancy_revenue", night={"kind": "weekday", "weekday": "venerdi"})],
        "Venerdì 7 agosto ci sono {truth.rooms_fri} camere prenotate, pari al {truth.occ_fri} % di "
        "occupazione.",
        [["{truth.occ_fri}"]],
        {},
    ),
    (
        ("Com'è il sabato 8 agosto?", "Quante camere ho prenotate sabato 8 agosto?"),
        [C("get_occupancy_revenue", night={"kind": "date", "date": "2026-08-08"})],
        "Sabato 8 agosto ci sono {truth.rooms_sat8} camere prenotate, il {truth.occ_sat8} % di "
        "occupazione.",
        [["{truth.occ_sat8}", "{truth.rooms_sat8}"]],
        {},
    ),
    (
        ("Qual è la notte più debole dei prossimi 30 giorni?", "Quando ho meno prenotazioni?"),
        [C("get_occupancy_revenue", nights_filter="weakest")],
        "La notte più debole è il 7 agosto, con il {truth.weakest_occ} % di occupazione sulle "
        "prenotazioni attuali.",
        [["{truth.weakest_occ}"]],
        {},
    ),
    (
        (
            "Come sta andando il pickup della prossima settimana?",
            "Quante camere in più ho rispetto a una settimana fa nei prossimi 7 giorni?",
        ),
        [C("get_pickup", window=7)],
        "Rispetto a una settimana fa ci sono {truth.delta7_7} camere-notte in più sui prossimi 7 "
        "giorni.",
        [["{truth.delta7_7}"]],
        {},
    ),
    (
        (
            "Com'è il pickup dei prossimi 30 giorni?",
            "Quante nuove camere-notte ho prenotato nell'ultima settimana?",
        ),
        [C("get_pickup", window=30)],
        "Rispetto a una settimana fa i prossimi 30 giorni hanno {truth.delta7_30} camere-notte in "
        "più.",
        [["{truth.delta7_30}"]],
        {},
    ),
    (
        (
            "Confronta la prossima settimana con il resto del mese",
            "Come va la settimana rispetto ai 30 giorni?",
        ),
        [C("compare_windows")],
        "Sui prossimi 7 giorni l'occupazione è del {truth.occ7} %, sui prossimi 30 giorni del "
        "{truth.occ30} %.",
        [["{truth.occ7}"], ["{truth.occ30}"]],
        {},
    ),
    (
        ("Quanto dipendo dalle OTA?", "Qual è la mia quota OTA?"),
        [C("get_distribution")],
        "La quota OTA è del {truth.ota_share} %, contro un riferimento di NINFA del "
        "{truth.ota_reference} %; le prenotazioni dirette sono il {truth.direct_share} %.",
        [["{truth.ota_share}"]],
        {},
    ),
    (
        ("Quanto sto dipendendo da Booking.com?", "Quanto pesa Booking.com sulle mie camere?"),
        [C("get_channel_breakdown")],
        "Booking.com pesa il {truth.channel_bookingcom} % delle camere-notte prenotate dei "
        "prossimi "
        "30 giorni.",
        [["{truth.channel_bookingcom}"]],
        {},
    ),
    (
        ("Quanta parte delle prenotazioni è diretta?", "Quanto è forte il canale diretto?"),
        [C("get_distribution")],
        "Le prenotazioni dirette sono il {truth.direct_share} % del totale tra OTA e dirette.",
        [["{truth.direct_share}"]],
        {},
    ),
    (
        ("Com'è il mix dei canali?", "Come si dividono le prenotazioni tra i canali?"),
        [C("get_channel_breakdown")],
        "Sulle camere-notte dei prossimi 30 giorni: Booking.com {truth.channel_bookingcom} %, "
        "Expedia {truth.channel_expedia} %, Diretto {truth.channel_diretto} %, Agency "
        "{truth.channel_agency} %.",
        [["{truth.channel_expedia}"]],
        {},
    ),
    (
        ("Quanto ho speso a luglio?", "Quanto sono i costi dell'ultimo mese?"),
        [C("get_cost_metrics")],
        "A luglio i costi netti registrati sono {truth.cost_total} euro, il {truth.cost_delta} % "
        "in "
        "più di giugno ({truth.cost_prev} euro).",
        [["{truth.cost_total}"]],
        {},
    ),
    (
        ("Quanto ho speso in lavanderia a luglio?", "Quanto costa la lavanderia?"),
        [C("get_cost_metrics", category="Lavanderia")],
        "A luglio la lavanderia è costata {truth.cost_laundry} euro netti.",
        [["{truth.cost_laundry}"]],
        {},
    ),
    (
        ("Quanto mi costa una camera occupata?", "Qual è il costo per camera?"),
        [C("get_cpor")],
        "Il costo per camera occupata è di {truth.cpor_utilities} euro per le utenze, "
        "{truth.cpor_food} per il cibo e {truth.cpor_laundry} per la lavanderia.",
        [["{truth.cpor_laundry}"]],
        {},
    ),
    (
        (
            "Quante ore di personale ho pianificato?",
            "Quanto costa il personale pianificato questa settimana?",
        ),
        [C("get_staff_metrics")],
        "Nei prossimi 7 giorni sono pianificate {truth.labor_hours} ore di personale, per un costo "
        "pianificato di {truth.labor_cost} euro.",
        [["{truth.labor_hours}"]],
        {},
    ),
    (
        ("Quante ore ha la governanza?", "Che ore ha pianificato il reparto pulizie?"),
        [C("get_staff_metrics")],
        "La governanza ha {truth.labor_hours_housekeeping} ore pianificate nei prossimi 7 giorni.",
        [["{truth.labor_hours_housekeeping}"]],
        {},
    ),
    (
        ("Quanto pesa il personale sui ricavi?", "Che incidenza ha il personale sui ricavi?"),
        [C("get_staff_metrics")],
        "Il costo pianificato del personale pesa il {truth.labor_incidence} % dei ricavi sulle "
        "prenotazioni degli stessi giorni.",
        [["{truth.labor_incidence}"]],
        {},
    ),
    (
        ("Quante decisioni ho oggi?", "Quante cose richiedono la mia attenzione oggi?"),
        [C("get_today_summary")],
        "Oggi NINFA ha {truth.decision_count} decisioni che richiedono attenzione.",
        [["{truth.decision_count}"]],
        {"decision_claims": True},
    ),
    (
        ("Quante camere risultano vendibili?", "Qual è il numero di camere della struttura?"),
        [C("get_room_inventory")],
        "Per l'inventario di NINFA le camere vendibili sono {truth.rooms_inventory}.",
        [["{truth.rooms_inventory}"]],
        {},
    ),
    (
        (
            "Che cosa sai di questa struttura?",
            "Dammi le informazioni principali sulla mia struttura.",
        ),
        [C("get_current_property_context"), C("get_property_profile")],
        "La struttura usa l'euro come valuta e la data di riferimento è il 1 agosto 2026. Le "
        "informazioni che NINFA ha sono quelle del profilo e dell'inventario camere.",
        [["euro", "eur"]],
        {},
    ),
    (
        ("Da dove arrivano questi dati?", "Da dove prendi i dati che mi mostri?"),
        [C("get_connected_sources"), C("get_data_status")],
        "I dati arrivano dai file importati nelle fonti dati: prenotazioni, costi e personale. "
        "L'ultimo import delle prenotazioni è di oggi.",
        [["import", "fonti"]],
        {},
    ),
    (
        (
            "Quando è stato l'ultimo import delle prenotazioni?",
            "Quanto sono aggiornate le prenotazioni?",
        ),
        [C("get_data_status")],
        "L'ultimo import delle prenotazioni è di oggi alle 09:15.",
        [["oggi"], ["09:15"]],
        {},
    ),
)

# (decision type, what a good answer says, what it must mention)
DECISIONS: Sequence[tuple[str, str, Sequence[Sequence[str]]]] = (
    (
        "REV_PICKUP_LOW",
        "Nelle ultime osservazioni il ritmo delle nuove prenotazioni è inferiore a quello atteso "
        "per la notte del 15 agosto.",
        [["pickup", "nuove prenotazioni", "ritmo"]],
    ),
    (
        "REV_OCCUPANCY_RISK",
        "Per la notte del 20 agosto l'occupazione sulle prenotazioni attuali è sotto il livello "
        "atteso: è un rischio sull'occupazione.",
        [["occupazione"]],
    ),
    (
        "REV_OTA_DEPENDENCY",
        "La quota di prenotazioni da OTA è del {truth.ota_share} %, sopra il livello atteso del "
        "{truth.ota_reference} %.",
        [["{truth.ota_share}"]],
    ),
    (
        "COST_CPOR_ANOMALY",
        "A luglio il costo per camera occupata della lavanderia è di {truth.cost_dec_actual} euro, "
        "contro un livello atteso di {truth.cost_dec_expected}.",
        [["{truth.cost_dec_actual}"]],
    ),
    (
        "LABOR_OVERSTAFFING",
        "Per il 1 agosto la governanza ha {truth.labor_dec_scheduled} ore programmate contro "
        "{truth.labor_dec_expected} attese: {truth.labor_dec_excess} ore in più.",
        [["{truth.labor_dec_excess}"]],
    ),
)
_DECISION_QUESTIONS: dict[str, tuple[str, ...]] = {
    "REV_PICKUP_LOW": (
        "Perché mi dici che il pickup è sotto le attese?",
        "Cosa significa la decisione sul pickup?",
        "Come hai capito che le prenotazioni stanno rallentando?",
    ),
    "REV_OCCUPANCY_RISK": (
        "Perché c'è un rischio sull'occupazione?",
        "Spiegami la decisione Rischio occupazione.",
        "Su che notte vedi un problema di occupazione?",
    ),
    "REV_OTA_DEPENDENCY": (
        "Perché dici che dipendo troppo dalle OTA?",
        "Spiegami la decisione sulla dipendenza OTA.",
        "Come hai calcolato che la quota OTA è alta?",
    ),
    "COST_CPOR_ANOMALY": (
        "Perché il costo per camera è anomalo?",
        "Spiegami la decisione sul costo per camera.",
        "Cosa non va nei costi di lavanderia?",
    ),
    "LABOR_OVERSTAFFING": (
        "Perché mi dici che ci sono troppe ore di personale?",
        "Spiegami la decisione sulle ore di personale.",
        "Su quale reparto hai visto ore in più?",
    ),
}
_PAGE_QUESTIONS = ("Perché me lo stai dicendo?", "Mi spieghi questa decisione?", "Cosa significa?")


def _decision_scenarios() -> list[Scenario]:
    out: list[Scenario] = []
    next_id = numbered("dec")
    for kind, answer, mention in DECISIONS:
        extra: dict[str, Any] = {"decision_claims": True, "not_": _NOT_CODES}
        # three on the decision page: the screen says which decision, one tool call explains it
        for question in _PAGE_QUESTIONS:
            out.append(
                S(
                    next_id(),
                    "decision_explanation",
                    "full",
                    T(
                        question,
                        [C("explain_decision", decision_id=f"$decision:{kind}")],
                        answer,
                        mention=mention,
                        ui={
                            "route": "/oggi/decisioni/[decisionId]",
                            "decision_id": f"$decision:{kind}",
                        },
                        **extra,
                    ),
                    tags=("page_aware",),
                )
            )
        # three from Mia on the Home: find the decision first, then explain it
        for question in _DECISION_QUESTIONS[kind]:
            out.append(
                S(
                    next_id(),
                    "decision_explanation",
                    "full",
                    T(
                        question,
                        [
                            [C("list_decisions")],
                            [C("explain_decision", decision_id=f"$decision:{kind}")],
                        ],
                        answer,
                        mention=mention,
                        tools=[{"explain_decision"}, {"explain_decision", "list_decisions"}],
                        max_calls=4,
                        **extra,
                    ),
                )
            )
    return out


# (question, rounds of calls, answer, mention, alternative tool sets)
MULTI: Sequence[
    tuple[str, list[Any], str, Sequence[Sequence[str]], Sequence[Iterable[str]], dict[str, Any]]
] = (
    (
        "Fammi un riepilogo della situazione dell'hotel.",
        [
            [
                C("get_today_summary"),
                C("get_data_status"),
                C("get_occupancy_revenue"),
                C("get_distribution"),
                C("get_cost_metrics"),
                C("get_staff_metrics"),
            ]
        ],
        "Oggi NINFA ha {truth.decision_count} decisioni che richiedono attenzione. L'occupazione "
        "sulle "
        "prenotazioni attuali dei prossimi 30 giorni è del {truth.occ30} %; la quota OTA è del "
        "{truth.ota_share} %. A luglio i costi netti sono {truth.cost_total} euro.",
        [["{truth.occ30}"], ["{truth.decision_count}"]],
        [
            {"get_today_summary", "get_occupancy_revenue"},
            {"get_data_status", "get_occupancy_revenue"},
        ],
        {"decision_claims": True},
    ),
    (
        "Qual è il problema più importante adesso?",
        [[C("get_today_summary")]],
        "La prima decisione nell'ordine di NINFA è «{truth.title_rev_pickup_low}». Tra le "
        "decisioni "
        "di oggi ce ne sono {truth.decision_count} in tutto.",
        [["pickup sotto le attese"]],
        [{"get_today_summary"}, {"list_decisions"}],
        {"decision_claims": True},
    ),
    (
        "Confrontami ricavi, distribuzione e personale.",
        [[C("get_occupancy_revenue"), C("get_distribution"), C("get_staff_metrics")]],
        "Ricavi: i ricavi camera sulle prenotazioni attuali sono {truth.rev30} euro. "
        "Distribuzione: "
        "la quota OTA è del {truth.ota_share} %. Personale: {truth.labor_hours} ore pianificate "
        "nei prossimi 7 giorni.",
        [["{truth.rev30}"], ["{truth.ota_share}"], ["{truth.labor_hours}"]],
        [{"get_occupancy_revenue", "get_distribution", "get_staff_metrics"}],
        {},
    ),
    (
        "Sto vendendo bene ma sto guadagnando?",
        [[C("get_occupancy_revenue"), C("get_cost_metrics"), C("get_staff_metrics")]],
        "Sulle prenotazioni attuali l'occupazione è del {truth.occ30} % e i ricavi camera sono "
        "{truth.rev30} euro. A luglio i costi netti sono {truth.cost_total} euro e il personale "
        "pianificato pesa il {truth.labor_incidence} % dei ricavi dei prossimi 7 giorni. Il "
        "margine "
        "non lo calcola NINFA, quindi non posso dire se stai guadagnando: questa è una mia lettura "
        "dei dati, non una Decision.",
        [["{truth.occ30}"], ["margine", "guadagn"]],
        [
            {"get_occupancy_revenue", "get_cost_metrics"},
            {"get_occupancy_revenue", "get_staff_metrics"},
        ],
        {"not_": (r"stai guadagnando bene",)},
    ),
    (
        "Quali giorni della prossima settimana meritano attenzione?",
        [
            [
                C("get_occupancy_revenue", window=7, nights_filter="weakest"),
                C("get_pickup", window=7),
            ]
        ],
        "La notte più debole è il 7 agosto, con il {truth.weakest_occ} % di occupazione sulle "
        "prenotazioni attuali. Rispetto a una settimana fa la settimana ha {truth.delta7_7} "
        "camere-notte in più.",
        [["{truth.weakest_occ}"]],
        [{"get_occupancy_revenue"}],
        {},
    ),
    (
        "Come sta andando l'hotel?",
        [[C("get_today_summary"), C("get_occupancy_revenue"), C("get_distribution")]],
        "Oggi ci sono {truth.decision_count} decisioni che richiedono attenzione. L'occupazione "
        "sulle "
        "prenotazioni attuali dei prossimi 30 giorni è del {truth.occ30} %.",
        [["{truth.occ30}"]],
        [{"get_today_summary", "get_occupancy_revenue"}, {"get_occupancy_revenue"}],
        {"decision_claims": True},
    ),
    (
        "Dove devo concentrarmi questa settimana?",
        [[C("get_today_summary"), C("get_occupancy_revenue", window=7, nights_filter="weakest")]],
        "La prima decisione nell'ordine di NINFA è «{truth.title_rev_pickup_low}». Tra le notti "
        "dei "
        "prossimi 7 giorni la più debole è il 7 agosto, con il {truth.weakest_occ} %.",
        [["{truth.weakest_occ}"]],
        [{"get_today_summary", "get_occupancy_revenue"}, {"get_occupancy_revenue"}],
        {"decision_claims": True},
    ),
    (
        "I costi stanno pesando troppo rispetto ai ricavi?",
        [[C("get_cost_metrics"), C("get_occupancy_revenue")]],
        "A luglio i costi netti registrati sono {truth.cost_total} euro; i ricavi camera sulle "
        "prenotazioni attuali dei prossimi 30 giorni sono {truth.rev30} euro. Sono periodi "
        "diversi, "
        "quindi NINFA non calcola il peso dei costi sui ricavi: è una mia lettura, non una "
        "Decision.",
        [["{truth.cost_total}"]],
        [{"get_cost_metrics", "get_occupancy_revenue"}],
        {},
    ),
    (
        "Il personale è in linea con l'occupazione?",
        [[C("get_staff_metrics"), C("get_occupancy_revenue", window=7)]],
        "Il personale pianificato per i prossimi 7 giorni è di {truth.labor_hours} ore; "
        "l'occupazione sulle prenotazioni attuali dei prossimi 7 giorni è del {truth.occ7} %.",
        [["{truth.labor_hours}"], ["{truth.occ7}"]],
        [{"get_staff_metrics", "get_occupancy_revenue"}],
        {},
    ),
    (
        "Quanto dipendo dalle OTA e quanto costa il personale?",
        [[C("get_distribution"), C("get_staff_metrics")]],
        "La quota OTA è del {truth.ota_share} %. Il costo pianificato del personale per i prossimi "
        "7 giorni è di {truth.labor_cost} euro.",
        [["{truth.ota_share}"], ["{truth.labor_cost}"]],
        [{"get_distribution", "get_staff_metrics"}],
        {},
    ),
    (
        "Dammi occupazione, ADR e costo per camera.",
        [[C("get_occupancy_revenue"), C("get_cpor")]],
        "L'occupazione sulle prenotazioni attuali è del {truth.occ30} %, l'ADR è di {truth.adr30} "
        "euro. Il costo per camera occupata della lavanderia è di {truth.cpor_laundry} euro.",
        [["{truth.occ30}"], ["{truth.adr30}"], ["{truth.cpor_laundry}"]],
        [{"get_occupancy_revenue", "get_cpor"}],
        {},
    ),
    (
        "Cosa non va nella mia struttura?",
        [[C("get_today_summary"), C("get_data_status")]],
        "NINFA ha {truth.decision_count} decisioni oggi, tra cui "
        "«{truth.title_rev_ota_dependency}» e "
        "«{truth.title_cost_cpor_anomaly}». Le trovi nella sezione Decisioni.",
        [["decision"]],
        [{"get_today_summary"}, {"list_decisions"}],
        {"decision_claims": True},
    ),
    (
        "Ho abbastanza dati per fidarmi dell'analisi di oggi?",
        [[C("get_data_status"), C("get_today_summary")]],
        "L'analisi di oggi copre tutte e quattro le aree e l'ultimo import delle prenotazioni è di "
        "oggi: i controlli hanno potuto concludere.",
        [["aree", "copertura", "analizzat"]],
        [{"get_data_status"}, {"get_today_summary"}],
        {},
    ),
    (
        "Fammi un confronto tra questa settimana e il mese e dimmi anche le OTA.",
        [[C("compare_windows"), C("get_distribution")]],
        "Sui prossimi 7 giorni l'occupazione è del {truth.occ7} %, sui prossimi 30 del "
        "{truth.occ30} "
        "%. La quota OTA è del {truth.ota_share} %.",
        [["{truth.occ7}"], ["{truth.ota_share}"]],
        [{"compare_windows", "get_distribution"}],
        {},
    ),
    (
        "Qual è la situazione dei costi e delle prenotazioni?",
        [[C("get_cost_metrics"), C("get_occupancy_revenue")]],
        "A luglio i costi netti registrati sono {truth.cost_total} euro. Sulle prenotazioni "
        "attuali "
        "l'occupazione dei prossimi 30 giorni è del {truth.occ30} %.",
        [["{truth.cost_total}"], ["{truth.occ30}"]],
        [{"get_cost_metrics", "get_occupancy_revenue"}],
        {},
    ),
    (
        "Dammi un quadro di ricavi, costi e personale.",
        [[C("get_occupancy_revenue"), C("get_cost_metrics"), C("get_staff_metrics")]],
        "Ricavi camera sulle prenotazioni attuali: {truth.rev30} euro. Costi netti di luglio: "
        "{truth.cost_total} euro. Personale: {truth.labor_hours} ore pianificate nei prossimi 7 "
        "giorni.",
        [["{truth.rev30}"], ["{truth.cost_total}"], ["{truth.labor_hours}"]],
        [{"get_occupancy_revenue", "get_cost_metrics", "get_staff_metrics"}],
        {},
    ),
    (
        "Come sono messo con distribuzione e costi?",
        [[C("get_distribution"), C("get_cost_metrics")]],
        "La quota OTA è del {truth.ota_share} % e a luglio i costi netti sono {truth.cost_total} "
        "euro.",
        [["{truth.ota_share}"], ["{truth.cost_total}"]],
        [{"get_distribution", "get_cost_metrics"}],
        {},
    ),
    (
        "Mi fai il punto su occupazione, pickup e OTA?",
        [[C("get_occupancy_revenue"), C("get_pickup", window=7), C("get_distribution")]],
        "L'occupazione sulle prenotazioni attuali è del {truth.occ30} %; rispetto a una settimana "
        "fa i "
        "prossimi 7 giorni hanno {truth.delta7_7} camere-notte in più; la quota OTA è del "
        "{truth.ota_share} %.",
        [["{truth.occ30}"], ["{truth.delta7_7}"], ["{truth.ota_share}"]],
        [{"get_occupancy_revenue", "get_pickup", "get_distribution"}],
        {},
    ),
    (
        "Qual è il quadro complessivo e cosa dovrei guardare per primo?",
        [[C("get_today_summary"), C("get_occupancy_revenue"), C("get_cost_metrics")]],
        "Oggi NINFA ha {truth.decision_count} decisioni; la prima nel suo ordine è "
        "«{truth.title_rev_pickup_low}». "
        "L'occupazione sulle prenotazioni attuali è del {truth.occ30} %.",
        [["{truth.occ30}"]],
        [{"get_today_summary", "get_occupancy_revenue"}],
        {"decision_claims": True},
    ),
    (
        "Il costo del personale è alto rispetto alle prenotazioni?",
        [[C("get_staff_metrics"), C("get_occupancy_revenue")]],
        "Il costo pianificato del personale pesa il {truth.labor_incidence} % dei ricavi sulle "
        "prenotazioni degli stessi giorni; è una misura di NINFA, non una Decision.",
        [["{truth.labor_incidence}"]],
        [{"get_staff_metrics"}],
        {},
    ),
    (
        "Quanto ricavo e quanto spendo in lavanderia?",
        [[C("get_occupancy_revenue"), C("get_cost_metrics", category="Lavanderia")]],
        "I ricavi camera sulle prenotazioni attuali sono {truth.rev30} euro; a luglio la "
        "lavanderia è "
        "costata {truth.cost_laundry} euro netti.",
        [["{truth.rev30}"], ["{truth.cost_laundry}"]],
        [{"get_occupancy_revenue", "get_cost_metrics"}],
        {},
    ),
    (
        "Riassumimi occupazione e canali.",
        [[C("get_occupancy_revenue"), C("get_channel_breakdown")]],
        "L'occupazione sulle prenotazioni attuali è del {truth.occ30} %. Booking.com pesa il "
        "{truth.channel_bookingcom} % delle camere-notte.",
        [["{truth.occ30}"], ["{truth.channel_bookingcom}"]],
        [{"get_occupancy_revenue", "get_channel_breakdown"}],
        {},
    ),
    (
        "Che situazione c'è tra personale e ricavi della prossima settimana?",
        [[C("get_staff_metrics"), C("get_occupancy_revenue", window=7)]],
        "Per i prossimi 7 giorni sono pianificate {truth.labor_hours} ore di personale e i ricavi "
        "camera sulle prenotazioni attuali sono {truth.rev7} euro.",
        [["{truth.labor_hours}"], ["{truth.rev7}"]],
        [{"get_staff_metrics", "get_occupancy_revenue"}],
        {},
    ),
    (
        "Mi dai una fotografia di prenotazioni, personale e costi?",
        [[C("get_occupancy_revenue"), C("get_staff_metrics"), C("get_cost_metrics")]],
        "Prenotazioni: l'occupazione sulle prenotazioni attuali è del {truth.occ30} %. Personale: "
        "{truth.labor_hours} ore pianificate nei prossimi 7 giorni. Costi: a luglio i costi netti "
        "registrati sono {truth.cost_total} euro.",
        [["{truth.occ30}"], ["{truth.labor_hours}"], ["{truth.cost_total}"]],
        [{"get_occupancy_revenue", "get_staff_metrics", "get_cost_metrics"}],
        {},
    ),
    (
        "Confronta quota OTA, occupazione e costo del personale.",
        [[C("get_distribution"), C("get_occupancy_revenue"), C("get_staff_metrics")]],
        "La quota OTA è del {truth.ota_share} %, l'occupazione sulle prenotazioni attuali è del "
        "{truth.occ30} % e il costo pianificato del personale è di {truth.labor_cost} euro.",
        [["{truth.ota_share}"], ["{truth.occ30}"], ["{truth.labor_cost}"]],
        [{"get_distribution", "get_occupancy_revenue", "get_staff_metrics"}],
        {},
    ),
)


def build() -> list[Scenario]:
    scenarios: list[Scenario] = []
    next_id = numbered("data")
    for questions, calls, answer, mention, extra in FACTS:
        for question in questions:
            scenarios.append(
                S(
                    next_id(),
                    "data_interpretation",
                    "full",
                    T(question, calls, answer, mention=mention, **extra),
                )
            )
    scenarios.extend(_decision_scenarios())
    next_multi = numbered("multi")
    for question, calls, answer, mention, tools, extra in MULTI:
        scenarios.append(
            S(
                next_multi(),
                "multi_domain",
                "full",
                T(question, calls, answer, mention=mention, tools=tools, max_calls=8, **extra),
                tags=("multi_tool",),
            )
        )
    return scenarios


__all__ = ["DECISIONS", "FACTS", "MULTI", "build"]
