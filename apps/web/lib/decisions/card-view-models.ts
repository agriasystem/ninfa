import type {
  CostDecisionTarget,
  DecisionFacts,
  DecisionTarget,
  EconomicProxy,
  FeedItemResponse,
  LaborDecisionTarget,
  OtaDecisionTarget,
  RevenueDecisionTarget,
} from "@ninfa/contracts";

import { decisionTypeTitles } from "@/lib/copy";

/**
 * Explicit, per-decision_type view-model adapters over the REAL Gate 12 facts contract (see
 * `services/api/app/api/v1/decisions/serializers.py`'s own `_FACTS_WHITELIST`, audited by hand
 * against this file). No `Object.entries(facts)`, no raw JSON, no invented field. Every
 * `*_exact`/Decimal-shaped fact is kept as its ORIGINAL STRING here - formatting for display
 * happens only in the component that renders it (`lib/decisions/format.ts`), and nothing here
 * ever parses one back into a number for a decision (no ranking, no thresholding).
 */

/** Exported for reuse by `lib/decisions/evidence-rows.ts` (Gate 15), which reads the SAME
 * `evidence` record shape, never a duplicate reader. */
export function textOf(facts: DecisionFacts, key: string): string | null {
  const value = facts[key];
  return typeof value === "string" ? value : null;
}

export function numberOf(facts: DecisionFacts, key: string): number | null {
  const value = facts[key];
  return typeof value === "number" ? value : null;
}

function boolOf(facts: DecisionFacts, key: string): boolean | null {
  const value = facts[key];
  return typeof value === "boolean" ? value : null;
}

export interface PickupCardViewModel {
  kind: "PICKUP";
  stayDate: string;
  windowDays: number | null;
  actualPickup: number | null;
  expectedPickup: string | null;
  deltaRooms: string | null;
  missingRooms: string | null;
}

export interface OccupancyCardViewModel {
  kind: "OCCUPANCY";
  stayDate: string;
  forecastRooms: string | null;
  expectedFinalRooms: string | null;
  occupancyGapPp: string | null;
  roomShortfall: string | null;
}

export interface OtaCardViewModel {
  kind: "OTA";
  windowStart: string;
  windowEnd: string;
  otaShare: string | null;
  expectedOtaShare: string | null;
  structuralCondition: boolean | null;
  risingCondition: boolean | null;
}

export interface CostCardViewModel {
  kind: "COST";
  costCategory: string;
  periodStart: string;
  currency: string;
  actualCpor: string | null;
  expectedCpor: string | null;
  deltaCpor: string | null;
  deltaPercent: string | null;
}

export interface LaborCardViewModel {
  kind: "LABOR";
  workDate: string;
  laborCategory: string;
  scheduledHours: string | null;
  expectedHours: string | null;
  excessHours: string | null;
}

export type DecisionCardViewModel =
  | PickupCardViewModel
  | OccupancyCardViewModel
  | OtaCardViewModel
  | CostCardViewModel
  | LaborCardViewModel;

export interface DecisionCardData {
  decisionId: string;
  rank: number;
  title: string;
  confidencePercent: number | null;
  economicProxy: EconomicProxy | null;
  card: DecisionCardViewModel;
}

function pickupCard(target: RevenueDecisionTarget, facts: DecisionFacts): PickupCardViewModel {
  return {
    kind: "PICKUP",
    stayDate: target.stay_date,
    windowDays: numberOf(facts, "window_days"),
    actualPickup: numberOf(facts, "actual_pickup"),
    expectedPickup: textOf(facts, "expected_pickup"),
    deltaRooms: textOf(facts, "delta_rooms"),
    missingRooms: textOf(facts, "missing_rooms"),
  };
}

