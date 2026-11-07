import type {
  AnalysisDomain,
  DataDateConflicts,
  DomainState,
  LaborRevenueGap,
  NightStatus,
} from "@ninfa/contracts";

import { formatPercent } from "@/lib/data/format";
import { formatCount } from "@/lib/decisions/format";

/**
 * Centralised Italian copy for Dati UI V1 - one source per string, exactly like `lib/copy.ts`.
 *
 * Wording rules that are product decisions, not style:
 * - ricavi camera "sulle prenotazioni già a sistema" (on-books): NEVER fatturato, incassi, utile or
 *   margine - NINFA has no accounting model of revenue;
 * - "camere-notte", never "prenotazioni": a multi-night booking is one booking but several room-nights;
 * - a freshness is a FACT ("Ultimo import ..."), never "Dati aggiornati";
 * - a percentage is never compared with a "target": the OTA level is "Riferimento NINFA";
 * - nothing here ever shows a technical identifier: every backend code is mapped to plain Italian
 *   below, and anything unknown falls back to a neutral phrase rather than the raw code.
 */
export const datiCopy = {
  heading: "Dati",
  subtitle: "I numeri operativi della struttura.",
  tabsLabel: "Sezioni di Dati",
  tabs: {
    overview: "Panoramica",
    bookings: "Prenotazioni",
    distribution: "Distribuzione",
    costs: "Costi",
    labor: "Personale",
  },
  refresh: "Aggiorna dati",
  /** The accessible name of a table's scroll region: never the same as its card's title. */
  scrollable: (name: string) => `Tabella scorrevole: ${name}`,
  retry: "Riprova",
  loadError: "Non siamo riusciti a caricare i dati. Riprova.",
  loading: "Caricamento dei dati in corso",
  notAvailable: "Non disponibile",
  period: {
    groupLabel: "Periodo",
    days7: "7 giorni",
    days30: "30 giorni",
    nextDays: (days: number) => `prossimi ${days} giorni`,
  },
  occupancy: {
    title: "Occupazione",
    basis: "sulle prenotazioni attuali",
    roomNightsBooked: (count: number) => `${formatCount(count)} camere-notte prenotate`,
    capacityKnownFor: (known: number, total: number) => `Capienza nota per ${known} di ${total} notti`,
    capacityUnknown: "Capienza non nota per questo periodo",
    bookingsKnownFor: (known: number, total: number) =>
      `Prenotazioni registrate per ${known} di ${total} notti`,
    todayTile: "Oggi",
    sevenTile: "7 giorni",
    thirtyTile: "30 giorni",
    roomsOfAvailable: (booked: number, available: number) =>
      `${formatCount(booked)} / ${formatCount(available)} camere`,
    roomNightsShort: (count: number) => `${formatCount(count)} camere-notte`,
    unavailableTitle: "Occupazione non disponibile",
    miniTilesLabel: "Occupazione per periodo",
    // No room inventory: the bookings are real, only what needs the number of rooms is missing. A
    // capacity is never inferred from the bookings.
    inventoryMissingValue: "Inventario camere da configurare",
    inventoryMissingNote: "Le prenotazioni sono disponibili, ma manca la capacità camere della struttura.",
    inventoryAwaitingValue: "Occupazione non ancora calcolata",
    inventoryAwaitingNote:
      "L'inventario camere è configurato: l'occupazione sarà calcolata alla prossima analisi delle prenotazioni.",
    configureInventory: "Configura inventario",
    notComputable: "Non calcolabile",
  },
  kpi: {
    groupLabel: "Indicatori del periodo",
    roomRevenue: "Ricavi camera",
    roomRevenueNote: "prenotazioni già a sistema",
    adr: "ADR",
    adrNote: "tariffa media on-books",
    roomNights: "Camere-notte",
    roomNightsNote: "prenotate sulle notti del periodo",
    costs: (month: string) => `Costi di ${month}`,
    costsNote: "ultimo mese concluso, per data fattura",
    deltaVsWeek: (signed: string) => `${signed} vs 7 giorni fa`,
    deltaVsMonth: (signed: string, month: string) => `${signed} vs ${month}`,
  },
  chart: {
    title: (days: number) => `Occupazione prossimi ${days} giorni`,
    subtitle: "Camere prenotate su camere disponibili, notte per notte",
    ariaSummary: (days: number) =>
      `Grafico a barre: occupazione sulle prenotazioni attuali per ciascuna delle prossime ${days} notti. I valori sono nella tabella equivalente.`,
    tableCaption: "Occupazione per notte (equivalente testuale del grafico)",
    colNight: "Notte",
    colOccupancy: "Occupazione",
    attentionLegend: "Richiede attenzione",
    attentionTip: "Richiede attenzione",
    unknownCapacityLegend: "Capienza non nota",
    unknownCapacityTip: "Capienza non nota: occupazione non calcolabile",
    noDataTip: "Nessun dato per questa notte",
    emptyTitle: "Nessun dato di occupazione",
    inventoryMissingTitle: "Occupazione non calcolabile",
    inventoryMissingBody:
      "Per calcolare l'occupazione NINFA deve conoscere il numero di camere disponibili della struttura.",
    inventoryAwaitingTitle: "Occupazione non ancora calcolata",
    axisLabel: "Occupazione (%)",
  },
  distribution: {
    title: "Dipendenza OTA",
    window: (range: string) => `${range}`,
    ota: "OTA",
    direct: "Diretto",
    reference: (formatted: string) => `Riferimento NINFA: ${formatted}`,
    attention: "Richiede attenzione",
    coverageShare: (formatted: string) => `Prenotazioni su canali classificati: ${formatted}`,
    channelsTitle: "Peso dei canali",
    channelsNote:
      "Il peso è sul totale delle camere-notte di tutti i canali: non coincide con la quota OTA, che è sul solo totale OTA + diretto.",
    channelsEmpty: "Nessuna prenotazione certa da cui ricavare il peso dei canali.",
    // What the weights are a share of - always said, never left to guess.
    channelsBasis: (total: number) =>
      `Percentuali su ${formatCount(total)} camere-notte dei prossimi 30 giorni.`,
    channelsBasisOnBooks: (total: number) =>
      `Percentuali su tutte le ${formatCount(total)} camere-notte prenotate nei prossimi 30 giorni.`,
    channelsBasisOnBooksUnclassified: (total: number, unclassified: number) =>
      `Percentuali su tutte le ${formatCount(total)} camere-notte prenotate nei prossimi 30 giorni, comprese ${formatCount(unclassified)} su canali non classificati.`,
    channelsIndicative: (total: number, onBooks: number) =>
      `Composizione indicativa: le percentuali sono su ${formatCount(total)} camere-notte, non sulle ${formatCount(onBooks)} prenotate nei prossimi 30 giorni.`,
    checkBookingsHint: "Controlla queste prenotazioni nei dati importati.",
    channelRoomNights: (count: number) => `${formatCount(count)} camere-notte`,
    allChannels: (count: number) => `Tutti i ${count} canali`,
    moreChannels: (count: number) => (count === 1 ? "+ 1 altro canale" : `+ altri ${count} canali`),
    infoTitle: "Come leggere i numeri",
    defOtaTerm: "Quota OTA",
    defOtaText:
      "Le camere-notte prenotate sulle OTA rispetto al totale OTA + diretto, nei prossimi 30 giorni. Gli altri canali non sono nel totale.",
    defWeightTerm: "Peso di un canale",
    defWeightText:
      "Le camere-notte di quel canale rispetto a tutte le camere-notte prenotate. È una misura diversa dalla quota OTA.",
    defReferenceTerm: "Riferimento NINFA",
    defReferenceText:
      "Il livello di quota OTA che NINFA si aspetta per questa struttura. Non è un obiettivo.",
    notAnalyzedTitle: "Distribuzione non analizzata",
    unavailableTitle: "Distribuzione non disponibile",
    insufficientTitle: "Dati insufficienti",
    insufficientBecause: (reasons: string) => `Perché: ${reasons}.`,
  },
  table: {
    title: "Dettaglio soggiorni",
    caption: "Dettaglio per notte di soggiorno",
    scrollRegion: "Tabella scorrevole: dettaglio per notte",
    colDate: "Data",
    colBookings: "Prenotazioni",
    colRoomsBooked: "Camere prenotate",
    colAvailable: "Disponibili",
    colOccupancy: "Occupazione",
    colRevenue: "Ricavi camera",
    colAdr: "ADR",
    colSevenAgo: "7 giorni fa",
    colChange: "Variazione",
    colStatus: "Stato",
    searchLabel: "Cerca per data",
    searchPlaceholder: "Cerca data",
    attentionOnly: "Solo attenzione",
    empty: "Nessuna notte corrisponde alla ricerca.",
    noData: "Non disponibile",
    notePartial:
      "Lo stato riflette solo le decisioni di NINFA per la notte: non è un giudizio sui numeri.",
    noteInventory:
      "Disponibili e occupazione compariranno quando NINFA conoscerà le camere disponibili della struttura.",
    shown: (shown: number, total: number) => `${shown} di ${total} notti`,
    openDecision: "Apri la decisione",
  },
  status: {
    ATTENTION: "Attenzione",
    PARTIAL: "Analisi parziale",
    REGULAR: "Regolare",
    NOT_EVALUATED: "Non valutato",
  } satisfies Record<NightStatus, string>,
  summary: {
    title: "Riepilogo per periodo",
    caption: "Occupazione e ricavi per periodo",
    colPeriod: "Periodo",
    colOccupancy: "Occupazione",
    colRoomNights: "Camere-notte",
    colAvailable: "Camere disponibili",
    colRevenue: "Ricavi camera",
    colAdr: "ADR",
    colChange: "Variazione vs 7 giorni fa",
    today: "Oggi",
    capacityNote: "La capienza disponibile conta solo le notti con capienza nota.",
    changeNote:
      "La variazione compare solo quando ogni notte del periodo ha un dato sia oggi sia nello snapshot di 7 giorni fa.",
  },
  costs: {
    summaryTitle: (month: string) => `Costi di ${month}`,
    basis: "Ultimo mese concluso, per data fattura. Il mese in corso non è mostrato.",
    total: "Costo netto registrato",
    deltaVsMonth: (signed: string, month: string) => `${signed} vs ${month}`,
    classification: (formatted: string) => `Costi in una categoria riconosciuta: ${formatted}`,
    otherCurrencies: "Sono presenti costi in un'altra valuta: non sono inclusi.",
    categoriesTitle: "Costi per categoria",
    caption: "Costi del mese per categoria",
    colCategory: "Categoria",
    colNet: "Costo netto",
    colCpor: "Costo per camera occupata",
    emptyTitle: "Costi non disponibili",
    emptyBody: "Non ci sono dati di costo sufficienti per questo periodo.",
    decisionTitle: "Costo per camera sopra il normale",
    decisionBody: (month: string, category: string) => `${category}, ${month}`,
    decisionFigures: (actual: string, expected: string) =>
      `Costo per camera occupata ${actual}, atteso ${expected}`,
    decisionLink: "Apri la decisione",
    attentionRow: "Richiede attenzione",
    notAnalyzedNote: "I costi non fanno parte dell'analisi di oggi: qui sono mostrati i dati registrati.",
  },
  labor: {
    heading: "Personale",
    subtitle: "Ore, costi e impatto sul business della tua struttura.",
    kpiGroupLabel: "Indicatori del personale",
    basis: (range: string) => `Prossimi 7 giorni (${range}), dal piano più recente.`,
    kpi: {
      hours: "Ore pianificate",
      cost: "Costo pianificato",
      hourlyCost: "Costo medio/ora",
      incidence: "Incidenza sui ricavi on-books",
      revenuePerHour: "Ricavo on-books per ora",
      hoursNote: (range: string) => `Prossimi 7 giorni (${range})`,
      samePeriod: "Stesso periodo delle ore",
      hourlyCostNote: "Costo pianificato diviso le ore pianificate",
      incidenceNote: "Sui ricavi on-books degli stessi giorni",
      revenuePerHourNote: "Ricavi on-books per ora di personale, non per singola persona",
      noCost: "Non tutte le righe del piano hanno un costo.",
      noHours: "Non ci sono ore pianificate per questo periodo.",
    },
    hoursAndCostsTitle: "Ore e costi del personale",
    factHours: "Ore totali",
    factCost: "Costo totale",
    factHourlyCost: "Costo medio/ora",
    factRevenue: "Ricavi on-books",
    revenueNote: (range: string) =>
      `Ricavi delle camere già prenotate, ${range}: solo ciò che è a sistema oggi.`,
    synthesisTitle: "In sintesi",
    categoriesTitle: "Ore e performance per ruolo",
    caption: "Ore, costi e peso di ogni ruolo",
    colCategory: "Ruolo",
    colHours: "Ore pianificate",
    colCost: "Costo pianificato",
    colHourlyCost: "Costo medio/ora",
    colShare: "% costo personale",
    colDays: "Giorni con dati",
    colIncidence: "Incidenza sui ricavi on-books",
    daysComplete: (complete: number) => `${complete}`,
    daysIncomplete: (incomplete: number) =>
      incomplete === 1 ? "1 giorno incompleto" : `${incomplete} giorni incompleti`,
    daysWithData: (count: number) => (count === 1 ? "1 giorno con dati" : `${count} giorni con dati`),
    emptyTitle: "Personale non disponibile",
    emptyBody: "Non ci sono ore pianificate disponibili per questo periodo.",
    decisionTitle: "Possibile sovradimensionamento del personale",
    decisionFigures: (scheduled: string, expected: string, excess: string) =>
      `Programmate ${scheduled}, attese ${expected}: ${excess} in più`,
    decisionLink: "Apri la decisione",
    notAnalyzedNote:
      "Il personale non fa parte dell'analisi di oggi: qui sono mostrate le ore pianificate registrate.",
    // Why there is no revenue beside the labor figures: they are only ever compared on the same days.
    revenueGap: {
      NO_LABOR: "Non ci sono ore pianificate da confrontare.",
      NO_ANALYSIS: "Servono prenotazioni analizzate per gli stessi giorni.",
      PERIOD_NOT_COVERED:
        "Non ci sono ricavi on-books confrontabili per tutti i giorni di questo periodo.",
      LABOR_INCOMPLETE: "Alcuni giorni del piano sono senza ore: il confronto non sarebbe corretto.",
      NO_REVENUE: "Non ci sono ricavi on-books in questi giorni.",
    } satisfies Record<LaborRevenueGap, string>,
    // Deterministic, from the backend's own figures.
    synthesis: {
      complete: (incidence: string, hourlyCost: string) =>
        `Il costo del personale incide per il ${incidence} sui ricavi on-books del periodo, con un costo medio di ${hourlyCost} per ora pianificata.`,
      hoursAndCosts:
        "Sono disponibili ore e costi del personale. Le metriche legate ai ricavi on-books saranno calcolate quando NINFA avrà ricavi on-books confrontabili sullo stesso periodo.",
      noCost:
        "Sono disponibili le ore del personale. Costo medio e incidenza sui ricavi on-books saranno calcolati quando tutte le righe del piano avranno un costo.",
    },
  },
  freshness: {
    bookings: "Ultimo import prenotazioni",
    costs: "Ultimo import costi",
    labor: "Ultimo import personale",
    unknown: {
      NO_SOURCE: "nessuna origine dati configurata",
      SEVERAL_SOURCES: "più origini dati: non confrontabili",
      NO_IMPORT: "nessun import completato",
    } as Record<string, string>,
    unknownFallback: "non disponibile",
  },
  coverage: {
    title: "Copertura dell'analisi",
    lastAnalysis: (businessDate: string) => `L'ultima analisi completata risale al ${businessDate}.`,
    neverAnalyzed: "NINFA non ha ancora completato una prima analisi.",
  },
  emptyStates: {
    bookingsNone: "Non ci sono dati di prenotazione per questa struttura nel periodo.",
  },
} as const;

