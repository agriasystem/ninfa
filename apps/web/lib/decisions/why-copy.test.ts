import { describe, expect, it } from "vitest";

import type { DecisionCardViewModel } from "./card-view-models";
import { whySentence } from "./why-copy";

describe("whySentence", () => {
  it("builds the PICKUP sentence from real facts only", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: 7,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: "-3.00",
      missingRooms: "3.00",
    };

    expect(whySentence(card)).toBe(
      "Negli ultimi 7 giorni sono entrate 4 camere, contro le 7 normalmente attese.",
    );
  });

  it("builds the OCCUPANCY sentence using the local stay date, no timezone reconversion", () => {
    const card: DecisionCardViewModel = {
      kind: "OCCUPANCY",
      stayDate: "2026-10-15",
      forecastRooms: "22.00",
      expectedFinalRooms: "34.00",
      occupancyGapPp: "12.00",
      roomShortfall: "12.00",
    };

    expect(whySentence(card)).toBe(
      "Per il 15 ottobre l'occupazione prevista è 12 punti sotto il livello atteso.",
    );
  });

  it("builds the OTA sentence without accusing a specific OTA", () => {
    const card: DecisionCardViewModel = {
      kind: "OTA",
      windowStart: "2026-08-01",
      windowEnd: "2026-09-25",
      otaShare: "74.00",
      expectedOtaShare: "58.00",
      structuralCondition: true,
      risingCondition: false,
    };

    const sentence = whySentence(card);
    expect(sentence).toBe(
      "Il 74% delle camere prenotate arriva da OTA, rispetto al 58% atteso.",
    );
    expect(sentence).not.toMatch(/booking\.com|expedia|airbnb/i);
  });

  it("builds the COST sentence with formatted money, never a raw number", () => {
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

    const sentence = whySentence(card);
    expect(sentence).toContain("31,20");
    expect(sentence).toContain("24%");
    expect(sentence).toContain("sopra il livello atteso");
  });

  it("builds the LABOR sentence without naming employees", () => {
    const card: DecisionCardViewModel = {
      kind: "LABOR",
      workDate: "2026-09-25",
      laborCategory: "HOUSEKEEPING",
      scheduledHours: "32.00",
      expectedHours: "24.00",
      excessHours: "8.00",
    };

    expect(whySentence(card)).toBe("Sono programmate 32 ore, contro 24 ore normalmente attese.");
  });

  it("returns null (never a half sentence) when a needed fact is missing", () => {
    const card: DecisionCardViewModel = {
      kind: "PICKUP",
      stayDate: "2026-10-01",
      windowDays: null,
      actualPickup: 4,
      expectedPickup: "7.00",
      deltaRooms: null,
      missingRooms: null,
    };

    expect(whySentence(card)).toBeNull();
  });

  it("never invents a value beyond what the real facts contain", () => {
    const card: DecisionCardViewModel = {
      kind: "OTA",
      windowStart: "2026-08-01",
      windowEnd: "2026-09-25",
      otaShare: null,
      expectedOtaShare: "58.00",
      structuralCondition: null,
      risingCondition: null,
    };

    expect(whySentence(card)).toBeNull();
  });
});
