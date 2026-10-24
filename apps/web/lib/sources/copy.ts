import type { ImportProblem, SourceCardKey, SourceMethod } from "@ninfa/contracts";

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
      title: "Importa tramite CSV",
      body: "Importa prenotazioni e dati operativi utilizzando un file compatibile.",
      cta: "Importa file",
    },
    channelCsv: {
      title: "Importa tramite CSV",
      body: "Carica il file delle prenotazioni: i canali (Booking.com, Expedia e altri) sono già al suo interno.",
      cta: "Importa file",
    },
    invoicesXml: {
      title: "Importa fatture",
      body: "Carica le fatture elettroniche in formato XML.",
      cta: "Importa file",
    },
    laborCsv: {
      title: "Importa CSV",
      body: "Ore, ruoli e costi del personale, in un file compatibile con NINFA.",
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
      CSV: "Utilizza il formato compatibile con NINFA: un file CSV con una riga di intestazione, date nel formato AAAA-MM-GG e numeri decimali con il punto.",
      XML: "Utilizza fatture elettroniche in formato XML (FatturaPA).",
    },
    template: "Scarica modello CSV",
    templateFailed: "Il modello non è disponibile al momento.",
    laborDate: (date: string) =>
      `I dati vengono registrati con la data di oggi (${date}), secondo il fuso orario della struttura.`,
    wrongType: {
      CSV: "Scegli un file con estensione .csv.",
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
  // --- manage / remove -----------------------------------------------------------------------------
  manage: {
    title: (name: string) => `Gestisci ${name}`,
    method: "Come arrivano i dati",
    removeTitle: "Rimuovere questa fonte?",
    removeBody:
      "NINFA non riceverà più nuovi dati da questa fonte. I dati già importati restano in NINFA.",
    removeConfirm: "Rimuovi fonte",
    removing: "Rimozione in corso…",
  },
} as const;
