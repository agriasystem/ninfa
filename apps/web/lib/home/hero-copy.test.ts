import { describe, expect, it } from "vitest";

import type { DecisionType, FeedItemResponse } from "@ninfa/contracts";

import { GOLDEN_FIVE_DECISION_TYPES, itemOfType } from "@/test/home-support";

import { heroFragmentsOf, heroTextOf } from "./hero-copy";

const EXPECTED: Record<DecisionType, string> = {
  REV_PICKUP_LOW: "Le prenotazioni per il 5 ottobre stanno arrivando sotto il ritmo atteso.",
  REV_OCCUPANCY_RISK: "L'occupazione prevista per il 12 ottobre è sotto il livello atteso.",
  REV_OTA_DEPENDENCY: "La quota di prenotazioni da OTA è sopra il livello atteso.",
  COST_CPOR_ANOMALY: "Il costo per camera è sopra il livello atteso.",
  LABOR_OVERSTAFFING: "Le ore di personale programmate sono sopra il livello atteso.",
};

describe("heroFragmentsOf - the five current decision types", () => {
  it("covers every one of the five types the golden feed carries", () => {
    expect(GOLDEN_FIVE_DECISION_TYPES.map((item) => item.decision_type).sort()).toEqual(
      Object.keys(EXPECTED).sort(),
    );
  });

  for (const [type, sentence] of Object.entries(EXPECTED) as [DecisionType, string][]) {
    it(`${type} reads exactly: "${sentence}"`, () => {
      expect(heroTextOf(heroFragmentsOf(itemOfType(type)))).toBe(sentence);
    });
  }

  it("styles the subject as strong and ends with exactly one accent state phrase", () => {
    for (const item of GOLDEN_FIVE_DECISION_TYPES) {
      const fragments = heroFragmentsOf(item);
      expect(fragments.some((fragment) => fragment.tone === "strong"), item.decision_type).toBe(true);
      const accents = fragments.filter((fragment) => fragment.tone === "accent");
      expect(accents, item.decision_type).toHaveLength(1);
      expect(fragments.at(-1)).toEqual(accents[0]);
      expect(accents[0]?.text).toMatch(/^(sotto|sopra) il (ritmo|livello) atteso\.$/u);
    }
  });

  it("names the stay date of a pickup/occupancy Decision in strong", () => {
    const pickup = heroFragmentsOf(itemOfType("REV_PICKUP_LOW"));
    expect(pickup).toContainEqual({ text: "5 ottobre", tone: "strong" });
    const occupancy = heroFragmentsOf(itemOfType("REV_OCCUPANCY_RISK"));
    expect(occupancy).toContainEqual({ text: "12 ottobre", tone: "strong" });
  });
});

describe("heroFragmentsOf - honesty", () => {
  it("never claims a time horizon no field supports ('prossimi 14 giorni' etc.)", () => {
    for (const item of GOLDEN_FIVE_DECISION_TYPES) {
      const text = heroTextOf(heroFragmentsOf(item));
      expect(text, item.decision_type).not.toMatch(/prossim|giorni|14/u);
    }
  });

  it("never shows a raw enum value or a snake_case word", () => {
    for (const item of GOLDEN_FIVE_DECISION_TYPES) {
      const text = heroTextOf(heroFragmentsOf(item));
      expect(text, item.decision_type).not.toMatch(/[A-Z]{3,}_[A-Z_]+|_|HOUSEKEEPING|FOOD_AND/u);
    }
  });

  it("never uses recommendation language (it presents what the engine decided, it advises nothing)", () => {
    for (const item of GOLDEN_FIVE_DECISION_TYPES) {
      const text = heroTextOf(heroFragmentsOf(item));
      expect(text, item.decision_type).not.toMatch(
        /abbass|aument|riduc|rivedi|dovresti|consigli|suggeri|taglia|licenzi/iu,
      );
    }
  });

  it("is a typed fragment list, never markup", () => {
    for (const item of GOLDEN_FIVE_DECISION_TYPES) {
      for (const fragment of heroFragmentsOf(item)) {
        expect(fragment.text).not.toMatch(/[<>]/u);
        expect(["plain", "strong", "accent"]).toContain(fragment.tone);
      }
    }
  });

  it("omits the date, instead of guessing one, when the stay date is unparseable or absent", () => {
    const broken: FeedItemResponse = {
      ...itemOfType("REV_PICKUP_LOW"),
      target: {
        type: "REV_PICKUP_LOW",
        booking_data_source_id: "x",
        stay_date: "not-a-date",
      },
    };
    expect(heroTextOf(heroFragmentsOf(broken))).toBe(
      "Le prenotazioni stanno arrivando sotto il ritmo atteso.",
    );

    const occupancyWithoutDate: FeedItemResponse = {
      ...itemOfType("REV_OCCUPANCY_RISK"),
      target: { type: "REV_OTA_DEPENDENCY", booking_data_source_id: "x" },
    };
    expect(heroTextOf(heroFragmentsOf(occupancyWithoutDate))).toBe(
      "L'occupazione prevista è sotto il livello atteso.",
    );
  });
});