// --- code -> plain Italian (never a raw code on screen) ---------------------------------------------

/** Why a block has no figure - rendered as a short sentence under its title. */
const UNAVAILABLE_REASONS: Record<string, string> = {
  NO_ANALYSIS: "L'analisi di oggi non è ancora disponibile.",
  NO_BOOKING_SOURCE: "L'origine dei dati di prenotazione non è registrata per questa analisi.",
  NO_BOOKING_DATA: "Non ci sono prenotazioni registrate per questo periodo.",
  COVERAGE_UNKNOWN: "La copertura dell'analisi non è registrata per questa analisi.",
  NOT_ANALYZED: "Quest'area non è stata analizzata.",
  EVALUATION_FAILED: "In questo momento non è stato possibile calcolare questo valore.",
  NO_DATA: "Non ci sono dati sufficienti per questo periodo.",
  NO_OCCUPANCY: "Mancano i dati di occupazione necessari.",
  NO_SOURCE: "Nessuna origine dati disponibile.",
  SEVERAL_SOURCES: "Ci sono più origini dati: NINFA non ne sceglie una.",
};

export function unavailableReasonText(reason: string | null): string {
  return (reason !== null ? UNAVAILABLE_REASONS[reason] : undefined) ?? "Dato non disponibile.";
}

