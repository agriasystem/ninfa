"""Glossary: the words of NINFA's own vocabulary, defined the way the product uses them."""

from app.modules.ai.mia.knowledge.entries._build import TERM, copy, doc, entry, enum
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_ORIGIN = "app.modules.snapshots.models:SnapshotOrigin"
_BOOKING_STATUS = "app.modules.bookings.models:BookingStatus"
_CHANNEL_TYPE = "app.modules.bookings.models:ChannelType"
_AREA = "app.modules.decisions.coverage:AnalysisDomain"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "term.observed",
        TERM,
        "Dato osservato",
        "Un dato osservato è ciò che NINFA ha davvero visto in un certo giorno, al momento in cui "
        "ha guardato le prenotazioni. Non viene mai riscritto.",
        enum(f"{_ORIGIN}.OBSERVED"),
        doc("docs/architecture/booking-snapshots-v1.md"),
        details=(
            "Solo le osservazioni vere sono la storia che NINFA usa per confrontare con il passato "
            "(atteso, pickup).",
            "Ogni giorno analizzato ha la sua osservazione delle notti da quel giorno in avanti.",
        ),
        related=("term.reconstructed", "term.snapshot", "decision.history_sample"),
        keywords=("osservato", "observed", "dato osservato", "osservazione", "visto da ninfa"),
    ),
    entry(
        "term.reconstructed",
        TERM,
        "Dato ricostruito",
        "Un dato ricostruito è stato dedotto dopo, per un giorno passato, dalle prenotazioni come "
        "sono "
        "adesso. È approssimato e non viene mai presentato come ciò che NINFA sapeva quel giorno.",
        enum(f"{_ORIGIN}.RECONSTRUCTED_APPROXIMATE"),
        doc("docs/architecture/adr/0048-reconstructed-is-not-observed-as-of.md"),
        details=(
            "Si legge dove serve sapere come finiva un giorno: per esempio le camere occupate di "
            "un mese per il costo per camera.",
            "Non è mai un campione di storia: non entra nell'atteso né nel pickup.",
            "Un'osservazione vera di una notte non viene mai sostituita da una ricostruzione.",
            "NINFA ricostruisce solo ciò che i dati permettono: mai prima dell'inizio delle "
            "prenotazioni importate, e solo con un inventario.",
        ),
        related=("term.observed", "dati.cpor_card", "workflow.set_inventory_valid_from"),
        keywords=(
            "ricostruito",
            "reconstructed",
            "dato ricostruito",
            "cosa significa ricostruito",
            "approssimato",
        ),
    ),
    entry(
        "term.snapshot",
        TERM,
        "Osservazione del giorno",
        "L'osservazione del giorno è la fotografia che NINFA scatta delle notti da quel giorno in "
        "avanti: camere prenotate, ricavi, capienza. I numeri di Dati sono quelli "
        "dell'osservazione di oggi.",
        enum(f"{_ORIGIN}.OBSERVED"),
        doc("docs/architecture/booking-snapshots-v1.md"),
        details=(
            "La capienza viene copiata nell'osservazione quando è presa: un inventario impostato "
            "dopo entra con la prossima analisi.",
            "Più file nello stesso giorno aggiungono revisioni alla stessa osservazione; l'ultima "
            "rappresenta il giorno.",
        ),
        related=("term.observed", "import.same_day_revision", "term.analysis_day"),
        keywords=("snapshot", "osservazione", "fotografia", "istantanea"),
    ),
    entry(
        "term.analysis_day",
        TERM,
        "Giorno di analisi",
        "Il giorno di analisi è la data (nel fuso orario della struttura) a cui si riferiscono i "
        "numeri "
        "mostrati: l'analisi di quel giorno descrive le notti da lì in avanti.",
        doc("docs/architecture/automatic-analysis-policy-v1.md"),
        related=("decision.daily_analysis", "dati.period_control"),
        keywords=("data di riferimento", "giorno di analisi", "as of", "oggi per ninfa"),
    ),
    entry(
        "term.on_books",
        TERM,
        "Sulle prenotazioni attuali (on-books)",
        "On-books, sulle prenotazioni attuali e già a sistema indicano la stessa cosa: ciò che è "
        "già "
        "prenotato oggi, non ciò che si avrà alla fine.",
        copy("sulle prenotazioni attuali"),
        copy("prenotazioni già a sistema"),
        related=("metric.occupancy", "metric.room_revenue", "metric.adr"),
        keywords=("on books", "on-books", "già a sistema", "prenotazioni attuali", "prenotato"),
        not_available=("On-books non è una previsione né un consuntivo.",),
    ),
    entry(
        "term.room_night",
        TERM,
        "Camera-notte",
        "Una camera venduta per una notte. Una prenotazione di due camere per tre notti vale sei "
        "camere-notte.",
        copy("camere-notte"),
        related=("metric.room_nights", "metric.ota_share"),
        keywords=("camera notte", "camere notte", "room night", "notte venduta"),
    ),
    entry(
        "term.stay_night",
        TERM,
        "Notte di soggiorno",
        "La notte in cui l'ospite dorme, non il giorno in cui prenota. Le analisi di NINFA sono "
        "organizzate per notte di soggiorno.",
        copy("Dettaglio per notte di soggiorno"),
        related=("dati.nights_table",),
        keywords=("notte di soggiorno", "stay date", "data del soggiorno"),
    ),
    entry(
        "term.ota",
        TERM,
        "OTA",
        "Le agenzie di viaggio online (Booking.com, Expedia e simili). NINFA le riconosce da un "
        "elenco prudente di nomi esatti; un nome generico non viene mai indovinato.",
        copy("OTA"),
        enum(f"{_CHANNEL_TYPE}.OTA"),
        related=("metric.ota_share", "term.channel_group", "term.direct"),
        keywords=("ota", "booking.com", "expedia", "portali", "agenzie online"),
    ),
    entry(
        "term.direct",
        TERM,
        "Canale diretto",
        "Le prenotazioni arrivate direttamente alla struttura: il sito, il telefono, l'email, "
        "chi si presenta di persona. NINFA riconosce solo nomi precisi.",
        copy("Diretto"),
        enum(f"{_CHANNEL_TYPE}.DIRECT"),
        related=("metric.direct_share", "term.ota"),
        keywords=("diretto", "direct", "sito", "telefono", "walk in"),
    ),
    entry(
        "term.channel_group",
        TERM,
        "Gruppi di canali",
        "Per la dipendenza OTA i canali sono raggruppati in OTA, Diretto, Altro canale (tour "
        "operator, agenzie, aziende) e Non classificato.",
        copy("Non classificato"),
        copy("Altro canale"),
        enum(f"{_CHANNEL_TYPE}.TOUR_OPERATOR"),
        details=(
            "Un canale non riconosciuto resta Non classificato: non si indovina.",
            "La quota OTA conta solo OTA e Diretto; gli altri gruppi sono fuori dal totale.",
        ),
        related=("metric.channel_classification_coverage", "metric.ota_share"),
        keywords=("gruppo canali", "tour operator", "agenzia", "altro canale", "non classificato"),
    ),
    entry(
        "term.booking_status",
        TERM,
        "Stati di una prenotazione",
        "NINFA conosce cinque stati: Confermata, Cancellata, Non presentato, Arrivato e Partito.",
        enum(f"{_BOOKING_STATUS}.CONFIRMED"),
        enum(f"{_BOOKING_STATUS}.CANCELLED"),
        enum(f"{_BOOKING_STATUS}.NO_SHOW"),
        copy("Non presentato"),
        details=(
            "Una parola del file che NINFA non conosce (per esempio «Modificata») viene chiesta "
            "alla persona e ricordata.",
            "Una cancellazione o un non presentato senza data rendono incerto il numero di camere "
            "occupate di quel giorno.",
        ),
        related=("import.question_value_labels", "import.bookings_file"),
        keywords=(
            "stato prenotazione",
            "confermata",
            "cancellata",
            "no show",
            "non presentato",
            "modificata",
        ),
    ),
    entry(
        "term.net_amount",
        TERM,
        "Importo al netto di IVA",
        "L'importo senza IVA (l'imponibile). NINFA analizza i costi al netto di IVA e non deve "
        "indovinare quale importo lo sia.",
        copy("Importo al netto di IVA"),
        related=("import.question_amount_basis", "import.blocker_amount_not_net"),
        keywords=("netto", "imponibile", "iva", "lordo"),
    ),
    entry(
        "term.planned_worked_hours",
        TERM,
        "Ore previste e ore lavorate",
        "Un file del personale può avere ore previste (il piano) o ore effettive (lavorate). Sono "
        "due letture diverse: l'una non sostituisce mai l'altra.",
        copy("Ore previste"),
        copy("Ore lavorate"),
        doc("docs/architecture/adr/0040-import-scope-semantics.md"),
        details=(
            "Dati > Personale mostra le ore pianificate, dal piano più recente.",
            "Il controllo Ore di personale sopra l'atteso confronta le ore programmate con quelle "
            "che domande confrontabili hanno richiesto.",
        ),
        related=(
            "metric.labor_planned_hours",
            "import.question_grid_hours",
            "decision.labor_overstaffing",
        ),
        keywords=("ore previste", "ore effettive", "ore lavorate", "pianificate", "consuntivo ore"),
    ),
    entry(
        "term.cost_categories",
        TERM,
        "Categorie di costo",
        "Le categorie di costo che NINFA riconosce: Personale, Lavanderia, Pulizie, Prodotti per "
        "gli "
        "ospiti, Cibo, Bevande, Utenze, Manutenzione, Software, Marketing, Commissioni OTA, "
        "Servizi "
        "professionali, Trasporti e Non classificato.",
        copy("Servizi professionali"),
        copy("Prodotti per gli ospiti"),
        related=("dati.cost_categories", "metric.cpor"),
        keywords=("categorie", "categoria di costo", "lavanderia", "utenze", "non classificato"),
        not_available=("Una spesa senza categoria riconosciuta non genera decisioni.",),
    ),
    entry(
        "term.labor_departments",
        TERM,
        "Reparti del personale",
        "I reparti che NINFA riconosce: Governanza, Ricevimento, Sala e bar, Cucina, Manutenzione, "
        "Direzione, Spa e benessere e Altro personale.",
        copy("Governanza"),
        copy("Spa e benessere"),
        details=(
            "Le righe con un reparto sconosciuto sono importate come Altro e non servono alle "
            "analisi sul personale.",
        ),
        related=("dati.labor_roles", "import.question_department_rows"),
        keywords=(
            "reparti",
            "governanza",
            "ricevimento",
            "sala e bar",
            "cucina",
            "direzione",
            "housekeeping",
        ),
    ),
    entry(
        "term.invoice_date_attribution",
        TERM,
        "Costi per data fattura",
        "NINFA attribuisce un costo al mese della data della fattura: non c'è competenza, ratei né "
        "risconti.",
        copy("ultimo mese concluso, per data fattura"),
        doc("docs/architecture/cost-cpor-anomaly-v1.md"),
        related=("metric.cost_total", "term.concluded_month"),
        keywords=("data fattura", "competenza", "attribuzione costi"),
        not_available=("NINFA non ripartisce i costi per periodo di competenza.",),
    ),
    entry(
        "term.concluded_month",
        TERM,
        "Mese concluso",
        "Per i costi conta solo l'ultimo mese concluso: il mese in corso non è mai un costo del "
        "mese.",
        copy("Il mese in corso non è mostrato."),
        related=("metric.cost_total", "term.invoice_date_attribution"),
        keywords=("mese concluso", "mese in corso", "ultimo mese"),
    ),
    entry(
        "term.family",
        TERM,
        "Famiglia di file",
        "Un gruppo di file con la stessa struttura di colonne che arrivano di continuo da una "
        "stessa "
        "fonte. NINFA ricorda come leggere ciascuna famiglia.",
        doc("docs/architecture/adr/0034-smart-import-source-families.md"),
        related=("import.families", "import.source_learning"),
        keywords=("famiglia", "struttura del file", "stessi file"),
    ),
    entry(
        "term.data_source",
        TERM,
        "Fonte dati",
        "Un tipo di dati di una struttura (prenotazioni, costi, personale) e il modo in cui "
        "arriva. "
        "Per ogni tipo c'è una fonte attiva alla volta; esiste solo dopo il primo import riuscito.",
        copy("Fonti dati"),
        related=("struttura.sources", "dati.data_origin", "state.several_sources"),
        keywords=("fonte", "sorgente", "origine dei dati"),
    ),
    entry(
        "term.inventory",
        TERM,
        "Inventario camere",
        "Il numero di camere che la struttura può vendere ogni notte. È ciò su cui NINFA calcola "
        "l'occupazione e non viene mai dedotto dalle prenotazioni.",
        copy("Inventario camere"),
        related=("struttura.rooms", "metric.occupancy"),
        keywords=("inventario", "capienza", "camere vendibili", "capacità"),
    ),
    entry(
        "term.analysis_areas",
        TERM,
        "Le quattro aree dell'analisi",
        "NINFA analizza quattro aree: Ricavi, Distribuzione, Costi e Personale.",
        enum(f"{_AREA}.REVENUE"),
        enum(f"{_AREA}.DISTRIBUTION"),
        enum(f"{_AREA}.COSTS"),
        enum(f"{_AREA}.LABOR"),
        related=("decision.area_summary", "dati.analysis_coverage"),
        keywords=("aree", "ricavi", "distribuzione", "costi", "personale"),
    ),
    entry(
        "term.currency",
        TERM,
        "Valuta",
        "NINFA non converte le valute: i costi in una valuta diversa da quella della struttura non "
        "sono "
        "inclusi nei totali, e la pagina lo segnala.",
        copy("Sono presenti costi in un'altra valuta: non sono inclusi."),
        related=("metric.cost_total",),
        keywords=("valuta", "euro", "altra valuta", "conversione"),
    ),
    entry(
        "term.property",
        TERM,
        "Struttura",
        "La struttura è l'hotel (o altra attività) di cui NINFA analizza i dati. Un account può "
        "avere "
        "più strutture e lavora su una alla volta, quella attiva.",
        copy("Struttura attiva"),
        related=("nav.property_selector", "nav.struttura"),
        keywords=("struttura", "hotel", "property", "attività"),
    ),
    entry(
        "term.coverage",
        TERM,
        "Copertura",
        "La copertura dice quanta parte di ciò che si è chiesto i dati coprono davvero: per "
        "esempio "
        "prenotazioni per 7 notti su 30, o un piano del personale per 3 giorni su 7. Una cifra con "
        "poca copertura va letta con prudenza.",
        copy("Capienza nota per"),
        copy("Copertura del piano"),
        related=("state.capacity_partial", "state.labor_plan_partial", "dati.analysis_coverage"),
        keywords=("copertura", "su quanti giorni", "quanti dati", "dati parziali", "copre solo"),
    ),
)

__all__ = ["ENTRIES"]
