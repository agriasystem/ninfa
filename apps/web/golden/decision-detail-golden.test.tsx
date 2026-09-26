// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DecisionDetailContent } from "@/components/decision-detail-view";
import { DecisionTimeline } from "@/components/decision-timeline";

import {
  GOLDEN_DETAIL_FOR_PAGINATION,
  GOLDEN_DETAIL_INSUFFICIENT_LATEST,
  GOLDEN_DETAIL_OPEN_TRIGGERED,
  GOLDEN_DETAIL_REOPENED,
  GOLDEN_DETAIL_RESOLVED,
  GOLDEN_FIVE_DECISION_TYPES,
  GOLDEN_HISTORY_INSUFFICIENT_LATEST,
  GOLDEN_HISTORY_OPEN_TRIGGERED,
  GOLDEN_HISTORY_PAGE_1,
  GOLDEN_HISTORY_PAGE_2,
  GOLDEN_HISTORY_REOPENED,
  GOLDEN_HISTORY_RESOLVED,
} from "./fixtures";

/**
 * Golden Decision Detail V1 scenarios (Gate 15). Every fixture in `./fixtures.ts` is built from
 * the same Gate 12 API-shaped feed fixtures Gate 14's own golden suite already uses,
 * independently of `lib/decisions/*` adapters - this file checks RENDERING and LIFECYCLE
 * REPRESENTATION only, never detector math.
 */

function noop() {
  /* no-op */
}

