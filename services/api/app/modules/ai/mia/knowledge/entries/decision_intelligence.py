"""Decision Intelligence: what a Decision is, the five types, and the words around them."""

from app.modules.ai.mia.knowledge.entries._build import (
    FEATURE,
    STATE,
    TERM,
    api,
    copy,
    doc,
    entry,
    enum,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_TYPE = "app.modules.intelligence.priority.types:PriorityDecisionType"
_STATUS = "app.modules.decisions.types:DecisionStatus"
_LIFECYCLE = "app.modules.decisions.types:LifecycleTransition"
_FEED = "app.modules.decision_memory.types:FeedState"
_EVAL = "app.modules.intelligence.revenue.types:EvaluationStatus"
_AREA = "app.modules.decisions.coverage:AnalysisDomain"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "decision.what_is",
        FEATURE,
        "Che cos'è una decisione",
        "Una decisione è un problema operativo che il motore di NINFA ha rilevato con regole "
        "deterministiche sui dati importati. Resta la stessa decisione nei giorni finché non "
        "rientra.",
        doc("docs/architecture/decision-layer-v1.md"),
        api("GET", "/decisions"),
        details=(
            "Ha uno stato: Aperta finché il problema c'è, Risolta quando i dati mostrano che è "
            "rientrato.",
            "Ci sono cinque tipi: Pickup sotto le attese, Rischio occupazione, Dipendenza OTA, "
            "Costo per camera anomalo, Ore di personale sopra l'atteso.",
            "È sempre un output ufficiale, deterministico e conservato: non lo crea né lo cambia "
            "Mia.",
            "Propone al massimo una verifica da fare, mai un'azione eseguita.",
        ),
        where="Oggi, Decisioni e dettaglio della decisione",
        related=(
            "decision.types",
            "decision.status",
            "decision.vs_insight",
            "nav.decisioni",
            "nav.decision_detail",
        ),
        keywords=("decisione", "cos'è una decisione", "problema", "alert", "segnalazione"),
        not_available=(
            "Una decisione non è una raccomandazione commerciale né un'azione automatica.",
        ),
    ),
    entry(
        "decision.vs_insight",
        FEATURE,
        "Decisione e spiegazione di Mia",
        "La decisione è l'output ufficiale e deterministico del motore di NINFA. Una spiegazione o "
        "un'osservazione di Mia è un'interpretazione a parole di dati già disponibili.",
        doc("docs/architecture/ask-mia-home-v1.md"),
        copy("Chiedi a Mia"),
        details=(
            "Mia può dire che il costo del personale sembra pesare molto, ma non per questo nasce "
            "una decisione.",
            "Solo il motore crea, conserva e fa evolvere le decisioni.",
        ),
        related=("nav.mia", "decision.what_is"),
        keywords=(
            "decisione ufficiale",
            "mia crea decisioni",
            "differenza insight decisione",
            "osservazione di mia",
        ),
        not_available=("Mia non crea né modifica decisioni.",),
    ),
    entry(
        "decision.types",
        FEATURE,
        "I cinque tipi di decisione",
        "Oggi NINFA rileva cinque tipi di problema: Pickup sotto le attese, Rischio occupazione, "
        "Dipendenza OTA, Costo per camera anomalo e Ore di personale sopra l'atteso.",
        copy("Pickup sotto le attese"),
        copy("Ore di personale sopra l'atteso"),
        enum(f"{_TYPE}.REV_PICKUP_LOW"),
        enum(f"{_TYPE}.REV_OCCUPANCY_RISK"),
        enum(f"{_TYPE}.REV_OTA_DEPENDENCY"),
        enum(f"{_TYPE}.COST_CPOR_ANOMALY"),
        enum(f"{_TYPE}.LABOR_OVERSTAFFING"),
        details=(
            "Le prime tre riguardano ricavi e distribuzione; le ultime due riguardano costi e "
            "personale.",
            "Ogni tipo ha un livello atteso diverso e una soglia propria stabilita dal motore.",
        ),
        related=(
            "decision.pickup_low",
            "decision.occupancy_risk",
            "decision.ota_dependency",
            "decision.cpor_anomaly",
            "decision.labor_overstaffing",
        ),
        keywords=(
            "tipi di decisione",
            "quali decisioni",
            "che problemi rileva",
            "cosa controlla ninfa",
        ),
        not_available=(
            "Non esistono altri tipi di decisione: per esempio non c'è un controllo dei prezzi dei "
            "concorrenti.",
        ),
    ),
    entry(
        "decision.pickup_low",
        FEATURE,
        "Pickup sotto le attese",
        "Per una notte di soggiorno, negli ultimi 7 giorni sono entrate meno camere di quante la "
        "storia dice di aspettarsi.",
        copy("Pickup sotto le attese"),
        enum(f"{_TYPE}.REV_PICKUP_LOW"),
        details=(
            "Confronta le camere di oggi con quelle di 7 giorni fa per la stessa notte e le mette "
            "a confronto con ciò che è successo in notti confrontabili.",
            "Serve una storia sufficiente di osservazioni vere: senza non c'è decisione.",
            "Se non sono arrivati nuovi dati di prenotazione, il pickup non è noto (non è zero): "
            "non c'è decisione.",
            "Non si applica a una notte chiusa o quasi esaurita.",
        ),
        related=("metric.pickup", "state.stale_booking", "decision.expected", "term.observed"),
        keywords=(
            "pickup basso",
            "prenotazioni lente",
            "ritmo delle prenotazioni",
            "rev_pickup_low",
        ),
    ),
    entry(
        "decision.occupancy_risk",
        FEATURE,
        "Rischio occupazione",
        "Le camere già prenotate, più il ritmo abituale di nuove prenotazioni, non raggiungono "
        "l'occupazione finale che di solito si ha in quella situazione.",
        copy("Rischio occupazione"),
        enum(f"{_TYPE}.REV_OCCUPANCY_RISK"),
        details=(
            "È una proiezione minima del pickup netto, non una previsione commerciale: le "
            "cancellazioni sono già dentro il movimento storico.",
            "La pagina lo racconta in punti di occupazione sotto il livello atteso.",
            "L'occupazione non viene mai tagliata al 100%: una prenotazione oltre l'inventario "
            "resta visibile.",
        ),
        related=("metric.occupancy", "decision.expected", "state.over_capacity"),
        keywords=("rischio occupazione", "occupazione bassa", "notte debole", "rev_occupancy_risk"),
        not_available=(
            "NINFA non fornisce previsioni dell'occupazione finale al di fuori di questa "
            "decisione.",
        ),
    ),
    entry(
        "decision.ota_dependency",
        FEATURE,
        "Dipendenza OTA",
        "La quota di camere-notte prenotate su OTA nei prossimi 30 giorni è sopra il livello "
        "atteso "
        "per la struttura.",
        copy("Dipendenza OTA"),
        enum(f"{_TYPE}.REV_OTA_DEPENDENCY"),
        doc("docs/architecture/ota-dependency-v1.md"),
        details=(
            "Misura la concentrazione della distribuzione, non le prestazioni di un canale.",
            "I canali sono classificati in modo prudente: OTA, Diretto, Altro o Non classificato; "
            "un nome ambiguo non viene indovinato.",
            "Se i dati non bastano o le date delle prenotazioni sono incoerenti, NINFA non valuta "
            "e lo spiega.",
        ),
        related=(
            "metric.ota_share",
            "metric.reference_ota_share",
            "dati.distribution",
            "state.channel_mix_conflict",
        ),
        keywords=("dipendenza ota", "troppo ota", "quota ota alta", "rev_ota_dependency"),
        not_available=(
            "NINFA non calcola commissioni, conversione o redditività dei canali e non suggerisce "
            "di chiuderne uno.",
        ),
    ),
    entry(
        "decision.cpor_anomaly",
        FEATURE,
        "Costo per camera anomalo",
        "Il costo per camera occupata di una categoria, in un mese concluso, è nettamente sopra "
        "ciò "
        "che la storia di mesi confrontabili indica.",
        copy("Costo per camera anomalo"),
        enum(f"{_TYPE}.COST_CPOR_ANOMALY"),
        doc("docs/architecture/cost-cpor-anomaly-v1.md"),
        details=(
            "Riguarda una categoria di costo alla volta (per esempio cibo o utenze).",
            "Serve che le camere occupate del mese siano note e che ci siano abbastanza mesi "
            "confrontabili.",
            "Le categorie Non classificato non generano decisioni.",
        ),
        related=("metric.cpor", "dati.costs", "dati.cpor_card"),
        keywords=("costo per camera", "cpor anomalo", "costi alti", "cost_cpor_anomaly"),
    ),
    entry(
        "decision.labor_overstaffing",
        FEATURE,
        "Ore di personale sopra l'atteso",
        "Per la domanda di camere che quel giorno ci si aspetta, le ore programmate di un reparto "
        "sono nettamente sopra quelle che domande confrontabili hanno richiesto.",
        copy("Ore di personale sopra l'atteso"),
        enum(f"{_TYPE}.LABOR_OVERSTAFFING"),
        doc("docs/architecture/labor-overstaffing-v1.md"),
        details=(
            "Si confrontano giornate con domanda confrontabile, non con la stessa data del "
            "calendario.",
            "Serve un piano del personale per quel giorno; senza piano o con ore mancanti, NINFA "
            "non conclude.",
            "Riguarda un reparto alla volta.",
        ),
        related=("dati.labor", "metric.labor_planned_hours", "term.planned_worked_hours"),
        keywords=(
            "sovradimensionamento",
            "troppe ore",
            "personale in eccesso",
            "labor_overstaffing",
        ),
    ),
    entry(
        "decision.expected",
        FEATURE,
        "Atteso",
        "L'atteso è il livello che NINFA considera normale per una situazione confrontabile, "
        "ricavato "
        "dalla storia di notti o mesi comparabili. Non è una previsione e non è un obiettivo.",
        copy("Atteso"),
        doc("docs/architecture/expected-engine-v1.md"),
        details=(
            "Per le prenotazioni è «quante camere si avevano di solito a quella distanza dal "
            "soggiorno».",
            "L'intervallo mostrato è la fascia centrale della storia, non un intervallo di "
            "confidenza.",
            "Nel dettaglio di una decisione compare nelle Evidenze accanto ad Attuale e "
            "Scostamento.",
        ),
        where="Dettaglio di una decisione > Evidenze",
        related=("decision.actual", "decision.delta", "metric.reference_ota_share"),
        keywords=("atteso", "livello atteso", "normalmente", "baseline", "riferimento"),
        not_available=(
            "L'atteso non è una previsione di quante camere si avranno a fine periodo.",
        ),
    ),
    entry(
        "decision.actual",
        FEATURE,
        "Attuale (rilevato)",
        "L'attuale (o rilevato) è il valore che i dati importati mostrano oggi per la cosa che la "
        "decisione controlla.",
        copy("Attuale"),
        copy("Rilevato"),
        where="Dettaglio di una decisione > Evidenze; elenco Decisioni (Rilevato)",
        related=("decision.expected", "decision.delta"),
        keywords=("attuale", "rilevato", "valore attuale"),
    ),
    entry(
        "decision.delta",
        FEATURE,
        "Scostamento",
        "Lo scostamento è la differenza tra ciò che è stato rilevato e ciò che era atteso. Nelle "
        "decisioni di NINFA va sempre nella stessa direzione: sotto l'atteso per pickup e "
        "occupazione, sopra per OTA, costi e ore.",
        copy("Scostamento"),
        where="Dettaglio di una decisione > Evidenze",
        related=("decision.expected", "decision.actual", "decision.impact"),
        keywords=("scostamento", "differenza", "delta", "sopra l'atteso", "sotto l'atteso"),
    ),
    entry(
        "decision.impact",
        FEATURE,
        "Impatto economico indicativo",
        "Quando c'è, è una stima indicativa dell'esposizione economica della decisione. Non è una "
        "perdita né un risparmio.",
        copy("Impatto economico indicativo"),
        copy("Impatto stimato"),
        details=(
            "Compare solo per i tipi di decisione che hanno una stima economica.",
            "Per la dipendenza OTA non c'è una stima in euro: si mostrano le camere-notte da OTA.",
            "Non è la priorità: la priorità non è in euro.",
        ),
        where="Dettaglio di una decisione; elenco Decisioni (Impatto stimato)",
        related=("decision.priority", "decision.delta"),
        keywords=("impatto", "euro", "impatto economico", "quanto perdo", "stima"),
        not_available=("NINFA non dice quanto si è perso né quanto si risparmierebbe.",),
    ),
    entry(
        "decision.priority",
        FEATURE,
        "Priorità",
        "La priorità dice in quale ordine guardare le decisioni di oggi: Priorità 1 è la prima. "
        "Nasce da una gravità normalizzata del segnale, non da un importo in euro.",
        copy("Priorità"),
        doc("docs/architecture/priority-engine-v1.md"),
        details=(
            "Si ordinano solo le decisioni già rilevate: non decide se una decisione sia giusta.",
            "L'ordine di priorità non va mai spiegato come giudizio sul valore del problema.",
        ),
        where="Elenco Decisioni (Priorità) e dettaglio (Priorità nell'analisi del giorno)",
        related=("decision.impact", "decision.reliability", "nav.decisioni"),
        keywords=("priorità", "ordine", "prima decisione", "più urgente", "ranking"),
    ),
    entry(
        "decision.reliability",
        FEATURE,
        "Affidabilità",
        "L'affidabilità dice quanto NINFA è sicura della conclusione, in percentuale. Una "
        "conclusione "
        "sotto la soglia di affidabilità non viene mostrata.",
        copy("Affidabilità"),
        copy("Alcuni risultati non sono abbastanza affidabili per essere mostrati."),
        details=(
            "Il motore la calcola per ogni controllo, dalla qualità dei dati e del confronto con "
            "la storia.",
            "Se non basta, il risultato resta nascosto invece di essere mostrato con "
            "un'affidabilità bassa.",
        ),
        where="Elenco Decisioni e dettaglio di una decisione",
        related=("state.no_reliable_decision", "decision.priority"),
        keywords=("affidabilità", "confidenza", "quanto è sicuro", "percentuale affidabilità"),
    ),
    entry(
        "decision.status",
        FEATURE,
        "Aperta e Risolta",
        "Una decisione è Aperta finché il problema che la ha generata è ancora presente nei dati, "
        "Risolta quando i dati mostrano che è rientrato. Aperta non significa che si debba agire.",
        copy("Aperta"),
        copy("Risolta"),
        enum(f"{_STATUS}.OPEN"),
        enum(f"{_STATUS}.RESOLVED"),
        details=(
            "La decisione si risolve da sola quando l'analisi la trova rientrata: non c'è un "
            "pulsante per chiuderla.",
            "Se il problema ricompare, la stessa decisione si riapre (Ricomparsa).",
        ),
        where="Dettaglio di una decisione > Stato attuale",
        related=("decision.history", "decision.what_is"),
        keywords=("aperta", "risolta", "stato decisione", "chiudere decisione"),
        not_available=("Non si può chiudere o ignorare una decisione a mano.",),
    ),
    entry(
        "decision.history",
        FEATURE,
        "Evoluzione di una decisione",
        "La sezione Evoluzione del dettaglio mostra, valutazione dopo valutazione, cosa è successo "
        "alla "
        "decisione: Rilevata, Ancora presente, Risolta, Ricomparsa.",
        copy("Evoluzione"),
        copy("Ancora presente"),
        api("GET", "/decisions/{decision_id}/history"),
        details=(
            "Quando i dati non bastano per una nuova conclusione lo dice (Dati non sufficienti per "
            "una nuova conclusione).",
            "Si possono caricare eventi precedenti con Mostra eventi precedenti.",
        ),
        where="Dettaglio di una decisione > Evoluzione",
        related=("decision.status", "nav.decision_detail"),
        keywords=("evoluzione", "storia", "cronologia", "ricomparsa", "ancora presente"),
    ),
    entry(
        "decision.evidence",
        FEATURE,
        "Evidenze di una decisione",
        "Le Evidenze mostrano Attuale, Atteso e Scostamento della decisione, con la copertura dei "
        "dati e il numero di periodi comparabili su cui si basa.",
        copy("Evidenze"),
        copy("Copertura dati"),
        where="Dettaglio di una decisione > Evidenze",
        related=("decision.expected", "decision.actual", "decision.delta"),
        keywords=("evidenze", "dati usati", "su cosa si basa", "periodi comparabili"),
    ),
    entry(
        "decision.recommendation",
        FEATURE,
        "Cosa puoi valutare",
        "Sotto una decisione NINFA propone una verifica da fare (per esempio rivedere prezzi e "
        "disponibilità), mai un'azione già eseguita.",
        copy("Cosa puoi valutare"),
        doc("docs/architecture/recommendation-ui-v1.md"),
        details=(
            "Ogni verifica usa parole come rivedi, verifica o controlla.",
            "Non ci sono caselle da spuntare: NINFA non registra che una verifica sia stata fatta.",
            "Può esserci un elenco Da verificare e delle note neutre in Da tenere presente.",
        ),
        where="Dettaglio di una decisione > Cosa puoi valutare",
        related=("nav.decision_detail", "decision.what_is"),
        keywords=(
            "raccomandazione",
            "cosa posso fare",
            "suggerimento",
            "cosa verificare",
            "consiglio",
        ),
        not_available=("NINFA non esegue azioni: nessun prezzo o turno viene cambiato.",),
    ),
    entry(
        "decision.area_summary",
        FEATURE,
        "Riepilogo per area",
        "Nella pagina Oggi, quattro riquadri (Ricavi, Distribuzione, Costi, Personale) dicono per "
        "ogni "
        "area se c'è una decisione, se l'analisi è parziale o se l'area non è stata analizzata.",
        copy("Riepilogo per area"),
        enum(f"{_AREA}.REVENUE"),
        enum(f"{_AREA}.DISTRIBUTION"),
        enum(f"{_AREA}.COSTS"),
        enum(f"{_AREA}.LABOR"),
        where="Oggi, riepilogo per area",
        related=("state.not_analyzed", "state.partial_analysis", "dati.analysis_coverage"),
        keywords=("aree", "ricavi", "distribuzione", "costi", "personale", "riquadri"),
    ),
    entry(
        "decision.feed_states",
        FEATURE,
        "I quattro esiti dell'analisi di oggi",
        "L'analisi di un giorno finisce in uno di quattro stati: ci sono decisioni da guardare, "
        "tutto "
        "sotto controllo, nessuna decisione affidabile, oppure l'analisi non c'è ancora.",
        enum(f"{_FEED}.ACTION_REQUIRED"),
        enum(f"{_FEED}.NO_ACTION_REQUIRED"),
        enum(f"{_FEED}.DATA_QUALITY_LIMITED"),
        enum(f"{_FEED}.NOT_PROCESSED"),
        details=(
            "Tutto sotto controllo vale solo se nulla è stato rilevato e nessun controllo è "
            "rimasto inconcludente.",
            "Nessuna decisione affidabile oggi non significa che vada tutto bene: dice solo che "
            "non c'è nulla di affidabile da segnalare.",
            "Analisi non ancora disponibile: l'analisi di oggi non è stata completata.",
        ),
        where="Oggi e Decisioni",
        related=(
            "state.all_under_control",
            "state.no_reliable_decision",
            "state.not_processed",
            "decision.daily_analysis",
        ),
        keywords=(
            "stati dell'analisi",
            "perché non ho decisioni",
            "nessuna decisione",
            "tutto sotto controllo",
        ),
    ),
    entry(
        "decision.statuses_of_check",
        FEATURE,
        "Perché un controllo può non dare una decisione",
        "Ogni controllo dà uno di cinque esiti: attivato, nella norma, dati insufficienti, non "
        "applicabile, oppure non abbastanza affidabile per essere mostrato. Solo il primo diventa "
        "una decisione.",
        enum(f"{_EVAL}.TRIGGERED"),
        enum(f"{_EVAL}.CLEAR"),
        enum(f"{_EVAL}.INSUFFICIENT_DATA"),
        enum(f"{_EVAL}.NOT_APPLICABLE"),
        enum(f"{_EVAL}.SUPPRESSED_LOW_CONFIDENCE"),
        details=(
            "Dati insufficienti: non ci sono abbastanza dati affidabili per valutare.",
            "Non applicabile: la regola non ha senso in quel contesto (per esempio una notte "
            "chiusa).",
            "Non abbastanza affidabile: la condizione numerica c'è ma NINFA non è abbastanza "
            "sicura da mostrarla.",
        ),
        related=(
            "decision.insufficient_data",
            "state.no_reliable_decision",
            "decision.reliability",
        ),
        keywords=("dati insufficienti", "non applicabile", "esiti", "perché non c'è una decisione"),
    ),
    entry(
        "decision.insufficient_data",
        STATE,
        "Dati insufficienti",
        "Quando i dati non bastano per una conclusione affidabile, NINFA non apre una decisione e "
        "lo "
        "dice, invece di mostrare un numero poco sicuro.",
        copy("Dati insufficienti"),
        enum(f"{_EVAL}.INSUFFICIENT_DATA"),
        details=(
            "Le cause tipiche: storico ancora troppo breve, prenotazioni insufficienti, canali non "
            "classificati, dati di prenotazione incompleti o con date incoerenti.",
            "Non è un errore: spesso si risolve da solo con il passare dei giorni.",
        ),
        related=(
            "decision.statuses_of_check",
            "state.distribution_history",
            "state.no_reliable_decision",
        ),
        keywords=("dati insufficienti", "non bastano i dati", "storico breve", "non può valutare"),
    ),
    entry(
        "decision.daily_analysis",
        FEATURE,
        "L'analisi giornaliera",
        "NINFA analizza ogni struttura da sola una volta al giorno, dopo le 10:00 del suo fuso "
        "orario, "
        "senza che nessuno la avvii. Ne parte una anche dopo ogni import che cambia qualcosa.",
        doc("docs/architecture/automatic-analysis-policy-v1.md"),
        api("GET", "/analysis/status"),
        details=(
            "Analizza 30 notti a partire da oggi, i costi dei mesi conclusi e il piano del "
            "personale presente.",
            "Per partire serve una sola fonte di prenotazioni con un import riuscito; con più "
            "fonti NINFA non ne sceglie una.",
            "Se l'analisi fallisce, viene ritentata dopo un'ora, fino a tre volte al giorno.",
            "Un giorno senza nuovi dati di prenotazione viene analizzato ma non vale come campione "
            "di storia.",
        ),
        related=("import.post_import_analysis", "state.stale_booking", "decision.feed_states"),
        keywords=(
            "analisi giornaliera",
            "ogni giorno",
            "quando analizza",
            "orario analisi",
            "analisi automatica",
        ),
    ),
    entry(
        "decision.history_sample",
        TERM,
        "Che cosa conta come storia",
        "Per confrontare con il passato NINFA usa solo osservazioni di giorni la cui analisi si è "
        "conclusa e che dice cosa aveva letto: una ricostruzione non è mai un campione di storia.",
        doc("docs/architecture/adr/0046-a-sample-of-history-is-what-a-finished-analysis-read.md"),
        doc("docs/architecture/adr/0048-reconstructed-is-not-observed-as-of.md"),
        related=("term.observed", "term.reconstructed", "decision.expected"),
        keywords=("storia", "campione", "storico", "confronto col passato"),
    ),
)

__all__ = ["ENTRIES"]
