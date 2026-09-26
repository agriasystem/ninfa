// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FeedItemResponse } from "@ninfa/contracts";

import { DecisionList } from "./decision-list";

function item(rank: number, decisionId: string): FeedItemResponse {
  return {
    decision_id: decisionId,
    decision_type: "REV_PICKUP_LOW",
    lifecycle_status: "OPEN",
    transition: "OPENED",
    priority: {
      rank,
      impact_score: "10",
      urgency_score: "10",
      confidence_score: "0.9",
      actionability_score: "10",
      priority_score: String(100 - rank), // rank order is NOT priority_score order
      candidate_fingerprint: `fp-${decisionId}`,
    },
    first_seen_local_date: "2026-09-20",
    last_seen_local_date: "2026-09-26",
    episode_count: 1,
    target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
    reason_codes: [],
    facts: { actual_pickup: rank },
    evidence: {},
    economic_proxy: null,
    source_status: "TRIGGERED",
  };
}

describe("DecisionList", () => {
  it("renders every item when there are 5 or fewer", () => {
    const items = [item(1, "d1"), item(2, "d2"), item(3, "d3")];
    render(<DecisionList items={items} propertyId="prop-1" />);

    expect(screen.getAllByText("Pickup sotto le attese")).toHaveLength(3);
  });

  it("renders at most 5 cards when the API returns 8 candidates", () => {
    const items = Array.from({ length: 8 }, (_, index) => item(index + 1, `d${index + 1}`));
    render(<DecisionList items={items} propertyId="prop-1" />);

    expect(screen.getAllByText("Pickup sotto le attese")).toHaveLength(5);
  });

  it("shows a discreet '+N altre decisioni' indication when there are more than 5", () => {
    const items = Array.from({ length: 8 }, (_, index) => item(index + 1, `d${index + 1}`));
    render(<DecisionList items={items} propertyId="prop-1" />);

    expect(screen.getByText("+ 3 altre decisioni")).not.toBeNull();
  });

  it("shows no '+N altre decisioni' when there are 5 or fewer", () => {
    const items = [item(1, "d1")];
    render(<DecisionList items={items} propertyId="prop-1" />);

    expect(screen.queryByText(/altre decisioni/)).toBeNull();
  });

  it("preserves the backend's own order (priority_rank ASC) - never re-sorts by anything else", () => {
    const items = [item(1, "first"), item(2, "second"), item(3, "third")];
    const { container } = render(<DecisionList items={items} propertyId="prop-1" />);

    const ranks = Array.from(container.querySelectorAll(".decision-card__rank")).map(
      (element) => element.textContent,
    );
    expect(ranks).toEqual(["#1", "#2", "#3"]);
  });

  it("makes every card a real link to its Decision Detail page, with property + decision ids", () => {
    const items = [item(1, "dec-abc")];
    render(<DecisionList items={items} propertyId="prop-1" />);

    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/oggi/decisioni/dec-abc?property=prop-1");
  });
});
