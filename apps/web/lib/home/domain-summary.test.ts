import { describe, expect, it } from "vitest";

import type { AnalysisDomain, DecisionFeedResponse, DecisionType } from "@ninfa/contracts";

import { analysisDomainLabels } from "@/lib/copy";
import {
  ALL_DOMAINS,
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_FIVE_DECISION_TYPES,
  actionRequired,
  coverageSkipping,
  feed,
  fullCoverage,
  itemOfType,
  notProcessed,
  unknownCoverage,
} from "@/test/home-support";

import {
  DOMAIN_ORDER,
  DOMAIN_OF_DECISION_TYPE,
  buildDomainSummary,
  decisionCountOf,
} from "./domain-summary";

function tiles(f: DecisionFeedResponse) {
  const result = buildDomainSummary(f);
  if (result === null) throw new Error("expected a domain summary");
  return Object.fromEntries(result.map((tile) => [tile.domain, tile])) as Record<
    AnalysisDomain,
    NonNullable<ReturnType<typeof buildDomainSummary>>[number]
  >;
}

describe("DOMAIN_OF_DECISION_TYPE", () => {
  it("is exhaustive over every decision type the API can produce", () => {
    const apiTypes = new Set<DecisionType>(
      GOLDEN_FIVE_DECISION_TYPES.map((item) => item.decision_type),
    );
    expect(apiTypes.size).toBe(5);
    expect(new Set(Object.keys(DOMAIN_OF_DECISION_TYPE))).toEqual(apiTypes);
  });

  it("groups them the way the backend documents (coverage.py)", () => {
    expect(DOMAIN_OF_DECISION_TYPE).toEqual({
      REV_PICKUP_LOW: "REVENUE",
      REV_OCCUPANCY_RISK: "REVENUE",
      REV_OTA_DEPENDENCY: "DISTRIBUTION",
      COST_CPOR_ANOMALY: "COSTS",
      LABOR_OVERSTAFFING: "LABOR",
    });
  });

  it("maps every type to one of the four displayed domains", () => {
    for (const domain of Object.values(DOMAIN_OF_DECISION_TYPE)) {
      expect(DOMAIN_ORDER).toContain(domain);
    }
    expect([...DOMAIN_ORDER]).toEqual([...ALL_DOMAINS]);
  });
});

describe("decisionCountOf", () => {
  it("counts EVERY triggered item, never the 5 that the list shows", () => {
    expect(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS.items).toHaveLength(8);
    expect(decisionCountOf(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS)).toBe(8);
  });

  it("counts one item as one", () => {
    expect(decisionCountOf(actionRequired([itemOfType("REV_PICKUP_LOW")]))).toBe(1);
  });

  it("is zero in every state that is not ACTION_REQUIRED", () => {
    expect(decisionCountOf(feed({ feed_state: "NO_ACTION_REQUIRED" }))).toBe(0);
    expect(decisionCountOf(feed({ feed_state: "DATA_QUALITY_LIMITED" }))).toBe(0);
    expect(decisionCountOf(notProcessed())).toBe(0);
  });
});

describe("buildDomainSummary - counts per domain", () => {
  it("counts a domain's decisions beyond five (8 items: 5 revenue, 1 of each other)", () => {
    const result = tiles(actionRequired(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS.items));

    expect(result.REVENUE.text).toBe("5 attenzioni");
    expect(result.DISTRIBUTION.text).toBe("1 attenzione");
    expect(result.COSTS.text).toBe("1 attenzione");
    expect(result.LABOR.text).toBe("1 attenzione");
    for (const domain of ALL_DOMAINS) expect(result[domain].tone).toBe("attention");
  });

  it("uses the singular for exactly one and the plural from two", () => {
    const one = tiles(actionRequired([itemOfType("REV_OTA_DEPENDENCY")]));
    expect(one.DISTRIBUTION.text).toBe("1 attenzione");
    const two = tiles(
      actionRequired([itemOfType("REV_PICKUP_LOW"), itemOfType("REV_OCCUPANCY_RISK")]),
    );
    expect(two.REVENUE.text).toBe("2 attenzioni");
  });

  it("says 'Nessuna attenzione' for an evaluated domain with nothing triggered", () => {
    const result = tiles(actionRequired([itemOfType("REV_PICKUP_LOW")]));

    expect(result.REVENUE.text).toBe("1 attenzione");
    expect(result.DISTRIBUTION.text).toBe("Nessuna attenzione");
    expect(result.DISTRIBUTION.tone).toBe("clear");
    expect(result.COSTS.text).toBe("Nessuna attenzione");
    expect(result.LABOR.text).toBe("Nessuna attenzione");
  });

  it("returns the four tiles in the approved order, with the user-facing labels", () => {
    const result = buildDomainSummary(actionRequired([itemOfType("REV_PICKUP_LOW")]));

    expect(result?.map((tile) => tile.label)).toEqual([
      "Ricavi",
      "Distribuzione",
      "Costi",
      "Personale",
    ]);
    expect(analysisDomainLabels.DISTRIBUTION).toBe("Distribuzione");
  });
});

