import { describe, expect, it } from "vitest";

import type { FeedItemResponse } from "@ninfa/contracts";

import { GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS, GOLDEN_FIVE_DECISION_TYPES, actionRequired, itemOfType } from "@/test/home-support";

import { buildDecisionRow, buildDecisionRows, countByArea, sortRows, type DecisionRowData } from "./list-view-model";

/** Intl puts a no-break space between a number and its currency symbol: compare with a plain space. */
function plain(text: string | null | undefined): string {
  return (text ?? "").replace(/[  ]/gu, " ");
}

function withFacts(item: FeedItemResponse, facts: Record<string, unknown>): FeedItemResponse {
  return { ...item, facts: { ...item.facts, ...facts } as FeedItemResponse["facts"] };
}

function without(item: FeedItemResponse, ...keys: string[]): FeedItemResponse {
  const facts: Record<string, unknown> = { ...item.facts };
  for (const key of keys) delete facts[key];
  return { ...item, facts: facts as FeedItemResponse["facts"] };
}

function textOfRow(row: DecisionRowData): string {
  return plain(
    [
      row.title,
      row.description,
      row.detectedOn,
      row.metric.label,
      row.metric.value,
      row.metric.caption,
      row.metric.delta?.text,
      row.metric.delta?.caption,
      row.impact?.label,
      row.impact?.value,
      row.impact?.caption,
    ].join(" | "),
  );
}

describe("buildDecisionRow - one row per decision type, from the decision's own facts", () => {
  it("REV_PICKUP_LOW: found vs expected pickup, the shortfall as the impact, a '-' departure", () => {
    const row = buildDecisionRow(itemOfType("REV_PICKUP_LOW"));

    expect(row.area).toBe("REVENUE");
    expect(row.rank).toBe(1);
    expect(row.title).toBe("Le prenotazioni per il 5 ottobre stanno arrivando sotto il ritmo atteso");
    expect(row.metric).toEqual({
      label: "Pickup rilevato",
      value: "3 camere",
      caption: "attesi 7,5",
      delta: { text: "−60,0%", caption: "vs atteso" },
    });
    expect(row.impact).toEqual({
      label: "Camere mancanti",
      value: "4,5",
      caption: "rispetto al ritmo atteso",
      estimate: false,
    });
    expect(row.visual).toEqual({ kind: "pair", found: 3, expected: 7.5 });
    expect(row.reliabilityPercent).toBe(81);
    expect(row.detectedOn).toBe("24 settembre");
  });

  it("REV_OCCUPANCY_RISK: forecast vs expected rooms, rooms short as the impact", () => {
    const row = buildDecisionRow(itemOfType("REV_OCCUPANCY_RISK"));

    expect(row.title).toBe("L'occupazione prevista per il 12 ottobre è sotto il livello atteso");
    expect(row.metric).toEqual({
      label: "Camere previste",
      value: "22,0",
      caption: "attesi 34,0",
      delta: { text: "−30,0 pp", caption: "vs atteso" },
    });
    expect(row.impact?.label).toBe("Camere in meno");
    expect(row.impact?.value).toBe("12,0");
    expect(row.impact?.estimate).toBe(false);
    expect(row.visual).toEqual({ kind: "pair", found: 22, expected: 34 });
  });

  it("REV_OTA_DEPENDENCY: the OTA share against the reference, room-nights as the impact, a share visual", () => {
    const row = buildDecisionRow(itemOfType("REV_OTA_DEPENDENCY"));

    expect(row.area).toBe("DISTRIBUTION");
    expect(row.title).toBe("La dipendenza dalle OTA è sopra il livello atteso");
    expect(row.metric.label).toBe("Prenotazioni da OTA");
    expect(plain(row.metric.value)).toBe("62,5%");
    expect(row.metric.delta?.text).toBe("+17,5 pp");
    expect(plain(row.metric.delta?.caption)).toBe("vs riferimento 45%");
    expect(row.impact).toEqual({
      label: "Camere-notte da OTA",
      value: "140",
      caption: "nel periodo osservato",
      estimate: false,
    });
    expect(row.visual).toEqual({ kind: "share", share: 62.5, reference: 45 });
  });

  it("COST_CPOR_ANOMALY: cost per room vs expected, the RECORDED estimate as the impact", () => {
    const row = buildDecisionRow(itemOfType("COST_CPOR_ANOMALY"));

    expect(row.area).toBe("COSTS");
    expect(row.metric.label).toBe("Costo per camera");
    expect(plain(row.metric.value)).toBe("12,40 €");
    expect(row.metric.delta?.text).toBe("+37,8%");
    expect(plain(row.metric.delta?.caption)).toBe("vs atteso 9,00 €");
    expect(row.impact?.label).toBe("Impatto stimato");
    expect(plain(row.impact?.value)).toBe("482 €");
    expect(row.impact?.estimate).toBe(true);
    expect(row.impact?.caption).toContain("stima indicativa");
    expect(row.visual).toEqual({ kind: "pair", found: 12.4, expected: 9 });
  });

  it("LABOR_OVERSTAFFING: scheduled vs expected hours, the RECORDED estimate as the impact", () => {
    const row = buildDecisionRow(itemOfType("LABOR_OVERSTAFFING"));

    expect(row.area).toBe("LABOR");
    expect(row.title).toBe("Le ore di personale della governanza sono sopra il livello atteso");
    expect(row.metric.label).toBe("Ore programmate");
    expect(plain(row.metric.value)).toBe("40,0 h");
    expect(row.metric.delta?.text).toBe("+42,9%");
    expect(plain(row.metric.delta?.caption)).toBe("vs atteso 28,0 h");
    expect(plain(row.impact?.value)).toBe("156 €");
    expect(row.impact?.estimate).toBe(true);
    expect(row.visual).toEqual({ kind: "pair", found: 40, expected: 28 });
  });
});

