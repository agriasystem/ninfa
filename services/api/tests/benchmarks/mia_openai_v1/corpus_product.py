"""Product knowledge and how-to scenarios.

Each question is anchored to an entry of the Product Knowledge Registry (the real, code-anchored
one). The oracle answers from the entry exactly as the tool hands it over; the rubric asks only for
what a correct answer cannot lack (the name of the thing) and forbids the data tools - a question
about what NINFA IS is not a question about a hotel.
"""

import re
from collections.abc import Sequence

from app.modules.ai.mia.knowledge.registry import default_registry
from app.modules.ai.mia.knowledge.types import KnowledgeEntry
from tests.benchmarks.mia_openai_v1.dsl import DATA_TOOLS, PRODUCT_TOOLS, C, S, T, numbered
from tests.benchmarks.mia_openai_v1.model import Scenario

_REGISTRY = default_registry()
_ANY_PRODUCT_TOOL = tuple(frozenset({name}) for name in sorted(PRODUCT_TOOLS))


def _entry(entry_id: str) -> KnowledgeEntry:
    entry = _REGISTRY.get(entry_id)
    if entry is None:
        raise KeyError(f"the corpus names an entry the registry does not have: {entry_id}")
    return entry


def answer_of(entry: KnowledgeEntry, *, with_where: bool = False) -> str:
    """What a good answer says: the entry's own words, kept short and ending like a sentence."""
    text = f"{entry.title}: {entry.summary.strip()}"
    if with_where and entry.where:
        text = f"{text} Lo trovi in: {entry.where}"
    text = re.sub(r"\s+", " ", text)
    return text if text.endswith((".", "!", "?")) else text + "."


