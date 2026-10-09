import type { DecisionType, FeedItemResponse } from "@ninfa/contracts";

import { formatBusinessDateItalian } from "@/lib/date/property-date";

/**
 * The Home's hero sentence for the top-priority Decision (Home UI V1) - presentation of what the
 * Decision Engine ALREADY decided, never a new judgement and never a recommendation ("abbassa il
 * prezzo" etc. is checked absent by tests). Returned as typed FRAGMENTS (never an HTML string):
 *
 * - `plain`: connective prose
 * - `strong`: the subject / key concept (dark, heavier)
 * - `accent`: the state phrase (brand blue)
 *
 * No claim here goes beyond the Decision's own data: a pickup Decision concerns ONE stay date, so
 * the sentence names that date - never "i prossimi 14 giorni" (the approved reference's example
 * wording, which no backend field supports; `window_days` is the 7-day pickup MEASUREMENT window).
 * Cost/Labor sentences do not name the category: the API carries it as a raw enum value, and a raw
 * enum is never shown to a user.
 */
export type HeroTone = "plain" | "strong" | "accent";

export interface HeroFragment {
  text: string;
  tone: HeroTone;
}

const plain = (text: string): HeroFragment => ({ text, tone: "plain" });
const strong = (text: string): HeroFragment => ({ text, tone: "strong" });
const accent = (text: string): HeroFragment => ({ text, tone: "accent" });

/** The stay date as Italian prose ("15 agosto"), or `null` when the target carries none (or an
 * unparseable one) - the sentence then simply omits the date instead of guessing. */
function stayDateOf(item: FeedItemResponse): string | null {
  const target = item.target;
  if (target.type !== "REV_PICKUP_LOW" && target.type !== "REV_OCCUPANCY_RISK") return null;
  try {
    return formatBusinessDateItalian(target.stay_date);
  } catch {
    return null;
  }
}

const BELOW_PACE = "sotto il ritmo atteso.";
const BELOW_LEVEL = "sotto il livello atteso.";
const ABOVE_LEVEL = "sopra il livello atteso.";

const heroBuilders: Record<DecisionType, (stayDate: string | null) => HeroFragment[]> = {
  REV_PICKUP_LOW: (stayDate) =>
    stayDate === null
      ? [plain("Le "), strong("prenotazioni"), plain(" stanno arrivando "), accent(BELOW_PACE)]
      : [
          plain("Le "),
          strong("prenotazioni"),
          plain(" per il "),
          strong(stayDate),
          plain(" stanno arrivando "),
          accent(BELOW_PACE),
        ],
  REV_OCCUPANCY_RISK: (stayDate) =>
    stayDate === null
      ? [plain("L'"), strong("occupazione prevista"), plain(" è "), accent(BELOW_LEVEL)]
      : [
          plain("L'"),
          strong("occupazione prevista"),
          plain(" per il "),
          strong(stayDate),
          plain(" è "),
          accent(BELOW_LEVEL),
        ],
  REV_OTA_DEPENDENCY: () => [
    plain("La "),
    strong("quota di prenotazioni da OTA"),
    plain(" è "),
    accent(ABOVE_LEVEL),
  ],
  COST_CPOR_ANOMALY: () => [
    plain("Il "),
    strong("costo per camera"),
    plain(" è "),
    accent(ABOVE_LEVEL),
  ],
  LABOR_OVERSTAFFING: () => [
    plain("Le "),
    strong("ore di personale"),
    plain(" programmate sono "),
    accent(ABOVE_LEVEL),
  ],
};

/** The hero fragments of ONE feed item. A `Record<DecisionType, ...>` makes a sixth decision type
 * fail to compile here instead of silently rendering nothing. */
export function heroFragmentsOf(item: FeedItemResponse): HeroFragment[] {
  return heroBuilders[item.decision_type](stayDateOf(item));
}

/** The plain-text reading of a fragment list (assistive tech, document title, tests). */
export function heroTextOf(fragments: HeroFragment[]): string {
  return fragments.map((fragment) => fragment.text).join("");
}
