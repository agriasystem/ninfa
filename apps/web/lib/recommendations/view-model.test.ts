import { describe, expect, it } from "vitest";

import type { RecommendationResponse, RecommendedActionResponse } from "@ninfa/contracts";

import { recommendationViewModel } from "./view-model";

const FORBIDDEN_PHRASES = [
  "abbassa il prezzo",
  "abbassa",
  "fai uno sconto",
  "sconto",
  "chiudi ota",
  "chiudi",
  "cambia fornitore",
  "riduci personale",
  "riduci",
  "manda a casa",
  "taglia",
  "elimina",
  "licenzia",
  "sostituisci",
  "aumenta automaticamente",
  "applica",
  "esegui",
  "approva",
  "conferma",
  "completa",
];

function action(overrides: Partial<RecommendedActionResponse> = {}): RecommendedActionResponse {
  return {
    action_code: "REVIEW_PRICING_AND_AVAILABILITY",
    title_key: "recommendation.action.REVIEW_PRICING_AND_AVAILABILITY.title",
    description_key: "recommendation.action.REVIEW_PRICING_AND_AVAILABILITY.description",
    category: "REVIEW_PRICING",
    scope: "STAY_DATE",
    supporting_facts: {},
    risk_notes: [],
    requires_human_review: true,
    ...overrides,
  };
}

function recommendation(overrides: Partial<RecommendationResponse> = {}): RecommendationResponse {
  return {
    status: "AVAILABLE",
    version: "recommendation-engine-v1",
    fingerprint: "a".repeat(64),
    primary_action: action(),
    supporting_checks: [],
    confidence: "81.23",
    requires_human_review: true,
    ...overrides,
  };
}

function allCopyText(vm: ReturnType<typeof recommendationViewModel>): string {
  return [
    vm.title,
    vm.primary?.title ?? "",
    vm.primary?.description ?? "",
    ...vm.supporting.map((s) => s.label),
    ...vm.riskNotes,
    vm.humanReviewNote ?? "",
    vm.insufficientContextNote ?? "",
  ].join(" \n ");
}

// --- 1-4: status ---------------------------------------------------------------------------

describe("recommendationViewModel - status", () => {
  it("1. AVAILABLE is visible", () => {
    expect(recommendationViewModel(recommendation()).visible).toBe(true);
  });

  it("2. NOT_AVAILABLE is hidden entirely - no stale/empty section", () => {
    const vm = recommendationViewModel(
      recommendation({ status: "NOT_AVAILABLE", primary_action: null, confidence: null }),
    );
    expect(vm.visible).toBe(false);
    expect(vm.primary).toBeNull();
    expect(vm.supporting).toEqual([]);
  });

  it("3. INSUFFICIENT_CONTEXT is visible with neutral, non-alarming copy", () => {
    const vm = recommendationViewModel(
      recommendation({ status: "INSUFFICIENT_CONTEXT", primary_action: null }),
    );
    expect(vm.visible).toBe(true);
    expect(vm.insufficientContextNote).toBe(
      "Non ci sono ancora elementi sufficienti per proporti una verifica affidabile.",
    );
    expect(vm.primary).toBeNull();
    expect(vm.insufficientContextNote?.toLowerCase()).not.toMatch(/errore|bug|fallimento/);
  });

  it("4. an unrecognised future status fails safe (hidden), never a crash or a guess", () => {
    const vm = recommendationViewModel(recommendation({ status: "SOMETHING_FUTURE" }));
    expect(vm.visible).toBe(false);
  });
});

// --- 5-9: five primary actions --------------------------------------------------------------