describe("buildDecisionRow - an estimate exists only where the engine recorded one", () => {
  it("never turns a revenue or OTA gap into money: those decisions carry no currency", () => {
    for (const type of ["REV_PICKUP_LOW", "REV_OCCUPANCY_RISK", "REV_OTA_DEPENDENCY"] as const) {
      const row = buildDecisionRow(itemOfType(type));
      expect(row.impact?.estimate).toBe(false);
      expect(textOfRow(row)).not.toMatch(/€|EUR|Impatto stimato/u);
    }
  });

  it("cost without an economic_proxy shows its per-room gap, not an 'Impatto stimato'", () => {
    const row = buildDecisionRow({ ...itemOfType("COST_CPOR_ANOMALY"), economic_proxy: null });

    expect(row.impact?.estimate).toBe(false);
    expect(row.impact?.label).toBe("Scostamento per camera");
    expect(plain(row.impact?.value)).toBe("3,40 €");
  });

  it("labor without an economic_proxy shows the excess hours instead", () => {
    const row = buildDecisionRow({ ...itemOfType("LABOR_OVERSTAFFING"), economic_proxy: null });

    expect(row.impact?.estimate).toBe(false);
    expect(row.impact?.label).toBe("Ore in eccesso");
    expect(plain(row.impact?.value)).toBe("12,0 h");
  });

  it("the estimate is the proxy's own amount in its own currency, rounded for display", () => {
    const item: FeedItemResponse = {
      ...itemOfType("COST_CPOR_ANOMALY"),
      economic_proxy: { label: "cost_gap_proxy", amount: "1240.60", currency: "EUR" },
    };

    expect(plain(buildDecisionRow(item).impact?.value)).toBe("1.241 €");
  });
});

describe("buildDecisionRow - a missing fact is a dash or nothing, never a made-up number", () => {
  it("pickup without its pickup facts: no value, no delta, no impact, no visual", () => {
    const row = buildDecisionRow(
      without(itemOfType("REV_PICKUP_LOW"), "actual_pickup", "expected_pickup", "missing_rooms", "delta_percent_exact"),
    );

    expect(row.metric.value).toBeNull();
    expect(row.metric.delta).toBeNull();
    expect(row.impact).toBeNull();
    expect(row.visual).toBeNull();
  });

  it("OTA without a reference keeps the departure but names no reference level", () => {
    const row = buildDecisionRow(without(itemOfType("REV_OTA_DEPENDENCY"), "expected_ota_share_exact"));

    expect(row.metric.delta?.caption).toBe("vs atteso");
    expect(row.visual).toEqual({ kind: "share", share: 62.5, reference: null });
  });

  it("an unparseable stay date is left out of the title, never guessed", () => {
    const item = itemOfType("REV_PICKUP_LOW");
    const broken = { ...item, target: { ...item.target, stay_date: "not-a-date" } } as FeedItemResponse;

    expect(buildDecisionRow(broken).title).toBe("Le prenotazioni stanno arrivando sotto il ritmo atteso");
  });

  it("an unknown cost category yields the generic sentence, and OTHER names no category at all", () => {
    const item = itemOfType("COST_CPOR_ANOMALY");
    for (const category of ["SOMETHING_NEW", "OTHER"]) {
      const row = buildDecisionRow({ ...item, target: { ...item.target, cost_category: category } } as FeedItemResponse);
      expect(row.title).toBe("Il costo per camera è sopra il livello atteso");
    }
  });

  it("a cost category the table knows is translated with its article", () => {
    const item = itemOfType("COST_CPOR_ANOMALY");
    const row = buildDecisionRow({ ...item, target: { ...item.target, cost_category: "LAUNDRY" } } as FeedItemResponse);

    expect(row.title).toBe("Il costo per camera della lavanderia è sopra il livello atteso");
  });

  it("a visual is built only from two real, non-negative numbers", () => {
    const row = buildDecisionRow(withFacts(itemOfType("REV_PICKUP_LOW"), { actual_pickup: -1 }));

    expect(row.visual).toBeNull();
  });
});

