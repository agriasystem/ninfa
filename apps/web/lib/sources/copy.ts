import type {
  ImportFieldKey,
  ImportProblem,
  SourceCardKey,
  SourceMethod,
} from "@ninfa/contracts";

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
  methodLabels: {
    CSV: "Import CSV",
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
      body: "Carica il file delle prenotazioni che hai già, in formato CSV o Excel: NINFA ti aiuta ad abbinare le colonne.",
      cta: "Importa file",
    },
    channelCsv: {
      title: "Importa da file",
      body: "Carica il file delle prenotazioni: i canali (Booking.com, Expedia e altri) sono già al suo interno.",
      cta: "Importa file",
    },
    invoicesXml: {
      title: "Importa fatture",
      body: "Carica le fatture elettroniche in formato XML.",
      cta: "Importa file",
    },
    laborCsv: {
      title: "Importa da file",
      body: "Ore, reparti e costi del personale: usa il file che hai già, in formato CSV o Excel.",
      cta: "Importa file",
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
    titles: {
      BOOKINGS: "Importa le prenotazioni",
      COSTS: "Importa le fatture",
      LABOR: "Importa i dati del personale",
    },
    chooseFile: "Seleziona file",
    chooseOther: "Scegli un altro file",
    chosen: (name: string) => `File selezionato: ${name}`,
    hints: {
      CSV: "Usa il file che hai già, in formato CSV o Excel (.xlsx): non devi rinominare le colonne, ti aiutiamo noi ad abbinarle.",
      XML: "Utilizza fatture elettroniche in formato XML (FatturaPA).",
    },
    template: "Scarica modello CSV",
    templateFailed: "Il modello non è disponibile al momento.",
    laborDate: (date: string) =>
      `I dati vengono registrati con la data di oggi (${date}), secondo il fuso orario della struttura.`,
    wrongType: {
      CSV: "Scegli un file CSV o Excel (con estensione .csv o .xlsx).",
      XML: "Scegli un file con estensione .xml.",
    },
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
    doneCounts: (created: number, updated: number, unchanged: number) => {
      const parts: string[] = [];
      if (created > 0) parts.push(`${created} nuov${created === 1 ? "o" : "i"}`);
      if (updated > 0) parts.push(`${updated} aggiornat${updated === 1 ? "o" : "i"}`);
      if (unchanged > 0) parts.push(`${unchanged} già present${unchanged === 1 ? "e" : "i"}`);
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
    SAME_DAY_CONFLICT:
      "Per oggi hai già caricato un file del personale diverso: carica la versione aggiornata domani.",
    MAPPING_INCOMPLETE: "Le colonne non sono ancora abbinate in modo completo.",
    FORMAT_UNCLEAR:
      "NINFA non riesce a capire come sono scritte le date o i numeri di questo file: indicalo tu.",
    PROFILE_NOT_USABLE:
      "La configurazione salvata non funziona con questo file: controlla le colonne e abbinale di nuovo.",
    SHEET_REQUIRED: "Il file Excel ha più fogli con dati: scegli quale importare.",
    GENERIC: "NINFA non è riuscita a leggere questa fonte. Riprova oppure utilizza un file CSV.",
  } satisfies Record<ImportProblem, string>,
  // what to do next, by method (appended to the sentence of the problem where it helps)
  problemHints: {
    UNSUPPORTED_FILE: { CSV: "Usa un file CSV.", XML: "Usa un file XML di fattura elettronica." },
    UNREADABLE_FILE: {
      CSV: "Controlla che sia un CSV in formato UTF-8.",
      XML: "Controlla che sia una fattura elettronica XML valida.",
    },
  } satisfies Partial<Record<ImportProblem, Record<SourceMethod, string>>>,
  errors: {
    sourceGone: "Questa fonte non è più disponibile. Aggiorna la pagina.",
    importInProgress: "È già in corso un altro import di questi dati. Attendi qualche istante e riprova.",
    alreadyConfigured: "Hai già una fonte per questi dati.",
    tryAgain: "Riprova",
  },
  // --- "Abbina le colonne": the file the hotel already has -------------------------------------------
  match: {
    title: "Abbina le colonne del tuo file",
    intro: "NINFA ha riconosciuto alcune colonne. Controlla che siano corrette prima di importare i dati.",
    introNothing:
      "NINFA non ha riconosciuto le colonne di questo file: scegli tu cosa significa ciascuna.",
    tableLabel: "Colonne del file",
    columns: { file: "Colonna nel tuo file", example: "Esempio", meaning: "Significato per NINFA" },
    ignore: "Ignora questa colonna",
    choose: "Scegli cosa significa",
    recognized: "Riconosciuto",
    toCheck: "Da verificare",
    notUsed: {
      PERSON: "NINFA non importa i nomi delle persone.",
      HOURLY_RATE: "NINFA non utilizza il costo orario.",
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
    rooms: "Numero di camere",
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
    role: "Reparto o ruolo",
    labor_category: "Reparto (nome standard di NINFA)",
    planned_hours: "Ore previste",
    actual_hours: "Ore lavorate",
    planned_cost: "Costo previsto",
    actual_cost: "Costo effettivo",
    currency: "Valuta",
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
      UNKNOWN_CATEGORY: "reparto non riconosciuto",
      CHECK_OUT_NOT_AFTER_CHECK_IN: "la partenza non è dopo l'arrivo",
      CANCELLED_AT_WITHOUT_CANCELLED_STATUS: "data di cancellazione senza stato cancellato",
      FRACTIONAL_MINUTES: "ore che non corrispondono a minuti interi",
      HOURS_MISSING: "mancano le ore",
      CURRENCY_REQUIRED: "manca la valuta dei costi",
      INVALID_CURRENCY: "valuta non valida",
    } satisfies Record<string, string>,
    rowProblemFallback: "valore non valido",
    save: "Salva questa configurazione per i prossimi file",
    saveHelp:
      "La prossima volta NINFA riconoscerà il file e non dovrai abbinare di nuovo le colonne.",
    import: "Importa dati",
    noRows: "Nessuna riga da importare.",
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
