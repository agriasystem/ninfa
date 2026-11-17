"""Metrics: every figure the Dati page shows, what it is made of and what it is not."""

from app.modules.ai.mia.knowledge.entries._build import METRIC, copy, doc, entry, enum
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_CAPACITY = "app.modules.data_overview.types:CapacityState"
_CPOR = "app.modules.data_overview.types:CporStatus"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "metric.occupancy",
        METRIC,
        "Occupazione",
        "Le camere prenotate diviso le camere disponibili, notte per notte, sulle prenotazioni "
        "attuali. "
        "Non è l'occupazione finale: è quanto è già venduto oggi.",
        copy("Occupazione"),
        copy("sulle prenotazioni attuali"),
        enum(f"{_CAPACITY}.KNOWN"),
        details=(
            "Per un periodo conta solo le notti con capienza nota: una notte con capienza ignota "
            "non entra nel calcolo.",
            "La capienza non si deduce mai dalle prenotazioni: viene dall'inventario camere.",
            "Può superare il 100%: in quel caso NINFA mostra il valore vero e segnala che "
            "prenotazioni e inventario non coincidono.",
        ),
        where="Dati > Panoramica e Dati > Prenotazioni",
        related=(
            "metric.rooms_available",
            "state.inventory_missing",
            "state.over_capacity",
            "dati.occupancy_card",
        ),
        keywords=("occupazione", "occupancy", "percentuale occupazione", "camere occupate"),
        not_available=("NINFA non mostra l'occupazione finale prevista.",),
    ),
    entry(
        "metric.rooms_available",
        METRIC,
        "Camere disponibili",
        "Il numero di camere che la struttura può vendere ciascuna notte, secondo l'inventario "
        "camere "
        "copiato nell'osservazione del giorno.",
        copy("Camere disponibili"),
        enum(f"{_CAPACITY}.MISSING"),
        details=(
            "Se non c'è l'inventario, le camere disponibili e l'occupazione non si calcolano, ma "
            "prenotazioni, ricavi e ADR restano.",
            "Se l'inventario è stato impostato dopo l'osservazione, l'occupazione compare con la "
            "prossima analisi.",
        ),
        where="Dati > Prenotazioni (Riepilogo per periodo) e tabella Dettaglio soggiorni",
        related=("struttura.rooms", "workflow.change_room_count", "state.inventory_missing"),
        keywords=("camere disponibili", "capienza", "capacità", "inventario", "camere vendibili"),
    ),
    entry(
        "metric.room_nights",
        METRIC,
        "Camere-notte",
        "Il numero di camere prenotate sommato notte per notte: una prenotazione di tre notti in "
        "una "
        "camera sono tre camere-notte. Si usano le camere-notte, non le prenotazioni.",
        copy("Camere-notte"),
        copy("camere-notte prenotate"),
        where="Dati > Panoramica (indicatori) e Prenotazioni",
        related=("term.room_night", "metric.room_revenue", "metric.adr"),
        keywords=("camere notte", "room nights", "notti vendute", "camere-notte prenotate"),
    ),
    entry(
        "metric.room_revenue",
        METRIC,
        "Ricavi camera",
        "I ricavi delle camere già prenotate, sulle notti del periodo: solo ciò che è a sistema "
        "oggi. "
        "Non sono fatturato, incassi, utile né margine.",
        copy("Ricavi camera"),
        copy("prenotazioni già a sistema"),
        details=(
            "Sono ricavi on-books: dipendono dalle prenotazioni attuali e cambiano quando ne "
            "arrivano di nuove o ne cadono.",
            "NINFA non ha un modello contabile del fatturato.",
        ),
        where="Dati > Panoramica (indicatori) e Prenotazioni",
        related=("term.on_books", "metric.adr", "metric.room_nights"),
        keywords=("ricavi", "ricavi camera", "revenue", "fatturato", "incassi", "on-books"),
        not_available=("NINFA non calcola fatturato, incassi, margine, utile né RevPAR.",),
    ),
    entry(
        "metric.adr",
        METRIC,
        "ADR",
        "La tariffa media sulle prenotazioni già a sistema: i ricavi camera diviso le camere-notte "
        "del "
        "periodo.",
        copy("ADR"),
        copy("tariffa media on-books"),
        where="Dati > Panoramica e Prenotazioni",
        related=("metric.room_revenue", "metric.room_nights", "term.on_books"),
        keywords=("adr", "tariffa media", "prezzo medio", "average daily rate"),
        not_available=("ADR è calcolato sulle prenotazioni attuali, non sul consuntivo.",),
    ),
    entry(
        "metric.pickup",
        METRIC,
        "Pickup",
        "Per NINFA il pickup è la variazione delle camere prenotate per una notte rispetto a 7 "
        "giorni "
        "fa: le camere di oggi meno quelle dell'osservazione di 7 giorni prima.",
        copy("7 giorni fa"),
        copy("Variazione vs 7 giorni fa"),
        doc("docs/architecture/revenue-decisions-v1.md"),
        details=(
            "In Dati compare come colonna 7 giorni fa e Variazione, e come variazione del periodo.",
            "Si misura solo con due osservazioni vere: una ricostruzione non basta.",
            "Senza nuovi dati di prenotazione il pickup non è noto: non è zero.",
            "La decisione Pickup sotto le attese lo confronta con quello che di solito entra in "
            "quella finestra.",
        ),
        where="Dati > Prenotazioni, tabella Dettaglio soggiorni e Riepilogo per periodo",
        related=("decision.pickup_low", "state.stale_booking", "term.observed"),
        keywords=(
            "pickup",
            "nuove prenotazioni",
            "variazione",
            "7 giorni fa",
            "come viene calcolato il pickup",
        ),
        not_available=("NINFA non mostra curve di pickup né previsioni dei prossimi giorni.",),
    ),
    entry(
        "metric.ota_share",
        METRIC,
        "Quota OTA",
        "Le camere-notte prenotate sulle OTA rispetto al totale OTA più diretto, nei prossimi 30 "
        "giorni. "
        "Gli altri canali non sono nel totale.",
        copy("Quota OTA"),
        details=(
            "È una quota sul solo totale OTA più diretto: non coincide con il peso di un canale.",
            "È la concentrazione della distribuzione, non la prestazione di un canale.",
        ),
        where="Dati > Distribuzione e riquadro Dipendenza OTA",
        related=(
            "metric.direct_share",
            "metric.reference_ota_share",
            "metric.channel_weight",
            "decision.ota_dependency",
        ),
        keywords=("quota ota", "percentuale ota", "dipendenza dalle ota", "booking.com", "ota"),
    ),
    entry(
        "metric.direct_share",
        METRIC,
        "Quota Diretto",
        "Le camere-notte prenotate sul canale diretto rispetto al totale OTA più diretto, nei "
        "prossimi 30 giorni.",
        copy("Diretto"),
        where="Dati > Distribuzione",
        related=("metric.ota_share", "term.direct"),
        keywords=("diretto", "canale diretto", "quota diretto", "sito diretto", "telefono"),
    ),
    entry(
        "metric.reference_ota_share",
        METRIC,
        "Riferimento NINFA (quota OTA attesa)",
        "Il livello di quota OTA che NINFA si aspetta per questa struttura, dalla storia. Non è un "
        "obiettivo da raggiungere.",
        copy("Riferimento NINFA"),
        doc("docs/architecture/ota-dependency-v1.md"),
        where="Dati > Distribuzione, riquadro Dipendenza OTA",
        related=("metric.ota_share", "decision.expected"),
        keywords=("riferimento", "atteso ota", "livello atteso ota"),
        not_available=(
            "La quota OTA non viene mai confrontata con un target deciso dalla persona.",
        ),
    ),
    entry(
        "metric.channel_weight",
        METRIC,
        "Peso di un canale",
        "Le camere-notte di un canale rispetto a tutte le camere-notte prenotate in quei giorni. È "
        "una "
        "misura diversa dalla quota OTA.",
        copy("Peso di un canale"),
        where="Dati > Distribuzione, Peso dei canali",
        related=("metric.ota_share", "dati.channel_weights", "term.channel_group"),
        keywords=("peso canale", "quanto pesa", "booking.com", "expedia", "percentuale canale"),
        not_available=("Il peso non dice quanto un canale rende né quanto costa in commissioni.",),
    ),
    entry(
        "metric.channel_classification_coverage",
        METRIC,
        "Prenotazioni su canali classificati",
        "La quota delle camere-notte il cui canale NINFA sa riconoscere come OTA o diretto. Se è "
        "troppo "
        "bassa, la quota OTA non si può valutare.",
        copy("Prenotazioni su canali classificati"),
        where="Dati > Distribuzione",
        related=("term.channel_group", "state.distribution_insufficient"),
        keywords=("canali non classificati", "classificazione", "canale sconosciuto"),
    ),
    entry(
        "metric.cost_total",
        METRIC,
        "Costo netto registrato",
        "La somma dei costi netti registrati per data fattura nell'ultimo mese concluso, nella "
        "valuta "
        "della struttura. Il mese in corso non è incluso.",
        copy("Costo netto registrato"),
        copy("ultimo mese concluso, per data fattura"),
        details=(
            "Le note di credito sono già negative e riducono il totale.",
            "I costi in un'altra valuta non sono inclusi.",
            "La variazione è rispetto al mese precedente.",
        ),
        where="Dati > Costi e indicatore Costi di… in Panoramica",
        related=("term.invoice_date_attribution", "term.concluded_month", "dati.costs"),
        keywords=("costi", "costo totale", "spese del mese", "costo netto", "ultimo mese"),
    ),
    entry(
        "metric.cpor",
        METRIC,
        "Costo per camera occupata (CPOR)",
        "Il costo netto di una categoria in un mese concluso diviso le camere occupate dello "
        "stesso "
        "mese. Le camere occupate sono una stima operativa, non l'occupazione certificata.",
        copy("Costo per camera occupata"),
        enum(f"{_CPOR}.INCOMPLETE"),
        doc("docs/architecture/cost-cpor-anomaly-v1.md"),
        details=(
            "Le camere occupate sono la somma, giorno per giorno, delle camere prenotate come le "
            "vedeva la fine di quel giorno.",
            "Se anche un solo giorno non è noto, non si calcola e la pagina spiega quale giorno "
            "manca.",
            "Non si calcola se il mese non ha camere occupate, se troppe spese non sono "
            "classificate o se non c'è alcun costo.",
        ),
        where="Dati > Costi, tabella Costi per categoria",
        related=(
            "dati.cpor_card",
            "state.cpor_not_computable",
            "decision.cpor_anomaly",
            "term.reconstructed",
        ),
        keywords=("cpor", "costo per camera", "costo camera occupata", "costo per camera occupata"),
        not_available=("Non è un costo per camera venduta né una redditività.",),
    ),
    entry(
        "metric.labor_planned_hours",
        METRIC,
        "Ore pianificate",
        "Le ore di lavoro previste dal piano del personale più recente, sui prossimi 7 giorni, per "
        "i "
        "soli giorni in cui il piano esiste.",
        copy("Ore pianificate"),
        details=("Sono ore previste, non ore lavorate.",),
        where="Dati > Personale",
        related=("term.planned_worked_hours", "dati.labor_coverage", "metric.labor_planned_cost"),
        keywords=("ore", "ore pianificate", "ore previste", "ore personale"),
    ),
    entry(
        "metric.labor_planned_cost",
        METRIC,
        "Costo pianificato",
        "Il costo previsto dal piano del personale per i giorni coperti. Se non tutte le righe "
        "hanno "
        "un costo, NINFA non lo calcola.",
        copy("Costo pianificato"),
        copy("Non tutte le righe del piano hanno un costo."),
        where="Dati > Personale",
        related=("metric.labor_planned_hours", "metric.labor_hourly_cost"),
        keywords=("costo del personale", "costo pianificato", "costo piano"),
    ),
    entry(
        "metric.labor_hourly_cost",
        METRIC,
        "Costo medio orario",
        "Il costo pianificato diviso le ore pianificate.",
        copy("Costo medio/ora"),
        copy("Costo pianificato diviso le ore pianificate"),
        where="Dati > Personale",
        related=("metric.labor_planned_cost", "metric.labor_planned_hours"),
        keywords=("costo orario", "costo medio ora", "costo ora"),
    ),
    entry(
        "metric.labor_incidence",
        METRIC,
        "Incidenza sui ricavi on-books",
        "Quanto pesa il costo pianificato del personale sui ricavi camera on-books degli stessi "
        "giorni "
        "del piano. Non è l'incidenza sul fatturato.",
        copy("Incidenza sui ricavi on-books"),
        doc("docs/architecture/adr/0043-dati-cause-and-denominator.md"),
        details=(
            "Si calcola sui soli giorni coperti dal piano: se il piano copre un solo giorno, "
            "riguarda quel giorno.",
            "Se non ci sono ricavi on-books confrontabili sugli stessi giorni, la pagina dice "
            "perché non c'è.",
        ),
        where="Dati > Personale",
        related=(
            "dati.labor_coverage",
            "state.labor_plan_partial",
            "metric.labor_revenue_per_hour",
        ),
        keywords=(
            "incidenza",
            "personale sui ricavi",
            "peso del personale",
            "costo personale su ricavi",
        ),
        not_available=("L'incidenza non è sul fatturato: NINFA non ha un dato di fatturato.",),
    ),
    entry(
        "metric.labor_revenue_per_hour",
        METRIC,
        "Ricavo on-books per ora",
        "I ricavi camera on-books diviso le ore di personale pianificate, sugli stessi giorni. È "
        "per "
        "ora di personale, non per singola persona.",
        copy("Ricavo on-books per ora"),
        where="Dati > Personale",
        related=("metric.labor_incidence", "metric.labor_planned_hours"),
        keywords=("ricavo per ora", "produttività", "ricavo ora personale"),
    ),
    entry(
        "metric.labor_cost_share",
        METRIC,
        "Quota del costo del personale per ruolo",
        "Nella tabella per ruolo, la parte del costo pianificato totale che spetta a quel reparto.",
        copy("% costo personale"),
        where="Dati > Personale, tabella per ruolo",
        related=("dati.labor_roles", "term.labor_departments"),
        keywords=("quota ruolo", "percentuale costo", "peso reparto"),
    ),
)

__all__ = ["ENTRIES"]
