"""Smart Import: how a file becomes data - the flow, the four outcomes, every question."""

from app.modules.ai.mia.knowledge.entries._build import (
    FEATURE,
    api,
    copy,
    doc,
    entry,
    enum,
)
from app.modules.ai.mia.knowledge.types import KnowledgeEntry

_IMPORT_PAGE = "Barra laterale > Importa file"
_QUESTION = "app.modules.data_sources.understanding_types:QuestionKind"
_BLOCKER = "app.modules.data_sources.understanding_types:BlockerCode"
_LEVEL = "app.modules.data_sources.understanding_types:UnderstandingLevel"
_SCOPE = "app.modules.ingestion.models:FileScope"

ENTRIES: tuple[KnowledgeEntry, ...] = (
    entry(
        "import.flow",
        FEATURE,
        "Come funziona l'importazione di un file",
        "Si sceglie il file; NINFA lo legge, capisce che cosa contiene, controlla tutte le righe, "
        "fa "
        "al massimo poche domande e importa solo dopo la conferma (Importa dati).",
        copy("Sto leggendo il file…"),
        copy("Sto controllando tutte le righe…"),
        api("POST", "/data-sources/import-understanding"),
        api("POST", "/data-sources/import-validation"),
        api("POST", "/data-sources/imports"),
        details=(
            "Prima legge e riconosce il file, poi verifica tutte le righe: nulla è scritto finché "
            "non si preme Importa dati.",
            "Se NINFA è sicura di tutto, mostra File riconosciuto e un solo pulsante.",
            "Se resta qualcosa di poco chiaro, fa una domanda alla volta.",
            "Se non è abbastanza sicura, propone di abbinare le colonne a mano; se il file non può "
            "essere importato, dice perché e che non è stato importato nulla.",
            "Quando l'importazione riesce, l'analisi si aggiorna da sola.",
        ),
        where=f"{_IMPORT_PAGE}",
        related=(
            "import.level_ready",
            "import.level_ask",
            "import.level_manual",
            "import.level_blocked",
            "import.post_import_analysis",
        ),
        keywords=(
            "importare",
            "come importo",
            "come funziona smart import",
            "smart import",
            "import",
            "caricare un file",
        ),
    ),
    entry(
        "import.formats",
        FEATURE,
        "Che file si possono importare",
        "Dalla pagina Importa file si importano file CSV (in formato UTF-8) ed Excel (.xlsx), uno "
        "alla "
        "volta, entro la dimensione massima indicata dalla pagina.",
        copy("CSV o Excel (.xlsx)"),
        api("GET", "/data-sources/import-limits"),
        details=(
            "I tipi di dati sono tre: prenotazioni, personale (ore e costi) e costi (registro dei "
            "costi).",
            "Un file Excel con più fogli di dati chiede quale foglio importare.",
            "Le fatture elettroniche XML non passano da qui: si importano da Struttura > Fonti "
            "dati.",
            "Un altro formato di file viene rifiutato con un messaggio che dice di scegliere CSV o "
            "Excel.",
        ),
        where=_IMPORT_PAGE,
        related=("nav.importa_file", "import.invoice_xml", "import.kinds"),
        keywords=(
            "formato",
            "csv",
            "xlsx",
            "excel",
            "pdf",
            "che file",
            "quali file",
            "estensione",
            "dimensione",
        ),
        not_available=("Non si importano file PDF, immagini o documenti di testo.",),
    ),
    entry(
        "import.kinds",
        FEATURE,
        "I tipi di dati importabili",
        "NINFA importa tre tipi di dati: prenotazioni, personale (ore e costi per reparto e "
        "giorno) "
        "e "
        "costi (fatture e registro dei costi). Riconosce da sola di quale tipo è il file.",
        copy("NINFA ha riconosciuto un file di prenotazioni"),
        copy("NINFA ha riconosciuto un file del personale"),
        copy("NINFA ha riconosciuto un registro dei costi"),
        details=(
            "Se non riesce a capire il tipo, lo chiede: la persona sceglie tra prenotazioni, "
            "personale e costi.",
            "Prenotazioni: arrivo, partenza, stato, camere, importo della camera, canale e altri "
            "campi.",
            "Personale: data, reparto o mansione, ore previste o effettive, costo previsto o "
            "effettivo.",
            "Costi: fornitore, documento, date, imponibile, IVA, categoria di costo.",
        ),
        where=_IMPORT_PAGE,
        related=(
            "import.question_domain",
            "import.bookings_file",
            "import.labor_file",
            "import.costs_file",
        ),
        keywords=("tipo di dati", "prenotazioni", "personale", "costi", "cosa posso importare"),
    ),
    entry(
        "import.bookings_file",
        FEATURE,
        "File delle prenotazioni",
        "Il file delle prenotazioni ha una riga per prenotazione, con date di arrivo e partenza, "
        "stato, "
        "camere, importo della camera e canale. NINFA lo riconosce da sola.",
        copy(
            "Usa il file delle prenotazioni che hai già, in formato CSV o Excel (.xlsx): NINFA lo "
            "riconosce da sola."
        ),
        details=(
            "Gli stati riconosciuti sono Confermata, Cancellata, Non presentato, Arrivato e "
            "Partito.",
            "Se il file non dice quante camere ha ogni prenotazione, NINFA ne conta una per riga e "
            "lo dice.",
            "Il canale (Booking.com, Expedia, diretto...) è letto dalla stessa colonna delle "
            "prenotazioni.",
        ),
        where=_IMPORT_PAGE,
        related=("import.kinds", "term.booking_status", "import.assumed_rooms"),
        keywords=("file prenotazioni", "prenotazioni", "pms", "export prenotazioni"),
    ),
    entry(
        "import.labor_file",
        FEATURE,
        "File del personale",
        "Il file del personale riporta, per giorno e reparto o mansione, le ore previste o "
        "effettive e "
        "i costi. NINFA conta le persone ma non salva i nomi.",
        copy("NINFA conta le persone ma non ne salva i nomi."),
        details=(
            "Può essere un elenco di righe giornaliere o una tabella con i giorni della settimana "
            "in colonna.",
            "Un riepilogo settimanale senza il dettaglio giorno per giorno non si può importare.",
            "Una riga con un reparto che NINFA non riconosce viene importata come Altro e non "
            "conta nelle analisi sul personale.",
        ),
        where=_IMPORT_PAGE,
        related=(
            "import.kinds",
            "term.planned_worked_hours",
            "import.blocker_period_summary_only",
            "import.personal_data",
        ),
        keywords=("file personale", "turni", "ore", "reparti", "piano del personale"),
    ),
    entry(
        "import.costs_file",
        FEATURE,
        "File dei costi",
        "Il registro dei costi (CSV o Excel) ha una riga per voce di fattura. NINFA lavora con gli "
        "importi al netto di IVA.",
        copy(
            "Usa il registro dei costi che hai già, in formato CSV o Excel (.xlsx): NINFA lo "
            "riconosce da sola."
        ),
        details=(
            "Se un importo non dice se comprende l'IVA, NINFA lo chiede; se comprende l'IVA e non "
            "c'è l'imponibile, il file non si può importare.",
            "Ogni costo ha una categoria; una voce non riconosciuta finisce in Non classificato.",
            "Il documento è l'unità: una riga corretta di un foglio di calcolo diventa la "
            "revisione di quel documento.",
        ),
        where=_IMPORT_PAGE,
        related=(
            "import.kinds",
            "import.question_amount_basis",
            "term.cost_categories",
            "term.net_amount",
        ),
        keywords=("file costi", "registro costi", "fatture", "imponibile", "iva"),
    ),
    entry(
        "import.level_ready",
        FEATURE,
        "File riconosciuto (nessuna domanda)",
        "Quando NINFA è sicura di tutto ciò che le serve, mostra File riconosciuto con un "
        "riepilogo "
        "e "
        "un solo pulsante, Importa dati: non si abbinano colonne.",
        copy("File riconosciuto"),
        enum(f"{_LEVEL}.READY"),
        details=(
            "Il riepilogo dice che tipo di dati ha riconosciuto e quante righe, persone o reparti "
            "ha trovato.",
            "Controlla cosa ho riconosciuto mostra, campo per campo, cosa ha capito e da dove.",
            "Se il formato è lo stesso dell'ultima volta lo dice: non c'è nulla da controllare.",
        ),
        where=_IMPORT_PAGE,
        related=("import.flow", "import.level_ask", "import.recognized_format"),
        keywords=("file riconosciuto", "importa dati", "riepilogo", "riconosciuto"),
    ),
    entry(
        "import.level_ask",
        FEATURE,
        "Poche domande su un file",
        "Se NINFA ha capito quasi tutto, chiede le poche cose che non può stabilire da sola, una "
        "alla volta (Mi serve solo una conferma).",
        copy("Mi serve solo una conferma"),
        enum(f"{_LEVEL}.ASK"),
        details=(
            "Chiede solo ciò che cambia il risultato: il tipo di dati, una tabella, come sono "
            "scritte le date, un significato.",
            "Le risposte si ricordano per i prossimi file della stessa fonte.",
            "Si può sempre scegliere un altro file.",
        ),
        where=_IMPORT_PAGE,
        related=("import.question_domain", "import.source_learning", "import.level_ready"),
        keywords=(
            "domanda",
            "conferma",
            "mi serve una conferma",
            "perché mi chiede",
            "perché questo file mi chiede",
        ),
    ),
    entry(
        "import.level_manual",
        FEATURE,
        "Abbinare le colonne a mano",
        "Se NINFA non riesce a leggere il file con sicurezza, dice che non può importarlo da sola "
        "e "
        "propone di abbinare le colonne.",
        copy("Non posso importare questo file da sola"),
        copy("Abbina le colonne"),
        enum(f"{_LEVEL}.MANUAL"),
        where=_IMPORT_PAGE,
        related=("import.manual_matching", "import.level_ready"),
        keywords=("manuale", "abbina colonne", "non riesce a leggere", "file non riconosciuto"),
    ),
    entry(
        "import.level_blocked",
        FEATURE,
        "File che non si può importare",
        "Alcuni file non si possono importare così come sono. NINFA lo dice con una frase chiara e "
        "specifica che non è stato importato nulla.",
        copy("Questo file non può essere importato così com'è"),
        enum(f"{_LEVEL}.BLOCKED"),
        details=("Le cause possibili sono sette; ognuna ha il suo messaggio.",),
        where=_IMPORT_PAGE,
        related=(
            "import.blocker_no_table",
            "import.blocker_missing_required",
            "import.blocker_period_summary_only",
            "import.blocker_grid_not_supported",
            "import.blocker_grid_not_hours",
            "import.blocker_amount_not_net",
            "import.blocker_mixed_formats",
        ),
        keywords=(
            "file bloccato",
            "non può essere importato",
            "errore importazione",
            "importazione non riuscita",
        ),
    ),
    entry(
        "import.manual_matching",
        FEATURE,
        "Abbina le colonne del tuo file",
        "La schermata in cui la persona dice che cosa significa ogni colonna: per ognuna si "
        "sceglie "
        "un significato oppure Ignora questa colonna.",
        copy("Abbina le colonne del tuo file"),
        copy("Ignora questa colonna"),
        api("POST", "/data-sources/import-mapping-check"),
        details=(
            "Ogni colonna è Riconosciuto o Da verificare.",
            "Se il file non ha una colonna per un'informazione, si può indicare un valore fisso "
            "uguale per tutte le righe.",
            "NINFA elenca le informazioni necessarie ancora mancanti.",
            "Se le date o i numeri sono scritti in modo non univoco, chiede come leggerli.",
        ),
        where=f"{_IMPORT_PAGE}, quando serve (Abbina le colonne) o con Controlla colonne",
        related=("import.level_manual", "workflow.review_column_matching", "import.preview"),
        keywords=(
            "abbinamento",
            "colonne",
            "significato colonna",
            "ignora colonna",
            "valore fisso",
        ),
        not_available=(
            "Alcune colonne non si abbinano mai: i nomi delle persone, il costo orario, e-mail e "
            "telefoni, codici fiscali e coordinate bancarie non vengono importati.",
        ),
    ),
    entry(
        "import.recognized_format",
        FEATURE,
        "Formato già riconosciuto",
        "Se il file ha la struttura di uno già importato, NINFA dice Abbiamo riconosciuto il "
        "formato "
        "del tuo file e lo legge con le stesse colonne dell'ultima volta.",
        copy("Abbiamo riconosciuto il formato del tuo file"),
        copy("Importa con questa configurazione"),
        details=(
            "Se le colonne sono cambiate o NINFA ha aggiornato le sue regole, la configurazione "
            "salvata non viene applicata e va controllata.",
        ),
        where=_IMPORT_PAGE,
        related=("import.source_learning", "struttura.import_configuration"),
        keywords=("formato riconosciuto", "stesse colonne", "configurazione salvata"),
    ),
    entry(
        "import.preview",
        FEATURE,
        "Anteprima importazione",
        "Prima di importare, l'anteprima mostra quante righe sono valide e quante da verificare e "
        "le "
        "prime righe come NINFA le leggerà.",
        copy("Anteprima importazione"),
        api("POST", "/data-sources/import-preview"),
        details=(
            "NINFA importa un file solo se tutte le righe sono valide: se anche una non lo è, non "
            "viene importato nulla.",
            "Le prime righe da correggere sono elencate con il numero di riga e il motivo.",
            "Si può salvare la configurazione per riconoscere il file la prossima volta.",
        ),
        where=_IMPORT_PAGE,
        related=("import.row_checks", "import.manual_matching"),
        keywords=("anteprima", "righe valide", "righe da verificare"),
    ),
    entry(
        "import.row_checks",
        FEATURE,
        "Importazione tutto o niente",
        "NINFA importa un file solo se tutte le righe sono valide. Se una riga non lo è, non viene "
        "importato nulla finché il file non è corretto.",
        copy("Alcune righe non possono essere importate"),
        api("POST", "/data-sources/imports"),
        details=(
            "Il messaggio elenca il problema, quante righe riguarda e le prime righe da "
            "controllare.",
            "Esempi di problemi di riga: data non valida, numero non valido, valore mancante, "
            "partenza non dopo l'arrivo, categoria non riconosciuta.",
        ),
        where=_IMPORT_PAGE,
        related=("import.preview", "import.level_blocked"),
        keywords=("righe non valide", "errore riga", "importazione fallita", "nulla importato"),
    ),
    entry(
        "import.question_domain",
        FEATURE,
        "Domanda: che tipo di dati contiene il file?",
        "NINFA chiede di che tipo di dati si tratta quando non lo capisce da sola o quando ha un "
        "suggerimento da confermare (per esempio: Questo sembra un file di prenotazioni. "
        "Corretto?).",
        copy("Che tipo di dati contiene questo file?"),
        enum(f"{_QUESTION}.DOMAIN"),
        details=("Le scelte sono i tipi di dati: prenotazioni, personale, costi.",),
        where=_IMPORT_PAGE,
        related=("import.kinds", "import.level_ask"),
        keywords=("tipo di dati", "che tipo di file", "corretto"),
    ),
    entry(
        "import.question_table",
        FEATURE,
        "Domanda: quale tabella devo leggere?",
        "Se nel file ci sono più tabelle (anche in fogli diversi), NINFA chiede quale leggere, "
        "descrivendo ogni scelta con foglio, riga di partenza, numero di righe e colonne.",
        copy("Ho trovato più di una tabella nel file. Quale devo leggere?"),
        enum(f"{_QUESTION}.TABLE"),
        where=_IMPORT_PAGE,
        related=("import.level_ask", "import.blocker_no_table"),
        keywords=("più tabelle", "quale foglio", "quale tabella", "foglio excel"),
        not_available=(
            "NINFA non sceglie da sola tra due tabelle: è una decisione della persona.",
        ),
    ),
    entry(
        "import.question_department_rows",
        FEATURE,
        "Domanda: a quale reparto appartengono le righe?",
        "Nei file del personale in cui nessuna colonna, riga, foglio o titolo dice il reparto, "
        "NINFA "
        "chiede a quale reparto appartengono tutte le righe.",
        copy("A quale reparto appartengono le righe di questo file?"),
        enum(f"{_QUESTION}.DEPARTMENT_ROWS"),
        where=_IMPORT_PAGE,
        related=("import.labor_file", "term.labor_departments"),
        keywords=("reparto", "a quale reparto", "righe del personale"),
    ),
    entry(
        "import.question_department_confirm",
        FEATURE,
        "Domanda: il titolo indica il reparto?",
        "Quando il titolo del file nomina un reparto (per esempio «Housekeeping»), NINFA chiede se "
        "sono "
        "tutte righe di quel reparto.",
        copy("Sì, sono righe di"),
        enum(f"{_QUESTION}.DEPARTMENT_CONFIRM"),
        where=_IMPORT_PAGE,
        related=("import.question_department_rows", "import.labor_file"),
        keywords=("titolo", "reparto nel titolo", "housekeeping"),
    ),
    entry(
        "import.question_value_labels",
        FEATURE,
        "Domanda: che cosa significa questa parola?",
        "Per parole che NINFA non conosce (un turno, uno stato, una categoria) chiede a quale "
        "reparto, "
        "stato o categoria di costo corrispondono, e le ricorda per i prossimi file.",
        copy("NINFA ricorderà questa parola per i prossimi file di questa fonte."),
        enum(f"{_QUESTION}.VALUE_LABELS"),
        details=(
            "Esempio: che reparto è «HK»? Che stato è «Modificata»? A quale categoria appartiene "
            "«Bolletta»?",
            "La risposta si può correggere o far dimenticare in Struttura > Fonti dati > Gestisci "
            "> Risposte ricordate.",
        ),
        where=_IMPORT_PAGE,
        related=("struttura.remembered_answers", "import.source_learning"),
        keywords=("parola", "stato modificata", "turno", "categoria", "significato"),
    ),
    entry(
        "import.question_column_meaning",
        FEATURE,
        "Domanda: che cosa contiene questa colonna?",
        "Quando una colonna è chiaramente ore, costo o importo ma NINFA non sa quale, chiede di "
        "scegliere cosa contiene (La colonna «…» è «…»?).",
        copy("No, controllo le colonne"),
        enum(f"{_QUESTION}.COLUMN_MEANING"),
        where=_IMPORT_PAGE,
        related=("import.manual_matching", "import.level_ask"),
        keywords=("significato colonna", "colonna ore", "colonna importo"),
    ),
    entry(
        "import.question_grid_hours",
        FEATURE,
        "Domanda: ore previste o effettive?",
        "Se il file del personale è una tabella di giorni con delle ore, NINFA chiede se sono ore "
        "previste o ore effettive.",
        copy("Le ore scritte nella tabella sono ore previste o ore effettive?"),
        enum(f"{_QUESTION}.GRID_HOURS"),
        where=_IMPORT_PAGE,
        related=("term.planned_worked_hours", "import.labor_file"),
        keywords=("ore previste", "ore effettive", "ore lavorate", "tabella giorni"),
    ),
    entry(
        "import.question_period",
        FEATURE,
        "Domanda: a quale settimana si riferisce il file?",
        "Se i giorni della tabella sono scritti Lun, Mar, Mer…, NINFA chiede a quale settimana si "
        "riferisce il file e usa il lunedì di quella settimana come primo giorno.",
        copy("A quale settimana si riferisce il file?"),
        enum(f"{_QUESTION}.PERIOD"),
        where=_IMPORT_PAGE,
        related=("import.labor_file", "import.question_grid_hours"),
        keywords=("settimana", "lunedì", "giorni della settimana"),
    ),
    entry(
        "import.question_amount_basis",
        FEATURE,
        "Domanda: l'importo è al netto di IVA?",
        "Nei file dei costi, se un importo non dice se comprende l'IVA, NINFA chiede se è al "
        "netto. "
        "Analizza i costi al netto di IVA e non deve indovinare.",
        copy("NINFA analizza i costi al netto di IVA, e non deve indovinare quale importo sia."),
        enum(f"{_QUESTION}.AMOUNT_BASIS"),
        where=_IMPORT_PAGE,
        related=("term.net_amount", "import.costs_file", "import.blocker_amount_not_net"),
        keywords=("iva", "netto", "lordo", "imponibile", "importo con iva"),
    ),
    entry(
        "import.question_date_order",
        FEATURE,
        "Domanda: come sono scritte le date?",
        "Una data come 03/10/2026 può essere il 3 ottobre o il 10 marzo: solo la persona lo sa. "
        "NINFA "
        "chiede se è giorno/mese/anno o mese/giorno/anno.",
        copy("Come sono scritte le date di questo file?"),
        enum(f"{_QUESTION}.DATE_ORDER"),
        where=_IMPORT_PAGE,
        related=("import.question_decimal_style", "import.blocker_mixed_formats"),
        keywords=("date", "formato data", "giorno mese anno", "mese giorno anno"),
    ),
    entry(
        "import.question_decimal_style",
        FEATURE,
        "Domanda: come sono scritti i decimali?",
        "Un numero come 1,234 può essere mille duecento o uno e qualcosa: NINFA chiede se i "
        "decimali "
        "sono scritti con la virgola o con il punto.",
        copy("Come sono scritti i numeri con i decimali?"),
        enum(f"{_QUESTION}.DECIMAL_STYLE"),
        where=_IMPORT_PAGE,
        related=("import.question_date_order",),
        keywords=("decimali", "virgola", "punto", "numeri"),
    ),
    entry(
        "import.question_dates_reversed",
        FEATURE,
        "Domanda: arrivo e partenza sono invertiti?",
        "Se in quasi tutte le righe l'arrivo viene dopo la partenza, NINFA segnala che le due "
        "colonne "
        "sembrano invertite e propone di controllarle. Non le scambia da sola.",
        copy("Controlla le colonne"),
        enum(f"{_QUESTION}.DATES_REVERSED"),
        where=_IMPORT_PAGE,
        related=("import.manual_matching", "import.bookings_file"),
        keywords=("date invertite", "arrivo dopo partenza", "colonne invertite"),
        not_available=("NINFA non scambia le colonne da sola e non importa il file così com'è.",),
    ),
    entry(
        "import.question_file_scope",
        FEATURE,
        "Domanda: il file contiene tutto il periodo?",
        "Se NINFA ha già dei record di quel periodo che il nuovo file non contiene, chiede se il "
        "file "
        "contiene tutto il periodo, solo una parte o solo le novità. Non lo deduce mai dal file.",
        copy(
            "Questo file contiene tutte le prenotazioni del periodo oppure soltanto quelle nuove o "
            "modificate?"
        ),
        copy("Questo file contiene tutti i reparti del periodo oppure solo alcuni?"),
        enum(f"{_QUESTION}.FILE_SCOPE"),
        details=(
            "La domanda compare solo quando la risposta cambia ciò che viene contato, e solo dopo "
            "le altre domande.",
            "Un primo file non la pone mai: non c'è nulla che possa mancare.",
            "Un file dei costi con il numero del documento non la pone mai: l'unità è il "
            "documento.",
            "I costi operativi senza numero documento la pongono come le prenotazioni: un file "
            "completo toglie i costi del periodo che non contiene, uno parziale no.",
        ),
        where=_IMPORT_PAGE,
        related=("import.scope", "import.scope_full", "import.scope_partial", "import.scope_delta"),
        keywords=(
            "scope",
            "tutto il periodo",
            "completo",
            "parziale",
            "solo novità",
            "file completo",
        ),
    ),
    entry(
        "import.question_file_scope_confirm",
        FEATURE,
        "Domanda: conferma che il file è completo",
        "Se quel tipo di file è ricordato come completo e questo file farebbe smettere di contare "
        "qualcosa, NINFA chiede conferma per questo import: una memoria non toglie nulla da sola.",
        copy("Questo file contiene tutto il piano del periodo?"),
        enum(f"{_QUESTION}.FILE_SCOPE_CONFIRM"),
        details=(
            "Dice quante prenotazioni o giornate di reparto non compaiono più e cosa succede nei "
            "due casi.",
            "Ricorda questa scelta per i prossimi file è una casella che parte vuota.",
        ),
        where=_IMPORT_PAGE,
        related=("import.scope", "import.remembered_scope_safety"),
        keywords=("conferma", "file completo", "ricorda questa scelta", "non compaiono più"),
    ),
    entry(
        "import.question_document_identity",
        FEATURE,
        "Domanda: costi senza numero documento",
        "Un file di costi senza il numero del documento non viene mai trattato da solo come un "
        "registro di fatture. Se nulla nel file indica documenti fiscali, NINFA lo registra come "
        "costi operativi con un riferimento interno, senza domande. Se qualcosa li indica (per "
        "esempio la colonna del tipo di documento), chiede se sono fatture o costi operativi.",
        copy("Questo file contiene fatture o documenti, oppure un registro di costi operativi?"),
        enum(f"{_QUESTION}.DOCUMENT_IDENTITY"),
        details=(
            "Le risposte sono Un registro di costi operativi e Fatture o documenti: la risposta "
            "vale anche per i prossimi file fatti così e si corregge o si fa dimenticare dalle "
            "risposte ricordate.",
            "Una scadenza o un numero di riga da soli non bastano a dire che è un registro di "
            "fatture: un registro di costi operativi li ha spesso.",
            "Con Fatture o documenti il file non viene importato: senza il numero del documento "
            "le fatture non si possono registrare, e NINFA non lo inventa.",
            "Le righe con tipo di documento nota di credito e senza numero non vengono mai "
            "registrate come costi operativi.",
            "Lo stesso costo importato due volte non si duplica; due righe uguali nel file restano "
            "due costi.",
        ),
        where=_IMPORT_PAGE,
        related=("import.blocker_missing_required", "import.scope"),
        keywords=(
            "costi operativi",
            "senza numero documento",
            "numero fattura",
            "riferimento interno",
        ),
    ),
    entry(
        "import.blocker_no_table",
        FEATURE,
        "File senza tabella",
        "Il messaggio Non riesco a trovare una tabella di dati in questo file compare quando NINFA "
        "non "
        "individua righe di dati interpretabili.",
        copy("Non riesco a trovare una tabella di dati in questo file."),
        enum(f"{_BLOCKER}.NO_TABLE"),
        where=_IMPORT_PAGE,
        related=("import.level_blocked", "import.question_table"),
        keywords=("nessuna tabella", "file vuoto", "tabella non trovata"),
    ),
    entry(
        "import.blocker_missing_required",
        FEATURE,
        "Informazioni necessarie mancanti",
        "Il file non contiene un'informazione che NINFA richiede (per esempio la data di arrivo). "
        "Il "
        "messaggio elenca ciò che non ha trovato.",
        copy("Nel file non ho trovato:"),
        enum(f"{_BLOCKER}.MISSING_REQUIRED"),
        details=("Alcune informazioni hanno alternative: il messaggio le elenca con «oppure».",),
        where=_IMPORT_PAGE,
        related=("import.manual_matching", "struttura.template_csv"),
        keywords=("colonna mancante", "campo mancante", "manca", "informazione necessaria"),
    ),
    entry(
        "import.blocker_period_summary_only",
        FEATURE,
        "Riepilogo settimanale del personale",
        "Un file del personale con solo il riepilogo della settimana non si importa: per le "
        "analisi "
        "NINFA ha bisogno del dettaglio giorno per giorno.",
        copy("Questo file contiene un riepilogo settimanale."),
        enum(f"{_BLOCKER}.PERIOD_SUMMARY_ONLY"),
        where=_IMPORT_PAGE,
        related=("import.labor_file", "import.level_blocked"),
        keywords=("riepilogo settimanale", "ore per settimana", "totale settimana"),
    ),
    entry(
        "import.blocker_grid_not_supported",
        FEATURE,
        "Tabella con più blocchi di giorni",
        "Una tabella con più blocchi di giorni (per esempio ore previste ed effettive insieme) non "
        "è "
        "ancora leggibile: va esportato un blocco alla volta.",
        copy("Questa tabella ha più blocchi di giorni"),
        enum(f"{_BLOCKER}.GRID_NOT_SUPPORTED"),
        where=_IMPORT_PAGE,
        related=("import.labor_file", "import.question_grid_hours"),
        keywords=("più blocchi", "tabella complessa", "previste ed effettive insieme"),
    ),
    entry(
        "import.blocker_grid_not_hours",
        FEATURE,
        "Celle che non sono ore",
        "Se le celle della tabella dei giorni non sono ore (sembrano turni o orari), NINFA non può "
        "importarla: le servono le ore di ogni giorno.",
        copy("Le celle della tabella non sono ore"),
        enum(f"{_BLOCKER}.GRID_NOT_HOURS"),
        where=_IMPORT_PAGE,
        related=("import.labor_file",),
        keywords=("turni", "orari", "celle", "non sono ore"),
    ),
    entry(
        "import.blocker_amount_not_net",
        FEATURE,
        "Importo con IVA e senza imponibile",
        "Se l'importo comprende l'IVA e il file non ha l'imponibile, NINFA non può importarlo: "
        "lavora "
        "con l'importo al netto di IVA e chiede di esportare anche quella colonna.",
        copy("L'importo comprende l'IVA."),
        enum(f"{_BLOCKER}.AMOUNT_NOT_NET"),
        where=_IMPORT_PAGE,
        related=("term.net_amount", "import.question_amount_basis", "import.costs_file"),
        keywords=("iva", "importo lordo", "imponibile mancante"),
    ),
    entry(
        "import.blocker_mixed_formats",
        FEATURE,
        "Date o numeri scritti in modi diversi",
        "Se una colonna scrive le date (o i numeri) in modi diversi, NINFA non può importare il "
        "file: "
        "va corretto e ricaricato.",
        copy("In una colonna le date (o i numeri) sono scritti in modi diversi."),
        enum(f"{_BLOCKER}.MIXED_FORMATS"),
        where=_IMPORT_PAGE,
        related=("import.question_date_order", "import.question_decimal_style"),
        keywords=("formati misti", "date diverse", "numeri misti"),
    ),
    entry(
        "import.blocker_document_number_missing",
        FEATURE,
        "Fatture senza numero del documento",
        "Se la persona dice che un file di costi senza numero del documento contiene fatture, "
        "NINFA non lo importa: senza il numero le fatture non si possono registrare, e NINFA non "
        "lo inventa né chiede di abbinare una colonna che il file non ha.",
        copy("Questo file non contiene il numero del documento, che serve per registrare"),
        enum(f"{_BLOCKER}.DOCUMENT_NUMBER_MISSING"),
        details=(
            "Per le fatture si carica la fattura elettronica XML da Importa le fatture, oppure un "
            "registro esportato dal gestionale con la colonna del numero del documento.",
            "Se invece sono costi operativi, si sceglie di nuovo il file e si risponde Un registro "
            "di costi operativi.",
        ),
        where=_IMPORT_PAGE,
        related=("import.question_document_identity", "import.level_blocked"),
        keywords=("fatture senza numero", "numero documento mancante", "numero fattura"),
    ),
    entry(
        "import.source_learning",
        FEATURE,
        "NINFA ricorda le tue risposte (Source Learning)",
        "Quello che la persona conferma viene ricordato per i prossimi file della stessa fonte, "
        "così "
        "NINFA fa meno domande ogni volta.",
        doc("docs/architecture/adr/0033-smart-import-source-learning.md"),
        details=(
            "Una fonte è un tipo di dati di una struttura (per esempio le prenotazioni); dentro la "
            "fonte NINFA riconosce la struttura del file, mai il nome del file.",
            "Si ricordano le parole insegnate, come sono scritte date e numeri, se gli importi "
            "sono al netto, il reparto e lo scope del file.",
            "Non si salva alcun valore di riga: nessun nome, email, telefono, codice fiscale o "
            "IBAN.",
            "Le risposte ricordate si vedono e si correggono in Struttura > Fonti dati > Gestisci.",
        ),
        where="Struttura > Fonti dati > Gestisci > Risposte ricordate",
        related=("import.families", "struttura.remembered_answers", "import.level_ask"),
        keywords=(
            "source learning",
            "ricorda",
            "impara",
            "meno domande",
            "memoria",
            "apprendimento",
        ),
        not_available=("NINFA non usa il nome del file per riconoscere una fonte.",),
    ),
    entry(
        "import.families",
        FEATURE,
        "Famiglie di file di una fonte",
        "Una fonte può ricevere più tipi ricorrenti di file con colonne diverse (per esempio una "
        "esportazione per reparto): NINFA ne ricorda ciascuna come una famiglia a sé.",
        doc("docs/architecture/adr/0034-smart-import-source-families.md"),
        details=(
            "Un file che somiglia a una famiglia nota ne riusa le risposte; un file diverso crea "
            "una nuova famiglia.",
            "Se un file potrebbe appartenere a due famiglie, NINFA non ne sceglie una: chiede.",
        ),
        related=("import.source_learning", "term.family"),
        keywords=("famiglia", "famiglie", "stessa fonte", "più formati"),
    ),
    entry(
        "import.scope",
        FEATURE,
        "Che cosa dice l'assenza di un record (FULL, PARTIAL, DELTA)",
        "Un record che manca in un file successivo non dice sempre la stessa cosa: dipende se il "
        "file "
        "contiene tutto il periodo (FULL), una parte (PARTIAL) o solo le novità (DELTA).",
        doc("docs/architecture/adr/0040-import-scope-semantics.md"),
        enum(f"{_SCOPE}.FULL"),
        enum(f"{_SCOPE}.PARTIAL"),
        enum(f"{_SCOPE}.DELTA"),
        details=(
            "NINFA non lo capisce guardando il file (righe, date, nome): lo chiede alla persona, "
            "una volta, solo quando cambia ciò che viene contato.",
            "Con una risposta ricordata come PARTIAL o DELTA non si toglie nulla; una memoria FULL "
            "non toglie nulla da sola e chiede conferma.",
            "Le prenotazioni non si cancellano: si marcano come non più nel file e restano nello "
            "storico; un file successivo che le contiene le riporta.",
            "I costi non pongono mai la domanda.",
        ),
        where="Compare come domanda durante l'importazione di un secondo file",
        related=(
            "import.scope_full",
            "import.scope_partial",
            "import.scope_delta",
            "import.question_file_scope",
            "import.remembered_scope_safety",
        ),
        keywords=(
            "full",
            "partial",
            "delta",
            "scope",
            "differenza",
            "file completo",
            "assenza",
            "record mancanti",
        ),
    ),
    entry(
        "import.scope_full",
        FEATURE,
        "FULL: il file contiene tutto il periodo",
        "Con FULL il file contiene tutto il periodo che copre: ciò che non contiene più, non c'è "
        "più. "
        "Le prenotazioni mancanti smettono di essere contate (restano nello storico).",
        enum(f"{_SCOPE}.FULL"),
        copy("Tutte le prenotazioni del periodo"),
        details=(
            "Per il personale, un file completo parla per tutti i reparti dei giorni che copre; "
            "solo un file completo toglie una cella (giorno e reparto).",
        ),
        related=("import.scope", "import.scope_partial", "import.scope_delta"),
        keywords=("full", "completo", "tutto il periodo"),
    ),
    entry(
        "import.scope_partial",
        FEATURE,
        "PARTIAL: il file contiene una parte",
        "Con PARTIAL il file contiene una parte del periodo (un canale, un reparto): ciò che non "
        "contiene non dice nulla e NINFA non toglie niente.",
        enum(f"{_SCOPE}.PARTIAL"),
        copy("Solo una parte (per esempio un canale)"),
        related=("import.scope", "import.scope_full", "import.scope_delta"),
        keywords=("partial", "parziale", "una parte", "un canale", "alcuni reparti"),
    ),
    entry(
        "import.scope_delta",
        FEATURE,
        "DELTA: il file contiene solo le novità",
        "Con DELTA il file contiene solo ciò che è nuovo o cambiato: ciò che non contiene non dice "
        "nulla e NINFA non toglie niente.",
        enum(f"{_SCOPE}.DELTA"),
        copy("Solo quelle nuove o modificate"),
        related=("import.scope", "import.scope_full", "import.scope_partial"),
        keywords=("delta", "novità", "solo nuove", "solo modificate", "incrementale"),
    ),
    entry(
        "import.remembered_scope_safety",
        FEATURE,
        "Una risposta ricordata non toglie nulla da sola",
        "Anche se NINFA ricorda che i file di una fonte sono completi, non fa smettere di contare "
        "nulla senza chiedere: la risposta riguarda solo l'import in corso.",
        doc("docs/architecture/adr/0041-remembered-scope-safety.md"),
        details=(
            "Rispondere «No, contiene solo una parte» non rende la fonte parziale: un'esportazione "
            "non dice nulla sulla successiva.",
            "La memoria cambia solo con una parola esplicita, la casella Ricorda questa scelta per "
            "i prossimi file.",
            "Prima dell'importazione il server ricalcola cosa verrebbe tolto: se non coincide con "
            "ciò che la persona ha visto, non importa nulla.",
            "Per il personale, solo un file dichiarato completo toglie una cella (giorno e "
            "reparto); zero ore non è una rimozione.",
        ),
        where="Compare come domanda di conferma durante l'importazione",
        related=("import.scope", "import.question_file_scope_confirm"),
        keywords=(
            "memoria",
            "ricorda scelta",
            "conferma",
            "non toglie nulla",
            "file completo ricordato",
        ),
    ),
    entry(
        "import.same_day_revision",
        FEATURE,
        "Più file nello stesso giorno",
        "Si possono importare più file nello stesso giorno: una notte vista di nuovo diventa la "
        "revisione successiva del giorno e nulla di già salvato viene riscritto.",
        doc("docs/architecture/same-day-revisions-v1.md"),
        doc("docs/architecture/adr/0039-same-day-revisions.md"),
        details=(
            "Prenotazioni: si scrivono solo le notti cambiate; contenuto identico non scrive "
            "nulla.",
            "Personale: un file vale per le celle (giorno e reparto) che contiene; dove parla "
            "vince il più recente.",
            "Costi: una riga corretta di un foglio è la revisione successiva del suo documento; "
            "una fattura elettronica XML già importata non viene sostituita.",
            "L'ultima revisione del giorno rappresenta quel giorno nelle analisi.",
        ),
        related=("import.no_op", "import.post_import_analysis", "import.scope"),
        keywords=(
            "più file",
            "stesso giorno",
            "revisione",
            "secondo file",
            "file corretto",
            "rimandare un file",
        ),
    ),
    entry(
        "import.no_op",
        FEATURE,
        "File che non cambia nulla",
        "Se un file non cambia nulla di ciò che NINFA ha già, lo dice: l'analisi resta quella di "
        "prima e non ne parte una nuova. Ricaricare lo stesso file non duplica i dati.",
        copy(
            "Questo file non cambia nulla di ciò che NINFA ha già: l'analisi resta quella di prima."
        ),
        copy("Questo file è già stato importato: caricarlo di nuovo non duplica i dati."),
        details=(
            "Un file che non cambia nulla non mette in coda un'analisi e non sposta lo stato.",
        ),
        where=_IMPORT_PAGE,
        related=("import.same_day_revision", "import.post_import_analysis"),
        keywords=(
            "nessuna modifica",
            "stesso file",
            "file già importato",
            "duplicato",
            "non cambia nulla",
        ),
    ),
    entry(
        "import.post_import_analysis",
        FEATURE,
        "Dopo l'importazione l'analisi parte da sola",
        "Quando un import cambia qualcosa, NINFA aggiorna l'analisi da sola: nessuno deve "
        "avviarla. "
        "La pagina dice a che punto è (Aggiornamento analisi…).",
        doc("docs/architecture/post-import-analysis-v1.md"),
        api("GET", "/analysis/status"),
        api("POST", "/analysis/refresh"),
        details=(
            "Servono le prenotazioni: senza prenotazioni nessuna analisi può partire, anche se ci "
            "sono costi o personale.",
            "Se l'analisi non si aggiorna, i dati importati sono al sicuro; si può riprovare con "
            "Avvia analisi.",
            "Se le prenotazioni cambiano dopo la lettura di oggi, entrano nell'analisi di domani.",
        ),
        related=(
            "state.analysis_updating",
            "state.new_data_imported",
            "state.analysis_failed",
            "decision.daily_analysis",
            "workflow.refresh_analysis",
        ),
        keywords=(
            "analisi automatica",
            "dopo l'import",
            "aggiornamento analisi",
            "perché non vedo",
            "analisi non parte",
        ),
    ),
    entry(
        "import.recent",
        FEATURE,
        "Importazioni recenti",
        "L'elenco in fondo alla pagina Importa file con i file importati di recente: nome, tipo, "
        "data "
        "e stato (Completata, Non riuscita, In corso).",
        copy("Importazioni recenti"),
        api("GET", "/data-sources/imports"),
        where=f"{_IMPORT_PAGE}, in fondo alla pagina",
        related=("nav.importa_file", "workflow.find_import_history"),
        keywords=("importazioni recenti", "storico import", "ultimi file", "file importati"),
    ),
    entry(
        "import.invoice_xml",
        FEATURE,
        "Fatture elettroniche XML",
        "Le fatture elettroniche in formato XML si importano dalla scheda Contabilità di "
        "Struttura. "
        "Una fattura già importata che torna diversa viene rifiutata.",
        copy("Carica una fattura elettronica in formato XML"),
        doc("docs/architecture/cost-ingestion-v1.md"),
        where="Struttura > Fonti dati > Contabilità > Importa fatture XML",
        related=("struttura.invoice_xml", "import.costs_file"),
        keywords=("xml", "fattura elettronica", "fatturapa"),
    ),
    entry(
        "import.personal_data",
        FEATURE,
        "Dati personali: cosa NINFA non importa",
        "NINFA non importa i nomi delle persone, il costo orario delle persone, e-mail e numeri di "
        "telefono, codici fiscali e coordinate bancarie delle persone.",
        copy("NINFA non importa i nomi delle persone."),
        copy("NINFA non importa e-mail e numeri di telefono."),
        details=("Nel personale NINFA conta le persone ma non ne salva i nomi.",),
        where="Abbina le colonne: le colonne di questo tipo sono segnalate",
        related=("import.manual_matching", "import.labor_file"),
        keywords=("privacy", "dati personali", "nomi", "email", "telefono", "ospiti", "pii"),
    ),
    entry(
        "import.assumed_rooms",
        FEATURE,
        "Camere della prenotazione",
        "Se il file delle prenotazioni non dice quante camere ha ogni prenotazione, NINFA ne conta "
        "una "
        "per riga e lo scrive nel riepilogo.",
        copy("Il file non dice quante camere ha ogni prenotazione: NINFA ne conta una per riga."),
        where=_IMPORT_PAGE,
        related=("import.bookings_file", "struttura.rooms"),
        keywords=("camere per prenotazione", "una camera per riga"),
        not_available=(
            "Le camere della prenotazione non sono le camere della struttura: quelle sono "
            "l'inventario.",
        ),
    ),
    entry(
        "import.problems",
        FEATURE,
        "Perché un file non viene accettato",
        "I motivi più comuni sono: tipo di file non supportato, file illeggibile, file vuoto o con "
        "la sola "
        "intestazione, file troppo grande, colonne mancanti o duplicate, righe non valide.",
        copy("Questo tipo di file non è supportato."),
        copy("Il file è vuoto."),
        copy("Il file è troppo grande."),
        details=(
            "Ogni motivo ha una frase chiara; per alcuni c'è anche un suggerimento (per esempio "
            "usare un file CSV o Excel).",
            "Se i dati di NINFA sono cambiati dopo la lettura del file, va ricaricato per rivedere "
            "cosa cambia.",
        ),
        where=_IMPORT_PAGE,
        related=("import.formats", "import.row_checks"),
        keywords=(
            "errore",
            "file non accettato",
            "file illeggibile",
            "troppo grande",
            "colonne duplicate",
        ),
    ),
    entry(
        "import.review_page",
        FEATURE,
        "Rivedere come NINFA legge i file di una fonte",
        "Da Struttura > Fonti dati > Gestisci si può chiedere di rivedere come NINFA legge le "
        "colonne "
        "di una fonte: la pagina Importa file si apre per quel tipo di dati.",
        copy("Carica un file di questa fonte per rivedere come NINFA ne legge le colonne."),
        copy("Modifica associazioni"),
        where="Struttura > Fonti dati > Gestisci > Modifica associazioni",
        related=("workflow.review_column_matching", "struttura.import_configuration"),
        keywords=("rivedere colonne", "modifica associazioni", "rileggere"),
    ),
)

__all__ = ["ENTRIES"]
