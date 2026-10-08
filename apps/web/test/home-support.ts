import type {
  AnalysisCoverage,
  AnalysisDomain,
  DecisionFeedResponse,
  DecisionType,
  FeedItemResponse,
} from "@ninfa/contracts";

import {
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_ACTION_REQUIRED_FIVE_TYPES,
  GOLDEN_FIVE_DECISION_TYPES,
  GOLDEN_NO_ACTION_REQUIRED,
  GOLDEN_NOT_PROCESSED,
} from "@/golden/fixtures";

/**
 * Shared builders for the Home UI V1 tests. Everything starts from the hand-authored golden
 * feeds (`golden/fixtures.ts`, audited against the real Gate 12 contract) and only overrides what a
 * test is about - never a screenshot string: the approved reference's demo values ("Hotel Villa
 * Aurora", "Luca", "09:31", ...) appear nowhere in these fixtures, which is exactly what the Home
 * tests assert about the rendered UI.
 */
export { GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS, GOLDEN_ACTION_REQUIRED_FIVE_TYPES, GOLDEN_FIVE_DECISION_TYPES };

export const ALL_DOMAINS: readonly AnalysisDomain[] = ["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"];

export function fullCoverage(): AnalysisCoverage {
  return {
    summary: "FULL",
    domains: ALL_DOMAINS.map((domain) => ({ domain, status: "EVALUATED", reason: null })),
  };
}

/** Coverage with the given domains skipped (`NOT_REQUESTED`) and every other one evaluated. */
export function coverageSkipping(...skipped: AnalysisDomain[]): AnalysisCoverage {
  return {
    summary: skipped.length === 0 ? "FULL" : "PARTIAL",
    domains: ALL_DOMAINS.map((domain) =>
      skipped.includes(domain)
        ? { domain, status: "SKIPPED", reason: "NOT_REQUESTED" }
        : { domain, status: "EVALUATED", reason: null },
    ),
  };
}

export function unknownCoverage(): AnalysisCoverage {
  return { summary: "UNKNOWN", domains: [] };
}

export function feed(overrides: Partial<DecisionFeedResponse>): DecisionFeedResponse {
  return { ...GOLDEN_NO_ACTION_REQUIRED, analysis_coverage: fullCoverage(), ...overrides };
}

export function actionRequired(
  items: FeedItemResponse[],
  overrides: Partial<DecisionFeedResponse> = {},
): DecisionFeedResponse {
  return {
    ...GOLDEN_ACTION_REQUIRED_FIVE_TYPES,
    analysis_coverage: fullCoverage(),
    triggered_count: items.length,
    items,
    ...overrides,
  };
}

export function notProcessed(overrides: Partial<DecisionFeedResponse> = {}): DecisionFeedResponse {
  return { ...GOLDEN_NOT_PROCESSED, ...overrides };
}

export function itemOfType(type: DecisionType): FeedItemResponse {
  const found = GOLDEN_FIVE_DECISION_TYPES.find((item) => item.decision_type === type);
  if (!found) throw new Error(`no golden item of type ${type}`);
  return found;
}

/** A booking-import freshness that is KNOWN at `instant` (ISO, timezone-aware). */
export function knownFreshness(instant: string): DecisionFeedResponse["input_freshness"] {
  return { bookings: { status: "KNOWN", last_successful_import_finished_at: instant } };
}

export const UNKNOWN_FRESHNESS: DecisionFeedResponse["input_freshness"] = {
  bookings: { status: "UNKNOWN", last_successful_import_finished_at: null },
};