const COST_CATEGORIES: Record<string, string> = {
  PERSONNEL: "Personale",
  LAUNDRY: "Lavanderia",
  CLEANING: "Pulizie",
  AMENITIES: "Prodotti per gli ospiti",
  FOOD: "Cibo",
  BEVERAGE: "Bevande",
  UTILITIES: "Utenze",
  MAINTENANCE: "Manutenzione",
  SOFTWARE: "Software",
  MARKETING: "Marketing",
  OTA_COMMISSIONS: "Commissioni OTA",
  PROFESSIONAL_SERVICES: "Servizi professionali",
  TRANSPORT: "Trasporti",
  OTHER: "Non classificato",
};

export function costCategoryLabel(category: string): string {
  return COST_CATEGORIES[category] ?? "Altra voce";
}

const LABOR_CATEGORIES: Record<string, string> = {
  HOUSEKEEPING: "Governanza",
  FRONT_OFFICE: "Ricevimento",
  FOOD_BEVERAGE: "Sala e bar",
  KITCHEN: "Cucina",
  MAINTENANCE: "Manutenzione",
  MANAGEMENT: "Direzione",
  SPA_WELLNESS: "Spa e benessere",
  OTHER: "Altro personale",
};

export function laborCategoryLabel(category: string): string {
  return LABOR_CATEGORIES[category] ?? "Altro personale";
}

