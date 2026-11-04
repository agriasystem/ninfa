import type {
  ImportFieldKey,
  ImportProblem,
  ImportProfileInfo,
  RecentImport,
  SourceCardKey,
  SourceMethod,
} from "@ninfa/contracts";

/** "1.284": Italian leaves a four-digit number ungrouped by default. */
function countText(count: number): string {
  return new Intl.NumberFormat("it-IT", { useGrouping: "always" }).format(count);
}

/**
 * Italian copy of "Fonti dati" (Struttura). One source per string, like `lib/copy.ts`.
 *
 * The hotelier is never shown a technical word: no API key, webhook, endpoint, token, payload,
 * mapping, schema. The only column names ever printed are the ones a file must carry - and they come
 * with a template to download. Nothing here names a vendor: NINFA states what it can really do today
 * (import a file) and, for the rest, only that automatic integrations are "Prossimamente".
 */
export const sourcesCopy = {
  sectionIntro:
    "Collega le fonti utilizzate dalla struttura per permettere a NINFA di analizzare prenotazioni, distribuzione, costi e personale.",
  loading: "Caricamento delle fonti dati in corso",
  loadError: "Non siamo riusciti a caricare le fonti dati.",
  retry: "Riprova",
  cardLabels: {
    PMS: "PMS",
    CHANNEL_MANAGER: "Channel Manager",
    OTA: "OTA",
    ACCOUNTING: "Contabilità",
    STAFF: "Personale",
  } satisfies Record<SourceCardKey, string>,
  // The "CSV" method is the file import of bookings and staff: a CSV or an Excel (.xlsx) file, so the label
  // names no single format (a source can receive both over time).
  methodLabels: {
    CSV: "Import file",
    XML: "Import fatture XML",
  } satisfies Record<SourceMethod, string>,
  // --- the state of a card -------------------------------------------------------------------------
  state: {
    notConfigured: "Non configurato",
    configured: "Configurato",
    connected: "Connesso",
    derived: "Già ricevuto",
  },
  lines: {
    none: "Nessuna fonte collegata",
    noChannelData: "Nessun dato canale disponibile",
    several: "Più fonti configurate",
    automatic: "Connessione automatica",
    bookingsReceived: "Prenotazioni già ricevute",
    channelsReceived: "Canali ricevuti con le prenotazioni",
  },
  update: {
    label: "Ultimo aggiornamento",
    never: "Mai importato",
    today: (time: string) => `Oggi alle ${time}`,
    yesterday: (time: string) => `Ieri alle ${time}`,
  },
  receivedVia: {
    label: "Ricevuti tramite",
    BOOKINGS_FILE: "Prenotazioni importate",
    PMS: "PMS",
    CHANNEL_MANAGER: "Channel Manager",
  },
  // --- actions -------------------------------------------------------------------------------------
  actions: {
    connect: "Collega fonte",
    connectNew: "Collega una nuova fonte",
    configure: "Configura fonte",
    upload: "Carica file",
    uploadNew: "Carica nuovo file",
    importFile: "Importa un file",
    manage: "Gestisci",
    remove: "Rimuovi fonte",
    viewChannels: "Visualizza canali",
    view: "Visualizza",
    menuLabel: (name: string) => `Azioni per ${name}`,
    connectLabel: (name: string) => `Collega fonte ${name}`,
    configureLabel: (name: string) => `Configura fonte ${name}`,
    manageLabel: (name: string) => `Gestisci ${name}`,
    viewLabel: (name: string) => `Visualizza ${name}`,
  },
  // --- dialogs -------------------------------------------------------------------------------------
  dialog: {
    close: "Chiudi",
    cancel: "Annulla",
    back: "Indietro",
    comingSoon: "Prossimamente",
    automaticTitle: "Integrazioni automatiche",
    automaticBody: "Il collegamento diretto con i tuoi software non è ancora disponibile.",
    unavailable: "Questa modalità non è disponibile al momento.",
  },
  connect: {
    PMS: {
      title: "Collega il tuo PMS",
      intro: "Indica da quale sistema NINFA riceverà i dati della struttura.",
    },
    CHANNEL_MANAGER: {
      title: "Collega il tuo Channel Manager",
      intro:
        "Se il tuo Channel Manager raccoglie già le prenotazioni provenienti da Booking.com, Expedia e altri portali, NINFA può utilizzare quella fonte senza richiedere collegamenti separati per ogni OTA.",
    },
    OTA: {
      title: "Configura la fonte dei canali",
      intro:
        "Normalmente NINFA riceve questi dati dal PMS o dal Channel Manager. Non è necessario collegare ogni portale separatamente se il tuo gestionale li raccoglie già.",
    },
    ACCOUNTING: {
      title: "Come vuoi fornire i dati dei costi?",
      intro: "Scegli come NINFA riceverà le fatture e i costi della struttura.",
    },
    STAFF: {
      title: "Come vuoi fornire i dati del personale?",
      intro: "Scegli come NINFA riceverà le ore e i costi del personale.",
    },
  },
  methods: {
    bookingsCsv: {
      title: "Importa da file",
      body: "Usa il file delle prenotazioni che hai già, in formato CSV o Excel (.xlsx): NINFA lo riconosce da sola.",
      cta: "Importa un file",
    },
    channelCsv: {
      title: "Importa da file",
      body: "Usa il file delle prenotazioni, in formato CSV o Excel (.xlsx): i canali (Booking.com, Expedia e altri) sono già al suo interno.",
      cta: "Importa un file",
    },
    invoicesXml: {
      title: "Fatture elettroniche",
      body: "Carica le fatture elettroniche in formato XML.",
      cta: "Importa fatture XML",
    },
    costsRegister: {
      title: "Registro dei costi",
      body: "Usa il registro dei costi che hai già, in formato CSV o Excel (.xlsx): NINFA lo riconosce da sola.",
      cta: "Importa un file",
    },
    laborCsv: {
      title: "Importa da file",
      body: "Ore, reparti e costi del personale: usa il file che hai già, in formato CSV o Excel (.xlsx).",
      cta: "Importa un file",
    },
  },
  // --- the "Collega una nuova fonte" wizard ----------------------------------------------------------
  wizard: {
    title: "Collega una fonte dati",
    question: "Quali dati vuoi collegare a NINFA?",
    howQuestion: "Come vuoi fornire questi dati?",
    kinds: {
      bookings: { title: "Prenotazioni", body: "Le prenotazioni della struttura." },
      distribution: { title: "Distribuzione", body: "I canali di vendita: Booking.com, Expedia e altri." },
      costs: { title: "Costi", body: "Le fatture e i costi della struttura." },
      labor: { title: "Personale", body: "Ore e costi del personale." },
    },
    distributionNote:
      "I canali di vendita arrivano insieme alle prenotazioni: non serve collegarli separatamente. Importa il file delle prenotazioni e NINFA li riconosce da sola.",
    alreadyHave:
      "Hai già una fonte per questi dati. Puoi caricare un nuovo file per aggiornarli.",
  },
  // --- importing a file ---------------------------------------------------------------------------
  importFlow: {
    invoiceTitle: "Importa le fatture",
    chooseFile: "Seleziona file",
    chooseOther: "Scegli un altro file",
    chosen: (name: string) => `File selezionato: ${name}`,
    invoiceHint:
      "Carica una fattura elettronica in formato XML. Per un registro dei costi in CSV o Excel usa «Importa file».",
    template: "Scarica modello CSV",
    templateFailed: "Il modello non è disponibile al momento.",
    laborDate: (date: string) =>
      `I dati vengono registrati con la data di oggi (${date}), secondo il fuso orario della struttura.`,
    invoiceWrongType: "Scegli un file XML di fattura elettronica (con estensione .xml).",
    checking: "Controllo del file in corso…",
    importing: "Importazione in corso…",
    previewTitle: "Cosa NINFA ha trovato nel file",
    rowsFound: (count: number, method: SourceMethod) =>
      method === "XML"
        ? count === 1
          ? "1 fattura trovata"
          : `${count} fatture trovate`
        : count === 1
          ? "1 riga trovata"
          : `${count} righe trovate`,
    unusedColumns: (names: string) => `Queste colonne non verranno utilizzate: ${names}.`,
    alreadyImported: "Questo file è già stato importato: caricarlo di nuovo non duplica i dati.",
    rowChecks:
      "I controlli sulle singole righe avvengono durante l'importazione: se una riga non è valida, non viene importato nulla.",
    sampleLabel: "Prime righe del file",
    missingTitle: "Colonne richieste da NINFA che mancano nel file:",
    missingGroup: (names: string[]) => names.join(" oppure "),
    confirm: "Conferma importazione",
    doneTitle: "Importazione completata",
    doneCounts: (created: number, updated: number, unchanged: number, removed = 0) => {
      const parts: string[] = [];
      if (created > 0) parts.push(`${created} nuov${created === 1 ? "o" : "i"}`);
      if (updated > 0) parts.push(`${updated} aggiornat${updated === 1 ? "o" : "i"}`);
      if (unchanged > 0) parts.push(`${unchanged} già present${unchanged === 1 ? "e" : "i"}`);
      if (removed > 0) parts.push(`${removed} non più nel file`);
      return parts.length > 0 ? `Elementi: ${parts.join(", ")}.` : "Nessun nuovo elemento.";
    },
    doneNote: "L'ultimo aggiornamento di questa fonte è stato registrato.",
    configurationSaved:
      "Configurazione salvata: la prossima volta NINFA riconoscerà il formato di questo file.",
    failedTitle: "Importazione non riuscita",
    nothingImported: "Non è stato importato nulla.",
  },
  // --- sentence for every reason a file cannot be used ----------------------------------------------
  problems: {
    UNSUPPORTED_FILE: "Questo tipo di file non è supportato.",
    UNREADABLE_FILE: "NINFA non riesce a leggere questo file.",
    EMPTY_FILE: "Il file è vuoto.",
    NO_ROWS: "Il file contiene solo l'intestazione, senza righe di dati.",
    FILE_TOO_LARGE: "Il file è troppo grande.",
    MISSING_COLUMNS: "Il file non contiene alcune colonne richieste da NINFA.",
    DUPLICATE_COLUMNS: "Il file ha colonne con lo stesso nome: rinomina o elimina quelle duplicate.",
    INVALID_ROWS: "Alcune righe del file non sono valide, quindi non è stato importato nulla.",
    UNSUPPORTED_FORMAT: "Questa fattura non è in un formato che NINFA sa leggere.",
    MAPPING_INCOMPLETE: "Le colonne non sono ancora abbinate in modo completo.",
    FORMAT_UNCLEAR:
      "NINFA non riesce a capire come sono scritte le date o i numeri di questo file: indicalo tu.",
    PROFILE_NOT_USABLE:
      "La configurazione salvata non funziona con questo file: controlla le colonne e abbinale di nuovo.",
    SHEET_REQUIRED: "Il file Excel ha più fogli con dati: scegli quale importare.",
    GENERIC: "NINFA non è riuscita a leggere questa fonte. Riprova oppure carica un altro file.",
  } satisfies Record<ImportProblem, string>,
  // what to do next, by method (appended to the sentence of the problem where it helps)
  problemHints: {
    UNSUPPORTED_FILE: {
      CSV: "Usa un file CSV o Excel (.xlsx).",
      XML: "Usa un file XML di fattura elettronica.",
    },
    UNREADABLE_FILE: {
      CSV: "Controlla che sia un file CSV (in formato UTF-8) o Excel (.xlsx) valido.",
      XML: "Controlla che sia una fattura elettronica XML valida.",
    },
  } satisfies Partial<Record<ImportProblem, Record<SourceMethod, string>>>,
  errors: {
    sourceGone: "Questa fonte non è più disponibile. Aggiorna la pagina.",
    importInProgress: "È già in corso un altro import di questi dati. Attendi qualche istante e riprova.",
    alreadyConfigured: "Hai già una fonte per questi dati.",
    severalSources: "Per questi dati risultano più fonti attive e NINFA non ne sceglie una da sola.",
    sessionExpired: "La sessione è scaduta. Accedi di nuovo per continuare.",
    tryAgain: "Riprova",
  },
  // --- "Abbina le colonne": the file the hotel already has -------------------------------------------
  match: {
    title: "Abbina le colonne del tuo file",
    // Always true, whatever NINFA could or could not recognise: the per-column badges say which is which.
    intro: "NINFA ha analizzato le colonne del file. Controlla gli abbinamenti prima di continuare.",
    // shown when a saved configuration exists but was not applied to this file
    savedNotApplied: {
      COLUMNS_CHANGED:
        "Questo file ha colonne diverse dall'ultima volta, quindi la configurazione salvata non è stata applicata. Controlla l'abbinamento.",
      VERSION_CHANGED:
        "NINFA ha aggiornato il modo di leggere questi file: controlla l'abbinamento prima di importare.",
      INVALID: "La configurazione salvata non è più valida: abbina di nuovo le colonne.",
    } satisfies Record<NonNullable<ImportProfileInfo["reason"]>, string>,
    tableLabel: "Colonne del file",
    columns: { file: "Colonna nel tuo file", example: "Esempio", meaning: "Significato per NINFA" },
    ignore: "Ignora questa colonna",
    choose: "Scegli cosa significa",
    recognized: "Riconosciuto",
    toCheck: "Da verificare",
    notUsed: {
      PERSON: "NINFA non importa i nomi delle persone.",
      HOURLY_RATE: "NINFA non utilizza il costo orario.",
      CONTACT: "NINFA non importa e-mail e numeri di telefono.",
      IDENTITY: "NINFA non importa codici fiscali e coordinate bancarie delle persone.",
    },
    meaningLabel: (header: string) => `Cosa significa la colonna ${header}`,
    fixedTitle: "Se il file non ha una colonna per questa informazione",
    fixedIntro: "Puoi indicare lo stesso valore per tutte le righe.",
    fixedNone: "Nessun valore",
    fixedRequired: "Necessario",
    fixedLabels: {
      status: "Stato di tutte le prenotazioni",
      rooms: "Camere di ogni prenotazione",
      channel: "Canale di vendita di tutte le prenotazioni",
      labor_category: "Reparto di tutte le righe",
      currency: "Valuta degli importi",
      cost_category: "Categoria di tutti i costi",
      document_type: "Tipo di tutti i documenti",
    } satisfies Partial<Record<ImportFieldKey, string>>,
    fixedPlaceholder: { CURRENCY: "Per esempio EUR", TEXT: "Scrivi il valore", INTEGER: "Per esempio 1" },
    missingTitle: (count: number) =>
      count === 1
        ? "Manca ancora 1 informazione necessaria:"
        : `Mancano ancora ${count} informazioni necessarie:`,
    missingGroup: (labels: string[]) => labels.join(" oppure "),
    complete: "Tutte le informazioni necessarie sono state abbinate.",
    checking: "Controllo delle colonne in corso…",
    continue: "Continua",
    problems: {
      UNKNOWN_FIELD: "C'è un significato che NINFA non conosce.",
      FIELD_USED_TWICE: "Lo stesso significato è stato dato a due colonne.",
      COLUMN_AND_VALUE: "Per la stessa informazione hai scelto sia una colonna sia un valore fisso.",
      CONSTANT_NOT_ALLOWED: "Per questa informazione non si può usare un valore fisso.",
      INVALID_CONSTANT: "Il valore fisso indicato non è valido.",
      UNKNOWN_COLUMN: "Una delle colonne scelte non è nel file.",
      DATES_MIXED: "Le date di questo file non sono scritte sempre allo stesso modo.",
      NUMBERS_MIXED: "I numeri di questo file non sono scritti sempre allo stesso modo.",
    } satisfies Record<string, string>,
    problemFallback: "L'abbinamento delle colonne non è valido.",
    datesQuestion: "Come sono scritte le date?",
    dateOptions: {
      DMY: "Giorno/mese/anno (per esempio 31/12/2026)",
      MDY: "Mese/giorno/anno (per esempio 12/31/2026)",
    },
    numbersQuestion: "Come sono scritti i numeri con i decimali?",
    numberOptions: {
      COMMA: "Con la virgola (per esempio 1.234,50)",
      POINT: "Con il punto (per esempio 1,234.50)",
    },
    formatColumns: (names: string) => `Riguarda: ${names}`,
    sheetTitle: "Quale foglio vuoi importare?",
    sheetIntro: "Questo file Excel ha più fogli con dati.",
    back: "Torna alle colonne",
  },
  // the name of what a column can mean, in the hotelier's words
  fields: {
    source_record_id: "Numero della prenotazione",
    booked_at: "Data della prenotazione",
    check_in: "Data di arrivo",
    check_out: "Data di partenza",
    status: "Stato",
    // The rooms OF THE BOOKING: the rooms of the hotel are a property's own data (Struttura).
    rooms: "Camere della prenotazione",
    room_revenue: "Importo della camera",
    channel: "Canale",
    guests: "Ospiti",
    total_revenue: "Importo totale",
    commission_amount: "Commissione (importo)",
    commission_rate: "Commissione (%)",
    cancelled_at: "Data di cancellazione",
    room_type: "Tipo di camera",
    rate_plan: "Tariffa",
    work_date: "Data",
    // The free text a staff file uses for a shift: a department ("Reception", "Cucina") or a job ("Cuoco").
    // NINFA only reads it to work out the department; the name itself is never used elsewhere.
    role: "Reparto o mansione",
    labor_category: "Reparto (nome standard di NINFA)",
    planned_hours: "Ore previste",
    actual_hours: "Ore lavorate",
    planned_cost: "Costo previsto",
    actual_cost: "Costo effettivo",
    currency: "Valuta",
    // costs: a register of invoices
    supplier_name: "Fornitore",
    supplier_vat_number: "Partita IVA del fornitore",
    supplier_tax_code: "Codice fiscale del fornitore",
    supplier_iban: "IBAN del fornitore",
    invoice_number: "Numero del documento",
    invoice_date: "Data del documento",
    due_date: "Scadenza",
    document_type: "Tipo di documento",
    invoice_net_amount: "Imponibile del documento",
    invoice_tax_amount: "IVA",
    invoice_gross_amount: "Totale con IVA",
    line_number: "Numero di riga",
    line_description: "Descrizione",
    quantity: "Quantità",
    unit: "Unità di misura",
    unit_price: "Prezzo unitario",
    line_total: "Importo al netto di IVA",
    vat_rate: "Aliquota IVA",
    cost_category: "Categoria di costo",
  } satisfies Record<ImportFieldKey, string>,
  // the values a fixed-value field can take
  choices: {
    status: {
      CONFIRMED: "Confermata",
      CANCELLED: "Cancellata",
      NO_SHOW: "Non presentato",
      CHECKED_IN: "Arrivato",
      CHECKED_OUT: "Partito",
    },
    labor_category: {
      HOUSEKEEPING: "Piani (housekeeping)",
      FRONT_OFFICE: "Reception",
      FOOD_BEVERAGE: "Sala e bar",
      KITCHEN: "Cucina",
      MAINTENANCE: "Manutenzione",
      MANAGEMENT: "Direzione",
      SPA_WELLNESS: "Spa e benessere",
      OTHER: "Altro",
    },
    cost_category: {
      PERSONNEL: "Personale",
      LAUNDRY: "Lavanderia",
      CLEANING: "Pulizie",
      AMENITIES: "Articoli di cortesia",
      FOOD: "Cibo",
      BEVERAGE: "Bevande",
      UTILITIES: "Utenze",
      MAINTENANCE: "Manutenzione",
      SOFTWARE: "Software",
      MARKETING: "Marketing",
      OTA_COMMISSIONS: "Commissioni dei portali",
      PROFESSIONAL_SERVICES: "Consulenze",
      TRANSPORT: "Trasporti",
      OTHER: "Altro",
    },
    document_type: {
      INVOICE: "Fattura",
      CREDIT_NOTE: "Nota di credito",
    },
  } satisfies Partial<Record<ImportFieldKey, Record<string, string>>>,
  // --- a format NINFA already knows ----------------------------------------------------------------------
  recognized: {
    title: "Abbiamo riconosciuto il formato del tuo file",
    body: "NINFA lo leggerà con le stesse colonne dell'ultima volta: non devi abbinarle di nuovo.",
    lastUsed: (date: string) => `Ultimo utilizzo: ${date}`,
    confirm: "Importa con questa configurazione",
    review: "Controlla colonne",
  },
  // --- the preview before anything is imported ------------------------------------------------------------
  preview: {
    title: "Anteprima importazione",
    rowsFound: (count: number) => (count === 1 ? "1 riga trovata" : `${count} righe trovate`),
    valid: (count: number) => (count === 1 ? "1 valida" : `${count} valide`),
    invalid: (count: number) => (count === 1 ? "1 da verificare" : `${count} da verificare`),
    sampleTitle: "Come NINFA leggerà i dati",
    sampleLabel: "Prime righe, nel formato di NINFA",
    sampleNote: "Le prime righe valide del file, come verranno importate.",
    columns: {
      source_record_id: "Prenotazione",
      check_in: "Arrivo",
      check_out: "Partenza",
      rooms: "Camere",
      room_revenue: "Importo",
      channel: "Canale",
      status: "Stato",
      work_date: "Data",
      labor_category: "Reparto",
      planned_hours: "Ore previste",
      actual_hours: "Ore lavorate",
      planned_cost: "Costo previsto",
      actual_cost: "Costo effettivo",
      invoice_number: "Documento",
      invoice_date: "Data",
      supplier_name: "Fornitore",
      line_description: "Descrizione",
      line_total: "Importo al netto",
      cost_category: "Categoria",
    } satisfies Partial<Record<ImportFieldKey, string>>,
    hoursUnit: "ore",
    datesRead: {
      DMY: "Le date sono lette come giorno/mese/anno.",
      MDY: "Le date sono lette come mese/giorno/anno.",
    },
    numbersRead: {
      COMMA: "I numeri con i decimali sono letti con la virgola.",
      POINT: "I numeri con i decimali sono letti con il punto.",
    },
    alreadyImported: "Questo file è già stato importato: caricarlo di nuovo non duplica i dati.",
    // Staff files only: rows whose department NINFA could not work out. They import (as "Altro"), but no
    // staffing decision uses "Altro", so the person is told BEFORE importing, not left to find out.
    unclassified: (count: number) =>
      count === 1
        ? "Per 1 riga NINFA non riconosce il reparto: verrà importata come «Altro» e non potrà essere usata nelle analisi sul personale."
        : `Per ${count} righe NINFA non riconosce il reparto: verranno importate come «Altro» e non potranno essere usate nelle analisi sul personale.`,
    unclassifiedHelp: "Se il reparto è scritto in un'altra colonna, usa «Controlla colonne».",
    blockedTitle: "Alcune righe non possono essere importate",
    blockedBody:
      "NINFA importa un file solo se tutte le righe sono valide: finché non le correggi nel file, non viene importato nulla.",
    problemLine: (what: string, field: string, count: number) =>
      `${field.length > 0 ? `${field}: ` : ""}${what} (${count === 1 ? "1 riga" : `${count} righe`})`,
    firstRows: "Prime righe da controllare",
    rowLine: (row: number, what: string) => `Riga ${row}: ${what}`,
    rowProblems: {
      REQUIRED_VALUE_MISSING: "manca un valore necessario",
      INVALID_DATE: "data non valida",
      INVALID_DATETIME: "data non valida",
      NONEXISTENT_LOCAL_TIME: "orario che non esiste (cambio dell'ora)",
      AMBIGUOUS_LOCAL_TIME: "orario ambiguo (cambio dell'ora)",
      INVALID_NUMBER: "numero non valido",
      INVALID_INTEGER: "numero intero non valido",
      AMOUNT_PRECISION: "troppi decimali",
      NEGATIVE_VALUE: "valore negativo",
      NOT_POSITIVE: "il valore deve essere maggiore di zero",
      OUT_OF_RANGE: "valore fuori dai limiti",
      VALUE_TOO_LONG: "testo troppo lungo",
      DUPLICATE_SOURCE_ID: "numero di prenotazione ripetuto nel file",
      UNKNOWN_STATUS: "stato non riconosciuto",
      UNKNOWN_CATEGORY: "reparto o categoria non riconosciuti",
      CHECK_OUT_NOT_AFTER_CHECK_IN: "la partenza non è dopo l'arrivo",
      CANCELLED_AT_WITHOUT_CANCELLED_STATUS: "data di cancellazione senza stato cancellato",
      FRACTIONAL_MINUTES: "ore che non corrispondono a minuti interi",
      HOURS_MISSING: "mancano le ore",
      CURRENCY_REQUIRED: "manca la valuta dei costi",
      INVALID_CURRENCY: "valuta non valida",
      INCONSISTENT_HEADER: "lo stesso documento ha dati diversi su righe diverse",
      DUPLICATE_LINE: "riga ripetuta nello stesso documento",
      INVALID_VAT_NUMBER: "partita IVA non valida",
      INVALID_TAX_CODE: "codice fiscale non valido",
      UNKNOWN_DOCUMENT_TYPE: "tipo di documento non riconosciuto",
    } satisfies Record<string, string>,
    rowProblemFallback: "valore non valido",
    save: "Salva questa configurazione per i prossimi file",
    saveHelp:
      "La prossima volta NINFA riconoscerà il file e non dovrai abbinare di nuovo le colonne.",
    import: "Importa dati",
    noRows: "Nessuna riga da importare.",
  },
  // --- NINFA understands the file: "File riconosciuto" and the few questions ------------------------------
  understanding: {
    recognizedTitle: "File riconosciuto",
    removes: {
      BOOKINGS: (count: number) =>
        count === 1
          ? "1 prenotazione che in questo file non compare non sarà più contata. Resta nello storico di NINFA."
          : `${count} prenotazioni che in questo file non compaiono non saranno più contate. Restano nello storico di NINFA.`,
      LABOR: (count: number) =>
        count === 1
          ? "1 giornata di reparto che in questo file non compare non sarà più contata. Resta nello storico di NINFA."
          : `${count} giornate di reparto che in questo file non compaiono non saranno più contate. Restano nello storico di NINFA.`,
    },
    kinds: {
      BOOKINGS: "NINFA ha riconosciuto un file di prenotazioni",
      LABOR: "NINFA ha riconosciuto un file del personale",
      COSTS: "NINFA ha riconosciuto un registro dei costi",
    },
    // a kind of data in a sentence ("Questo sembra un file ...")
    kindPhrase: { BOOKINGS: "di prenotazioni", LABOR: "del personale", COSTS: "dei costi" },
    kindName: { BOOKINGS: "Prenotazioni", LABOR: "Personale", COSTS: "Costi" },
    sameAsLastTime: "NINFA lo leggerà come l'ultima volta: non devi controllare nulla.",
    primary: "Importa dati",
    explain: "Controlla cosa ho riconosciuto",
    hideExplain: "Nascondi i dettagli",
    reviewColumns: "Controlla colonne",
    trying: "Controllo di tutte le righe in corso…",
    facts: {
      people: (count: number) => (count === 1 ? "1 persona" : `${count} persone`),
      departments: (count: number) => (count === 1 ? "1 reparto" : `${count} reparti`),
      plannedHours: (hours: string) => `${hours} ore previste`,
      actualHours: (hours: string) => `${hours} ore effettive`,
      plannedCost: (amount: string) => `${amount} di costo previsto`,
      actualCost: (amount: string) => `${amount} di costo effettivo`,
      rows: (count: number) => (count === 1 ? "1 riga" : `${countText(count)} righe`),
      bookings: (count: number) => (count === 1 ? "1 prenotazione" : `${countText(count)} prenotazioni`),
      fields: (count: number) => (count === 1 ? "1 campo riconosciuto" : `${count} campi riconosciuti`),
      channels: (count: number) => (count === 1 ? "1 canale" : `${count} canali`),
      revenue: (amount: string) => `${amount} di ricavo delle camere`,
      documents: (count: number) => (count === 1 ? "1 fattura" : `${count} fatture`),
      suppliers: (count: number) => (count === 1 ? "1 fornitore" : `${count} fornitori`),
      netTotal: (amount: string) => `${amount} al netto di IVA`,
      period: (from: string, to: string) => (from === to ? `il ${from}` : `dal ${from} al ${to}`),
    },
    peopleNote: "NINFA conta le persone ma non ne salva i nomi.",
    skipped: {
      totals: (count: number) =>
        count === 1 ? "Ho lasciato fuori 1 riga di totale." : `Ho lasciato fuori ${count} righe di totale.`,
      notes: (count: number) =>
        count === 1 ? "Ho lasciato fuori 1 nota." : `Ho lasciato fuori ${count} note.`,
      sections: (count: number) =>
        count === 1
          ? "1 riga con il nome di un reparto indica i reparti delle righe sotto."
          : `${count} righe con il nome di un reparto indicano i reparti delle righe sotto.`,
    },
    totalsCheck: {
      MATCH: "I totali del file tornano con le righe.",
      PARTIAL: "I totali del file tornano solo in parte con le righe.",
      MISMATCH: "Attenzione: i totali del file non tornano con le righe.",
      UNVERIFIED: "Non ho potuto controllare i totali del file.",
    },
    amountsCheck: {
      MATCH: "Imponibile e IVA tornano con il totale su tutte le righe.",
      MISMATCH: "Attenzione: imponibile e IVA non tornano con il totale in alcune righe.",
    },
    unclassified: (count: number) =>
      count === 1
        ? "1 riga ha un reparto che NINFA non conosce: verrà importata come «Altro»."
        : `${count} righe hanno un reparto che NINFA non conosce: verranno importate come «Altro».`,
    // The explain view: Campo / Valore / Origine
    explainTitle: "Cosa ho riconosciuto",
    // What the file does not state and NINFA reads from its absence: said on the summary, never hidden.
    assumed: {
      rooms: "Il file non dice quante camere ha ogni prenotazione: NINFA ne conta una per riga.",
    },
    assumedFallback: (field: string) => `Il file non indica: ${field}. NINFA usa il valore previsto.`,
    columns: { field: "Campo", value: "Valore", origin: "Origine" },
    tableLabel: "Cosa ha riconosciuto NINFA",
    toCheck: "Da controllare",
    origins: {
      COLUMN: (column: string) => `colonna «${column}»`,
      SECTION: "riga con il nome del reparto sopra le persone",
      SHEET: "nome del foglio",
      TITLE: "titolo del documento",
      PROFILE: (column: string) => `come l'ultima volta (colonna «${column}»)`,
      USER: "indicato da te",
      LEARNED: "parola che mi hai insegnato",
      GRID: "giorni della tabella",
      PROPERTY: "impostazioni della struttura",
      ASSISTANT: (column: string) => `suggerito da NINFA, da controllare (colonna «${column}»)`,
    },
    // --- the one question at a time ---
    question: {
      // How many questions the backend still has for this file, this one included.
      progress: (count: number) => (count > 1 ? `Mi servono ${count} conferme` : "Mi serve solo una conferma"),
      thinking: "Un attimo…",
      back: "Scegli un altro file",
      yes: "Sì",
      no: "No",
      DOMAIN: {
        withCandidate: (what: string) => `Questo sembra un file ${what}. Corretto?`,
        asIs: (what: string) => `Sì, è un file ${what}`,
        notIt: (what: string) => `No, è un file ${what}`,
        nothing: "Che tipo di dati contiene questo file?",
        suggested: "Suggerimento di NINFA, da controllare.",
      },
      TABLE: {
        title: "Ho trovato più di una tabella nel file. Quale devo leggere?",
        choice: (title: string, sheet: string, firstRow: number, rows: number, columns: string) =>
          `${title.length > 0 ? `«${title}» - ` : ""}foglio ${sheet}, dalla riga ${firstRow} (${rows === 1 ? "1 riga" : `${rows} righe`}; colonne: ${columns})`,
      },
      DEPARTMENT_ROWS: "A quale reparto appartengono le righe di questo file?",
      DEPARTMENT_CONFIRM: {
        title: (department: string) =>
          `Il titolo del file parla di «${department}». Sono tutte righe di ${department}?`,
        yes: (department: string) => `Sì, sono righe di ${department}`,
        other: "No, sono di un altro reparto:",
      },
      VALUE_LABELS: {
        department: (word: string, rows: number) =>
          `Che reparto è «${word}»? (${rows === 1 ? "1 riga" : `${rows} righe`})`,
        category: (word: string, rows: number) =>
          `A quale categoria di costo appartiene «${word}»? (${rows === 1 ? "1 riga" : `${rows} righe`})`,
        status: (word: string, rows: number) =>
          `Che stato è «${word}»? (${rows === 1 ? "1 prenotazione" : `${rows} prenotazioni`})`,
        remembered: "NINFA ricorderà questa parola per i prossimi file di questa fonte.",
        left: (count: number) => (count === 1 ? "Ne resta 1" : `Ne restano ${count}`),
      },
      COLUMN_MEANING: {
        confirm: (column: string, meaning: string) => `La colonna «${column}» è «${meaning}»?`,
        choose: (column: string) => `Cosa contiene la colonna «${column}»?`,
        notThis: "No, controllo le colonne",
      },
      GRID_HOURS: {
        title: "Le ore scritte nella tabella sono ore previste o ore effettive?",
      },
      PERIOD: {
        title: "A quale settimana si riferisce il file?",
        label: "Un giorno qualsiasi della settimana",
        help: "NINFA usa il lunedì di quella settimana come primo giorno. I giorni del file sono scritti come Lun, Mar, Mer…",
        confirm: "Conferma la settimana",
      },
      AMOUNT_BASIS: {
        title: (column: string) => `L'importo della colonna «${column}» è al netto di IVA?`,
        net: "Sì, è al netto di IVA",
        gross: "No, comprende l'IVA",
        why: "NINFA analizza i costi al netto di IVA, e non deve indovinare quale importo sia.",
      },
      DATE_ORDER: { title: "Come sono scritte le date di questo file?" },
      DECIMAL_STYLE: { title: "Come sono scritti i numeri con i decimali?" },
      FILE_SCOPE: {
        BOOKINGS: {
          title:
            "Questo file contiene tutte le prenotazioni del periodo oppure soltanto quelle nuove o modificate?",
          FULL: "Tutte le prenotazioni del periodo",
          PARTIAL: "Solo una parte (per esempio un canale)",
          DELTA: "Solo quelle nuove o modificate",
          absent: (count: number) =>
            count === 1
              ? "In NINFA c'è 1 prenotazione di questo periodo che in questo file non compare."
              : `In NINFA ci sono ${count} prenotazioni di questo periodo che in questo file non compaiono.`,
        },
        LABOR: {
          title: "Questo file contiene tutti i reparti del periodo oppure solo alcuni?",
          FULL: "Tutti i reparti del periodo",
          PARTIAL: "Solo alcuni reparti",
          DELTA: "Solo i turni nuovi o modificati",
          absent: (count: number) =>
            count === 1
              ? "In NINFA c'è 1 giornata di reparto di questo periodo che in questo file non compare."
              : `In NINFA ci sono ${count} giornate di reparto di questo periodo che in questo file non compaiono.`,
        },
        remembered: "NINFA lo ricorderà per i prossimi file fatti così.",
      },
      DATES_REVERSED: {
        title: (arrival: string, departure: string) =>
          `Le colonne «${arrival}» e «${departure}» sembrano invertite. Vuoi controllarle?`,
        why: "In quasi tutte le righe la data di arrivo viene dopo quella di partenza. NINFA non le scambia da sola e non importa il file così com'è.",
        check: "Controlla le colonne",
      },
    },
    // --- a file that cannot be imported as it is ---
    blocked: {
      title: "Questo file non può essere importato così com'è",
      nothingImported: "Non è stato importato nulla.",
      NO_TABLE: "Non riesco a trovare una tabella di dati in questo file.",
      MISSING_REQUIRED: "Nel file non ho trovato:",
      missingGroup: (labels: string[]) => labels.join(" oppure "),
      PERIOD_SUMMARY_ONLY:
        "Questo file contiene un riepilogo settimanale. Per le analisi del personale NINFA ha bisogno del dettaglio giorno per giorno.",
      GRID_NOT_SUPPORTED:
        "Questa tabella ha più blocchi di giorni (per esempio ore previste ed effettive insieme). NINFA non sa ancora leggerla: esporta un blocco alla volta.",
      GRID_NOT_HOURS:
        "Le celle della tabella non sono ore (sembrano turni o orari). NINFA ha bisogno delle ore di ogni giorno.",
      AMOUNT_NOT_NET:
        "L'importo comprende l'IVA. NINFA lavora con l'importo al netto di IVA (l'imponibile): esporta anche quella colonna e riprova.",
      MIXED_FORMATS:
        "In una colonna le date (o i numeri) sono scritti in modi diversi. Correggi il file e riprova.",
      checkColumns: "Controlla colonne",
    },
    manualIntro:
      "NINFA ha letto il file ma non è sicura di tutto. Controlla gli abbinamenti e continua.",
    assistantNote: "Alcuni abbinamenti sono suggerimenti di NINFA: controllali prima di continuare.",
    // The week: the day picked is moved back to its Monday.
    weekStarts: (date: string) => `Settimana dal ${date}`,
  },
  // --- the "Importa file" page: the person hands over the file, NINFA works out what it is -------------------
  importPage: {
    heading: "Importa file",
    subtitle: "NINFA riconosce automaticamente il contenuto del file e prepara i dati per l'analisi.",
    reviewSubtitle: "Carica un file di questa fonte per rivedere come NINFA ne legge le colonne.",
    backToSources: "Torna a Fonti dati",
    panelLabel: "Importazione del file",
    drop: {
      title: "Trascina qui il tuo file",
      or: "oppure",
      pick: "Selezionalo dal computer",
      // The size is the backend's own limit: never written here.
      formats: (size: string | null) =>
        size === null ? "CSV o Excel (.xlsx)" : `CSV o Excel (.xlsx), fino a ${size}`,
      inputLabel: "Seleziona un file CSV o Excel",
    },
    rejected: {
      WRONG_TYPE:
        "Questo formato non è supportato: scegli un file CSV o Excel (.xlsx). Le fatture elettroniche XML si importano da Struttura, in Fonti dati.",
      EMPTY: "Il file è vuoto: non c'è nulla da importare.",
      TOO_LARGE: "Il file è troppo grande per essere importato.",
      SEVERAL: "Trascina un file alla volta.",
    },
    tooLarge: (size: string) => `Il file supera ${size}: è troppo grande per essere importato.`,
    checking: {
      reading: "Sto leggendo il file…",
      verifying: "Sto controllando tutte le righe…",
      stepReading: "Lettura e riconoscimento del file",
      stepVerifying: "Verifica di tutte le righe",
    },
    kind: {
      title: "Non riesco a capire che tipo di dati contiene questo file",
      body: "NINFA importa prenotazioni, personale e costi. Se il file contiene uno di questi dati, indicalo:",
    },
    manual: {
      title: "Non posso importare questo file da sola",
      body: "NINFA ha letto il file, ma non è abbastanza sicura di come interpretarlo.",
      offer: "Puoi indicare tu cosa contiene ogni colonna, oppure scegliere un altro file.",
      action: "Abbina le colonne",
    },
    done: {
      file: "File",
      kind: "Tipo di dati",
      rows: "Contenuto",
      period: "Periodo",
      nothingNew: "Questo file non cambia nulla di ciò che NINFA ha già: l'analisi resta quella di prima.",
      goToday: "Vai a Oggi",
      another: "Importa un altro file",
    },
    recent: {
      title: "Importazioni recenti",
      columns: { file: "File", kind: "Tipo", date: "Data", status: "Stato" },
      loading: "Caricamento delle importazioni recenti…",
      loadError: "Non siamo riusciti a caricare le importazioni recenti.",
      empty: "Qui troverai i file che hai importato.",
      unnamed: "File senza nome",
      status: {
        SUCCEEDED: "Completata",
        FAILED: "Non riuscita",
        RUNNING: "In corso",
        PENDING: "In corso",
      } satisfies Record<RecentImport["status"], string>,
    },
  },
  // --- manage / remove -----------------------------------------------------------------------------
  manage: {
    title: (name: string) => `Gestisci ${name}`,
    method: "Come arrivano i dati",
    removeTitle: "Rimuovere questa fonte?",
    removeBody:
      "NINFA non riceverà più nuovi dati da questa fonte. I dati già importati restano in NINFA.",
    removeConfirm: "Rimuovi fonte",
    removing: "Rimozione in corso…",
    configuration: {
      title: "Configurazione import",
      intro: "Come NINFA legge i file di questa fonte.",
      loading: "Caricamento della configurazione…",
      loadError: "Non siamo riusciti a caricare la configurazione.",
      none: "Nessuna configurazione salvata: al prossimo file potrai abbinare le colonne e salvarle.",
      columnLine: (column: string, meaning: string) => `${column} → ${meaning}`,
      fixedLine: (meaning: string, value: string) => `${meaning}: sempre ${value}`,
      lastUsed: "Ultimo utilizzo",
      never: "Mai",
      outdated:
        "Questa configurazione è stata salvata con regole di NINFA diverse: al prossimo file controlla di nuovo le colonne.",
      edit: "Modifica associazioni",
      forget: "Dimentica configurazione",
      forgetTitle: "Dimenticare la configurazione?",
      forgetBody:
        "NINFA non riconoscerà più il formato dei tuoi file e ti chiederà di abbinare di nuovo le colonne. I dati già importati restano in NINFA.",
      forgetConfirm: "Dimentica configurazione",
      forgetting: "Operazione in corso…",
      forgotten: "Configurazione dimenticata. I dati già importati sono rimasti in NINFA.",
    },
  },
} as const;
