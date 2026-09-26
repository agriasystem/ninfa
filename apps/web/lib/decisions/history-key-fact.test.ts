import { describe, expect, it } from "vitest";

import type { DecisionCardViewModel } from "./card-view-models";
import { historyKeyFact } from "./history-key-fact";

describe("historyKeyFact", () => {
  it("gives one compact PICKUP fact", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: "-3.00",
      missingRooms: "3.00",
    };

    expect(historyKeyFact(card)).toBe("4 camere in pickup");
  });

  it("gives one compact OCCUPANCY fact", () => {
    const card: DecisionCardViewModel = {
      kind: "OCCUPANCY",
      stayDate: "2026-10-15",
      forecastRooms: "22.00",
      expectedFinalRooms: "34.00",
      occupancyGapPp: "12.00",
      roomShortfall: "12.00",
    };

    expect(historyKeyFact(card)).toBe("12 punti sotto l'atteso");
  });

  it("gives one compact OTA fact without accusing a specific OTA", () => {
    const card: DecisionCardViewModel = {
      kind: "OTA",
      windowStart: "2026-08-01",
      windowEnd: "2026-09-25",
      otaShare: "74.00",
      expectedOtaShare: "58.00",
      structuralCondition: true,
      risingCondition: false,
    };

    expect(historyKeyFact(card)).toBe("74% delle prenotazioni da OTA");
  });

  it("gives one compact COST fact, formatted as money", () => {
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

    expect(historyKeyFact(card)).toContain("31,20");
  });

  it("gives one compact LABOR fact without naming employees", () => {
    const card: DecisionCardViewModel = {
      kind: "LABOR",
      workDate: "2026-09-25",
      laborCategory: "HOUSEKEEPING",
      scheduledHours: "32.00",
      expectedHours: "24.00",
      excessHours: "8.00",
    };

    expect(historyKeyFact(card)).toBe("32 h programmate");
  });

  it("returns null (never a placeholder) when the underlying fact is missing", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: null,
      actualPickup: null,
      expectedPickup: null,
      deltaRooms: null,
      missingRooms: null,
    };

    expect(historyKeyFact(card)).toBeNull();
  });
});