const CHANNEL_GROUPS: Record<string, string> = {
  OTA: "OTA",
  DIRECT: "Diretto",
  OTHER: "Altro canale",
  UNKNOWN: "Non classificato",
};

export function channelGroupLabel(group: string): string {
  return CHANNEL_GROUPS[group] ?? "Non classificato";
}

/** What the OTA check concluded, as one sentence (never "va tutto bene"). */
const OTA_OUTCOMES: Record<string, string> = {
  CLEAR: "Per quanto analizzato oggi, NINFA non rileva criticità sulla dipendenza OTA.",
  INSUFFICIENT_DATA: "I dati non bastano per valutare la dipendenza OTA.",
  SUPPRESSED: "Il valore non è abbastanza affidabile per una valutazione.",
  NOT_APPLICABLE: "Il controllo sulla dipendenza OTA non è applicabile ai dati di oggi.",
  CHANGED_AFTER_ANALYSIS:
    "I dati di prenotazione sono cambiati dopo l'analisi di oggi: NINFA non mostra la quota finché l'analisi non viene rifatta.",
};

export function otaOutcomeText(outcome: string | null): string | null {
  return outcome === null ? null : (OTA_OUTCOMES[outcome] ?? null);
}

const OTA_INSUFFICIENT_REASONS: Record<string, string> = {
  OTA_NO_ON_BOOKS_DEMAND: "nei prossimi 30 giorni non ci sono prenotazioni",
  OTA_BOOKING_VOLUME_LOW: "le prenotazioni classificate come OTA o dirette sono troppo poche",
  OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW:
    "troppe prenotazioni sono su canali non classificabili come OTA o diretti",
  OTA_SNAPSHOT_WINDOW_INCOMPLETE: "i dati di prenotazione dei prossimi 30 giorni sono incompleti",
  OTA_SNAPSHOT_WINDOW_UNCERTAIN: "alcune prenotazioni del periodo hanno uno stato incerto",
  // the fallback when the bookings' own dates do not explain it (see `dateConflictsText`)
  OTA_CHANNEL_MIX_RECONCILIATION_FAILED:
    "le prenotazioni lette per canale non coincidono con quelle registrate per lo stesso periodo",
  OTA_COMPARABLE_SAMPLE_INSUFFICIENT:
    "mancano periodi storici confrontabili per stabilire il livello atteso",
  LOW_CONFIDENCE: "l'affidabilità del confronto è troppo bassa",
};

