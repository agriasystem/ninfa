import type { AnalysisDomain, DecisionFacts, DecisionFeedResponse, FeedItemResponse } from "@ninfa/contracts";

import { formatMoneyWhole } from "@/lib/data/format";
import { formatBusinessDateItalian } from "@/lib/date/property-date";
import { DOMAIN_OF_DECISION_TYPE } from "@/lib/home/domain-summary";

import {
  buildDecisionCardData,
  confidencePercentOf,
  numberOf,
  textOf,
  type DecisionCardViewModel,
} from "./card-view-models";
import { formatCount, formatDecimal, formatHours, formatMoney, formatPercent } from "./format";
import { costCategoryPhrase, decisioniCopy, laborCategoryPhrase, rowTitleOf } from "./list-copy";
import { whySentence } from "./why-copy";

/**
 * The row model of the redesigned `/decisioni` list: ONE feed item -> everything a row shows, decided here
 * and nowhere else. Every figure is a fact the decision already carries (never invented, never summed across
 * decisions), and the rules this module enforces are the product's own:
 *
 * - "Priorità N" is the engine's ordinal rank, copied verbatim - never an Alta/Media/Bassa bucket;
 * - an economic estimate exists ONLY where the engine recorded one (`economic_proxy`: cost and labor, with
 *   its own currency) and is labelled an indicative estimate; revenue and OTA decisions have no currency and
 *   show their operational gap instead (missing rooms, rooms short, room-nights from OTA);
 * - the small visual compares the two numbers the decision itself carries (found vs expected, or the OTA
 *   share) - it is a picture of those facts, never a trend, because no time series is part of a decision;
 * - nothing here is a recommendation, and a raw enum code never reaches the text.
 */

export interface RowDelta {
  /** "−60,0%", "+17,5 pp", "+37,8%": a signed departure from the level NINFA expected. */
  text: string;
  /** What it is compared with: "vs atteso", "vs riferimento 50%". */
  caption: string;
}

export interface RowMetric {
  label: string;
  /** `null` when the fact is missing: the row then shows a dash, never a made-up number. */
  value: string | null;
  caption: string | null;
  delta: RowDelta | null;
}

export interface RowImpact {
  label: string;
  value: string;
  caption: string;
  /** `true` only for a recorded economic estimate (cost / labor): rendered as an indicative estimate. */
  estimate: boolean;
}

/** The picture of the key metric. Heights / angles are geometry of the numbers below, scaled for display. */
export type RowVisual =
  | { kind: "pair"; found: number; expected: number }
  | { kind: "share"; share: number; reference: number | null };

export interface DecisionRowData {
  decisionId: string;
  rank: number;
  area: AnalysisDomain;
  title: string;
  description: string | null;
  /** The ISO date the decision was first detected - kept for sorting. */
  firstSeenLocalDate: string;
  /** The same date as Italian prose ("24 settembre"), or `null` if it cannot be read. */
  detectedOn: string | null;
  reliabilityPercent: number | null;
  metric: RowMetric;
  impact: RowImpact | null;
  visual: RowVisual | null;
}

const MINUS = "−";

function magnitude(value: string): string {
  return value.replace(/^[+-]/u, "");
}

/** A departure from the expected level, written with the sign the decision type implies: each detector only
 * fires in ONE direction (`why-copy.ts` relies on the same fact), so the sign is a property of the type. */
function departure(value: string | null, sign: "+" | "-", unit: "%" | " pp"): string | null {
  if (value === null) return null;
  const formatted = formatDecimal(magnitude(value), 1);
  if (formatted === "—") return null;
  return `${sign === "-" ? MINUS : "+"}${formatted}${unit}`;
}