function occupancyCard(target: RevenueDecisionTarget, facts: DecisionFacts): OccupancyCardViewModel {
  return {
    kind: "OCCUPANCY",
    stayDate: target.stay_date,
    forecastRooms: textOf(facts, "forecast_rooms"),
    expectedFinalRooms: textOf(facts, "expected_final_rooms"),
    occupancyGapPp: textOf(facts, "occupancy_gap_pp_exact"),
    roomShortfall: textOf(facts, "room_shortfall"),
  };
}

function otaCard(_target: OtaDecisionTarget, facts: DecisionFacts): OtaCardViewModel {
  return {
    kind: "OTA",
    windowStart: textOf(facts, "window_start") ?? "",
    windowEnd: textOf(facts, "window_end") ?? "",
    otaShare: textOf(facts, "ota_share_exact"),
    expectedOtaShare: textOf(facts, "expected_ota_share_exact"),
    structuralCondition: boolOf(facts, "structural_condition"),
    risingCondition: boolOf(facts, "rising_condition"),
  };
}

function costCard(target: CostDecisionTarget, facts: DecisionFacts): CostCardViewModel {
  return {
    kind: "COST",
    costCategory: target.cost_category,
    periodStart: target.target_period_start,
    currency: target.currency,
    actualCpor: textOf(facts, "actual_cpor_exact"),
    expectedCpor: textOf(facts, "expected_cpor_exact"),
    deltaCpor: textOf(facts, "delta_cpor_exact"),
    deltaPercent: textOf(facts, "delta_percent_exact"),
  };
}

function laborCard(target: LaborDecisionTarget, facts: DecisionFacts): LaborCardViewModel {
  return {
    kind: "LABOR",
    workDate: target.work_date,
    laborCategory: target.labor_category,
    scheduledHours: textOf(facts, "scheduled_hours_exact"),
    expectedHours: textOf(facts, "expected_labor_hours_exact"),
    excessHours: textOf(facts, "excess_hours_exact"),
  };
}

/**
 * The shared dispatcher: a `target` + `facts` pair (whatever they came from - a feed item, a
 * Decision Detail's `latest_observation`, or one historical `ObservationDetail` - target is
 * always the DECISION's own, facts belong to the specific observation) -> a typed view model.
 * Gate 15's detail/history adapters call this directly instead of duplicating the per-type
 * mapping functions above.
 */
export function cardViewModelFromTargetAndFacts(
  target: DecisionTarget,
  facts: DecisionFacts,
): DecisionCardViewModel {
  switch (target.type) {
    case "REV_PICKUP_LOW":
      return pickupCard(target, facts);
    case "REV_OCCUPANCY_RISK":
      return occupancyCard(target, facts);
    case "REV_OTA_DEPENDENCY":
      return otaCard(target, facts);
    case "COST_CPOR_ANOMALY":
      return costCard(target, facts);
    case "LABOR_OVERSTAFFING":
      return laborCard(target, facts);
  }
}

function cardViewModelOf(item: FeedItemResponse): DecisionCardViewModel {
  return cardViewModelFromTargetAndFacts(item.target, item.facts);
}

/** Exported for reuse by `lib/decisions/evidence-rows.ts` (Gate 15): the SAME confidence-to-
 * percent conversion used here, never a second implementation. */
export function confidencePercentOf(confidenceScore: string): number | null {
  const value = Number.parseFloat(confidenceScore);
  return Number.isFinite(value) ? Math.round(value * 100) : null;
}

/** The one entry point: a real `FeedItemResponse` -> a typed, presentation-ready view model.
 * `rank`/`confidencePercent` are copied verbatim from the backend's own `PrioritySnapshot` -
 * never recomputed. */
export function buildDecisionCardData(item: FeedItemResponse): DecisionCardData {
  return {
    decisionId: item.decision_id,
    rank: item.priority.rank,
    title: decisionTypeTitles[item.decision_type],
    confidencePercent: confidencePercentOf(item.priority.confidence_score),
    economicProxy: item.economic_proxy,
    card: cardViewModelOf(item),
  };
}
