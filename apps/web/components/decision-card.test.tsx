// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DecisionCardData } from "@/lib/decisions/card-view-models";

import { DecisionCard } from "./decision-card";

const FORBIDDEN_RECOMMENDATIONS = [
  "Abbassa il prezzo",
  "Riduci il personale",
  "Chiudi Booking",
  "Fai una promozione",
  "Contatta il fornitore",
];

function base(overrides: Partial<DecisionCardData>): DecisionCardData {
  return {
    decisionId: "dec-1",
    rank: 1,
    title: "Pickup sotto le attese",
    confidencePercent: 82,
    economicProxy: null,
    card: { kind: "PICKUP", stayDate: "2026-10-01", actualPickup: 3, expectedPickup: "7.50", deltaRooms: "-4.50", missingRooms: "4.50" },
    ...overrides,
  };
}

describe("DecisionCard", () => {
  it("shows the rank and the static title", () => {
    render(<DecisionCard data={base({ rank: 2 })} />);

    expect(screen.getByText("#2")).not.toBeNull();
    expect(screen.getByText("Pickup sotto le attese")).not.toBeNull();
  });

  it("shows confidence as 'Affidabilità N%' - never a bucketed Alta/Media/Bassa label", () => {
    const { container } = render(<DecisionCard data={base({ confidencePercent: 82 })} />);

    expect(container.textContent).toContain("Affidabilità 82%");
    expect(container.textContent).not.toMatch(/Alta|Media|Bassa/);
  });

  it("renders a PICKUP card with its own real facts", () => {
    render(<DecisionCard data={base({})} />);

    expect(screen.getByText("2026-10-01")).not.toBeNull();
    expect(screen.getByText("3")).not.toBeNull();
  });

  it("renders an OCCUPANCY card", () => {
    const data = base({
      title: "Rischio occupazione",
      card: {
        kind: "OCCUPANCY",
        stayDate: "2026-10-02",
        forecastRooms: "40.00",
        expectedFinalRooms: "55.00",
        occupancyGapPp: "27.30",
        roomShortfall: "15.00",
      },
    });
    render(<DecisionCard data={data} />);

    expect(screen.getByText("Rischio occupazione")).not.toBeNull();
    expect(screen.getByText("2026-10-02")).not.toBeNull();
  });

  it("renders an OTA card without accusing a specific OTA and without a recommendation", () => {
    const data = base({
      title: "Dipendenza OTA",
      card: {
        kind: "OTA",
        windowStart: "2026-08-01",
        windowEnd: "2026-09-30",
        otaShare: "62.50",
        expectedOtaShare: "45.00",
        structuralCondition: true,
        risingCondition: false,
      },
    });
    const { container } = render(<DecisionCard data={data} />);

    expect(container.textContent).toContain("62,5%");
    expect(container.textContent).not.toMatch(/booking\.com|expedia|airbnb/i);
  });

  it("renders a COST card with a formatted economic proxy", () => {
    const data = base({
      title: "Costo per camera anomalo",
      card: {
        kind: "COST",
        costCategory: "FOOD_AND_BEVERAGE",
        periodStart: "2026-09-01",
        currency: "EUR",
        actualCpor: "12.40",
        expectedCpor: "9.00",
        deltaCpor: "3.40",
      },
      economicProxy: { label: "cost_gap_proxy", amount: "482.30", currency: "EUR" },
    });
    const { container } = render(<DecisionCard data={data} />);

    expect(container.textContent).toContain("FOOD_AND_BEVERAGE");
    expect(container.textContent).toContain("482,30");
    // Never labelled as a loss/saving outright - only the neutral proxy figure.
    expect(container.textContent?.toLowerCase()).not.toMatch(/perdita|risparmio/);
  });

  it("renders a LABOR card without naming individual employees", () => {
    const data = base({
      title: "Ore di personale sopra l'atteso",
      card: {
        kind: "LABOR",
        workDate: "2026-09-25",
        laborCategory: "HOUSEKEEPING",
        scheduledHours: "40.00",
        expectedHours: "28.00",
        excessHours: "12.00",
      },
    });
    const { container } = render(<DecisionCard data={data} />);

    expect(container.textContent).toContain("HOUSEKEEPING");
    expect(container.textContent).toContain("12,0 h");
  });

  it("handles a missing economic proxy gracefully - no crash, no 'undefined' text", () => {
    const { container } = render(<DecisionCard data={base({ economicProxy: null })} />);

    expect(container.textContent).not.toContain("undefined");
    expect(container.textContent).not.toContain("null");
  });

  it("never renders the raw facts object as JSON", () => {
    const { container } = render(<DecisionCard data={base({})} />);

    expect(container.innerHTML).not.toMatch(/[{[]"[a-z_]+":/);
  });

  it("never renders a recommendation - only problem + evidence", () => {
    const { container } = render(<DecisionCard data={base({})} />);

    for (const phrase of FORBIDDEN_RECOMMENDATIONS) {
      expect(container.textContent).not.toContain(phrase);
    }
  });

  it("never renders a graph element (svg/canvas)", () => {
    const { container } = render(<DecisionCard data={base({})} />);

    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("omits the confidence line entirely when confidencePercent is null, rather than showing a placeholder", () => {
    const { container } = render(<DecisionCard data={base({ confidencePercent: null })} />);

    expect(container.textContent).not.toContain("Affidabilità");
  });
});