# (entry id, the question, what a correct answer cannot lack - alternatives per group)
PRODUCT: Sequence[tuple[str, str, Sequence[Sequence[str]]]] = (
    ("nav.oggi", "Cosa vedo nella pagina Oggi?", [("oggi",)]),
    ("nav.decisioni", "A cosa serve la sezione Decisioni?", [("decision",)]),
    ("nav.dati", "Cosa trovo nella sezione Dati?", [("panoramica", "prenotazioni", "costi")]),
    ("nav.importa_file", "A cosa serve Importa file?", [("import", "file")]),
    ("nav.struttura", "Che cosa posso fare in Struttura?", [("struttura",)]),
    ("nav.mia", "Chi sei e cosa sai fare?", [("mia",)]),
    ("nav.settings", "Che cosa c'è in Impostazioni?", [("impostazioni",)]),
    ("nav.property_selector", "A cosa serve il selettore della struttura?", [("struttura",)]),
    ("dati.overview", "Cosa mostra la Panoramica in Dati?", [("panoramica",)]),
    ("dati.bookings", "Cosa vedo nella scheda Prenotazioni di Dati?", [("prenotazioni",)]),
    ("dati.distribution", "Cosa mostra la scheda Distribuzione?", [("distribuzione", "ota")]),
    ("dati.costs", "Che cosa c'è nella scheda Costi?", [("costi",)]),
    ("dati.labor", "Cosa mostra la scheda Personale?", [("personale",)]),
    ("dati.period_control", "A cosa servono i pulsanti 7 e 30 giorni in Dati?", [("7", "30")]),
    ("dati.channel_weights", "Cos'è il peso dei canali?", [("peso", "canal")]),
    ("dati.nights_table", "Cosa significa il dettaglio soggiorni?", [("soggiorn", "nott")]),
    ("dati.freshness", "Cos'è l'ultimo import che vedo in Dati?", [("import",)]),
    ("dati.analysis_coverage", "Cos'è la copertura dell'analisi?", [("copertura",)]),
    ("metric.occupancy", "Come si calcola l'occupazione?", [("occupazione",)]),
    ("metric.adr", "Cos'è l'ADR?", [("adr", "tariffa media")]),
    (
        "metric.pickup",
        "Come viene calcolato il pickup?",
        [("pickup",), ("7 giorni", "una settimana")],
    ),
    ("metric.ota_share", "Che cos'è la quota OTA?", [("ota",)]),
    ("metric.cpor", "Cos'è il costo per camera occupata?", [("costo per camera", "cpor")]),
    ("metric.room_revenue", "I ricavi camera sono il fatturato?", [("ricavi camera", "ricavi")]),
    (
        "metric.labor_incidence",
        "Cosa significa incidenza sui ricavi per il personale?",
        [("incidenza",)],
    ),
    (
        "metric.reference_ota_share",
        "Cos'è il riferimento di NINFA per la quota OTA?",
        [("riferimento", "atteso")],
    ),
    ("term.observed", "Cosa significa dato osservato?", [("osservat",)]),
    ("term.reconstructed", "Cosa significa dato ricostruito?", [("ricostruit",)]),
    ("term.snapshot", "Cos'è un'osservazione del giorno?", [("osservazione",)]),
    (
        "term.on_books",
        "Cosa vuol dire sulle prenotazioni attuali?",
        [("prenotazioni attuali", "on-books", "on books")],
    ),
    ("term.room_night", "Cos'è una camera-notte?", [("camera-notte", "camera notte")]),
    ("term.family", "Cos'è una famiglia di file?", [("famiglia",)]),
    ("term.inventory", "Cos'è l'inventario camere?", [("inventario",)]),
    ("term.coverage", "Cosa si intende per copertura?", [("copertura",)]),
    (
        "term.analysis_areas",
        "Quali sono le quattro aree dell'analisi?",
        [("ricavi", "distribuzione", "costi", "personale")],
    ),
    ("state.partial_analysis", "Cosa significa Analisi parziale?", [("parziale",)]),
    (
        "state.no_reliable_decision",
        "Cosa significa Nessuna decisione affidabile oggi?",
        [("affidabil", "elementi sufficienti")],
    ),
    ("state.all_under_control", "Cosa vuol dire Tutto sotto controllo?", [("sotto controllo",)]),
    (
        "state.over_capacity",
        "Cosa significa prenotazioni superiori all'inventario?",
        [("inventario",)],
    ),
    (
        "state.not_processed",
        "Cosa vuol dire Analisi non ancora disponibile?",
        [("non ancora disponibile", "analisi")],
    ),
    ("decision.what_is", "Che cos'è una Decision?", [("decision",)]),
    (
        "decision.vs_insight",
        "Che differenza c'è tra una Decision e una tua spiegazione?",
        [("decision",)],
    ),
    ("decision.types", "Che tipi di Decision esistono?", [("pickup", "occupazione", "ota")]),
    ("decision.expected", "Cosa significa Atteso in una decisione?", [("atteso",)]),
    ("decision.delta", "Cos'è lo scostamento?", [("scostamento",)]),
    (
        "decision.impact",
        "Cos'è l'impatto economico di una decisione?",
        [("impatto",), ("indicativ", "stima")],
    ),
    ("decision.reliability", "Cosa significa affidabilità in una decisione?", [("affidabil",)]),
    ("decision.priority", "Come funziona la priorità delle decisioni?", [("priorit", "ordine")]),
    ("import.flow", "Come funziona Smart Import?", [("import",)]),
    ("import.formats", "Che file posso importare?", [("csv", "xlsx", "excel")]),
    (
        "import.scope",
        "Che differenza c'è tra FULL, PARTIAL e DELTA?",
        [("full",), ("partial",), ("delta",)],
    ),
    ("import.source_learning", "Cos'è Source Learning?", [("ricord",)]),
    (
        "import.same_day_revision",
        "Che succede se carico due file nello stesso giorno?",
        [("stesso giorno", "secondo file", "più file")],
    ),
    (
        "import.no_op",
        "Cosa succede se il file non cambia nulla?",
        [("non cambia", "nulla", "niente")],
    ),
)