function plural(count: number, one: string, many: string): string {
  return count === 1 ? `1 ${one}` : `${formatCount(count)} ${many}`;
}

/** Why the channel mix does not reconcile with the bookings on the books, in the bookings' own terms:
 * how many of the period have dates that contradict today, and how. Counted by the backend. */
export function dateConflictsText(conflicts: DataDateConflicts): string {
  const parts = [
    conflicts.booked_after > 0
      ? plural(conflicts.booked_after, "risulta prenotata dopo oggi", "risultano prenotate dopo oggi")
      : null,
    conflicts.cancelled_after > 0
      ? plural(conflicts.cancelled_after, "risulta cancellata dopo oggi", "risultano cancellate dopo oggi")
      : null,
    conflicts.no_show_before_arrival > 0
      ? plural(
          conflicts.no_show_before_arrival,
          "è segnata come non presentata per un soggiorno non ancora iniziato",
          "sono segnate come non presentate per soggiorni non ancora iniziati",
        )
      : null,
  ].filter((part): part is string => part !== null);
  const head = plural(
    conflicts.total,
    "prenotazione del periodo ha date incoerenti con oggi",
    "prenotazioni del periodo hanno date incoerenti con oggi",
  );
  return `${head} (${parts.join("; ")})`;
}

/** The facts a reason can be stated with: the OTA check's own classification coverage, and the date
 * conflicts read beside the channel weights. */