describe("recommendationViewModel - the five primary actions, by ActionCode only", () => {
  it("5. Pickup: REVIEW_PRICING_AND_AVAILABILITY", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ action_code: "REVIEW_PRICING_AND_AVAILABILITY" }) }),
    );
    expect(vm.primary?.title).toBe("Rivedi prezzi e disponibilità");
  });

  it("6. Occupancy: REVIEW_DEMAND_POSITIONING", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ action_code: "REVIEW_DEMAND_POSITIONING" }) }),
    );
    expect(vm.primary?.title).toBe("Rivedi il posizionamento della data");
  });

  it("7. OTA: REVIEW_DISTRIBUTION_MIX", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ action_code: "REVIEW_DISTRIBUTION_MIX" }) }),
    );
    expect(vm.primary?.title).toBe("Rivedi il mix distributivo");
  });

  it("8. Cost: REVIEW_COST_DRIVERS", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ action_code: "REVIEW_COST_DRIVERS" }) }),
    );
    expect(vm.primary?.title).toBe("Verifica cosa sta incidendo sui costi");
  });

  it("9. Labor: REVIEW_STAFFING_PLAN", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ action_code: "REVIEW_STAFFING_PLAN" }) }),
    );
    expect(vm.primary?.title).toBe("Rivedi la pianificazione delle ore");
  });
});

// --- 10-15: supporting checks -----------------------------------------------------------------

describe("recommendationViewModel - supporting checks", () => {
  it("10. zero checks renders zero", () => {
    const vm = recommendationViewModel(recommendation({ supporting_checks: [] }));
    expect(vm.supporting).toEqual([]);
  });

  it("11. one check renders one", () => {
    const vm = recommendationViewModel(
      recommendation({ supporting_checks: [action({ action_code: "CHECK_CHANNEL_VISIBILITY" })] }),
    );
    expect(vm.supporting).toHaveLength(1);
    expect(vm.supporting[0]?.label).toBe("Verifica la visibilità sui canali");
  });

  it("12. two checks render two", () => {
    const vm = recommendationViewModel(
      recommendation({
        supporting_checks: [
          action({ action_code: "CHECK_CHANNEL_VISIBILITY" }),
          action({ action_code: "CHECK_BOOKING_RESTRICTIONS" }),
        ],
      }),
    );
    expect(vm.supporting).toHaveLength(2);
  });

  it("13. backend order is preserved, never reordered", () => {
    const vm = recommendationViewModel(
      recommendation({
        supporting_checks: [
          action({ action_code: "CHECK_BOOKING_RESTRICTIONS" }),
          action({ action_code: "CHECK_CHANNEL_VISIBILITY" }),
        ],
      }),
    );
    expect(vm.supporting.map((s) => s.actionCode)).toEqual([
      "CHECK_BOOKING_RESTRICTIONS",
      "CHECK_CHANNEL_VISIBILITY",
    ]);
  });

  it("14. never shows more checks than the backend actually provided", () => {
    const vm = recommendationViewModel(
      recommendation({ supporting_checks: [action({ action_code: "CHECK_CHANNEL_VISIBILITY" })] }),
    );
    expect(vm.supporting).toHaveLength(1);
  });

  it("15. an unrecognised action_code is dropped, never shown as a raw enum", () => {
    const vm = recommendationViewModel(
      recommendation({
        supporting_checks: [
          action({ action_code: "CHECK_CHANNEL_VISIBILITY" }),
          action({ action_code: "SOME_FUTURE_CHECK_CODE" }),
        ],
      }),
    );
    expect(vm.supporting).toHaveLength(1);
    expect(vm.supporting.some((s) => s.label.includes("SOME_FUTURE_CHECK_CODE"))).toBe(false);
    expect(JSON.stringify(vm)).not.toContain("SOME_FUTURE_CHECK_CODE");
  });
});

// --- 16-20: risk notes -----------------------------------------------------------------------

describe("recommendationViewModel - risk notes", () => {
  it("16. no risk note degrades gracefully to an empty list", () => {
    const vm = recommendationViewModel(recommendation({ primary_action: action({ risk_notes: [] }) }));
    expect(vm.riskNotes).toEqual([]);
  });

  it("17. pricing risk note", () => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ risk_notes: ["PRICING_CHANGE_MAY_AFFECT_REVENUE"] }),
      }),
    );
    expect(vm.riskNotes).toEqual(["Le variazioni di prezzo possono incidere sui ricavi."]);
  });

  it("18. staffing risk note", () => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ risk_notes: ["STAFFING_CHANGE_MAY_AFFECT_SERVICE"] }),
      }),
    );
    expect(vm.riskNotes).toEqual([
      "Le variazioni di personale possono incidere sul livello di servizio.",
    ]);
  });

  it("19. distribution risk note", () => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ risk_notes: ["DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY"] }),
      }),
    );
    expect(vm.riskNotes).toEqual(["Le variazioni distributive possono incidere sulla visibilità."]);
  });

  it("20. never invents a numeric/severity risk score", () => {
    const vm = recommendationViewModel(
      recommendation({ primary_action: action({ risk_notes: ["PRICING_CHANGE_MAY_AFFECT_REVENUE"] }) }),
    );
    expect(JSON.stringify(vm)).not.toMatch(/alto|medio|basso|rischio elevato|risk_score/i);
  });
});

