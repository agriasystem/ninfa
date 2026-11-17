"""States: the messages and conditions a person can read on screen, in the product's own words."""

from app.modules.ai.mia.knowledge.entries._build import STATE, api, copy, doc, entry, enum
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_CAPACITY = "app.modules.data_overview.types:CapacityState"
_NIGHT = "app.modules.data_overview.types:NightStatus"
_UPDATE = "app.modules.analysis.status:AnalysisUpdateState"
_DOMAIN_STATE = "app.modules.data_overview.types:DomainState"
_OTA = "app.modules.data_overview.types:OtaOutcome"
_CPOR = "app.modules.data_overview.types:CporStatus"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "state.partial_analysis",
        STATE,
        "Analisi parziale",
        "Analisi parziale vuol dire che per quell'area, o per quella notte, alcuni controlli non "
        "hanno "
        "potuto concludere: NINFA non può dire che vada tutto bene. Non è un errore.",
        copy("Analisi parziale"),
        copy("Analisi parziale: NINFA non può dire che in quest'area vada tutto bene."),
        enum(f"{_DOMAIN_STATE}.PARTIAL"),
        enum(f"{_NIGHT}.PARTIAL"),
        details=(
            "È uno stato secondario: compare come etichetta di un'area o di una notte, non come "
            "titolo della pagina.",
            "Quanti controlli sono rimasti inconcludenti non si mostra.",
            "Il feed non dice il motivo: Mia non deve inventarne uno.",
        ),
        where="Oggi (riepilogo per area), Decisioni, Dati (stato di una notte)",
        related=("state.no_reliable_decision", "decision.area_summary", "state.night_status"),
        keywords=(
            "analisi parziale",
            "perché vedo analisi parziale",
            "parziale",
            "controlli inconcludenti",
        ),
    ),
    entry(
        "state.no_reliable_decision",
        STATE,
        "Nessuna decisione affidabile oggi",
        "Significa che NINFA non ha elementi sufficienti per formulare nuove decisioni affidabili "
        "oggi. "
        "Non vuol dire che vada tutto bene, né che ci sia un allarme.",
        copy("Nessuna decisione affidabile oggi"),
        copy("NINFA non ha ancora elementi sufficienti per formulare nuove decisioni affidabili."),
        enum("app.modules.decision_memory.types:FeedState.DATA_QUALITY_LIMITED"),
        details=(
            "Può dipendere da uno storico ancora corto, dall'assenza di nuove prenotazioni o da "
            "una "
            "affidabilità troppo bassa; il sistema non sa dire quale delle cause sia, e non la "
            "nomina.",
            "Restano visibili l'ultimo import delle prenotazioni e lo stato delle quattro aree.",
            "È diverso da Tutto sotto controllo (nulla rilevato) e da Analisi non ancora "
            "disponibile (nulla analizzato).",
        ),
        where="Oggi e Decisioni",
        related=(
            "state.all_under_control",
            "state.not_processed",
            "state.partial_analysis",
            "decision.feed_states",
        ),
        keywords=(
            "nessuna decisione",
            "perché oggi non ho decisioni",
            "nessuna decisione affidabile",
            "non ci sono decisioni",
            "oggi niente",
        ),
        not_available=(
            "NINFA non dice perché oggi non c'è nulla di affidabile: il dato non esiste.",
        ),
    ),
    entry(
        "state.all_under_control",
        STATE,
        "Tutto sotto controllo",
        "Nessuna decisione richiede attenzione in questo momento. Si dice solo quando nulla è "
        "stato "
        "rilevato e nessun controllo è rimasto inconcludente.",
        copy("Tutto sotto controllo"),
        copy("Nessuna decisione richiede la tua attenzione in questo momento."),
        enum("app.modules.decision_memory.types:FeedState.NO_ACTION_REQUIRED"),
        details=(
            "Può essere accompagnato da Non analizzati: … se qualche area non è stata analizzata: "
            "non vale per quell'area.",
        ),
        where="Oggi",
        related=("state.no_reliable_decision", "dati.analysis_coverage", "decision.feed_states"),
        keywords=("tutto sotto controllo", "va tutto bene", "nessuna attenzione"),
    ),
    entry(
        "state.not_processed",
        STATE,
        "Analisi non ancora disponibile",
        "NINFA non ha ancora completato l'analisi per oggi (oppure non ne ha mai completata una). "
        "L'interfaccia non dice il motivo, perché non lo sa.",
        copy("Analisi non ancora disponibile"),
        copy("NINFA non ha ancora completato l'analisi per oggi."),
        copy("NINFA non ha ancora completato una prima analisi."),
        enum("app.modules.decision_memory.types:FeedState.NOT_PROCESSED"),
        details=(
            "Se esiste un'analisi precedente, indica la data dell'ultima completata.",
            "Un'analisi fallita non viene conservata: non si distingue da una non ancora fatta.",
            "L'analisi parte da sola dopo le 10:00 e dopo ogni import che cambia qualcosa.",
        ),
        where="Oggi e Decisioni",
        related=("decision.daily_analysis", "import.post_import_analysis", "state.no_data"),
        keywords=(
            "analisi non disponibile",
            "analisi mancante",
            "perché non c'è l'analisi",
            "prima analisi",
        ),
    ),
    entry(
        "state.no_data",
        STATE,
        "Nessun dato importato",
        "Se non è stato importato nulla, la pagina Oggi invita a importare i primi dati: l'analisi "
        "partirà da sola.",
        copy("Importa i primi dati della struttura e NINFA avvierà l'analisi da sola."),
        copy("Importa un file"),
        enum(f"{_UPDATE}.NO_DATA"),
        where="Oggi",
        related=("nav.importa_file", "state.needs_bookings"),
        keywords=("primi dati", "nessun dato", "struttura vuota", "iniziare"),
    ),
    entry(
        "state.needs_bookings",
        STATE,
        "Servono anche le prenotazioni",
        "Se la struttura ha costi o personale ma non prenotazioni, l'analisi di Oggi non può "
        "partire: "
        "tutti i controlli hanno bisogno delle prenotazioni. I dati importati si vedono in Dati.",
        copy("Per l'analisi di Oggi servono anche le prenotazioni."),
        enum(f"{_UPDATE}.NEEDS_BOOKINGS"),
        where="Oggi",
        related=("nav.dati", "import.post_import_analysis"),
        keywords=("servono prenotazioni", "senza prenotazioni", "solo costi", "solo personale"),
    ),
    entry(
        "state.analysis_updating",
        STATE,
        "Aggiornamento analisi in corso",
        "NINFA sta analizzando i dati appena importati. Il risultato compare da solo; se richiede "
        "più "
        "del previsto, la pagina lo dice e i dati importati restano al sicuro.",
        copy("Aggiornamento analisi…"),
        copy("Sta richiedendo più del previsto."),
        enum(f"{_UPDATE}.IN_PROGRESS"),
        enum(f"{_UPDATE}.DELAYED"),
        where="Oggi, Dati, Struttura",
        related=("import.post_import_analysis", "state.analysis_failed"),
        keywords=("aggiornamento analisi", "analisi in corso", "sta richiedendo più del previsto"),
    ),
    entry(
        "state.new_data_imported",
        STATE,
        "Nuovi dati importati",
        "Dei dati sono stati importati ma l'analisi non è ancora partita (L'analisi non è ancora "
        "partita) oppure è rimandata a domani perché le prenotazioni sono cambiate dopo la lettura "
        "di oggi.",
        copy("Nuovi dati importati"),
        copy("entreranno nell'analisi di domani"),
        enum(f"{_UPDATE}.NEW_DATA"),
        enum(f"{_UPDATE}.DEFERRED"),
        details=("Con Avvia analisi si può chiedere di nuovo l'analisi, quando è possibile.",),
        where="Oggi",
        related=("import.post_import_analysis", "workflow.refresh_analysis"),
        keywords=("nuovi dati importati", "analisi non partita", "analisi di domani"),
    ),
    entry(
        "state.analysis_failed",
        STATE,
        "Aggiornamento analisi non riuscito",
        "L'analisi non si è aggiornata, ma i dati importati sono al sicuro. Si può riprovare dalla "
        "pagina con Riprova.",
        copy("Aggiornamento analisi non riuscito"),
        copy("I dati importati sono al sicuro: è l'analisi a non essersi aggiornata."),
        enum(f"{_UPDATE}.FAILED"),
        where="Oggi, Dati",
        related=("import.post_import_analysis", "workflow.refresh_analysis"),
        keywords=("analisi non riuscita", "analisi fallita", "errore analisi"),
    ),
    entry(
        "state.several_sources",
        STATE,
        "Più origini di prenotazioni",
        "Se ci sono più fonti attive di prenotazioni, NINFA non ne sceglie una da sola: l'analisi "
        "non "
        "parte finché le fonti non si controllano in Struttura.",
        copy("Più origini di prenotazioni"),
        copy("NINFA non ne sceglie una da sola: controlla le fonti in Struttura."),
        enum(f"{_UPDATE}.SEVERAL_SOURCES"),
        where="Oggi (Controlla le fonti) e Struttura > Fonti dati",
        related=("struttura.sources", "dati.data_origin"),
        keywords=("più fonti", "più origini", "due fonti", "fonti duplicate"),
    ),
    entry(
        "state.not_analyzed",
        STATE,
        "Area non analizzata",
        "Non analizzati (o Non analizzata, Non analizzato) vuol dire che quell'area non fa parte "
        "dell'analisi di oggi: i dati registrati si vedono comunque in Dati.",
        copy("Non analizzati"),
        copy("Quest'area non è stata analizzata."),
        enum(f"{_DOMAIN_STATE}.NOT_ANALYZED"),
        details=(
            "L'interfaccia non ne dichiara il motivo: dice solo che l'area non è stata analizzata.",
        ),
        where="Oggi (riepilogo per area), Decisioni, Dati",
        related=("decision.area_summary", "dati.analysis_coverage"),
        keywords=(
            "non analizzati",
            "area non analizzata",
            "costi non analizzati",
            "personale non analizzato",
        ),
    ),
    entry(
        "state.inventory_missing",
        STATE,
        "Inventario camere da configurare",
        "Le prenotazioni ci sono ma manca il numero di camere della struttura: l'occupazione non "
        "si "
        "può calcolare. NINFA non deduce mai la capienza dalle prenotazioni.",
        copy("Inventario camere da configurare"),
        copy("Configura inventario"),
        enum(f"{_CAPACITY}.MISSING"),
        details=("Ricavi camera, camere-notte e ADR restano visibili.",),
        where="Dati > Panoramica e Prenotazioni",
        related=("workflow.change_room_count", "struttura.rooms", "metric.occupancy"),
        keywords=(
            "inventario mancante",
            "occupazione non disponibile",
            "perché non vedo l'occupazione",
            "configura inventario",
        ),
    ),
    entry(
        "state.inventory_awaiting",
        STATE,
        "Occupazione non ancora calcolata",
        "L'inventario camere è configurato, ma l'occupazione sarà calcolata alla prossima analisi "
        "delle prenotazioni.",
        copy("Occupazione non ancora calcolata"),
        enum(f"{_CAPACITY}.AWAITING_ANALYSIS"),
        details=(
            "L'osservazione del giorno copia la capienza quando viene presa: una capienza "
            "impostata dopo entra con la prossima.",
        ),
        where="Dati > Panoramica e Prenotazioni",
        related=("struttura.rooms", "import.post_import_analysis"),
        keywords=("occupazione non calcolata", "inventario appena impostato"),
    ),
    entry(
        "state.capacity_partial",
        STATE,
        "Capienza nota solo per alcune notti",
        "Quando la capienza è nota solo per alcune notti, l'occupazione si basa su quelle notti "
        "sole, "
        "e la pagina lo dice (Capienza nota per N di M notti).",
        copy("Capienza nota per"),
        enum(f"{_CAPACITY}.PARTIAL"),
        where="Dati > Panoramica, riquadro Occupazione",
        related=("metric.occupancy", "metric.rooms_available"),
        keywords=("capienza nota", "notti con capienza", "occupazione parziale"),
    ),
    entry(
        "state.over_capacity",
        STATE,
        "Prenotazioni superiori all'inventario",
        "In alcune date risultano prenotate più camere di quelle configurate come disponibili. È "
        "una "
        "domanda sui dati, non una decisione: l'inventario potrebbe essere troppo basso, ci "
        "potrebbe "
        "essere overbooking o una prenotazione sbagliata.",
        copy("Prenotazioni superiori all'inventario"),
        copy("Controlla inventario"),
        details=(
            "L'occupazione resta quella calcolata, anche oltre il 100%: non viene tagliata.",
            "Il grafico mantiene l'altezza vera della barra e disegna l'inventario come linea "
            "tratteggiata al 100%.",
            "La tabella segna la riga con Sopra l'inventario e il dettaglio (N prenotate / M "
            "disponibili).",
            "NINFA non sa dire quale delle tre cause sia quella giusta.",
        ),
        where="Dati > Panoramica e Prenotazioni",
        related=("workflow.check_over_capacity", "struttura.rooms", "metric.occupancy"),
        keywords=(
            "occupazione sopra 100",
            "oltre il 100",
            "overbooking",
            "sopra l'inventario",
            "più prenotazioni che camere",
        ),
        not_available=("NINFA non apre una decisione per le prenotazioni sopra l'inventario.",),
    ),
    entry(
        "state.night_status",
        STATE,
        "Stato di una notte",
        "Nella tabella Dettaglio soggiorni ogni notte ha uno stato: Attenzione, Analisi parziale, "
        "Regolare o Non valutato. Riflette solo le decisioni di NINFA per quella notte.",
        copy("Regolare"),
        copy("Non valutato"),
        enum(f"{_NIGHT}.ATTENTION"),
        enum(f"{_NIGHT}.REGULAR"),
        enum(f"{_NIGHT}.NOT_EVALUATED"),
        details=(
            "Attenzione: una decisione di oggi riguarda quella notte.",
            "Analisi parziale: i ricavi sono stati analizzati ma alcuni controlli non hanno potuto "
            "concludere.",
            "Regolare: ricavi analizzati, nessuna decisione sulla notte e nessun controllo "
            "inconcludente.",
            "Non valutato: nessuna analisi, ricavi non analizzati o nessun dato di prenotazione "
            "per la notte.",
            "Non è un giudizio sui numeri della notte.",
        ),
        where="Dati > Dettaglio soggiorni, colonna Stato",
        related=("dati.nights_table", "state.partial_analysis"),
        keywords=("stato notte", "attenzione", "regolare", "non valutato", "notti da guardare"),
    ),
    entry(
        "state.distribution_insufficient",
        STATE,
        "Distribuzione: dati insufficienti",
        "Il riquadro Dipendenza OTA dice Dati insufficienti e il motivo quando NINFA non può "
        "valutare: "
        "per esempio nessuna prenotazione nei prossimi 30 giorni, troppe poche prenotazioni OTA o "
        "dirette, "
        "troppi canali non classificati, dati incompleti o con stato incerto.",
        copy("Dati insufficienti"),
        copy("Perché:"),
        enum(f"{_OTA}.INSUFFICIENT_DATA"),
        where="Dati > Distribuzione e riquadro Dipendenza OTA",
        related=(
            "decision.insufficient_data",
            "state.channel_mix_conflict",
            "metric.channel_classification_coverage",
        ),
        keywords=("dati insufficienti ota", "perché non valuta le ota", "ota non valutata"),
    ),
    entry(
        "state.distribution_history",
        STATE,
        "Storico ancora insufficiente",
        "I dati attuali sulla distribuzione bastano, ma servono più periodi confrontabili per "
        "valutare "
        "se la dipendenza dalle OTA è anomala. Si risolve da solo, un'analisi alla volta.",
        copy("Storico ancora insufficiente"),
        copy("Periodi confrontabili disponibili"),
        details=(
            "Non c'è nulla da correggere nei dati: mancano solo i periodi passati con cui "
            "confrontare.",
        ),
        where="Dati > Distribuzione",
        related=("state.distribution_insufficient", "decision.ota_dependency"),
        keywords=("storico insufficiente", "periodi confrontabili", "troppo presto"),
    ),
    entry(
        "state.channel_mix_conflict",
        STATE,
        "Composizione dei canali non coerente",
        "Quando i canali non coincidono con le prenotazioni registrate, NINFA spiega quante "
        "prenotazioni "
        "hanno date incoerenti con oggi: prenotate dopo oggi, cancellate dopo oggi, oppure non "
        "presentate "
        "per soggiorni non ancora iniziati.",
        copy("Controlla queste prenotazioni nei dati importati."),
        copy("Composizione indicativa"),
        doc("docs/architecture/adr/0043-dati-cause-and-denominator.md"),
        details=(
            "La quota OTA non viene valutata finché le due letture dei dati non coincidono.",
            "Il controllo non viene allentato né presentato come un successo.",
        ),
        where="Dati > Distribuzione",
        related=("state.distribution_insufficient", "dati.channel_weights", "metric.ota_share"),
        keywords=(
            "date incoerenti",
            "composizione indicativa",
            "canali non coincidono",
            "prenotate dopo oggi",
        ),
    ),
    entry(
        "state.ota_changed_after_analysis",
        STATE,
        "Dati cambiati dopo l'analisi",
        "Se i dati di prenotazione sono cambiati dopo l'analisi di oggi, NINFA non mostra la quota "
        "OTA "
        "finché l'analisi non viene rifatta.",
        copy("NINFA non mostra la quota finché l'analisi non viene rifatta."),
        enum(f"{_OTA}.CHANGED_AFTER_ANALYSIS"),
        where="Dati > Distribuzione",
        related=("import.post_import_analysis", "metric.ota_share"),
        keywords=("quota ota non mostrata", "dati cambiati", "analisi da rifare"),
    ),
    entry(
        "state.cpor_not_computable",
        STATE,
        "Costo per camera occupata non calcolabile",
        "Il costo per camera occupata non si calcola quando manca una parte dei dati: occupazione "
        "non "
        "disponibile o incompleta, nessuna camera occupata, troppe spese non classificate, nessun "
        "costo.",
        copy("Occupazione del mese incompleta"),
        copy("Troppe spese non classificate"),
        enum(f"{_CPOR}.NO_COST_DATA"),
        details=(
            "Quando sa di più, la pagina dice quale giorno manca e perché (inventario, "
            "prenotazioni, date incerte, calcolo in attesa).",
        ),
        where="Dati > Costi",
        related=("dati.cpor_card", "metric.cpor", "workflow.set_inventory_valid_from"),
        keywords=(
            "costo per camera non disponibile",
            "cpor non calcolabile",
            "occupazione incompleta",
            "spese non classificate",
        ),
    ),
    entry(
        "state.labor_plan_partial",
        STATE,
        "Piano del personale parziale",
        "Quando il piano copre solo alcuni giorni dei 7, la pagina dice Piano disponibile per N "
        "giorni "
        "su 7: costo medio, incidenza e ricavo per ora riguardano solo quei giorni.",
        copy("Solo i giorni coperti dal piano"),
        copy("Piano disponibile per"),
        where="Dati > Personale",
        related=("dati.labor_coverage", "metric.labor_incidence"),
        keywords=("piano parziale", "pochi giorni", "giorni coperti", "incidenza su un giorno"),
    ),
    entry(
        "state.labor_revenue_gap",
        STATE,
        "Perché manca il confronto con i ricavi nel Personale",
        "Il confronto con i ricavi on-books si fa solo sugli stessi giorni: manca quando non ci "
        "sono "
        "ore pianificate, servono prenotazioni analizzate, o alcuni giorni del piano sono senza "
        "ore.",
        copy("Non ci sono ore pianificate da confrontare."),
        copy("Servono prenotazioni analizzate per gli stessi giorni."),
        where="Dati > Personale",
        related=("metric.labor_incidence", "dati.labor"),
        keywords=(
            "incidenza non disponibile",
            "ricavi non confrontabili",
            "perché non c'è l'incidenza",
        ),
    ),
    entry(
        "state.not_available",
        STATE,
        "Non disponibile",
        "Non disponibile significa che NINFA non ha i dati per quel valore. Mai zero: un valore "
        "mancante resta mancante, con la sua ragione quando c'è.",
        copy("Non disponibile"),
        copy("Dato non disponibile."),
        details=(
            "Le ragioni più comuni: l'analisi di oggi non è ancora disponibile, l'origine dei dati "
            "di prenotazione non è registrata, "
            "non ci sono prenotazioni nel periodo, quell'area non è stata analizzata, più origini "
            "dati.",
        ),
        where="In tutta l'interfaccia",
        related=("state.not_processed", "state.not_analyzed", "state.several_sources"),
        keywords=("non disponibile", "dato mancante", "perché non vedo il dato", "metrica assente"),
    ),
    entry(
        "state.last_import_unknown",
        STATE,
        "Ultimo import non disponibile",
        "Quando non c'è un import a cui riferirsi, la pagina dice Ultimo import prenotazioni non "
        "disponibile, oppure nessun import completato o più origini non confrontabili.",
        copy("Ultimo import prenotazioni non disponibile"),
        copy("nessun import completato"),
        where="Oggi e Dati",
        related=("dati.freshness", "state.several_sources"),
        keywords=("ultimo import", "import non disponibile", "nessun import"),
    ),
    entry(
        "state.stale_booking",
        STATE,
        "Nessun nuovo dato di prenotazione",
        "Un giorno in cui non sono arrivati nuovi dati di prenotazione viene analizzato, ma non "
        "conta "
        "come storia e non apre decisioni sui ricavi: il pickup non è noto, non è zero.",
        doc("docs/architecture/adr/0045-no-new-booking-data-is-not-zero-pickup.md"),
        enum("app.modules.intelligence.revenue.types:ReasonCode.BOOKING_DATA_STALE"),
        details=(
            "Un file ricaricato che non cambia nulla non fa un nuovo giorno di dati.",
            "Un file che cambia qualcosa conta come nuovo, anche se arriva nel pomeriggio.",
            "Per questo, senza nuovi dati di prenotazione, "
            "può non esserci alcuna decisione sui ricavi.",
        ),
        related=(
            "metric.pickup",
            "decision.pickup_low",
            "decision.occupancy_risk",
            "decision.daily_analysis",
        ),
        keywords=(
            "dati vecchi",
            "nessun nuovo dato",
            "prenotazioni ferme",
            "stale",
            "booking data stale",
        ),
    ),
    entry(
        "state.import_done",
        STATE,
        "Importazione completata",
        "Dopo un import riuscito la pagina dice Importazione completata con il tipo di dati, il "
        "contenuto e il periodo; se il file non cambia nulla, lo dice.",
        copy("Importazione completata"),
        api("POST", "/data-sources/imports"),
        where="Importa file",
        related=("import.no_op", "import.post_import_analysis"),
        keywords=("importazione completata", "import riuscito", "file importato"),
    ),
    entry(
        "state.import_failed",
        STATE,
        "Importazione non riuscita",
        "Quando un import non riesce, la pagina dice Importazione non riuscita e che non è stato "
        "importato nulla; in Importazioni recenti compare Non riuscita.",
        copy("Importazione non riuscita"),
        copy("Non è stato importato nulla."),
        where="Importa file",
        related=("import.problems", "import.row_checks", "import.recent"),
        keywords=("import non riuscito", "errore import", "file rifiutato"),
    ),
    entry(
        "state.mia_unavailable",
        STATE,
        "Mia non è disponibile",
        "Quando Mia non riesce a completare l'analisi dice che non è disponibile in questo "
        "momento; "
        "i "
        "dati di NINFA restano disponibili normalmente e si può riprovare.",
        copy("Mia non è disponibile in questo momento."),
        copy("Puoi riprovare manualmente."),
        where="Oggi e dettaglio di una decisione",
        related=("nav.mia", "state.mia_insufficient_context"),
        keywords=("mia non risponde", "mia non disponibile", "errore mia"),
    ),
    entry(
        "state.mia_insufficient_context",
        STATE,
        "Mia non ha abbastanza informazioni",
        "Mia dice che non ha abbastanza informazioni per rispondere con affidabilità quando i dati "
        "disponibili non coprono la domanda; suggerisce di riformularla o di aprire le decisioni "
        "di oggi.",
        copy(
            "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda."
        ),
        where="Oggi e dettaglio di una decisione",
        related=("nav.mia", "state.mia_unavailable"),
        keywords=("mia non sa", "informazioni insufficienti", "domanda senza risposta"),
    ),
    entry(
        "state.no_property",
        STATE,
        "Nessuna struttura disponibile",
        "Se l'account non è associato a nessuna struttura, la pagina dice Nessuna struttura "
        "disponibile. Se la struttura selezionata non c'è più, lo segnala.",
        copy("Nessuna struttura disponibile"),
        copy("La struttura selezionata non è più disponibile."),
        related=("nav.property_selector",),
        keywords=("nessuna struttura", "struttura non disponibile", "account senza struttura"),
    ),
    entry(
        "state.decision_not_found",
        STATE,
        "Decisione non disponibile",
        "Se si apre una decisione che non esiste per la struttura selezionata, la pagina dice "
        "Decisione non disponibile e riporta alle Decisioni.",
        copy("Decisione non disponibile"),
        copy("Torna alle Decisioni"),
        related=("nav.decision_detail", "nav.decisioni"),
        keywords=("decisione non trovata", "decisione non disponibile", "link decisione"),
    ),
)

__all__ = ["ENTRIES"]