describe("buildDomainSummary - skipped domains (grammar per domain)", () => {
  it("writes each 'not analysed' in the gender/number of its own domain", () => {
    const result = tiles(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        analysis_coverage: coverageSkipping("REVENUE", "DISTRIBUTION", "COSTS", "LABOR"),
      }),
    );

    expect(result.REVENUE.text).toBe("Non analizzati");
    expect(result.DISTRIBUTION.text).toBe("Non analizzata");
    expect(result.COSTS.text).toBe("Non analizzati");
    expect(result.LABOR.text).toBe("Non analizzato");
    for (const domain of ALL_DOMAINS) expect(result[domain].tone).toBe("unavailable");
  });

  it("the approved example: booking-only analysis -> Costi/Personale not analysed", () => {
    const result = tiles(
      actionRequired([itemOfType("REV_PICKUP_LOW"), itemOfType("REV_OCCUPANCY_RISK")], {
        analysis_coverage: coverageSkipping("COSTS", "LABOR"),
      }),
    );

    expect(result.REVENUE.text).toBe("2 attenzioni");
    expect(result.DISTRIBUTION.text).toBe("Nessuna attenzione");
    expect(result.COSTS.text).toBe("Non analizzati");
    expect(result.LABOR.text).toBe("Non analizzato");
  });

  it("never lets a decision hide behind a (contradictory) 'skipped' coverage line", () => {
    const result = tiles(
      actionRequired([itemOfType("COST_CPOR_ANOMALY")], {
        analysis_coverage: coverageSkipping("COSTS"),
      }),
    );
    expect(result.COSTS.text).toBe("1 attenzione");
  });
});

describe("buildDomainSummary - unknown, partial and not processed", () => {
  it("shows 'Non disponibile' for every domain when coverage is UNKNOWN - never inferred", () => {
    const result = tiles(feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: unknownCoverage() }));

    for (const domain of ALL_DOMAINS) {
      expect(result[domain].text).toBe("Non disponibile");
      expect(result[domain].tone).toBe("unavailable");
    }
  });

  it("shows 'Analisi parziale' (never 'Nessuna attenzione') for an evaluated domain of a data-quality-limited run", () => {
    const result = tiles(
      feed({ feed_state: "DATA_QUALITY_LIMITED", analysis_coverage: coverageSkipping("COSTS", "LABOR") }),
    );

    expect(result.REVENUE.text).toBe("Analisi parziale");
    expect(result.REVENUE.tone).toBe("partial");
    expect(result.DISTRIBUTION.text).toBe("Analisi parziale");
    // ... while a domain that was never analysed still says so.
    expect(result.COSTS.text).toBe("Non analizzati");
    expect(result.LABOR.text).toBe("Non analizzato");
  });

  it("is null for NOT_PROCESSED: no run, no coverage - the strip is hidden, never invented", () => {
    expect(buildDomainSummary(notProcessed())).toBeNull();
  });

  it("every tile text is human copy - no raw enum, no snake_case", () => {
    const feeds = [
      actionRequired(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS.items),
      feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: coverageSkipping("COSTS") }),
      feed({ feed_state: "DATA_QUALITY_LIMITED", analysis_coverage: fullCoverage() }),
      feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: unknownCoverage() }),
    ];
    for (const f of feeds) {
      for (const tile of buildDomainSummary(f) ?? []) {
        expect(tile.text).not.toMatch(/[A-Z]{3,}|_|SKIPPED|EVALUATED|NOT_REQUESTED/u);
        expect(tile.label).not.toMatch(/[A-Z]{3,}|_/u);
      }
    }
  });
});
