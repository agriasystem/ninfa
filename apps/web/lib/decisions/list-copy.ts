import type { DecisionType } from "@ninfa/contracts";

import { copy } from "@/lib/copy";

/**
 * Italian wording for the redesigned `/decisioni` list. One sentence per decision type, built ONLY from the
 * decision's own target (a stay date, a cost or labor category) - problem + evidence, never a
 * recommendation, never a raw enum. A category the API names in an UPPER_SNAKE code is translated here with
 * its grammatical article ("del cibo", "della cucina"); a code this table does not know yields the generic
 * sentence instead of a guess, and `OTHER` (the unclassified bucket) never names a category at all.
 */

/** "il costo per camera {del cibo}": the cost category with its article. */
const COST_CATEGORY_PHRASE: Record<string, string> = {
  PERSONNEL: "del personale",
  LAUNDRY: "della lavanderia",
  CLEANING: "delle pulizie",
  AMENITIES: "dei prodotti per gli ospiti",
  FOOD: "del cibo",
  BEVERAGE: "delle bevande",
  UTILITIES: "delle utenze",
  MAINTENANCE: "della manutenzione",
  SOFTWARE: "del software",
  MARKETING: "del marketing",
  OTA_COMMISSIONS: "delle commissioni OTA",
  PROFESSIONAL_SERVICES: "dei servizi professionali",
  TRANSPORT: "dei trasporti",
};

/** "le ore di personale {della cucina}": the labor category with its article. */
const LABOR_CATEGORY_PHRASE: Record<string, string> = {
  HOUSEKEEPING: "della governanza",
  FRONT_OFFICE: "del ricevimento",
  FOOD_BEVERAGE: "di sala e bar",
  KITCHEN: "della cucina",
  MAINTENANCE: "della manutenzione",
  MANAGEMENT: "della direzione",
  SPA_WELLNESS: "della spa",
};

export function costCategoryPhrase(category: string): string | null {
  return COST_CATEGORY_PHRASE[category] ?? null;
}

export function laborCategoryPhrase(category: string): string | null {
  return LABOR_CATEGORY_PHRASE[category] ?? null;
}

const BELOW_PACE = "sotto il ritmo atteso";
const BELOW_LEVEL = "sotto il livello atteso";
const ABOVE_LEVEL = "sopra il livello atteso";

/** The row title of each decision type. `stayDate`/`phrase` are `null` when the target carries nothing the
 * sentence can honestly name, and the sentence then simply omits them. */
export function rowTitleOf(
  type: DecisionType,
  subject: { stayDate: string | null; categoryPhrase: string | null },
): string {
  switch (type) {
    case "REV_PICKUP_LOW":
      return subject.stayDate === null
        ? `Le prenotazioni stanno arrivando ${BELOW_PACE}`
        : `Le prenotazioni per il ${subject.stayDate} stanno arrivando ${BELOW_PACE}`;
    case "REV_OCCUPANCY_RISK":
      return subject.stayDate === null
        ? `L'occupazione prevista è ${BELOW_LEVEL}`
        : `L'occupazione prevista per il ${subject.stayDate} è ${BELOW_LEVEL}`;
    case "REV_OTA_DEPENDENCY":
      return `La dipendenza dalle OTA è ${ABOVE_LEVEL}`;
    case "COST_CPOR_ANOMALY":
      return subject.categoryPhrase === null
        ? `Il costo per camera è ${ABOVE_LEVEL}`
        : `Il costo per camera ${subject.categoryPhrase} è ${ABOVE_LEVEL}`;
    case "LABOR_OVERSTAFFING":
      return subject.categoryPhrase === null
        ? `Le ore di personale programmate sono ${ABOVE_LEVEL}`
        : `Le ore di personale ${subject.categoryPhrase} sono ${ABOVE_LEVEL}`;
  }
}

export const decisioniCopy = {
  heading: copy.decisioni.heading,
  /** Section label above the list, for assistive technology. */
  listLabel: "Decisioni di oggi",
  filtersLabel: "Filtra per area",
  all: "Tutte",
  sortLabel: "Ordina per",
  sort: {
    priority: "Priorità",
    recent: "Più recenti",
    oldest: "Aperte da più tempo",
  },
  firstDecision: "Prima decisione",
  involvedAreas: "Aree coinvolte",
  involvedAreasOf: (involved: number, analysed: number) => `${involved} di ${analysed}`,
  rank: (rank: number) => `Priorità ${rank}`,
  reliability: (percent: number) => `Affidabilità ${percent}%`,
  detectedOn: (date: string) => `Rilevata il ${date}`,
  open: "Apri dettaglio",
  openNamed: (title: string) => `Apri dettaglio: ${title}`,
  found: "Rilevato",
  expected: "Atteso",
  countInArea: (area: string, count: number) =>
    count === 1 ? `${area}, 1 decisione` : `${area}, ${count} decisioni`,
  countAll: (count: number) => (count === 1 ? "Tutte, 1 decisione" : `Tutte, ${count} decisioni`),
  emptyArea: {
    clear: "Per quanto analizzato oggi, NINFA non ha decisioni in quest'area.",
    partial: "Analisi parziale: NINFA non può dire che in quest'area vada tutto bene.",
    unavailable: "Quest'area non è stata analizzata oggi.",
  },
  impact: {
    estimated: "Impatto stimato",
    estimatedCost: "stima indicativa del costo sopra il livello atteso",
    estimatedLabor: "stima indicativa del costo del personale sopra il livello atteso",
    missingRooms: "Camere mancanti",
    missingRoomsHint: "rispetto al ritmo atteso",
    roomShortfall: "Camere in meno",
    roomShortfallHint: "rispetto all'atteso a fine finestra",
    otaNights: "Camere-notte da OTA",
    otaNightsHint: "nel periodo osservato",
    costGap: "Scostamento per camera",
    costGapHint: "rispetto al livello atteso",
    excessHours: "Ore in eccesso",
    excessHoursHint: "rispetto alle ore attese",
  },
  metric: {
    pickup: "Pickup rilevato",
    pickupUnit: "camere",
    occupancy: "Camere previste",
    otaShare: "Prenotazioni da OTA",
    costPerRoom: "Costo per camera",
    scheduledHours: "Ore programmate",
    vsExpected: "vs atteso",
    vsExpectedValue: (formatted: string) => `vs atteso ${formatted}`,
    vsReference: (formatted: string) => `vs riferimento ${formatted}`,
    expectedPickup: (formatted: string) => `attesi ${formatted}`,
  },
} as const;
