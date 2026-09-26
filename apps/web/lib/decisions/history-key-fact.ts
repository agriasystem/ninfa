import type { DecisionCardViewModel } from "@/lib/decisions/card-view-models";
import { formatCount, formatDecimal, formatHours, formatMoney, formatPercent } from "@/lib/decisions/format";

/**
 * ONE compact, synthetic fact per timeline entry - never every score, never a raw dump. Built
 * from the SAME view model the current card and the "why" sentence use, applied to a HISTORICAL
 * observation's own facts (see `components/decision-timeline.tsx`) - never the current detail's
 * facts, so the timeline genuinely reflects what that day looked like.
 */
export function historyKeyFact(card: DecisionCardViewModel): string | null {
  switch (card.kind) {
    case "PICKUP":
      return card.actualPickup !== null ? `${formatCount(card.actualPickup)} camere in pickup` : null;
    case "OCCUPANCY":
      return card.occupancyGapPp !== null
        ? `${formatDecimal(card.occupancyGapPp, 0)} punti sotto l'atteso`
        : null;
    case "OTA":
      return card.otaShare !== null ? `${formatPercent(card.otaShare, 0)} delle prenotazioni da OTA` : null;
    case "COST":
      return card.actualCpor !== null ? `${formatMoney(card.actualCpor, card.currency)} a camera` : null;
    case "LABOR":
      return card.scheduledHours !== null ? `${formatHours(card.scheduledHours, 0)} programmate` : null;
  }
}
