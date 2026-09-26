import { describe, expect, it } from "vitest";

import type { DecisionCardViewModel } from "./card-view-models";
import { evidenceRows } from "./evidence-rows";

describe("evidenceRows", () => {
  it("builds Attuale/Atteso/Scostamento + Affidabilità for a PICKUP card", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: "-3.00",
      missingRooms: "3.00",
    };

    const rows = evidenceRows(card, "0.81", {});

    expect(rows).toEqual([
      { label: "Attuale", value: "4" },
      { label: "Atteso", value: "7" },
      { label: "Scostamento", value: "-3" },
      { label: "Affidabilità", value: "81%" },
    ]);
  });

  it("adds a coverage row only when the real evidence carries it (OTA/Cost/Labor)", () => {
    const card: DecisionCardViewModel = {
      kind: "OTA",
      windowStart: "2026-08-01",
      windowEnd: "2026-09-25",
      otaShare: "74.00",
      expectedOtaShare: "58.00",
      structuralCondition: true,
      risingCondition: false,
    };

    const rows = evidenceRows(card, "0.84", { classification_coverage_pct_exact: "92.00" });

    expect(rows).toContainEqual({ label: "", value: "Copertura dati 92%" });
  });

  it("adds a comparable-periods row for Revenue types, which have no coverage field", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: "-3.00",
      missingRooms: "3.00",
    };

    const rows = evidenceRows(card, "0.81", { pattern_pair_count: 8 });

    expect(rows).toContainEqual({ label: "", value: "Basato su 8 periodi comparabili" });
  });

  it("never invents a coverage/sample row when the evidence carries neither field", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: "-3.00",
      missingRooms: "3.00",
    };

    const rows = evidenceRows(card, "0.81", {});

    expect(rows.some((row) => row.label === "")).toBe(false);
  });

  it("caps at 5 rows", () => {
    const card: DecisionCardViewModel = {
      kind: "COST",
      costCategory: "FOOD_AND_BEVERAGE",
      periodStart: "2026-09-01",
      currency: "EUR",
      actualCpor: "31.20",
      expectedCpor: "25.16",
      deltaCpor: "6.04",
      deltaPercent: "24.00",
    };

    const rows = evidenceRows(card, "0.80", { classification_coverage_pct_exact: "92.00" });

    expect(rows.length).toBeLessThanOrEqual(5);
  });

  it("skips a row entirely when its underlying fact is missing, never a placeholder row", () => {
    const card: DecisionCardViewModel = {
      kind: "OCCUPANCY",
      stayDate: "2026-10-15",
      forecastRooms: null,
      expectedFinalRooms: null,
      occupancyGapPp: null,
      roomShortfall: null,
    };

    const rows = evidenceRows(card, "0.5", {});

    expect(rows).toEqual([{ label: "Affidabilità", value: "50%" }]);
  });
});
