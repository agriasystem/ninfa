import type {
  AnalysisDomain,
  DecisionFeedResponse,
  DecisionType,
  DomainCoverage,
} from "@ninfa/contracts";

import { analysisDomainLabels, copy, domainNotAnalyzedCopy } from "@/lib/copy";

/**
 * decision_type -> analysis domain: the SAME grouping the backend documents in
 * `app/modules/decisions/coverage.py`, written out here because the feed does not carry a `domain`
 * per item. A `Record<DecisionType, ...>` makes a sixth decision type a COMPILE error, and
 * `domain-summary.test.ts` re-checks it exhaustively at runtime.
 */
export const DOMAIN_OF_DECISION_TYPE: Record<DecisionType, AnalysisDomain> = {
  REV_PICKUP_LOW: "REVENUE",
  REV_OCCUPANCY_RISK: "REVENUE",
  REV_OTA_DEPENDENCY: "DISTRIBUTION",
  COST_CPOR_ANOMALY: "COSTS",
  LABOR_OVERSTAFFING: "LABOR",
};

/** The fixed display order of the Home's domain strip (the approved reference's own order). */
export const DOMAIN_ORDER: readonly AnalysisDomain[] = [
  "REVENUE",
  "DISTRIBUTION",
  "COSTS",
  "LABOR",
];

/**
 * How a tile reads WITHOUT colour (the text always says it too - D4):
 * - `attention`: at least one Decision requires attention in this domain
 * - `clear`: evaluated, and no Decision requires attention here
 * - `partial`: evaluated, but the run as a whole had too little data to conclude (never "clear")
 * - `unavailable`: not analysed (skipped) or no coverage information exists
 */
export type DomainTone = "attention" | "clear" | "partial" | "unavailable";

export interface DomainTile {
  domain: AnalysisDomain;
  label: string;
  text: string;
  tone: DomainTone;
}

/** The number of Decisions that "require attention": exactly the triggered feed items, and only
 * ever in `ACTION_REQUIRED` (`items` is empty in every other state, by the backend's own
 * construction). NEVER the length of the visible slice - `DecisionList` shows at most 5. */
export function decisionCountOf(feed: DecisionFeedResponse): number {
  return feed.feed_state === "ACTION_REQUIRED" ? feed.items.length : 0;
}

function countsByDomain(feed: DecisionFeedResponse): Map<AnalysisDomain, number> {
  const counts = new Map<AnalysisDomain, number>();
  if (feed.feed_state !== "ACTION_REQUIRED") return counts;
  for (const item of feed.items) {
    const domain = DOMAIN_OF_DECISION_TYPE[item.decision_type];
    counts.set(domain, (counts.get(domain) ?? 0) + 1);
  }
  return counts;
}

function tileOf(
  domain: AnalysisDomain,
  coverage: DomainCoverage | undefined,
  count: number,
  feed: DecisionFeedResponse,
): DomainTile {
  const label = analysisDomainLabels[domain];
  // A Decision that exists IS evidence the domain was analysed: it is shown, never hidden behind
  // a coverage line that (impossibly, by the backend's invariants) said otherwise.
  if (count > 0) {
    return { domain, label, text: copy.home.attention(count), tone: "attention" };
  }
  if (coverage === undefined) {
    return { domain, label, text: copy.home.unavailable, tone: "unavailable" };
  }
  if (coverage.status === "SKIPPED") {
    return { domain, label, text: domainNotAnalyzedCopy[domain], tone: "unavailable" };
  }
  // EVALUATED with nothing triggered. In a data-quality-limited run the per-domain cause cannot be
  // told apart (the run's counts are domain-blind), so a reassuring "nessuna attenzione" would be
  // unsafe: it stays "Analisi parziale".
  if (feed.feed_state === "DATA_QUALITY_LIMITED") {
    return { domain, label, text: copy.home.partialAnalysis, tone: "partial" };
  }
  return { domain, label, text: copy.home.noAttention, tone: "clear" };
}

/**
 * The four tiles of the Home's domain strip, or `null` when there is nothing honest to show:
 * `NOT_PROCESSED` has no run, hence no coverage - the strip is hidden, never four invented tiles.
 * A processed run with `coverage.summary === "UNKNOWN"` (no domains) shows four "Non disponibile".
 */
export function buildDomainSummary(feed: DecisionFeedResponse): DomainTile[] | null {
  if (feed.feed_state === "NOT_PROCESSED") return null;
  const counts = countsByDomain(feed);
  const coverageOf = new Map<AnalysisDomain, DomainCoverage>(
    feed.analysis_coverage.domains.map((item) => [item.domain, item]),
  );
  return DOMAIN_ORDER.map((domain) =>
    tileOf(domain, coverageOf.get(domain), counts.get(domain) ?? 0, feed),
  );
}