export interface OtaReasonFacts {
  conflicts?: DataDateConflicts | null;
  coveragePct?: string | null;
}

export function otaInsufficientReasonsText(codes: readonly string[], facts: OtaReasonFacts = {}): string {
  const phrases = codes.map((code) => {
    if (code === "OTA_CHANNEL_MIX_RECONCILIATION_FAILED" && facts.conflicts && facts.conflicts.total > 0) {
      return dateConflictsText(facts.conflicts);
    }
    if (code === "OTA_CHANNEL_CLASSIFICATION_COVERAGE_LOW" && facts.coveragePct) {
      return `NINFA riconosce come OTA o dirette solo il ${formatPercent(facts.coveragePct)} delle camere-notte del periodo: le altre sono su canali non classificati o di altro tipo`;
    }
    return OTA_INSUFFICIENT_REASONS[code] ?? "dati insufficienti";
  });
  return [...new Set(phrases)].join("; ");
}

const CPOR_STATUSES: Record<string, string> = {
  NO_OCCUPANCY_SOURCE: "Occupazione non disponibile",
  INCOMPLETE: "Occupazione del mese incompleta",
  ZERO_OCCUPANCY: "Nessuna camera occupata nel mese",
  LOW_CLASSIFICATION_COVERAGE: "Troppe spese non classificate",
  NO_COST_DATA: "Nessun costo",
  NOT_APPLICABLE: "Non applicabile",
};

export function cporStatusText(status: string): string {
  return CPOR_STATUSES[status] ?? "Non disponibile";
}

// Each area agrees with its own grammatical gender/number, like `domainNotAnalyzedCopy` on the Home.
const ANALYZED: Record<AnalysisDomain, string> = {
  REVENUE: "Analizzati",
  DISTRIBUTION: "Analizzata",
  COSTS: "Analizzati",
  LABOR: "Analizzato",
};
const NOT_ANALYZED: Record<AnalysisDomain, string> = {
  REVENUE: "Non analizzati",
  DISTRIBUTION: "Non analizzata",
  COSTS: "Non analizzati",
  LABOR: "Non analizzato",
};

export function domainStateText(domain: AnalysisDomain, state: DomainState): string {
  switch (state) {
    case "ANALYZED":
      return ANALYZED[domain];
    case "NOT_ANALYZED":
      return NOT_ANALYZED[domain];
    case "PARTIAL":
      return "Analisi parziale";
    case "UNKNOWN":
      return "Non disponibile";
  }
}

export function nightStatusText(status: NightStatus): string {
  return datiCopy.status[status] ?? datiCopy.status.NOT_EVALUATED;
}