describe("buildDecisionRows - the whole feed", () => {
  it("keeps the backend's order and the engine's rank untouched", () => {
    const reversed = [...GOLDEN_FIVE_DECISION_TYPES].reverse();
    const rows = buildDecisionRows(actionRequired(reversed));

    expect(rows.map((row) => row.rank)).toEqual([5, 4, 3, 2, 1]);
    expect(rows.map((row) => row.decisionId)).toEqual(reversed.map((item) => item.decision_id));
  });

  it("builds one row for each of the 8 decisions (no top-5 cut)", () => {
    expect(buildDecisionRows(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS)).toHaveLength(8);
  });

  it("never shows a raw enum code and never recommends: problem + evidence only", () => {
    const rows = [
      ...buildDecisionRows(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS),
      ...buildDecisionRows(actionRequired(GOLDEN_FIVE_DECISION_TYPES)),
    ];

    for (const row of rows) {
      const text = textOfRow(row);
      expect(text).not.toMatch(/[A-Z]{2,}_[A-Z_]+/u); // an UPPER_SNAKE code
      expect(text).not.toMatch(/\b(dovresti|consigliamo|ti consigliamo|verifica|rivedi|riduci|aumenta|chiama)\b/iu);
      expect(text).not.toMatch(/\b(alta|media|bassa)\b/iu); // priority is the engine's rank, not a bucket
      expect(text).not.toMatch(/undefined|null|NaN/u);
    }
  });

  it("copies the priority as the engine's own ordinal, nothing bucketed", () => {
    const rows = buildDecisionRows(actionRequired(GOLDEN_FIVE_DECISION_TYPES));

    expect(rows.map((row) => row.rank)).toEqual([1, 2, 3, 4, 5]);
    expect(Object.keys(rows[0] as object)).not.toContain("severity");
    expect(Object.keys(rows[0] as object)).not.toContain("total");
  });
});

describe("sortRows", () => {
  const rows = buildDecisionRows(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);

  it("'priority' is the rows exactly as given - a copy, never mutated", () => {
    const sorted = sortRows(rows, "priority");

    expect(sorted).toEqual(rows);
    expect(sorted).not.toBe(rows);
  });

  it("'recent' puts the most recently detected first, ties broken by the engine's rank", () => {
    const sorted = sortRows(rows, "recent");

    const dates = sorted.map((row) => row.firstSeenLocalDate);
    expect(dates).toEqual([...dates].sort().reverse());
    for (let i = 1; i < sorted.length; i += 1) {
      const a = sorted[i - 1] as DecisionRowData;
      const b = sorted[i] as DecisionRowData;
      if (a.firstSeenLocalDate === b.firstSeenLocalDate) expect(a.rank).toBeLessThan(b.rank);
    }
  });

  it("'oldest' puts the longest-open first", () => {
    const sorted = sortRows(rows, "oldest");

    expect(sorted[0]?.firstSeenLocalDate).toBe("2026-08-20"); // the OTA dependency
    const dates = sorted.map((row) => row.firstSeenLocalDate);
    expect(dates).toEqual([...dates].sort());
  });

  it("keeps every row, whatever the order", () => {
    for (const sort of ["priority", "recent", "oldest"] as const) {
      expect(sortRows(rows, sort).map((row) => row.decisionId).sort()).toEqual(rows.map((row) => row.decisionId).sort());
    }
  });
});

describe("countByArea", () => {
  it("counts the decisions of each area, with a zero for the areas that have none", () => {
    expect(countByArea(buildDecisionRows(actionRequired(GOLDEN_FIVE_DECISION_TYPES)))).toEqual({
      REVENUE: 2,
      DISTRIBUTION: 1,
      COSTS: 1,
      LABOR: 1,
    });
    expect(countByArea([])).toEqual({ REVENUE: 0, DISTRIBUTION: 0, COSTS: 0, LABOR: 0 });
  });
});
