"""Struttura: the four numbered blocks, the data-source cards and what can be done with a source."""

from app.modules.ai.mia.knowledge.entries._build import (
    FEATURE,
    SUBSECTION,
    api,
    copy,
    doc,
    entry,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_STRUTTURA = "Barra laterale > Struttura"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "struttura.profile",
        SUBSECTION,
        "Struttura > 1. Profilo struttura",
        "Il primo blocco di Struttura: nome, tipologia, categoria, località, numero camere, fuso "
        "orario, "
        "valuta e stagionalità principale.",
        copy("struttura-profile"),
        copy("1. Profilo struttura"),
        details=(
            "Oggi la pagina mostra con certezza solo il nome della struttura e il fuso orario "
            "(Timezone).",
            "Gli altri campi risultano Non configurata o Non configurato: la pagina non mostra "
            "valori che non ha.",
            "Il Numero camere è lo stesso numero dell'inventario camere, quando questo è "
            "configurato.",
        ),
        where=f"{_STRUTTURA}, primo blocco",
        page="/struttura",
        query={"section": "struttura-profile"},
        related=("struttura.rooms", "struttura.edit_structure", "term.property"),
        keywords=("profilo", "nome struttura", "fuso orario", "timezone", "valuta", "località"),
        not_available=(
            "Il pulsante Modifica struttura è presente ma non è ancora collegato a una modifica: "
            "tipologia, categoria, località, valuta e stagionalità non si possono ancora impostare "
            "dall'interfaccia.",
        ),
    ),
    entry(
        "struttura.rooms",
        SUBSECTION,
        "Struttura > 2. Inventario camere",
        "Il secondo blocco: quante camere può vendere la struttura. È il numero su cui NINFA "
        "calcola "
        "l'occupazione.",
        copy("struttura-rooms"),
        copy("2. Inventario camere"),
        api("GET", "/room-inventory"),
        api("PUT", "/room-inventory"),
        details=(
            "Si configura o si modifica con Configura inventario / Modifica inventario: un numero "
            "intero di camere.",
            "Il numero vale per tutte le notti dalla data scelta in poi; le analisi già fatte non "
            "cambiano.",
            "Dopo il salvataggio NINFA aggiorna da sola l'occupazione (Occupazione aggiornata).",
            "Se il numero varia nei prossimi mesi, la pagina lo dice e mostra quello della prima "
            "notte.",
        ),
        where=f"{_STRUTTURA}, secondo blocco (Inventario camere)",
        page="/struttura",
        query={"section": "struttura-rooms"},
        related=(
            "workflow.change_room_count",
            "struttura.inventory_valid_from",
            "state.inventory_missing",
            "metric.rooms_available",
        ),
        keywords=(
            "inventario",
            "camere",
            "numero camere",
            "camere disponibili",
            "capacità",
            "quante camere",
            "configura inventario",
        ),
        not_available=(
            "L'inventario è un solo numero di camere vendibili: non gestisce tipologie di camera "
            "né numeri diversi per stagione.",
        ),
    ),
    entry(
        "struttura.inventory_valid_from",
        FEATURE,
        "Inventario: Valido dal",
        "Nel modulo dell'inventario, Valido dal dice da quale giorno il numero di camere è vero. "
        "Di "
        "default è oggi; si può scegliere un giorno passato, mai uno futuro.",
        copy("Valido dal"),
        details=(
            "Con un giorno passato NINFA fa una nuova analisi con questo inventario, anche per i "
            "giorni già passati.",
            "Serve quando la struttura aveva già queste camere prima della data in cui si è "
            "configurato l'inventario.",
            "Un giorno futuro o troppo lontano nel passato viene rifiutato, e la pagina indica i "
            "limiti.",
        ),
        where="Struttura > Inventario camere > Configura inventario o Modifica inventario",
        related=("struttura.rooms", "workflow.set_inventory_valid_from", "dati.cpor_card"),
        keywords=("valido dal", "data inventario", "inventario passato", "da quando"),
    ),
    entry(
        "struttura.parameters",
        SUBSECTION,
        "Struttura > 3. Parametri operativi",
        "Il terzo blocco: periodo di apertura, stagionalità, alta stagione e capacità operativa "
        "massima.",
        copy("struttura-parameters"),
        copy("3. Parametri operativi"),
        details=(
            "Mostra Aperto tutto l'anno oppure Apertura stagionale, e la capacità massima in "
            "ospiti.",
        ),
        where=f"{_STRUTTURA}, terzo blocco",
        page="/struttura",
        query={"section": "struttura-parameters"},
        related=("struttura.profile",),
        keywords=("parametri", "apertura", "stagionalità", "alta stagione", "chiusura annuale"),
        not_available=(
            "Il pulsante Modifica parametri è presente ma non è ancora collegato: oggi i valori "
            "risultano Non configurati.",
        ),
    ),
    entry(
        "struttura.sources",
        SUBSECTION,
        "Struttura > 4. Fonti dati",
        "Il quarto blocco: i sistemi da cui NINFA riceve i dati della struttura, in cinque schede "
        "(PMS, Channel Manager, OTA, Contabilità, Personale).",
        copy("struttura-sources"),
        copy("4. Fonti dati"),
        api("GET", "/data-sources"),
        details=(
            "Ogni scheda dice se la fonte è Non configurata, Configurata, Connessa o Già ricevuta, "
            "e quando è stato l'ultimo aggiornamento.",
            "Oggi l'unico modo di portare dati in NINFA è importare un file: i collegamenti "
            "automatici sono Prossimamente.",
            "Dalle schede si apre Gestisci per vedere la configurazione dell'import e le risposte "
            "ricordate.",
        ),
        where=f"{_STRUTTURA}, quarto blocco",
        page="/struttura",
        query={"section": "struttura-sources"},
        related=(
            "struttura.source_cards",
            "struttura.manage_source",
            "struttura.automatic_integrations",
            "dati.data_origin",
        ),
        keywords=("fonti", "fonti dati", "sorgenti", "pms", "channel manager", "collega fonte"),
    ),
    entry(
        "struttura.edit_structure",
        FEATURE,
        "Modifica struttura",
        "Il pulsante in alto nella pagina Struttura. Al momento non apre nessuna modifica.",
        copy("Modifica struttura"),
        where=f"{_STRUTTURA}, in alto a destra",
        related=("struttura.profile", "struttura.parameters"),
        keywords=("modifica struttura", "modificare profilo", "cambiare nome"),
        not_available=(
            "Non è ancora collegato: il profilo e i parametri non si modificano dall'interfaccia. "
            "L'unica configurazione modificabile in Struttura è l'inventario camere.",
        ),
    ),
    entry(
        "struttura.source_cards",
        FEATURE,
        "Le schede delle fonti",
        "Le cinque schede di Fonti dati: PMS, Channel Manager, OTA, Contabilità e Personale.",
        copy("Collega fonte"),
        copy("Channel Manager"),
        details=(
            "PMS e Channel Manager sono le fonti delle prenotazioni.",
            "OTA non si collega da sola: i canali (Booking.com, Expedia e altri) arrivano insieme "
            "alle prenotazioni.",
            "Contabilità è la fonte dei costi; Personale è la fonte di ore e costi del personale.",
            "Una fonte da file risulta Configurata solo dopo che un import è andato a buon fine.",
        ),
        where=f"{_STRUTTURA} > Fonti dati",
        related=("struttura.sources", "struttura.connect_wizard", "struttura.source_states"),
        keywords=("pms", "channel manager", "ota", "contabilità", "personale", "schede"),
        not_available=(
            "NINFA non si collega direttamente a PMS, Channel Manager o portali: usa i file.",
        ),
    ),
    entry(
        "struttura.source_states",
        FEATURE,
        "Stato di una fonte",
        "Una scheda può essere Non configurato, Configurato, Connesso o Già ricevuto, con l'Ultimo "
        "aggiornamento (oggi, ieri o una data).",
        copy("Non configurato"),
        copy("Già ricevuto"),
        copy("Mai importato"),
        details=(
            "Già ricevuto vale per i canali, che arrivano con le prenotazioni.",
            "Mai importato significa che la fonte non ha ancora consegnato un file valido.",
            "Più fonti configurate per gli stessi dati: NINFA non ne sceglie una da sola.",
        ),
        where=f"{_STRUTTURA} > Fonti dati",
        related=("struttura.source_cards", "state.several_sources"),
        keywords=("stato fonte", "configurato", "non configurato", "ultimo aggiornamento"),
        not_available=(
            "NINFA non giudica se una fonte è vecchia: dice solo quando è stata aggiornata.",
        ),
    ),
    entry(
        "struttura.connect_wizard",
        FEATURE,
        "Collegare una nuova fonte",
        "Il percorso Collega una nuova fonte chiede quali dati collegare (prenotazioni, "
        "distribuzione, "
        "costi, personale) e come fornirli.",
        copy("Collega una nuova fonte"),
        copy("Quali dati vuoi collegare a NINFA?"),
        details=(
            "La distribuzione non va collegata a parte: i canali arrivano con le prenotazioni.",
            "Se esiste già una fonte per quei dati, si può caricare un nuovo file per aggiornarli.",
        ),
        where=f"{_STRUTTURA} > Fonti dati > Collega una nuova fonte",
        related=("struttura.sources", "workflow.import_file"),
        keywords=("collegare fonte", "nuova fonte", "aggiungere fonte"),
    ),
    entry(
        "struttura.manage_source",
        FEATURE,
        "Gestisci una fonte",
        "Gestisci apre le impostazioni di una fonte: come arrivano i dati, la Configurazione "
        "import, le "
        "Risposte ricordate e Rimuovi fonte.",
        copy("Gestisci"),
        api("GET", "/data-sources/{data_source_id}/import-configuration"),
        where=f"{_STRUTTURA} > Fonti dati > Gestisci",
        related=(
            "struttura.import_configuration",
            "struttura.remembered_answers",
            "struttura.remove_source",
        ),
        keywords=("gestisci", "gestire fonte", "impostazioni fonte"),
    ),
    entry(
        "struttura.import_configuration",
        FEATURE,
        "Configurazione import",
        "Come NINFA legge i file di una fonte: quale colonna significa cosa, e i valori fissi. Si "
        "può "
        "modificare con Modifica associazioni o far dimenticare con Dimentica configurazione.",
        copy("Configurazione import"),
        copy("Dimentica configurazione"),
        api("DELETE", "/data-sources/{data_source_id}/import-configuration"),
        details=(
            "Dimenticare la configurazione non cancella i dati già importati: al prossimo file "
            "NINFA chiede di nuovo gli abbinamenti.",
            "Se la configurazione è stata salvata con regole di NINFA diverse, al prossimo file "
            "conviene controllare le colonne.",
        ),
        where=f"{_STRUTTURA} > Fonti dati > Gestisci > Configurazione import",
        related=(
            "workflow.forget_import_configuration",
            "import.recognized_format",
            "import.manual_matching",
        ),
        keywords=(
            "configurazione",
            "associazioni",
            "abbinamenti salvati",
            "dimentica configurazione",
        ),
    ),
    entry(
        "struttura.remembered_answers",
        FEATURE,
        "Risposte ricordate",
        "Quello che NINFA ha imparato dalle risposte della persona e usa per i prossimi file di "
        "una "
        "fonte: parole, formati, scope del file, colonne abbinate. Si possono correggere o far "
        "dimenticare.",
        copy("Risposte ricordate"),
        api("GET", "/data-sources/{data_source_id}/remembered-answers"),
        api("PUT", "/data-sources/{data_source_id}/remembered-answers/{answer_id}"),
        api("DELETE", "/data-sources/{data_source_id}/remembered-answers/{answer_id}"),
        details=(
            "Una parola ricordata ha la forma Stato, Canale, Reparto o Categoria con il suo "
            "significato.",
            "Si ricordano anche come sono scritte le date, i decimali, se gli importi sono al "
            "netto di IVA e se il file contiene tutto il periodo.",
            "Correggi vale dal prossimo file; Dimentica fa in modo che NINFA lo chieda di nuovo se "
            "serve.",
            "I dati già importati non cambiano: per correggere anche quelli si ricarica il file.",
        ),
        where=f"{_STRUTTURA} > Fonti dati > Gestisci > Risposte ricordate",
        related=(
            "workflow.correct_remembered_answer",
            "workflow.forget_remembered_answer",
            "import.source_learning",
        ),
        keywords=(
            "risposte ricordate",
            "memoria",
            "ricorda",
            "corregge risposta",
            "parole insegnate",
        ),
    ),
    entry(
        "struttura.remove_source",
        FEATURE,
        "Rimuovere una fonte",
        "Rimuovi fonte spegne la fonte: NINFA non riceverà più nuovi dati da lì. I dati già "
        "importati "
        "restano in NINFA.",
        copy("Rimuovere questa fonte?"),
        api("DELETE", "/data-sources/{data_source_id}"),
        where=f"{_STRUTTURA} > Fonti dati > Gestisci o menu della scheda",
        related=("workflow.remove_source", "struttura.manage_source"),
        keywords=("rimuovi fonte", "elimina fonte", "cancella fonte", "spegni fonte"),
        not_available=("Rimuovere una fonte non cancella i dati già importati.",),
    ),
    entry(
        "struttura.invoice_xml",
        FEATURE,
        "Importare fatture XML",
        "Le fatture elettroniche in formato XML si importano dalla scheda Contabilità di Struttura "
        "> "
        "Fonti dati con Importa fatture XML, non dalla pagina Importa file.",
        copy("Importa fatture XML"),
        copy("Fatture elettroniche"),
        where=f"{_STRUTTURA} > Fonti dati > Contabilità",
        related=("import.invoice_xml", "nav.importa_file"),
        keywords=("fattura elettronica", "xml", "fatturapa", "fatture"),
    ),
    entry(
        "struttura.automatic_integrations",
        FEATURE,
        "Integrazioni automatiche",
        "Il collegamento diretto con i software della struttura (PMS, Channel Manager, portali) "
        "non "
        "è "
        "ancora disponibile: è indicato come Prossimamente.",
        copy("Integrazioni automatiche"),
        copy("Prossimamente"),
        where=f"{_STRUTTURA} > Fonti dati",
        related=("struttura.sources", "nav.importa_file"),
        keywords=(
            "integrazione",
            "api",
            "collegamento automatico",
            "prossimamente",
            "connessione diretta",
        ),
        not_available=(
            "Non esiste ancora nessuna integrazione automatica: i dati entrano con i file.",
        ),
    ),
    entry(
        "struttura.template_csv",
        FEATURE,
        "Modello CSV",
        "Per ogni tipo di dati NINFA offre un modello CSV scaricabile con le colonne che il file "
        "deve avere (Scarica modello CSV).",
        copy("Scarica modello CSV"),
        api("GET", "/data-sources/templates/{domain}"),
        where="Nel flusso di importazione dalle fonti dati",
        related=("import.formats", "workflow.download_template"),
        keywords=("modello", "template", "csv", "colonne richieste", "scarica modello"),
        not_available=(
            "Il modello non è obbligatorio: NINFA riconosce anche il file che la struttura ha già.",
        ),
    ),
    entry(
        "struttura.purpose",
        FEATURE,
        "A cosa serve Struttura",
        "Struttura descrive la struttura e i sistemi collegati; non giudica la qualità dei dati: "
        "questo lo fa Dati.",
        doc("docs/architecture/struttura-ui-v1.md"),
        where=_STRUTTURA,
        related=("nav.struttura", "nav.dati"),
        keywords=("a cosa serve struttura",),
    ),
)

__all__ = ["ENTRIES"]
