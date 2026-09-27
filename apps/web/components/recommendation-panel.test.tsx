// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecommendationResponse, RecommendedActionResponse } from "@ninfa/contracts";

import { RecommendationPanel } from "./recommendation-panel";

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

describe("RecommendationPanel - status", () => {
  it("renders nothing for NOT_AVAILABLE", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({ status: "NOT_AVAILABLE", primary_action: null, confidence: null })}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a discreet, neutral section for INSUFFICIENT_CONTEXT", () => {
    render(<RecommendationPanel recommendation={recommendation({ status: "INSUFFICIENT_CONTEXT", primary_action: null })} />);
    expect(screen.getByText("Cosa puoi valutare")).not.toBeNull();
    expect(
      screen.getByText("Non ci sono ancora elementi sufficienti per proporti una verifica affidabile."),
    ).not.toBeNull();
  });

  it("renders nothing for an unrecognised future status", () => {
    const { container } = render(
      <RecommendationPanel recommendation={recommendation({ status: "SOMETHING_ELSE" })} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for AVAILABLE with an unrecognised primary action_code, never a raw enum", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({ primary_action: action({ action_code: "FUTURE_ACTION_CODE" }) })}
      />,
    );
    expect(container.firstChild).toBeNull();
    expect(container.textContent).not.toContain("FUTURE_ACTION_CODE");
  });
});

describe("RecommendationPanel - structure and content", () => {
  it("shows the primary action's title and description, the supporting checks and the human-review note", () => {
    render(
      <RecommendationPanel
        recommendation={recommendation({
          supporting_checks: [action({ action_code: "CHECK_CHANNEL_VISIBILITY" })],
        })}
      />,
    );

    expect(screen.getByRole("heading", { name: "Cosa puoi valutare" })).not.toBeNull();
    expect(screen.getByText("Rivedi prezzi e disponibilità")).not.toBeNull();
    expect(
      screen.getByText(
        "Verifica se prezzi, disponibilità e restrizioni sono coerenti con l'andamento della data.",
      ),
    ).not.toBeNull();
    expect(screen.getByText("Da verificare")).not.toBeNull();
    expect(screen.getByText("Verifica la visibilità sui canali")).not.toBeNull();
    expect(
      screen.getByText("Valuta questa indicazione nel contesto operativo della tua struttura."),
    ).not.toBeNull();
  });

  it("uses a semantic list for supporting checks, never a checkbox", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({
          supporting_checks: [
            action({ action_code: "CHECK_CHANNEL_VISIBILITY" }),
            action({ action_code: "CHECK_BOOKING_RESTRICTIONS" }),
          ],
        })}
      />,
    );
    const list = container.querySelector(".recommendation-panel__supporting ul");
    expect(list?.tagName).toBe("UL");
    expect(list?.querySelectorAll("li").length).toBe(2);
    expect(container.querySelectorAll('input[type="checkbox"]').length).toBe(0);
  });

  it("uses a semantic list for risk notes", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({
          primary_action: action({ risk_notes: ["PRICING_CHANGE_MAY_AFFECT_REVENUE"] }),
        })}
      />,
    );
    expect(screen.getByText("Da tenere presente")).not.toBeNull();
    const list = container.querySelector(".recommendation-panel__risk-notes ul");
    expect(list?.tagName).toBe("UL");
    expect(screen.getByText("Le variazioni di prezzo possono incidere sui ricavi.")).not.toBeNull();
  });

  it("omits the supporting-checks block entirely when there are none - never an empty heading", () => {
    const { container } = render(<RecommendationPanel recommendation={recommendation({ supporting_checks: [] })} />);
    expect(screen.queryByText("Da verificare")).toBeNull();
    expect(container.querySelector(".recommendation-panel__supporting")).toBeNull();
  });

  it("omits the risk-notes block entirely when there are none", () => {
    const { container } = render(
      <RecommendationPanel recommendation={recommendation({ primary_action: action({ risk_notes: [] }) })} />,
    );
    expect(screen.queryByText("Da tenere presente")).toBeNull();
    expect(container.querySelector(".recommendation-panel__risk-notes")).toBeNull();
  });
});

describe("RecommendationPanel - safety", () => {
  it("has no button, link, or checkbox anywhere in the section - read-only by construction", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({
          supporting_checks: [action({ action_code: "CHECK_CHANNEL_VISIBILITY" })],
          primary_action: action({ risk_notes: ["PRICING_CHANGE_MAY_AFFECT_REVENUE"] }),
        })}
      />,
    );
    expect(container.querySelectorAll("button, a, input, [role='button'], [role='checkbox']").length).toBe(0);
  });

  it("never renders fingerprint, version, or raw action_code/category/scope", () => {
    const { container } = render(
      <RecommendationPanel
        recommendation={recommendation({
          fingerprint: "b".repeat(64),
          supporting_checks: [action({ action_code: "CHECK_CHANNEL_VISIBILITY" })],
        })}
      />,
    );
    expect(container.textContent).not.toContain("b".repeat(64));
    expect(container.textContent).not.toContain("recommendation-engine-v1");
    expect(container.textContent).not.toContain("REVIEW_PRICING_AND_AVAILABILITY");
    expect(container.textContent).not.toContain("CHECK_CHANNEL_VISIBILITY");
    expect(container.textContent).not.toContain("STAY_DATE");
  });

  it("never renders the recommendation's own confidence percentage", () => {
    const { container } = render(
      <RecommendationPanel recommendation={recommendation({ confidence: "81.23" })} />,
    );
    expect(container.textContent).not.toContain("81.23");
    expect(container.textContent).not.toMatch(/%/);
  });

  it("never uses forbidden autonomous-action vocabulary for any of the five primary actions", () => {
    const codes = [
      "REVIEW_PRICING_AND_AVAILABILITY",
      "REVIEW_DEMAND_POSITIONING",
      "REVIEW_DISTRIBUTION_MIX",
      "REVIEW_COST_DRIVERS",
      "REVIEW_STAFFING_PLAN",
    ];
    const forbidden = [
      "abbassa",
      "sconto",
      "chiudi",
      "cambia fornitore",
      "riduci personale",
      "manda a casa",
      "applica",
      "esegui",
      "approva",
    ];
    for (const code of codes) {
      const { container, unmount } = render(
        <RecommendationPanel recommendation={recommendation({ primary_action: action({ action_code: code }) })} />,
      );
      const text = (container.textContent ?? "").toLowerCase();
      for (const phrase of forbidden) {
        expect(text, `"${phrase}" must not appear for ${code}`).not.toContain(phrase);
      }
      unmount();
    }
  });
});
