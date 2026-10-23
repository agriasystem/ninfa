/**
 * Centralised Italian copy for Struttura UI V1 - one source per string, exactly like `lib/copy.ts` and
 * `lib/data/copy.ts`. The page only DESCRIBES the structure and its connected systems, so the wording
 * never borrows a PMS's vocabulary (no prenotazioni, tariffe, disponibilità, assegnazione, housekeeping)
 * and never judges the quality of the data - that is the Dati section's job.
 */
export const strutturaCopy = {
  heading: "Struttura",
  subtitle: "Informazioni e configurazioni operative della tua struttura.",
  editStructure: "Modifica struttura",
  /** What a value nothing has set reads like - neutral, never "mancante" or "errore". The page shows this
   * instead of any value it does not really have; it is the grammatical gender of the label that varies. */
  notConfigured: {
    feminine: "Non configurata",
    masculine: "Non configurato",
  },
  profile: {
    title: "1. Profilo struttura",
    description: "Informazioni generali che NINFA utilizza come contesto operativo.",
    name: "Nome struttura",
    type: "Tipologia",
    category: "Categoria",
    location: "Località",
    roomCount: "Numero camere",
    timeZone: "Timezone",
    currency: "Valuta",
    mainSeason: "Stagionalità principale",
    stars: (count: number) => (count === 1 ? "1 stella" : `${count} stelle`),
  },
  rooms: {
    title: "2. Inventario camere",
    description: "Le tipologie di camere e la loro configurazione operativa.",
    edit: "Modifica inventario",
    emptyTitle: "L'inventario camere non è ancora configurato",
    configure: "Configura inventario",
    tableLabel: "Inventario camere",
    scrollLabel: "Tabella scorrevole: Inventario camere",
    columns: {
      type: "Tipologia di camera",
      code: "Codice",
      rooms: "Camere",
      maxOccupancy: "Occupazione max",
      status: "Stato",
      actions: "Azioni",
    },
    adults: (count: number) => (count === 1 ? "1 adulto" : `${count} adulti`),
    children: (count: number) => (count === 1 ? "1 bambino" : `${count} bambini`),
    statusActive: "Attiva",
    statusInactive: "Non attiva",
    rowActions: (name: string) => `Azioni per ${name}`,
  },
  parameters: {
    title: "3. Parametri operativi",
    description: "Informazioni operative che influenzano l'analisi e l'interpretazione dei dati.",
    edit: "Modifica parametri",
    opening: "Periodo di apertura",
    openAllYear: "Aperto tutto l'anno",
    openSeasonal: "Apertura stagionale",
    annualClosure: (value: string) => `Chiusura annuale: ${value}`,
    noAnnualClosure: "nessuna",
    seasonality: "Stagionalità",
    peakSeason: "Alta stagione",
    capacity: "Capacità operativa rilevante",
    maxCapacity: "Capacità massima",
    guests: (count: number) => (count === 1 ? "1 ospite" : `${count} ospiti`),
  },
  sources: {
    title: "4. Fonti dati",
    description: "Sistemi collegati alla struttura da cui NINFA riceve i dati.",
    listLabel: "Fonti dati collegate e collegabili",
  },
  /** Capitalised on purpose: the page writes "Marzo – Novembre". Index 0 is January. */
  months: [
    "Gennaio",
    "Febbraio",
    "Marzo",
    "Aprile",
    "Maggio",
    "Giugno",
    "Luglio",
    "Agosto",
    "Settembre",
    "Ottobre",
    "Novembre",
    "Dicembre",
  ],
} as const;