# (entry id, the question, how to find it, what cannot be missing)
HOW_TO: Sequence[tuple[str, str, str, Sequence[Sequence[str]]]] = (
    (
        "workflow.change_room_count",
        "Come cambio il numero di camere?",
        "explain",
        [("struttura",), ("inventario",)],
    ),
    (
        "workflow.change_room_count",
        "Dove modifico il numero di camere della mia struttura?",
        "search",
        [("struttura",)],
    ),
    (
        "workflow.set_inventory_valid_from",
        "Come faccio a far valere l'inventario da una data passata?",
        "explain",
        [("valido dal",)],
    ),
    (
        "workflow.check_over_capacity",
        "Come controllo le prenotazioni sopra l'inventario?",
        "explain",
        [("inventario",)],
    ),
    ("workflow.import_file", "Come importo un file?", "explain", [("importa file",)]),
    ("workflow.import_costs", "Come importo i costi?", "explain", [("costi", "fattur")]),
    ("workflow.import_labor", "Come carico le ore del personale?", "explain", [("personale",)]),
    (
        "workflow.fix_blocked_import",
        "Cosa faccio se un file non si importa?",
        "explain",
        [("file", "colonn")],
    ),
    (
        "workflow.review_column_matching",
        "Come rivedo gli abbinamenti delle colonne?",
        "explain",
        [("abbinament", "colonn")],
    ),
    (
        "workflow.correct_remembered_answer",
        "Come correggo una risposta ricordata?",
        "explain",
        [("risposte ricordate", "ricordat")],
    ),
    (
        "workflow.forget_remembered_answer",
        "Come faccio dimenticare una risposta a NINFA?",
        "explain",
        [("dimentica",)],
    ),
    (
        "workflow.forget_import_configuration",
        "Come faccio dimenticare la configurazione di una fonte?",
        "explain",
        [("configurazione",)],
    ),
    ("workflow.remove_source", "Come rimuovo una fonte?", "explain", [("fonte",)]),
    (
        "workflow.configure_data_source",
        "Come collego una nuova fonte dati?",
        "explain",
        [("fonte", "fonti")],
    ),
    ("workflow.download_template", "Dove scarico un modello di file?", "search", [("modello",)]),
    ("workflow.find_import_history", "Dove vedo i file che ho importato?", "search", [("import",)]),
    (
        "workflow.second_file_same_day",
        "Come aggiorno i dati con un secondo file?",
        "explain",
        [("file",)],
    ),
    ("workflow.refresh_analysis", "Come aggiorno l'analisi?", "explain", [("aggiorn",)]),
    (
        "workflow.see_decision_detail",
        "Come apro il dettaglio di una decisione?",
        "explain",
        [("dettaglio",)],
    ),
    (
        "workflow.why_no_decisions",
        "Dove capisco perché oggi non vedo decisioni?",
        "explain",
        [("decision",)],
    ),
    ("workflow.change_dati_period", "Come cambio il periodo in Dati?", "explain", [("7", "30")]),
    ("workflow.switch_property", "Come cambio struttura?", "explain", [("struttura",)]),
    ("workflow.ask_mia", "Come ti faccio una domanda?", "explain", [("mia", "domanda")]),
    ("struttura.purpose", "Dove configuro la mia struttura?", "search", [("struttura",)]),
    ("struttura.template_csv", "Come scarico il modello CSV?", "search", [("modello", "csv")]),
    ("nav.decisioni", "Dove trovo le decisioni di oggi?", "search", [("decision",)]),
    ("dati.costs", "Dove vedo i costi?", "search", [("costi",)]),
    ("import.bookings_file", "Come carico un file di prenotazioni?", "search", [("prenotazioni",)]),
    (
        "import.invoice_xml",
        "Come importo una fattura elettronica XML?",
        "search",
        [("xml", "fattur")],
    ),
    ("nav.settings", "Dove si trovano le impostazioni?", "search", [("impostazioni",)]),
    (
        "workflow.change_dati_period",
        "Dove cambio il periodo di 7 e 30 giorni?",
        "search",
        [("7", "30")],
    ),
)


def _how(entry: KnowledgeEntry, question: str, via: str) -> tuple[list[object], str]:
    if via == "search":
        return [C("search_ninfa_knowledge", query=question)], answer_of(entry, with_where=True)
    return [C("get_feature_explanation", entry_id=entry.id)], answer_of(entry, with_where=True)


def build() -> list[Scenario]:
    scenarios: list[Scenario] = []
    pk, ht = numbered("pk"), numbered("how")
    for entry_id, question, mention in PRODUCT:
        entry = _entry(entry_id)
        scenarios.append(
            S(
                pk(),
                "product_knowledge",
                "full",
                T(
                    question,
                    [C("get_feature_explanation", entry_id=entry_id)],
                    answer_of(entry),
                    mention=mention,
                    tools=_ANY_PRODUCT_TOOL,
                    forbidden=DATA_TOOLS,
                    max_calls=3,
                ),
                tags=("product",),
            )
        )
    for entry_id, question, via, mention in HOW_TO:
        entry = _entry(entry_id)
        calls, answer = _how(entry, question, via)
        scenarios.append(
            S(
                ht(),
                "how_to",
                "full",
                T(
                    question,
                    calls,
                    answer,
                    mention=mention,
                    tools=_ANY_PRODUCT_TOOL,
                    forbidden=DATA_TOOLS,
                    max_calls=3,
                ),
                tags=("product", "how_to"),
            )
        )
    return scenarios


__all__ = ["HOW_TO", "PRODUCT", "answer_of", "build"]