// --- 21-26: human review ------------------------------------------------------------------------

describe("recommendationViewModel - human review", () => {
  it("21. human-review copy is present when AVAILABLE", () => {
    const vm = recommendationViewModel(recommendation());
    expect(vm.humanReviewNote).toBe(
      "Valuta questa indicazione nel contesto operativo della tua struttura.",
    );
  });

  it("22-25. the view model exposes plain data only - no execute/approve/apply/complete field exists", () => {
    const vm = recommendationViewModel(recommendation());
    const keys = JSON.stringify(vm);
    expect(keys).not.toMatch(/execute|approve|apply|complete|dismiss|acknowledge|snooze/i);
  });

  it("26. no mutation callback of any kind is part of the view model's own shape", () => {
    const vm = recommendationViewModel(recommendation());
    for (const value of Object.values(vm)) {
      expect(typeof value).not.toBe("function");
    }
  });
});

// --- 30-33: source status semantics (already enforced by the engine; the view model must not
// second-guess it - it only reacts to `status`) -----------------------------------------------

describe("recommendationViewModel - source status semantics", () => {
  it("30. RESOLVED/CLEAR (NOT_AVAILABLE) hides the recommendation", () => {
    expect(
      recommendationViewModel(recommendation({ status: "NOT_AVAILABLE", primary_action: null }))
        .visible,
    ).toBe(false);
  });

  it("31. OPEN/INSUFFICIENT_DATA (NOT_AVAILABLE) hides the recommendation", () => {
    expect(
      recommendationViewModel(recommendation({ status: "NOT_AVAILABLE", primary_action: null }))
        .visible,
    ).toBe(false);
  });

  it("32. OPEN/SUPPRESSED (NOT_AVAILABLE) hides the recommendation", () => {
    expect(
      recommendationViewModel(recommendation({ status: "NOT_AVAILABLE", primary_action: null }))
        .visible,
    ).toBe(false);
  });

  it("33. REOPENED/TRIGGERED (AVAILABLE) shows the current recommendation", () => {
    expect(recommendationViewModel(recommendation({ status: "AVAILABLE" })).visible).toBe(true);
  });
});

// --- 34-39: safety copy scan, across every real primary/supporting/risk-note string -------------

describe("recommendationViewModel - safety copy scan", () => {
  const ALL_PRIMARY_CODES = [
    "REVIEW_PRICING_AND_AVAILABILITY",
    "REVIEW_DEMAND_POSITIONING",
    "REVIEW_DISTRIBUTION_MIX",
    "REVIEW_COST_DRIVERS",
    "REVIEW_STAFFING_PLAN",
  ];
  const ALL_SUPPORTING_CODES = [
    "CHECK_CHANNEL_VISIBILITY",
    "CHECK_BOOKING_RESTRICTIONS",
    "CHECK_PRICING",
    "CHECK_AVAILABILITY_AND_RESTRICTIONS",
    "CHECK_DIRECT_CHANNEL_AVAILABILITY",
    "CHECK_DISTRIBUTION_CONFIGURATION",
    "CHECK_RECENT_COST_ENTRIES",
    "CHECK_VOLUME_VS_COST",
    "CHECK_SHIFT_COVERAGE",
    "CHECK_SCHEDULED_HOURS",
  ];
  const ALL_RISK_NOTES = [
    "PRICING_CHANGE_MAY_AFFECT_REVENUE",
    "STAFFING_CHANGE_MAY_AFFECT_SERVICE",
    "DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY",
  ];

  it.each(ALL_PRIMARY_CODES)("34-38. primary action %s never uses autonomous-action vocabulary", (code) => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ action_code: code, risk_notes: ALL_RISK_NOTES }),
        supporting_checks: ALL_SUPPORTING_CODES.map((c) => action({ action_code: c })),
      }),
    );
    const text = allCopyText(vm).toLowerCase();
    for (const phrase of FORBIDDEN_PHRASES) {
      expect(text, `expected "${phrase}" to be absent from copy for ${code}`).not.toContain(phrase);
    }
  });

  it("39. no autonomous-action vocabulary anywhere across the whole static copy set", () => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ risk_notes: ALL_RISK_NOTES }),
        supporting_checks: ALL_SUPPORTING_CODES.map((c) => action({ action_code: c })),
      }),
    );
    const text = allCopyText(vm).toLowerCase();
    for (const phrase of FORBIDDEN_PHRASES) {
      expect(text).not.toContain(phrase);
    }
  });
});

