"""Workflows: how to do the things people actually ask, step by step, on screens that exist."""

from app.modules.ai.mia.knowledge.entries._build import WORKFLOW, api, copy, doc, entry
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "workflow.change_room_count",
        WORKFLOW,
        "Come cambiare il numero di camere",
        "Il numero di camere vendibili si imposta in Struttura, nel blocco Inventario camere, con "
        "Configura inventario (se non c'è ancora) o Modifica inventario.",
        copy("Modifica inventario"),
        copy("Configura inventario"),
        api("PUT", "/room-inventory"),
        details=(
            "1. Apri Struttura dalla barra laterale.",
            "2. Nel blocco 2. Inventario camere scegli Modifica inventario (o Configura "
            "inventario).",
            "3. Scrivi il numero di camere disponibili, un numero intero, e scegli da quando vale "
            "(Valido dal).",
            "4. Premi Salva: NINFA aggiorna da sola l'occupazione.",
            "Da Dati, il collegamento Configura inventario porta direttamente a quel blocco.",
        ),
        where="Struttura > Inventario camere",
        related=("struttura.rooms", "struttura.inventory_valid_from", "state.inventory_missing"),
        keywords=(
            "cambiare numero camere",
            "modificare camere",
            "inventario",
            "come cambio il numero di camere",
            "numero di camere",
            "aggiungere camere",
        ),
        not_available=(
            "Non si possono impostare tipologie di camera né numeri diversi per stagione.",
        ),
    ),
    entry(
        "workflow.set_inventory_valid_from",
        WORKFLOW,
        "Come far valere l'inventario dal passato",
        "Nel modulo dell'inventario, Valido dal accetta anche un giorno passato: serve quando la "
        "struttura aveva già quelle camere, e permette a NINFA di ricostruire le camere occupate "
        "dei giorni passati.",
        copy("Valido dal"),
        api("PUT", "/room-inventory"),
        details=(
            "1. Struttura > Inventario camere > Configura inventario o Modifica inventario.",
            "2. Scrivi il numero di camere e imposta Valido dal sul primo giorno in cui era vero.",
            "3. Salva: NINFA farà una nuova analisi con questo inventario, anche per i giorni già "
            "passati.",
            "Un giorno futuro non è accettato.",
        ),
        where="Struttura > Inventario camere",
        related=("struttura.inventory_valid_from", "dati.cpor_card", "term.reconstructed"),
        keywords=(
            "inventario passato",
            "costo per camera mese scorso",
            "valido dal",
            "ricostruire camere occupate",
        ),
    ),
    entry(
        "workflow.check_over_capacity",
        WORKFLOW,
        "Come controllare prenotazioni sopra l'inventario",
        "Quando Dati dice Prenotazioni superiori all'inventario, il collegamento Controlla "
        "inventario "
        "porta al blocco Inventario camere di Struttura, dove si verifica il numero di camere.",
        copy("Controlla inventario"),
        details=(
            "Le cause possibili sono un inventario troppo basso, un vero overbooking o una "
            "prenotazione sbagliata.",
            "Per la prenotazione sbagliata si controllano i dati importati.",
        ),
        where="Dati > Panoramica > Controlla inventario",
        related=("state.over_capacity", "struttura.rooms"),
        keywords=("overbooking", "sopra 100", "controllare inventario"),
    ),
    entry(
        "workflow.import_file",
        WORKFLOW,
        "Come importare un file",
        "Si apre Importa file dalla barra laterale, si trascina il file (CSV o Excel) o lo si "
        "sceglie "
        "dal computer, si risponde alle poche domande eventuali e si preme Importa dati.",
        copy("Trascina qui il tuo file"),
        copy("Selezionalo dal computer"),
        api("POST", "/data-sources/imports"),
        details=(
            "1. Barra laterale > Importa file.",
            "2. Trascina il file o scegli Selezionalo dal computer (un file alla volta).",
            "3. Aspetta la lettura e il controllo delle righe.",
            "4. Se NINFA fa domande, rispondi; se serve, abbina le colonne.",
            "5. Controlla File riconosciuto e premi Importa dati.",
            "Dopo l'importazione l'analisi si aggiorna da sola.",
        ),
        where="Barra laterale > Importa file",
        related=("import.flow", "import.formats", "nav.importa_file"),
        keywords=(
            "come importo",
            "caricare file",
            "upload",
            "importare dati",
            "carica prenotazioni",
        ),
    ),
    entry(
        "workflow.import_costs",
        WORKFLOW,
        "Come importare i costi",
        "I costi si importano da Importa file con un registro dei costi in CSV o Excel, oppure da "
        "Struttura > Fonti dati > Contabilità con le fatture elettroniche XML.",
        copy("Registro dei costi"),
        copy("Importa fatture XML"),
        details=(
            "NINFA lavora con gli importi al netto di IVA: se il file non lo dice, lo chiede.",
            "Le categorie dei costi si riconoscono dalle parole del file; quelle sconosciute si "
            "chiedono.",
        ),
        where="Importa file (CSV o Excel) o Struttura > Fonti dati > Contabilità (XML)",
        related=("import.costs_file", "import.invoice_xml", "import.question_amount_basis"),
        keywords=("importare costi", "caricare fatture", "registro costi", "costi"),
    ),
    entry(
        "workflow.import_labor",
        WORKFLOW,
        "Come importare il personale",
        "Le ore e i costi del personale si importano da Importa file con un file CSV o Excel con "
        "il dettaglio giorno per giorno.",
        copy(
            "Ore, reparti e costi del personale: usa il file che hai già, in formato CSV o Excel "
            "(.xlsx)."
        ),
        details=(
            "Servono le ore di ogni giorno: un riepilogo settimanale non basta.",
            "NINFA conta le persone ma non salva i nomi.",
        ),
        where="Importa file",
        related=("import.labor_file", "import.blocker_period_summary_only"),
        keywords=("importare personale", "caricare turni", "ore personale", "piano personale"),
    ),
    entry(
        "workflow.fix_blocked_import",
        WORKFLOW,
        "Cosa fare se un file non si importa",
        "Si legge il messaggio che NINFA mostra (dice che non è stato importato nulla e perché), "
        "si "
        "corregge il file e lo si carica di nuovo.",
        copy("Questo file non può essere importato così com'è"),
        copy("Non è stato importato nulla."),
        details=(
            "Una riga non valida blocca l'importazione di tutto il file: le prime righe da "
            "controllare sono elencate.",
            "Per un file illeggibile si controlla che sia CSV in formato UTF-8 o Excel (.xlsx).",
            "Se NINFA non è sicura delle colonne, si possono abbinare a mano.",
        ),
        where="Importa file",
        related=(
            "import.level_blocked",
            "import.row_checks",
            "import.problems",
            "import.manual_matching",
        ),
        keywords=(
            "file non si importa",
            "errore importazione",
            "come correggo il file",
            "righe non valide",
        ),
    ),
    entry(
        "workflow.review_column_matching",
        WORKFLOW,
        "Come rivedere gli abbinamenti delle colonne",
        "Da Struttura > Fonti dati > Gestisci > Configurazione import, Modifica associazioni apre "
        "Importa file per rivedere come NINFA legge le colonne di quella fonte.",
        copy("Modifica associazioni"),
        copy("Controlla colonne"),
        details=(
            "Durante un'importazione normale si può usare Controlla colonne per rivedere gli "
            "abbinamenti proposti.",
        ),
        where="Struttura > Fonti dati > Gestisci > Configurazione import",
        related=("struttura.import_configuration", "import.manual_matching"),
        keywords=(
            "rivedere abbinamenti",
            "cambiare colonne",
            "colonna sbagliata",
            "modifica associazioni",
        ),
    ),
    entry(
        "workflow.correct_remembered_answer",
        WORKFLOW,
        "Come correggere una risposta ricordata",
        "In Struttura > Fonti dati > Gestisci > Risposte ricordate, accanto alla risposta "
        "sbagliata "
        "si "
        "sceglie Correggi, si indica il significato giusto e si preme Salva correzione.",
        copy("Correggi"),
        copy("Salva correzione"),
        api("PUT", "/data-sources/{data_source_id}/remembered-answers/{answer_id}"),
        details=(
            "La correzione vale dal prossimo file.",
            "I dati già importati non cambiano: per correggere anche quelli si ricarica il file.",
        ),
        where="Struttura > Fonti dati > Gestisci > Risposte ricordate",
        related=("struttura.remembered_answers", "workflow.forget_remembered_answer"),
        keywords=("correggere risposta", "risposta sbagliata", "cambiare parola", "correggi"),
    ),
    entry(
        "workflow.forget_remembered_answer",
        WORKFLOW,
        "Come far dimenticare una risposta",
        "In Risposte ricordate si sceglie Dimentica accanto alla risposta: al prossimo file NINFA "
        "la "
        "chiederà di nuovo, se ne ha bisogno.",
        copy("Dimentica"),
        copy("Dimentica questa risposta"),
        api("DELETE", "/data-sources/{data_source_id}/remembered-answers/{answer_id}"),
        where="Struttura > Fonti dati > Gestisci > Risposte ricordate",
        related=("struttura.remembered_answers", "workflow.correct_remembered_answer"),
        keywords=("dimenticare risposta", "cancellare risposta ricordata", "dimentica"),
        not_available=("Dimenticare una risposta non cambia i dati già importati.",),
    ),
    entry(
        "workflow.forget_import_configuration",
        WORKFLOW,
        "Come far dimenticare la configurazione di una fonte",
        "In Gestisci > Configurazione import si sceglie Dimentica configurazione: NINFA non "
        "riconoscerà "
        "più il formato dei file e chiederà di nuovo gli abbinamenti. I dati già importati "
        "restano.",
        copy("Dimentica configurazione"),
        copy("Dimenticare la configurazione?"),
        api("DELETE", "/data-sources/{data_source_id}/import-configuration"),
        where="Struttura > Fonti dati > Gestisci > Configurazione import",
        related=("struttura.import_configuration",),
        keywords=("dimenticare configurazione", "azzerare configurazione", "reimpostare colonne"),
    ),
    entry(
        "workflow.remove_source",
        WORKFLOW,
        "Come rimuovere una fonte",
        "In Struttura > Fonti dati, dal menu della scheda o da Gestisci, si sceglie Rimuovi fonte "
        "e "
        "si "
        "conferma: NINFA non riceverà più dati da lì, i dati già importati restano.",
        copy("Rimuovi fonte"),
        api("DELETE", "/data-sources/{data_source_id}"),
        where="Struttura > Fonti dati > Gestisci > Rimuovi fonte",
        related=("struttura.remove_source", "struttura.manage_source"),
        keywords=("rimuovere fonte", "eliminare fonte", "togliere fonte"),
    ),
    entry(
        "workflow.configure_data_source",
        WORKFLOW,
        "Come collegare una fonte dati",
        "In Struttura > Fonti dati si sceglie Collega fonte (o Collega una nuova fonte), si indica "
        "quali dati e come fornirli: oggi il modo è importare un file.",
        copy("Collega una nuova fonte"),
        copy("Collega fonte"),
        where="Struttura > Fonti dati",
        related=(
            "struttura.connect_wizard",
            "struttura.automatic_integrations",
            "workflow.import_file",
        ),
        keywords=(
            "collegare fonte",
            "aggiungere fonte",
            "collegare pms",
            "collegare channel manager",
        ),
        not_available=(
            "Non esistono ancora collegamenti automatici con PMS, Channel Manager o portali.",
        ),
    ),
    entry(
        "workflow.download_template",
        WORKFLOW,
        "Come scaricare un modello di file",
        "Nel flusso di importazione dalle fonti dati si può scaricare un modello CSV con le "
        "colonne "
        "che NINFA si aspetta (Scarica modello CSV).",
        copy("Scarica modello CSV"),
        api("GET", "/data-sources/templates/{domain}"),
        where="Struttura > Fonti dati, nel flusso di importazione",
        related=("struttura.template_csv",),
        keywords=("modello csv", "template", "scaricare modello", "colonne giuste"),
    ),
    entry(
        "workflow.find_import_history",
        WORKFLOW,
        "Come vedere i file importati",
        "In fondo alla pagina Importa file l'elenco Importazioni recenti mostra i file importati "
        "con "
        "tipo, data e stato.",
        copy("Importazioni recenti"),
        api("GET", "/data-sources/imports"),
        where="Importa file > Importazioni recenti",
        related=("import.recent",),
        keywords=(
            "storico importazioni",
            "ultimo file importato",
            "quando ho importato",
            "file che ho importato",
            "vedere i file importati",
            "importazioni passate",
        ),
    ),
    entry(
        "workflow.second_file_same_day",
        WORKFLOW,
        "Come aggiornare i dati con un secondo file",
        "Basta importare di nuovo il file aggiornato da Importa file: nulla di già salvato viene "
        "riscritto e, se serve, NINFA chiede se il file contiene tutto il periodo o solo una "
        "parte.",
        copy("Importa un altro file"),
        doc("docs/architecture/same-day-revisions-v1.md"),
        details=(
            "Se il file non cambia nulla, NINFA lo dice e non rifà l'analisi.",
            "Se cambia qualcosa, l'analisi si aggiorna anche lo stesso giorno.",
        ),
        where="Importa file",
        related=("import.same_day_revision", "import.scope", "import.no_op"),
        keywords=(
            "aggiornare dati",
            "file corretto",
            "reimportare",
            "secondo file",
            "nuovo export",
        ),
    ),
    entry(
        "workflow.refresh_analysis",
        WORKFLOW,
        "Come aggiornare l'analisi",
        "Di solito non serve: l'analisi parte da sola ogni giorno e dopo ogni import che cambia "
        "qualcosa. Avvia analisi (o Riprova) in Oggi la richiede quando è possibile; Aggiorna "
        "analisi "
        "e Aggiorna dati rileggono soltanto ciò che c'è già.",
        copy("Avvia analisi"),
        copy("Aggiorna analisi"),
        api("POST", "/analysis/refresh"),
        where="Oggi (Avvia analisi, Aggiorna analisi) e Dati (Aggiorna dati)",
        related=("import.post_import_analysis", "decision.daily_analysis", "dati.refresh"),
        keywords=(
            "aggiornare analisi",
            "rifare analisi",
            "ricalcolare",
            "avviare analisi",
            "aggiorna",
        ),
    ),
    entry(
        "workflow.see_decision_detail",
        WORKFLOW,
        "Come aprire il dettaglio di una decisione",
        "Da Decisioni si sceglie Apri dettaglio sulla riga; da Dati, dove una notte o una "
        "categoria "
        "ha una decisione, il collegamento Apri la decisione porta alla stessa pagina.",
        copy("Apri dettaglio"),
        copy("Apri la decisione"),
        where="Decisioni > Apri dettaglio; Dati > Apri la decisione",
        related=("nav.decision_detail", "nav.decisioni"),
        keywords=("dettaglio decisione", "aprire decisione", "perché questa decisione"),
    ),
    entry(
        "workflow.why_no_decisions",
        WORKFLOW,
        "Perché oggi non vedo decisioni",
        "Si guarda il messaggio in Oggi: Tutto sotto controllo (nulla rilevato), Nessuna decisione "
        "affidabile oggi (nulla di affidabile da segnalare) oppure Analisi non ancora disponibile.",
        copy("Nessuna decisione affidabile oggi"),
        copy("Tutto sotto controllo"),
        copy("Analisi non ancora disponibile"),
        details=(
            "In Dati, Copertura dell'analisi dice quali aree sono state analizzate.",
            "Il riepilogo per area dice se un'area è analizzata, parziale o non analizzata.",
            "Se i dati sono fermi, controlla Ultimo import prenotazioni.",
        ),
        where="Oggi",
        related=(
            "decision.feed_states",
            "state.no_reliable_decision",
            "state.all_under_control",
            "state.not_processed",
        ),
        keywords=(
            "perché non ho decisioni",
            "nessuna decisione oggi",
            "oggi vuoto",
            "manca la decisione",
        ),
    ),
    entry(
        "workflow.change_dati_period",
        WORKFLOW,
        "Come cambiare il periodo in Dati",
        "In Dati, nelle schede Panoramica e Prenotazioni, il selettore Periodo permette di "
        "scegliere "
        "7 giorni o 30 giorni.",
        copy("Periodo"),
        where="Dati > Panoramica o Prenotazioni, in alto a destra",
        related=("dati.period_control",),
        keywords=("cambiare periodo", "7 giorni", "30 giorni", "settimana", "mese"),
    ),
    entry(
        "workflow.switch_property",
        WORKFLOW,
        "Come cambiare struttura",
        "Con più strutture, si sceglie la struttura dal menu sul suo nome nell'intestazione della "
        "pagina.",
        copy("Struttura attiva"),
        where="Intestazione di ogni pagina",
        related=("nav.property_selector",),
        keywords=(
            "cambiare hotel",
            "altra struttura",
            "selezionare struttura",
            "cambio struttura",
            "cambiare struttura",
        ),
    ),
    entry(
        "workflow.ask_mia",
        WORKFLOW,
        "Come chiedere a Mia",
        "Dalla pagina Oggi si scrive la domanda in Chiedi a Mia... o si sceglie una domanda "
        "suggerita; "
        "nel dettaglio di una decisione c'è Chiedi a Mia per quella decisione.",
        copy("Domande suggerite"),
        copy("Chiedi a Mia..."),
        details=(
            "Nuova conversazione ricomincia da zero.",
            "Mia risponde sui dati che NINFA ha già analizzato e non esegue azioni.",
        ),
        where="Oggi e dettaglio di una decisione",
        related=("nav.mia", "state.mia_unavailable"),
        keywords=("chiedere a mia", "fare una domanda", "domande suggerite", "nuova conversazione"),
    ),
)

__all__ = ["ENTRIES"]
