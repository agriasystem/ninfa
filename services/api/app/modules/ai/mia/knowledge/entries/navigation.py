"""Navigation: the five sidebar sections, the decision page, Mia and the shell around them."""

from app.modules.ai.mia.knowledge.entries._build import (
    FEATURE,
    SECTION,
    SIDEBAR,
    api,
    copy,
    doc,
    entry,
    route,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "nav.sidebar",
        FEATURE,
        "Menu principale di NINFA",
        "La barra laterale ha cinque sezioni: Oggi, Decisioni, Dati, Importa file e Struttura. "
        "In basso ci sono il profilo e Impostazioni.",
        copy("Navigazione principale"),
        details=(
            "Oggi: com'è la situazione di oggi.",
            "Decisioni: le decisioni di oggi in elenco.",
            "Dati: i numeri operativi della struttura.",
            "Importa file: dove si portano i file in NINFA.",
            "Struttura: profilo, camere, parametri e fonti dati.",
        ),
        where=f"{SIDEBAR}, a sinistra",
        related=("nav.oggi", "nav.decisioni", "nav.dati", "nav.importa_file", "nav.struttura"),
        keywords=("menu", "navigazione", "sezioni", "barra laterale", "dove trovo", "pagine"),
    ),
    entry(
        "nav.oggi",
        SECTION,
        "Oggi",
        "La pagina iniziale: dice in una frase com'è la situazione di oggi, quante decisioni "
        "richiedono attenzione e a che punto è l'analisi delle quattro aree.",
        route("/oggi"),
        copy("Riepilogo per area"),
        api("GET", "/decision-feed"),
        details=(
            "Mette in evidenza la decisione più prioritaria del giorno e dice quante decisioni "
            "richiedono attenzione.",
            "Mostra l'ultimo import delle prenotazioni come fatto (data e ora), non come giudizio.",
            "Il riepilogo per area dice, per Ricavi, Distribuzione, Costi e Personale, se hanno "
            "richiesto attenzione, se l'analisi è parziale o se l'area non è stata analizzata.",
            "Il pulsante Aggiorna analisi rilegge ciò che NINFA ha già; Avvia analisi compare "
            "quando l'analisi non è ancora partita.",
            "Da qui si può scrivere a Mia (Chiedi a Mia...).",
        ),
        where=f"{SIDEBAR} > Oggi",
        page="/oggi",
        related=("nav.decisioni", "nav.mia", "decision.area_summary", "state.no_reliable_decision"),
        keywords=("home", "pagina iniziale", "situazione di oggi", "oggi", "decisioni di oggi"),
        not_available=("Oggi non mostra grafici né tabelle di dati: i numeri stanno in Dati.",),
    ),
    entry(
        "nav.decisioni",
        SECTION,
        "Decisioni",
        "L'elenco delle decisioni di oggi: le stesse che il conteggio della pagina Oggi riporta.",
        route("/decisioni"),
        copy("Filtra per area"),
        details=(
            "Si può filtrare per area (Ricavi, Distribuzione, Costi, Personale) e ordinare per "
            "Priorità, Più recenti o Aperte da più tempo.",
            "Ogni riga mostra la priorità, l'affidabilità, cosa è stato rilevato e cosa era "
            "atteso, "
            "e porta al dettaglio con Apri dettaglio.",
            "Se oggi non c'è nulla di affidabile, la pagina lo dice (Nessuna decisione affidabile "
            "oggi) "
            "invece di mostrare un elenco vuoto senza spiegazioni.",
        ),
        where=f"{SIDEBAR} > Decisioni",
        page="/decisioni",
        related=(
            "nav.decision_detail",
            "decision.what_is",
            "decision.priority",
            "decision.reliability",
        ),
        keywords=("decisioni", "elenco decisioni", "filtra", "ordina", "priorità"),
        not_available=("Non è un registro storico: mostra solo le decisioni di oggi.",),
    ),
    entry(
        "nav.decision_detail",
        SECTION,
        "Dettaglio di una decisione",
        "La pagina di una singola decisione: perché NINFA te la mostra, con quali evidenze e come "
        "è "
        "cambiata nel tempo.",
        route("/oggi/decisioni/[decisionId]"),
        copy("Perché NINFA te lo mostra"),
        api("GET", "/decisions/{decision_id}"),
        api("POST", "/decisions/{decision_id}/ask"),
        details=(
            "Stato attuale: se la decisione è Aperta o Risolta, quando è stata rilevata e la "
            "priorità del giorno.",
            "Perché NINFA te lo mostra: una frase che spiega lo scostamento.",
            "Evidenze: Attuale, Atteso e Scostamento, con la copertura dei dati e i periodi "
            "confrontabili.",
            "Evoluzione: la storia delle valutazioni di quella decisione.",
            "Cosa puoi valutare: una verifica suggerita, mai un'azione eseguita.",
            "Chiedi a Mia: domande su quella decisione.",
        ),
        where="Da Oggi o da Decisioni con Apri dettaglio, oppure da Dati con Apri la decisione",
        page="/oggi/decisioni/[decisionId]",
        related=(
            "decision.expected",
            "decision.actual",
            "decision.delta",
            "decision.history",
            "decision.recommendation",
        ),
        keywords=(
            "dettaglio decisione",
            "perché mi mostri",
            "evidenze",
            "evoluzione",
            "perché me lo stai dicendo",
        ),
    ),
    entry(
        "nav.dati",
        SECTION,
        "Dati",
        "I numeri operativi della struttura, divisi in cinque sezioni: Panoramica, Prenotazioni, "
        "Distribuzione, Costi e Personale.",
        route("/dati"),
        copy("I numeri operativi della struttura."),
        api("GET", "/data/overview"),
        details=(
            "Le cinque sezioni si scelgono con le schede in alto; la scelta resta nell'indirizzo "
            "della pagina.",
            "Panoramica e Prenotazioni hanno un periodo selezionabile: 7 o 30 giorni.",
            "Aggiorna dati rilegge i dati già presenti.",
            "Dati legge direttamente ciò che NINFA ha salvato: mostra anche costi e personale "
            "quando "
            "non fanno parte dell'analisi di oggi.",
        ),
        where=f"{SIDEBAR} > Dati",
        page="/dati",
        related=(
            "dati.overview",
            "dati.bookings",
            "dati.distribution",
            "dati.costs",
            "dati.labor",
            "dati.period_control",
        ),
        keywords=("numeri", "metriche", "occupazione", "ricavi", "tabelle", "grafici"),
        not_available=(
            "Non sono presenti previsioni dell'occupazione finale: i valori sono quelli delle "
            "prenotazioni attuali.",
        ),
    ),
    entry(
        "nav.importa_file",
        SECTION,
        "Importa file",
        "Dove si portano i file in NINFA: la persona consegna un file CSV o Excel e NINFA capisce "
        "da sola "
        "che cosa contiene.",
        route("/importa-file"),
        copy(
            "NINFA riconosce automaticamente il contenuto del file e prepara i dati per l'analisi."
        ),
        api("POST", "/data-sources/import-understanding"),
        details=(
            "Si trascina il file o lo si sceglie dal computer; NINFA legge il file e controlla "
            "tutte le righe.",
            "Se serve, NINFA fa poche domande, una alla volta; se non è sicura, propone di "
            "abbinare le colonne a mano.",
            "Nulla viene importato finché non si preme Importa dati.",
            "In fondo c'è l'elenco delle Importazioni recenti.",
            "Prenotazioni, personale (ore) e costi sono i tre tipi di dati importabili.",
        ),
        where=f"{SIDEBAR} > Importa file",
        page="/importa-file",
        related=("import.flow", "import.formats", "import.recent", "import.invoice_xml"),
        keywords=("importare", "carica", "upload", "csv", "excel", "xlsx", "file", "caricare dati"),
        not_available=(
            "Le fatture elettroniche XML non si importano da qui, ma da Struttura > Fonti dati.",
        ),
    ),
    entry(
        "nav.struttura",
        SECTION,
        "Struttura",
        "La pagina della struttura: profilo, inventario camere, parametri operativi e fonti dati, "
        "in "
        "quattro blocchi numerati.",
        route("/struttura"),
        copy("Informazioni e configurazioni operative della tua struttura."),
        api("GET", "/room-inventory"),
        details=(
            "1. Profilo struttura. 2. Inventario camere. 3. Parametri operativi. 4. Fonti dati.",
            "L'inventario camere è il blocco dove si imposta il numero di camere vendibili.",
            "Le fonti dati dicono da dove NINFA riceve i dati e permettono di gestire come sono "
            "letti i file.",
        ),
        where=f"{SIDEBAR} > Struttura",
        page="/struttura",
        related=(
            "struttura.profile",
            "struttura.rooms",
            "struttura.parameters",
            "struttura.sources",
        ),
        keywords=(
            "struttura",
            "configurazione",
            "impostazioni della struttura",
            "inventario",
            "fonti",
        ),
    ),
    entry(
        "nav.settings",
        FEATURE,
        "Impostazioni",
        "Impostazioni è disegnata in fondo alla barra laterale ma non è ancora una pagina: è "
        "segnata "
        "In arrivo e non si può aprire.",
        copy("Impostazioni"),
        copy("In arrivo"),
        where=f"{SIDEBAR}, in basso accanto al profilo",
        related=("nav.struttura", "nav.profile_menu"),
        keywords=("impostazioni", "settings", "preferenze"),
        not_available=(
            "Non esiste una pagina Impostazioni: le configurazioni della struttura si trovano in "
            "Struttura.",
        ),
    ),
    entry(
        "nav.profile_menu",
        FEATURE,
        "Profilo e account",
        "Il pulsante del profilo, in basso nella barra laterale, mostra il nome e l'email "
        "dell'account "
        "e permette di uscire con Esci.",
        copy("Profilo e account"),
        copy("Esci"),
        where=f"{SIDEBAR}, in basso a sinistra",
        related=("nav.sidebar",),
        keywords=("logout", "esci", "account", "profilo", "disconnettersi"),
        not_available=("Non ci sono impostazioni dell'account modificabili da qui.",),
    ),
    entry(
        "nav.property_selector",
        FEATURE,
        "Cambiare struttura",
        "Se l'account ha più strutture, il nome della struttura nell'intestazione diventa un menu "
        "per "
        "sceglierne un'altra. Con una sola struttura non compare.",
        copy("Struttura attiva"),
        details=(
            "La scelta vale per tutte le sezioni: le pagine mostrano i dati della struttura "
            "attiva.",
        ),
        where="Nell'intestazione della pagina, sul nome della struttura",
        related=("nav.struttura",),
        keywords=(
            "struttura attiva",
            "più strutture",
            "cambia hotel",
            "cambiare struttura",
            "hotel",
        ),
    ),
    entry(
        "nav.mia",
        FEATURE,
        "Mia, l'assistente di NINFA",
        "Mia è l'assistente di NINFA: risponde a domande sulla struttura, sui dati e sul "
        "funzionamento "
        "della piattaforma, e può essere interpellata da Oggi e dal dettaglio di una decisione.",
        copy("Chiedi a Mia"),
        copy("Chiedi a Mia..."),
        api("POST", "/ask"),
        details=(
            "Mia legge i dati che NINFA ha già calcolato e li spiega: non calcola e non inventa "
            "dati.",
            "Può spiegare una decisione, dire da dove arrivano i dati, aiutare a trovare una "
            "funzione.",
            "Nella pagina Oggi c'è Nuova conversazione per ricominciare da zero.",
        ),
        where="Pagina Oggi (Chiedi a Mia...) e dettaglio di una decisione (Chiedi a Mia)",
        related=("decision.vs_insight", "state.mia_unavailable", "state.mia_insufficient_context"),
        keywords=("mia", "assistente", "chat", "domande", "chiedere", "aiuto", "supporto"),
        not_available=(
            "Mia non modifica né configura nulla in NINFA e non crea decisioni ufficiali.",
            "Mia non cerca informazioni sul web: lavora sui dati di NINFA.",
        ),
    ),
    entry(
        "nav.documentation",
        FEATURE,
        "Come funziona NINFA, in sintesi",
        "NINFA importa i dati della struttura (prenotazioni, costi, personale), li analizza ogni "
        "giorno "
        "con regole deterministiche e mostra le decisioni che meritano attenzione.",
        doc("docs/architecture/architecture-v1.md"),
        details=(
            "Il motore calcola; Mia capisce, collega e spiega.",
            "L'analisi parte da sola una volta al giorno e dopo ogni import che cambia qualcosa.",
        ),
        related=("decision.daily_analysis", "decision.what_is", "nav.mia"),
        keywords=(
            "cosa fa ninfa",
            "cosa può fare ninfa",
            "come funziona ninfa",
            "a cosa serve ninfa",
        ),
        not_available=(
            "NINFA non ha un modello contabile: non calcola fatturato, incassi né margine.",
        ),
    ),
    entry(
        "nav.logo_home",
        FEATURE,
        "Tornare a Oggi",
        "Il logo NINFA in alto a sinistra riporta alla pagina Oggi.",
        copy("NINFA - vai a Oggi"),
        where="In alto a sinistra, sul logo",
        related=("nav.oggi",),
        keywords=("logo", "home", "tornare", "pagina iniziale"),
    ),
)

__all__ = ["ENTRIES"]
