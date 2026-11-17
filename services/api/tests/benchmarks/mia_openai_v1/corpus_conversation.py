"""Conversation follow-up and page-aware scenarios.

The second turn only makes sense with the first ("E domenica?", "Spiegamelo più semplicemente",
"Quante ore in più?"): the conversation is NINFA's own, the model sees the earlier turns as context,
not as facts, so a good follow-up RE-READS the data (the figure of the answer is the tool's of THIS
turn) and keeps the reference (the same area, the same period, the same decision). A refused turn
leaves no trace, and a correction ("no, intendevo i prossimi 7 giorni") is understood.
"""

from tests.benchmarks.mia_openai_v1.dsl import DATA_TOOLS, C, S, T, numbered
from tests.benchmarks.mia_openai_v1.model import Scenario

_PRODUCT_ANY = [{"get_feature_explanation"}, {"search_ninfa_knowledge"}, {"get_ninfa_glossary"}]
# what FULL, PARTIAL and DELTA mean is also what `explain_import_question` explains
_IMPORT_SCOPE_ANY = [{"explain_import_question"}]


def build() -> list[Scenario]:
    out: list[Scenario] = []
    next_id = numbered("conv")

    def add(world: str, *turns: object, tags: tuple[str, ...] = ()) -> None:
        out.append(S(next_id(), "conversation_follow_up", world, *turns, tags=tags))  # type: ignore[arg-type]

    friday = {"kind": "weekday", "weekday": "venerdi"}
    sunday = {"kind": "weekday", "weekday": "domenica"}
    add(
        "full",
        T(
            "Perché venerdì è debole?",
            [C("get_occupancy_revenue", night=friday), C("get_pickup", window=7)],
            "Venerdì 7 agosto ci sono {truth.rooms_fri} camere prenotate, il {truth.occ_fri} % di "
            "occupazione sulle prenotazioni attuali: è tra le notti meno piene.",
            mention=[["{truth.occ_fri}"]],
            tools=[{"get_occupancy_revenue"}],
        ),
        T(
            "E domenica?",
            [C("get_occupancy_revenue", night=sunday)],
            "Domenica 2 agosto ci sono {truth.rooms_sun} camere prenotate, il {truth.occ_sun} % di "
            "occupazione.",
            mention=[["{truth.occ_sun}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Com'è il sabato 8 agosto?",
            [C("get_occupancy_revenue", night={"kind": "date", "date": "2026-08-08"})],
            "Sabato 8 agosto ci sono {truth.rooms_sat8} camere prenotate, il {truth.occ_sat8} %.",
            mention=[["{truth.occ_sat8}"]],
        ),
        T(
            "E il giorno dopo?",
            [C("get_occupancy_revenue", night={"kind": "date", "date": "2026-08-09"})],
            "Domenica 9 agosto ci sono {truth.rooms_sun9} camere prenotate, il {truth.occ_sun9} %.",
            mention=[["{truth.occ_sun9}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quanto pesa Booking.com?",
            [C("get_channel_breakdown")],
            "Booking.com pesa il {truth.channel_bookingcom} % delle camere-notte prenotate.",
            mention=[["{truth.channel_bookingcom}"]],
        ),
        T(
            "E Expedia?",
            [C("get_channel_breakdown")],
            "Expedia pesa il {truth.channel_expedia} % delle camere-notte prenotate.",
            mention=[["{truth.channel_expedia}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quanto ho speso a luglio?",
            [C("get_cost_metrics")],
            "A luglio i costi netti registrati sono {truth.cost_total} euro.",
            mention=[["{truth.cost_total}"]],
        ),
        T(
            "E a giugno?",
            [C("get_cost_metrics")],
            "A giugno i costi netti registrati erano {truth.cost_prev} euro.",
            mention=[["{truth.cost_prev}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Qual è la quota OTA?",
            [C("get_distribution")],
            "La quota OTA è del {truth.ota_share} %, sopra il riferimento di NINFA del "
            "{truth.ota_reference} %.",
            mention=[["{truth.ota_share}"]],
        ),
        T(
            "Spiegamelo più semplicemente.",
            [C("get_distribution")],
            "In parole semplici: su 100 camere vendute tra OTA e diretto, circa {truth.ota_share} "
            "passano dalle OTA, mentre NINFA si aspetterebbe {truth.ota_reference}.",
            mention=[["{truth.ota_share}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Cos'è il pickup?",
            [C("get_feature_explanation", entry_id="metric.pickup")],
            "Il pickup per NINFA è la variazione delle camere prenotate per una notte rispetto a 7 "
            "giorni fa.",
            mention=[["pickup"]],
            tools=_PRODUCT_ANY,
        ),
        T(
            "Spiegamelo più semplicemente.",
            [C("get_feature_explanation", entry_id="metric.pickup")],
            "In breve: quante camere in più hai prenotato per una notte rispetto a 7 giorni fa.",
            mention=[["camere"]],
            tools=_PRODUCT_ANY,
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quali decisioni ho oggi?",
            [C("get_today_summary")],
            "Oggi NINFA ha {truth.decision_count} decisioni; la prima nel suo ordine è "
            "«{truth.title_rev_pickup_low}».",
            mention=[["{truth.decision_count}"]],
            tools=[{"get_today_summary"}, {"list_decisions"}],
            decision_claims=True,
        ),
        T(
            "Spiegami la seconda.",
            [
                [C("list_decisions")],
                [C("explain_decision", decision_id="$decision:REV_OCCUPANCY_RISK")],
            ],
            "La seconda è «{truth.title_rev_occupancy_risk}»: per la notte del 20 agosto "
            "l'occupazione sulle prenotazioni attuali è sotto il livello atteso.",
            mention=[["occupazione"]],
            tools=[{"explain_decision"}, {"explain_decision", "list_decisions"}],
            follow_up=True,
            decision_claims=True,
        ),
    )
    add(
        "full",
        T(
            "Com'è l'occupazione dei prossimi 7 giorni?",
            [C("get_occupancy_revenue", window=7)],
            "Nei prossimi 7 giorni l'occupazione sulle prenotazioni attuali è del {truth.occ7} %.",
            mention=[["{truth.occ7}"]],
        ),
        T(
            "E dei prossimi 30?",
            [C("get_occupancy_revenue", window=30)],
            "Nei prossimi 30 giorni è del {truth.occ30} %.",
            mention=[["{truth.occ30}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quanto ho speso a luglio?",
            [C("get_cost_metrics")],
            "A luglio i costi netti registrati sono {truth.cost_total} euro.",
            mention=[["{truth.cost_total}"]],
        ),
        T(
            "E in lavanderia?",
            [C("get_cost_metrics", category="Lavanderia")],
            "In lavanderia sono {truth.cost_laundry} euro netti.",
            mention=[["{truth.cost_laundry}"]],
            follow_up=True,
        ),
        T(
            "E il costo per camera?",
            [C("get_cpor", category="Lavanderia")],
            "Il costo per camera occupata della lavanderia è di {truth.cpor_laundry} euro.",
            mention=[["{truth.cpor_laundry}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Cosa vedo in Dati?",
            [C("get_feature_explanation", entry_id="nav.dati")],
            "In Dati trovi le sezioni Panoramica, Prenotazioni, Distribuzione, Costi e Personale.",
            mention=[["panoramica", "prenotazioni"]],
            tools=_PRODUCT_ANY,
        ),
        T(
            "E in Struttura?",
            [C("get_feature_explanation", entry_id="nav.struttura")],
            "In Struttura configuri la struttura: profilo, inventario camere, parametri operativi "
            "e "
            "fonti dati.",
            mention=[["struttura", "inventario"]],
            tools=_PRODUCT_ANY,
            follow_up=True,
        ),
        T(
            "E in Importa file?",
            [C("get_feature_explanation", entry_id="nav.importa_file")],
            "In Importa file carichi i file CSV o Excel di prenotazioni, costi e personale.",
            mention=[["file"]],
            tools=_PRODUCT_ANY,
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quante ore di personale ho pianificato?",
            [C("get_staff_metrics")],
            "Nei prossimi 7 giorni sono pianificate {truth.labor_hours} ore di personale.",
            mention=[["{truth.labor_hours}"]],
        ),
        T(
            "E quanto costano?",
            [C("get_staff_metrics")],
            "Il costo pianificato è di {truth.labor_cost} euro.",
            mention=[["{truth.labor_cost}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Qual è la notte più debole?",
            [C("get_occupancy_revenue", nights_filter="weakest")],
            "La notte più debole è il 7 agosto, con il {truth.weakest_occ} % di occupazione.",
            mention=[["{truth.weakest_occ}"]],
        ),
        T(
            "Quante camere sono prenotate quella notte?",
            [C("get_occupancy_revenue", night={"kind": "date", "date": "2026-08-07"})],
            "Il 7 agosto ci sono {truth.rooms_fri} camere prenotate.",
            mention=[["{truth.rooms_fri}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Qual è l'occupazione?",
            [C("get_occupancy_revenue")],
            "Nei prossimi 30 giorni l'occupazione sulle prenotazioni attuali è del {truth.occ30} "
            "%.",
            mention=[["{truth.occ30}"]],
        ),
        T(
            "No, intendevo i prossimi 7 giorni.",
            [C("get_occupancy_revenue", window=7)],
            "Nei prossimi 7 giorni l'occupazione è del {truth.occ7} %.",
            mention=[["{truth.occ7}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Quanto ricavo sulle prenotazioni?",
            [C("get_occupancy_revenue")],
            "I ricavi camera sulle prenotazioni attuali dei prossimi 30 giorni sono {truth.rev30} "
            "euro.",
            mention=[["{truth.rev30}"]],
        ),
        T(
            "E l'ADR?",
            [C("get_occupancy_revenue")],
            "L'ADR sulle prenotazioni attuali è di {truth.adr30} euro.",
            mention=[["{truth.adr30}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Che cos'è l'ADR?",
            [C("get_feature_explanation", entry_id="metric.adr")],
            "L'ADR è la tariffa media sulle camere prenotate.",
            mention=[["adr", "tariffa media"]],
            # a general concept: the model may answer "in generale" or look it up in the product
            # knowledge; what it may not do is read the property (first live run: it answered
            # in general and was marked wrong for not calling a product tool)
            tools=[],
            forbidden=DATA_TOOLS,
        ),
        T(
            "E come si calcola l'occupazione?",
            [C("get_feature_explanation", entry_id="metric.occupancy")],
            "L'occupazione è il rapporto tra le camere prenotate e quelle vendibili.",
            mention=[["occupazione"]],
            tools=[],
            forbidden=DATA_TOOLS,
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Spiegami la decisione sul personale.",
            [
                [C("list_decisions")],
                [C("explain_decision", decision_id="$decision:LABOR_OVERSTAFFING")],
            ],
            "Per il 1 agosto la governanza ha {truth.labor_dec_scheduled} ore programmate contro "
            "{truth.labor_dec_expected} attese.",
            mention=[["{truth.labor_dec_scheduled}"]],
            tools=[{"explain_decision"}, {"explain_decision", "list_decisions"}],
            decision_claims=True,
        ),
        T(
            "Quante ore in più?",
            [C("explain_decision", decision_id="$decision:LABOR_OVERSTAFFING")],
            "Sono {truth.labor_dec_excess} ore in più rispetto a quelle attese.",
            mention=[["{truth.labor_dec_excess}"]],
            follow_up=True,
            decision_claims=True,
        ),
    )
    add(
        "full",
        T(
            "Cambia il prezzo di tutte le camere a 50 euro.",
            [],
            "",
            status="REFUSED",
            no_tool=True,
            adversarial=True,
        ),
        T(
            "Ok, allora dimmi l'occupazione.",
            [C("get_occupancy_revenue")],
            "Nei prossimi 30 giorni l'occupazione sulle prenotazioni attuali è del {truth.occ30} "
            "%.",
            mention=[["{truth.occ30}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Come cambio il numero di camere?",
            [C("get_feature_explanation", entry_id="workflow.change_room_count")],
            "In Struttura, nel blocco Inventario camere, scegli Modifica inventario e scrivi il "
            "numero di camere.",
            mention=[["struttura"]],
            tools=_PRODUCT_ANY,
        ),
        T(
            "E da quando vale?",
            [C("get_feature_explanation", entry_id="workflow.set_inventory_valid_from")],
            "Vale dalla data che indichi in Valido dal: puoi anche farlo valere da una data "
            "passata.",
            mention=[["valido dal"]],
            tools=_PRODUCT_ANY,
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Qual è la quota OTA?",
            [C("get_distribution")],
            "La quota OTA è del {truth.ota_share} %.",
            mention=[["{truth.ota_share}"]],
        ),
        T(
            "E la quota diretta?",
            [C("get_distribution")],
            "La quota diretta è del {truth.direct_share} %.",
            mention=[["{truth.direct_share}"]],
            follow_up=True,
        ),
    )
    add(
        "full",
        T(
            "Che differenza c'è tra FULL e DELTA?",
            [C("get_feature_explanation", entry_id="import.scope")],
            "FULL vuol dire che il file contiene tutto il periodo; DELTA che contiene solo le "
            "novità.",
            mention=[["full"], ["delta"]],
            tools=_PRODUCT_ANY + _IMPORT_SCOPE_ANY,
        ),
        T(
            "E PARTIAL?",
            [C("get_feature_explanation", entry_id="import.scope_partial")],
            "PARTIAL vuol dire che il file contiene una parte del periodo, per esempio un solo "
            "canale.",
            mention=[["partial"]],
            tools=_PRODUCT_ANY + _IMPORT_SCOPE_ANY,
            follow_up=True,
        ),
    )
    # page-aware: the screen says what "it" is
    add(
        "full",
        T(
            "Perché è così alto?",
            [C("get_staff_metrics")],
            "Nel Personale il costo pianificato pesa il {truth.labor_incidence} % dei ricavi sulle "
            "prenotazioni degli stessi giorni, con {truth.labor_hours} ore pianificate. Intendo la "
            "scheda Personale che stai guardando.",
            mention=[["{truth.labor_incidence}", "{truth.labor_hours}"]],
            ui={"route": "/dati", "section": "labor", "period_days": 7},
        ),
        tags=("page_aware",),
    )
    add(
        "full",
        T(
            "Cosa vuol dire questo valore?",
            [C("get_cpor")],
            "Nella scheda Costi il costo per camera occupata è il costo netto diviso le camere "
            "occupate: per la lavanderia è di {truth.cpor_laundry} euro.",
            mention=[["{truth.cpor_laundry}"]],
            ui={"route": "/dati", "section": "costs", "period_days": 30},
            # no value is selected on the screen: "which one?" is the right answer (first live run)
            clarification_ok=True,
        ),
        tags=("page_aware",),
    )
    add(
        "full",
        T(
            "Cosa posso fare in questa pagina?",
            [C("get_page_help", route="/dati", section="distribution")],
            "In Distribuzione vedi la quota OTA, la quota diretta e il peso dei canali.",
            mention=[["distribuzione"]],
            tools=[{"get_page_help"}, {"get_feature_explanation"}],
            ui={"route": "/dati", "section": "distribution"},
        ),
        tags=("page_aware",),
    )
    return out


__all__ = ["build"]
