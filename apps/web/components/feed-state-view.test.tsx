// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DecisionFeedResponse, FeedItemResponse } from "@ninfa/contracts";

import { FeedStateView } from "./feed-state-view";

function feed(overrides: Partial<DecisionFeedResponse>): DecisionFeedResponse {
  return {
    property_id: "prop-1",
    as_of_local_date: "2026-09-26",
    feed_state: "NOT_PROCESSED",
    decision_run_id: null,
    run_sequence: null,
    triggered_count: null,
    clear_count: null,
    insufficient_count: null,
    not_applicable_count: null,
    suppressed_count: null,
    items: [],
    ...overrides,
  };
}

function triggeredItem(rank: number, decisionId: string): FeedItemResponse {
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
      priority_score: "10",
      candidate_fingerprint: `fp-${decisionId}`,
    },
    first_seen_local_date: "2026-09-20",
    last_seen_local_date: "2026-09-26",
    episode_count: 1,
    target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
    reason_codes: ["TRIGGER_PICKUP_SHORTFALL"],
    facts: { actual_pickup: 3, expected_pickup: "7.50" },
    evidence: {},
    economic_proxy: null,
    source_status: "TRIGGERED",
  };
}

function renderedStates(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("[data-feed-state]")).map(
    (element) => element.getAttribute("data-feed-state") ?? "",
  );
}

describe("FeedStateView", () => {
  it("renders the NOT_PROCESSED copy and never 'Tutto sotto controllo'", () => {
    const { container } = render(<FeedStateView feed={feed({ feed_state: "NOT_PROCESSED" })} />);

    expect(screen.getByText("Analisi non ancora disponibile")).not.toBeNull();
    expect(container.textContent).not.toContain("Tutto sotto controllo");
    expect(renderedStates(container)).toEqual(["NOT_PROCESSED"]);
  });

  it("renders the DATA_QUALITY_LIMITED copy and never 'Tutto sotto controllo'", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "DATA_QUALITY_LIMITED", insufficient_count: 2, suppressed_count: 1 })}
      />,
    );

    expect(screen.getByText("Analisi parziale")).not.toBeNull();
    expect(container.textContent).not.toContain("Tutto sotto controllo");
    expect(container.textContent).toContain("2 in attesa di dati sufficienti");
    expect(container.textContent).toContain("1 con confidenza troppo bassa");
    // "suppressed" must never be translated as a technical error.
    expect(container.textContent?.toLowerCase()).not.toContain("error");
    expect(renderedStates(container)).toEqual(["DATA_QUALITY_LIMITED"]);
  });

  it("renders 'Tutto sotto controllo' ONLY for NO_ACTION_REQUIRED", () => {
    const { container } = render(<FeedStateView feed={feed({ feed_state: "NO_ACTION_REQUIRED" })} />);

    expect(container.textContent).toContain("Tutto sotto controllo");
    expect(renderedStates(container)).toEqual(["NO_ACTION_REQUIRED"]);
  });

  it("renders decision cards for ACTION_REQUIRED", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({
          feed_state: "ACTION_REQUIRED",
          triggered_count: 1,
          items: [triggeredItem(1, "dec-1")],
        })}
      />,
    );

    expect(container.textContent).toContain("Pickup sotto le attese");
    expect(container.textContent).not.toContain("Tutto sotto controllo");
    expect(renderedStates(container)).toEqual(["ACTION_REQUIRED"]);
  });

  it("renders exactly one of the four states at a time - never two simultaneously", () => {
    const states: DecisionFeedResponse["feed_state"][] = [
      "NOT_PROCESSED",
      "DATA_QUALITY_LIMITED",
      "NO_ACTION_REQUIRED",
      "ACTION_REQUIRED",
    ];
    for (const state of states) {
      const { container, unmount } = render(<FeedStateView feed={feed({ feed_state: state })} />);
      expect(renderedStates(container)).toEqual([state]);
      unmount();
    }
  });
});
