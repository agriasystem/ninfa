import type { DecisionCardViewModel } from "@/lib/decisions/card-view-models";
import { formatCount, formatDecimal, formatMoney } from "@/lib/decisions/format";
import { formatLocalDateItalian } from "@/lib/date/local-date";

/**
 * "Perché NINFA te lo mostra": one deterministic Italian sentence per decision type, built ONLY
 * from real fields already on the view model (which itself is built only from the real facts
 * whitelist - see `card-view-models.ts`). No AI, no prose generation, no invented values: when a
 * fact this sentence needs is missing, it returns `null` and the caller omits the section
 * entirely rather than printing a half sentence.
 *
 * Each detector's trigger condition is one-directional by construction (`REV_PICKUP_LOW`/
 * `REV_OCCUPANCY_RISK` only fire on a shortfall, `LABOR_OVERSTAFFING` only on an excess,
 * `COST_CPOR_ANOMALY` only above its upper fence - see each detector's own trigger condition),
 * so the wording below never needs to branch on a sign.
 */
export function whySentence(card: DecisionCardViewModel): string | null {
  switch (card.kind) {
    case "PICKUP": {
      if (card.windowDays === null || card.actualPickup === null || card.expectedPickup === null) {
        return null;
      }
      return (
        `Negli ultimi ${card.windowDays} giorni sono entrate ${formatCount(card.actualPickup)} camere, ` +
        `contro le ${formatDecimal(card.expectedPickup, 0)} normalmente attese.`
      );
    }
    case "OCCUPANCY": {
      if (card.occupancyGapPp === null) return null;
      return (
        `Per il ${formatLocalDateItalian(card.stayDate)} l'occupazione prevista è ` +
        `${formatDecimal(card.occupancyGapPp, 0)} punti sotto il livello atteso.`
      );
    }
    case "OTA": {
      if (card.otaShare === null || card.expectedOtaShare === null) return null;
      return (
        `Il ${formatDecimal(card.otaShare, 0)}% delle camere prenotate arriva da OTA, ` +
        `rispetto al ${formatDecimal(card.expectedOtaShare, 0)}% atteso.`
      );
    }
    case "COST": {
      if (card.actualCpor === null || card.deltaPercent === null) return null;
      return (
        `Il costo per camera è ${formatMoney(card.actualCpor, card.currency)}, circa il ` +
        `${formatDecimal(card.deltaPercent, 0)}% sopra il livello atteso.`
      );
    }
    case "LABOR": {
      if (card.scheduledHours === null || card.expectedHours === null) return null;
      return (
        `Sono programmate ${formatDecimal(card.scheduledHours, 0)} ore, contro ` +
        `${formatDecimal(card.expectedHours, 0)} ore normalmente attese.`
      );
    }
  }
}