// --- 40-45: business logic boundary -------------------------------------------------------------

describe("recommendationViewModel - business logic boundary", () => {
  it("40. copy is derived from action_code alone - the view model never reads/branches on decision_type", () => {
    // The function signature itself proves this: `RecommendationResponse` carries no
    // `decision_type` field at all, so there is nothing to branch on even by accident.
    const vm = recommendationViewModel(recommendation());
    expect(vm).not.toHaveProperty("decision_type");
  });

  it("41. status is never recomputed - an AVAILABLE with a null primary_action (a hypothetical contract drift) fails safe, it does not invent one", () => {
    const vm = recommendationViewModel(recommendation({ status: "AVAILABLE", primary_action: null }));
    expect(vm.visible).toBe(false);
  });

  it("42. confidence is never read or re-formatted by this view model at all", () => {
    const vm = recommendationViewModel(recommendation({ confidence: "81.23" }));
    expect(JSON.stringify(vm)).not.toContain("81.23");
    expect(JSON.stringify(vm)).not.toMatch(/%/);
  });

  it("43. no priority/rank field is read or exposed", () => {
    const vm = recommendationViewModel(recommendation());
    expect(vm).not.toHaveProperty("priority");
    expect(vm).not.toHaveProperty("rank");
  });

  it("44. no threshold/business value comparison is performed - supporting_facts are never read here", () => {
    const vm = recommendationViewModel(
      recommendation({
        primary_action: action({ supporting_facts: { actual_pickup: "3", expected_pickup: "7.50" } }),
      }),
    );
    expect(JSON.stringify(vm)).not.toContain("3");
    expect(JSON.stringify(vm)).not.toContain("7.50");
  });

  it("45. supporting action order out of the engine is preserved exactly, never re-sorted by code", () => {
    const vm = recommendationViewModel(
      recommendation({
        supporting_checks: [
          action({ action_code: "CHECK_SCHEDULED_HOURS" }),
          action({ action_code: "CHECK_SHIFT_COVERAGE" }),
        ],
      }),
    );
    expect(vm.supporting.map((s) => s.actionCode)).toEqual(["CHECK_SCHEDULED_HOURS", "CHECK_SHIFT_COVERAGE"]);
  });
});

// --- 46-51: technical leaks ----------------------------------------------------------------------

describe("recommendationViewModel - technical leaks", () => {
  it("46-51. never exposes fingerprint/version/raw action_code/category/scope/observation ids", () => {
    const vm = recommendationViewModel(
      recommendation({
        fingerprint: "f".repeat(64),
        version: "recommendation-engine-v1",
        primary_action: action({
          action_code: "REVIEW_PRICING_AND_AVAILABILITY",
          category: "REVIEW_PRICING",
          scope: "STAY_DATE",
        }),
      }),
    );
    const text = JSON.stringify(vm);
    expect(text).not.toContain("f".repeat(64));
    expect(text).not.toContain("recommendation-engine-v1");
    expect(text).not.toContain("REVIEW_PRICING\"");
    expect(text).not.toContain("STAY_DATE");
    // The action_code itself is retained on the view model only as a React `key` - it is never
    // rendered as visible text by the component (see recommendation-panel.test.tsx).
  });
});