function geometry(value: string | number | null): number | null {
  const number = typeof value === "number" ? value : value === null ? Number.NaN : Number.parseFloat(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function pair(found: string | number | null, expected: string | number | null): RowVisual | null {
  const a = geometry(found);
  const b = geometry(expected);
  return a === null || b === null ? null : { kind: "pair", found: a, expected: b };
}

function stayDateOf(item: FeedItemResponse): string | null {
  const target = item.target;
  if (target.type !== "REV_PICKUP_LOW" && target.type !== "REV_OCCUPANCY_RISK") return null;
  try {
    return formatBusinessDateItalian(target.stay_date);
  } catch {
    return null; // an unparseable date is omitted, never guessed
  }
}

function dateProse(isoDate: string): string | null {
  try {
    return formatBusinessDateItalian(isoDate);
  } catch {
    return null;
  }
}

function categoryPhraseOf(item: FeedItemResponse): string | null {
  const target = item.target;
  if (target.type === "COST_CPOR_ANOMALY") return costCategoryPhrase(target.cost_category);
  if (target.type === "LABOR_OVERSTAFFING") return laborCategoryPhrase(target.labor_category);
  return null;
}

function money(amount: string | null, currency: string): string | null {
  return amount === null ? null : formatMoney(amount, currency);
}

interface Built {
  metric: RowMetric;
  impact: RowImpact | null;
  visual: RowVisual | null;
}

function pickup(card: Extract<DecisionCardViewModel, { kind: "PICKUP" }>, facts: DecisionFacts): Built {
  const found = card.actualPickup;
  const delta = departure(textOf(facts, "delta_percent_exact"), "-", "%");
  return {
    metric: {
      label: decisioniCopy.metric.pickup,
      value: found === null ? null : `${formatCount(found)} ${decisioniCopy.metric.pickupUnit}`,
      caption: card.expectedPickup === null ? null : decisioniCopy.metric.expectedPickup(formatDecimal(card.expectedPickup, 1)),
      delta: delta === null ? null : { text: delta, caption: decisioniCopy.metric.vsExpected },
    },
    impact:
      card.missingRooms === null
        ? null
        : {
            label: decisioniCopy.impact.missingRooms,
            value: formatDecimal(card.missingRooms, 1),
            caption: decisioniCopy.impact.missingRoomsHint,
            estimate: false,
          },
    visual: pair(found, card.expectedPickup),
  };
}

function occupancy(card: Extract<DecisionCardViewModel, { kind: "OCCUPANCY" }>): Built {
  const delta = departure(card.occupancyGapPp, "-", " pp");
  return {
    metric: {
      label: decisioniCopy.metric.occupancy,
      value: card.forecastRooms === null ? null : formatDecimal(card.forecastRooms, 1),
      caption: card.expectedFinalRooms === null ? null : decisioniCopy.metric.expectedPickup(formatDecimal(card.expectedFinalRooms, 1)),
      delta: delta === null ? null : { text: delta, caption: decisioniCopy.metric.vsExpected },
    },
    impact:
      card.roomShortfall === null
        ? null
        : {
            label: decisioniCopy.impact.roomShortfall,
            value: formatDecimal(card.roomShortfall, 1),
            caption: decisioniCopy.impact.roomShortfallHint,
            estimate: false,
          },
    visual: pair(card.forecastRooms, card.expectedFinalRooms),
  };
}

function ota(card: Extract<DecisionCardViewModel, { kind: "OTA" }>, facts: DecisionFacts): Built {
  const delta = departure(textOf(facts, "delta_pp_exact"), "+", " pp");
  const nights = numberOf(facts, "ota_room_nights");
  const reference = card.expectedOtaShare === null ? null : formatPercent(card.expectedOtaShare, 0);
  return {
    metric: {
      label: decisioniCopy.metric.otaShare,
      value: card.otaShare === null ? null : formatPercent(card.otaShare, 1),
      caption: null,
      delta:
        delta === null
          ? null
          : { text: delta, caption: reference === null ? decisioniCopy.metric.vsExpected : decisioniCopy.metric.vsReference(reference) },
    },
    impact:
      nights === null
        ? null
        : {
            label: decisioniCopy.impact.otaNights,
            value: formatCount(nights),
            caption: decisioniCopy.impact.otaNightsHint,
            estimate: false,
          },
    visual:
      geometry(card.otaShare) === null
        ? null
        : { kind: "share", share: geometry(card.otaShare) as number, reference: geometry(card.expectedOtaShare) },
  };
}

function cost(
  card: Extract<DecisionCardViewModel, { kind: "COST" }>,
  proxy: FeedItemResponse["economic_proxy"],
): Built {
  const delta = departure(card.deltaPercent, "+", "%");
  const expected = money(card.expectedCpor, card.currency);
  return {
    metric: {
      label: decisioniCopy.metric.costPerRoom,
      value: money(card.actualCpor, card.currency),
      caption: null,
      delta:
        delta === null
          ? null
          : { text: delta, caption: expected === null ? decisioniCopy.metric.vsExpected : decisioniCopy.metric.vsExpectedValue(expected) },
    },
    impact: proxy
      ? {
          label: decisioniCopy.impact.estimated,
          value: formatMoneyWhole(proxy.amount, proxy.currency),
          caption: decisioniCopy.impact.estimatedCost,
          estimate: true,
        }
      : card.deltaCpor === null
        ? null
        : {
            label: decisioniCopy.impact.costGap,
            value: money(card.deltaCpor, card.currency) ?? "—",
            caption: decisioniCopy.impact.costGapHint,
            estimate: false,
          },
    visual: pair(card.actualCpor, card.expectedCpor),
  };
}

function labor(
  card: Extract<DecisionCardViewModel, { kind: "LABOR" }>,
  facts: DecisionFacts,
  proxy: FeedItemResponse["economic_proxy"],
): Built {
  const delta = departure(textOf(facts, "delta_percent_exact"), "+", "%");
  const expected = card.expectedHours === null ? null : formatHours(card.expectedHours, 1);
  return {
    metric: {
      label: decisioniCopy.metric.scheduledHours,
      value: card.scheduledHours === null ? null : formatHours(card.scheduledHours, 1),
      caption: null,
      delta:
        delta === null
          ? null
          : { text: delta, caption: expected === null ? decisioniCopy.metric.vsExpected : decisioniCopy.metric.vsExpectedValue(expected) },
    },
    impact: proxy
      ? {
          label: decisioniCopy.impact.estimated,
          value: formatMoneyWhole(proxy.amount, proxy.currency),
          caption: decisioniCopy.impact.estimatedLabor,
          estimate: true,
        }
      : card.excessHours === null
        ? null
        : {
            label: decisioniCopy.impact.excessHours,
            value: formatHours(card.excessHours, 1),
            caption: decisioniCopy.impact.excessHoursHint,
            estimate: false,
          },
    visual: pair(card.scheduledHours, card.expectedHours),
  };
}

function builtOf(item: FeedItemResponse, card: DecisionCardViewModel): Built {
  switch (card.kind) {
    case "PICKUP":
      return pickup(card, item.facts);
    case "OCCUPANCY":
      return occupancy(card);
    case "OTA":
      return ota(card, item.facts);
    case "COST":
      return cost(card, item.economic_proxy);
    case "LABOR":
      return labor(card, item.facts, item.economic_proxy);
  }
}

/** ONE feed item -> one row. `rank` is the backend's own, copied verbatim. */
export function buildDecisionRow(item: FeedItemResponse): DecisionRowData {
  const base = buildDecisionCardData(item);
  const built = builtOf(item, base.card);
  return {
    decisionId: item.decision_id,
    rank: item.priority.rank,
    area: DOMAIN_OF_DECISION_TYPE[item.decision_type],
    title: rowTitleOf(item.decision_type, { stayDate: stayDateOf(item), categoryPhrase: categoryPhraseOf(item) }),
    description: whySentence(base.card),
    firstSeenLocalDate: item.first_seen_local_date,
    detectedOn: dateProse(item.first_seen_local_date),
    reliabilityPercent: confidencePercentOf(item.priority.confidence_score),
    ...built,
  };
}

/** Every row of a feed, in the BACKEND's order (`priority_rank ASC`) - never re-sorted here. */
export function buildDecisionRows(feed: DecisionFeedResponse): DecisionRowData[] {
  return feed.items.map(buildDecisionRow);
}

export type DecisionSort = "priority" | "recent" | "oldest";

/** The default `priority` returns the rows exactly as given. `recent` / `oldest` order by the date the
 * decision was first detected (ISO dates sort chronologically as text) with the engine's rank as the tie
 * break, so the order is always deterministic. */
export function sortRows(rows: readonly DecisionRowData[], sort: DecisionSort): DecisionRowData[] {
  if (sort === "priority") return [...rows];
  const direction = sort === "recent" ? -1 : 1;
  return [...rows].sort((a, b) => {
    if (a.firstSeenLocalDate !== b.firstSeenLocalDate) {
      return a.firstSeenLocalDate < b.firstSeenLocalDate ? -direction : direction;
    }
    return a.rank - b.rank;
  });
}

export function countByArea(rows: readonly DecisionRowData[]): Record<AnalysisDomain, number> {
  const counts: Record<AnalysisDomain, number> = { REVENUE: 0, DISTRIBUTION: 0, COSTS: 0, LABOR: 0 };
  for (const row of rows) counts[row.area] += 1;
  return counts;
}
