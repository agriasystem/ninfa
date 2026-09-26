import type { DecisionFacts } from "@ninfa/contracts";

import { copy } from "@/lib/copy";

import { confidencePercentOf, numberOf, textOf, type DecisionCardViewModel } from "./card-view-models";
import { formatCount, formatDecimal, formatHours, formatMoney, formatPercent } from "./format";

export interface EvidenceRow {
  label: string;
  value: string;
}

/**
 * At most 3-5 rows: Attuale/Atteso/Scostamento (from the SAME view model the card and the "why"
 * sentence already use - never a second reading of the facts), Affidabilità (the observation's
 * own `confidence_score`), and ONE coverage/sample row - shown ONLY when the real `evidence`
 * record carries EXACTLY that information (never invented for a type whose contract does not
 * have it).
 */
export function evidenceRows(
  card: DecisionCardViewModel,
  confidenceScore: string,
  evidence: DecisionFacts,
): EvidenceRow[] {
  const rows: EvidenceRow[] = [];

  switch (card.kind) {
    case "PICKUP":
      if (card.actualPickup !== null) {
        rows.push({ label: copy.detail.evidenceActual, value: formatCount(card.actualPickup) });
      }
      if (card.expectedPickup !== null) {
        rows.push({ label: copy.detail.evidenceExpected, value: formatDecimal(card.expectedPickup, 0) });
      }
      if (card.deltaRooms !== null) {
        rows.push({ label: copy.detail.evidenceDelta, value: formatDecimal(card.deltaRooms, 0) });
      }
      break;
    case "OCCUPANCY":
      if (card.forecastRooms !== null) {
        rows.push({ label: copy.detail.evidenceActual, value: formatDecimal(card.forecastRooms, 0) });
      }
      if (card.expectedFinalRooms !== null) {
        rows.push({
          label: copy.detail.evidenceExpected,
          value: formatDecimal(card.expectedFinalRooms, 0),
        });
      }
      if (card.occupancyGapPp !== null) {
        rows.push({ label: copy.detail.evidenceDelta, value: formatPercent(card.occupancyGapPp, 0) });
      }
      break;
    case "OTA":
      if (card.otaShare !== null) {
        rows.push({ label: copy.detail.evidenceActual, value: formatPercent(card.otaShare, 0) });
      }
      if (card.expectedOtaShare !== null) {
        rows.push({ label: copy.detail.evidenceExpected, value: formatPercent(card.expectedOtaShare, 0) });
      }
      break;
    case "COST":
      if (card.actualCpor !== null) {
        rows.push({ label: copy.detail.evidenceActual, value: formatMoney(card.actualCpor, card.currency) });
      }
      if (card.expectedCpor !== null) {
        rows.push({
          label: copy.detail.evidenceExpected,
          value: formatMoney(card.expectedCpor, card.currency),
        });
      }
      if (card.deltaPercent !== null) {
        rows.push({ label: copy.detail.evidenceDelta, value: formatPercent(card.deltaPercent, 0) });
      }
      break;
    case "LABOR":
      if (card.scheduledHours !== null) {
        rows.push({ label: copy.detail.evidenceActual, value: formatHours(card.scheduledHours, 0) });
      }
      if (card.expectedHours !== null) {
        rows.push({ label: copy.detail.evidenceExpected, value: formatHours(card.expectedHours, 0) });
      }
      if (card.excessHours !== null) {
        rows.push({ label: copy.detail.evidenceDelta, value: formatHours(card.excessHours, 0) });
      }
      break;
  }

  const confidencePercent = confidencePercentOf(confidenceScore);
  if (confidencePercent !== null) {
    rows.push({ label: copy.detail.reliabilityLabel, value: `${confidencePercent}%` });
  }

  const coveragePercent = textOf(evidence, "classification_coverage_pct_exact");
  const comparablePairs = numberOf(evidence, "pattern_pair_count");
  if (coveragePercent !== null) {
    rows.push({ label: "", value: copy.detail.evidenceCoverage(formatPercent(coveragePercent, 0)) });
  } else if (comparablePairs !== null) {
    rows.push({ label: "", value: copy.detail.evidenceComparablePeriods(comparablePairs) });
  }

  return rows.slice(0, 5);
}