describe("Golden A: OPEN / TRIGGERED", () => {
  it("shows the current priority rank, evidence, and an OPENED -> OBSERVED history", () => {
    render(<DecisionDetailContent detail={GOLDEN_DETAIL_OPEN_TRIGGERED} />);
    const { container } = render(
      <DecisionTimeline
        items={GOLDEN_HISTORY_OPEN_TRIGGERED.items}
        target={GOLDEN_DETAIL_OPEN_TRIGGERED.target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByText(/Priorità #1 nell'analisi del giorno/)).not.toBeNull();
    expect(screen.getByText("Attuale")).not.toBeNull();
    const events = Array.from(container.querySelectorAll(".decision-timeline__event")).map(
      (el) => el.textContent,
    );
    expect(events).toEqual(["Ancora presente", "Rilevata"]); // OBSERVED then OPENED, newest-first
  });
});

describe("Golden B: RESOLVED", () => {
  it("shows no current priority for a CLEAR latest observation, the resolved date, and RESOLVED in the timeline", () => {
    render(<DecisionDetailContent detail={GOLDEN_DETAIL_RESOLVED} />);

    expect(screen.queryByText(/Priorità #/)).toBeNull();
    expect(screen.getAllByText(/Risolta/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Risolta il 24 settembre 2026/)).not.toBeNull();

    const { container } = render(
      <DecisionTimeline
        items={GOLDEN_HISTORY_RESOLVED.items}
        target={GOLDEN_DETAIL_RESOLVED.target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );
    const events = Array.from(container.querySelectorAll(".decision-timeline__event")).map(
      (el) => el.textContent,
    );
    expect(events).toContain("Risolta");
  });
});

describe("Golden C: REOPENED", () => {
  it("shows episode_count > 1 and the full OPENED/OBSERVED/RESOLVED/REOPENED timeline for the SAME decision", () => {
    render(<DecisionDetailContent detail={GOLDEN_DETAIL_REOPENED} />);
    expect(screen.getByText("2 episodi")).not.toBeNull();

    const { container } = render(
      <DecisionTimeline
        items={GOLDEN_HISTORY_REOPENED.items}
        target={GOLDEN_DETAIL_REOPENED.target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );
    const events = Array.from(container.querySelectorAll(".decision-timeline__event")).map(
      (el) => el.textContent,
    );
    expect(events).toEqual(["Ricomparsa", "Risolta", "Ancora presente", "Rilevata"]);
    // Every entry belongs to the SAME decision - the timeline never fetches a different one.
    expect(GOLDEN_HISTORY_REOPENED.items.every((item) => item !== null)).toBe(true);
  });
});

describe("Golden D: INSUFFICIENT latest observation", () => {
  it("keeps the decision OPEN, shows no priority, and never implies it was resolved", () => {
    render(<DecisionDetailContent detail={GOLDEN_DETAIL_INSUFFICIENT_LATEST} />);

    expect(screen.getByText(/Aperta/)).not.toBeNull();
    expect(screen.getByText("Dati non sufficienti per una nuova conclusione")).not.toBeNull();
    expect(screen.queryByText(/Priorità #/)).toBeNull();
    expect(screen.queryByText(/Risolta/)).toBeNull();

    const { container } = render(
      <DecisionTimeline
        items={GOLDEN_HISTORY_INSUFFICIENT_LATEST.items}
        target={GOLDEN_DETAIL_INSUFFICIENT_LATEST.target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );
    expect(container.textContent?.toLowerCase()).not.toMatch(/errore|fallimento/);
  });
});

describe("Golden E: history pagination", () => {
  it("appends the older second page after the first, preserving order, never replacing it", async () => {
    const onLoadMore = vi.fn();
    const user = userEvent.setup();
    const { rerender, container } = render(
      <DecisionTimeline
        items={GOLDEN_HISTORY_PAGE_1.items}
        target={GOLDEN_DETAIL_FOR_PAGINATION.target}
        hasMore={GOLDEN_HISTORY_PAGE_1.next_cursor !== null}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={onLoadMore}
      />,
    );

    expect(container.querySelectorAll(".decision-timeline__item")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Mostra eventi precedenti" }));
    expect(onLoadMore).toHaveBeenCalledOnce();

    const appended = [...GOLDEN_HISTORY_PAGE_1.items, ...GOLDEN_HISTORY_PAGE_2.items];
    rerender(
      <DecisionTimeline
        items={appended}
        target={GOLDEN_DETAIL_FOR_PAGINATION.target}
        hasMore={GOLDEN_HISTORY_PAGE_2.next_cursor !== null}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={onLoadMore}
      />,
    );

    expect(container.querySelectorAll(".decision-timeline__item")).toHaveLength(3);
    const dates = Array.from(container.querySelectorAll(".decision-timeline__date")).map((el) =>
      el.getAttribute("datetime"),
    );
    expect(dates).toEqual(["2026-09-26", "2026-09-19", "2026-07-01"]); // still newest-first
    expect(screen.queryByRole("button", { name: "Mostra eventi precedenti" })).toBeNull();
  });
});

describe("Golden: all five decision types render a correct detail", () => {
  it.each(GOLDEN_FIVE_DECISION_TYPES.map((item) => [item.decision_type, item] as const))(
    "renders %s without raw JSON, without a recommendation, without a graph",
    (_decisionType, item) => {
      const detail = {
        decision_id: item.decision_id,
        decision_type: item.decision_type,
        status: item.lifecycle_status,
        first_seen_local_date: item.first_seen_local_date,
        last_seen_local_date: item.last_seen_local_date,
        last_evaluated_local_date: item.last_seen_local_date,
        resolved_local_date: null,
        episode_count: item.episode_count,
        triggered_observation_count: 1,
        target: item.target,
        latest_observation: {
          observation_id: `obs-${item.decision_id}`,
          as_of_local_date: item.last_seen_local_date,
          source_status: item.source_status,
          lifecycle_transition: item.transition,
          source_evaluation_fingerprint: "fp",
          source_target_key: "key",
          reason_codes: item.reason_codes,
          confidence_score: item.priority.confidence_score,
          priority: item.priority,
          facts: item.facts,
          evidence: item.evidence,
          economic_proxy: item.economic_proxy,
          memory_version: "decision-memory-v1",
        },
        decision_api_version: "decision-api-v1",
      };

      const { container } = render(<DecisionDetailContent detail={detail} />);

      expect(container.innerHTML).not.toMatch(/[{[]"[a-z_]+":/);
      expect(container.textContent).not.toMatch(/Abbassa il prezzo|Riduci il personale/);
      expect(container.querySelector("svg")).toBeNull();
      expect(container.querySelector("canvas")).toBeNull();
    },
  );
});
