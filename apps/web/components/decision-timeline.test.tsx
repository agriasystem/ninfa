// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DecisionTarget, ObservationDetail } from "@ninfa/contracts";

import { DecisionTimeline } from "./decision-timeline";

const target: DecisionTarget = {
  type: "REV_PICKUP_LOW",
  booking_data_source_id: "src-1",
  stay_date: "2026-10-01",
};

function observation(overrides: Partial<ObservationDetail>): ObservationDetail {
  return {
    observation_id: "obs-1",
    as_of_local_date: "2026-09-20",
    source_status: "TRIGGERED",
    lifecycle_transition: "OPENED",
    source_evaluation_fingerprint: "should-not-render-fp",
    source_target_key: "should-not-render-key",
    reason_codes: [],
    confidence_score: "0.8",
    priority: null,
    facts: {},
    evidence: {},
    economic_proxy: null,
    memory_version: "should-not-render-memver",
    ...overrides,
  };
}

function noop() {
  /* no-op */
}

describe("DecisionTimeline", () => {
  it("shows the empty-history message and never crashes when there are zero observations", () => {
    render(
      <DecisionTimeline
        items={[]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByText("Nessuna evoluzione disponibile.")).not.toBeNull();
  });

  it("renders items in exactly the given (newest-first) order - never re-sorts", () => {
    const items = [
      observation({ observation_id: "newest", as_of_local_date: "2026-09-26" }),
      observation({ observation_id: "older", as_of_local_date: "2026-09-20" }),
    ];
    const { container } = render(
      <DecisionTimeline
        items={items}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    const dates = Array.from(container.querySelectorAll(".decision-timeline__date")).map(
      (el) => el.getAttribute("datetime"),
    );
    expect(dates).toEqual(["2026-09-26", "2026-09-20"]);
  });

  it.each([
    ["OPENED", "TRIGGERED", "Rilevata"],
    ["OBSERVED", "TRIGGERED", "Ancora presente"],
    ["RESOLVED", "CLEAR", "Risolta"],
    ["REOPENED", "TRIGGERED", "Ricomparsa"],
    ["NO_STATE_CHANGE", "INSUFFICIENT_DATA", "Dati non sufficienti per una nuova conclusione"],
    ["NO_STATE_CHANGE", "SUPPRESSED_LOW_CONFIDENCE", "Nessuna nuova conclusione affidabile"],
    ["NO_STATE_CHANGE", "NOT_APPLICABLE", "Controllo non applicabile"],
  ] as const)("shows the right copy for %s + %s", (transition, sourceStatus, expected) => {
    render(
      <DecisionTimeline
        items={[observation({ lifecycle_transition: transition, source_status: sourceStatus })]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByText(expected)).not.toBeNull();
  });

  it("never calls any of these copy an error/failure/technical warning", () => {
    const { container } = render(
      <DecisionTimeline
        items={[observation({ lifecycle_transition: "NO_STATE_CHANGE", source_status: "SUPPRESSED_LOW_CONFIDENCE" })]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(container.textContent?.toLowerCase()).not.toMatch(/errore|fallimento|warning/);
  });

  it("shows the historical priority rank only when that observation was TRIGGERED with a rank", () => {
    const triggered = observation({
      observation_id: "t",
      source_status: "TRIGGERED",
      priority: {
        rank: 3,
        impact_score: "1",
        urgency_score: "1",
        confidence_score: "0.8",
        actionability_score: "1",
        priority_score: "1",
        candidate_fingerprint: "fp",
      },
    });
    const clear = observation({ observation_id: "c", source_status: "CLEAR", lifecycle_transition: "RESOLVED" });

    render(
      <DecisionTimeline
        items={[triggered, clear]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByText("Priorità #3")).not.toBeNull();
    expect(screen.queryAllByText(/Priorità #/)).toHaveLength(1);
  });

  it("builds the key fact from EACH observation's own historical facts, not the current detail's", () => {
    const items = [
      observation({ observation_id: "recent", as_of_local_date: "2026-09-26", facts: { actual_pickup: 2 } }),
      observation({ observation_id: "past", as_of_local_date: "2026-09-19", facts: { actual_pickup: 6 } }),
    ];

    render(
      <DecisionTimeline
        items={items}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByText("2 camere in pickup")).not.toBeNull();
    expect(screen.getByText("6 camere in pickup")).not.toBeNull();
  });

  it("never renders observation/run/fingerprint/memory-version technical ids", () => {
    const { container } = render(
      <DecisionTimeline
        items={[observation({})]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    expect(container.textContent).not.toContain("should-not-render-fp");
    expect(container.textContent).not.toContain("should-not-render-key");
    expect(container.textContent).not.toContain("should-not-render-memver");
    expect(container.textContent).not.toContain("obs-1");
  });

  it("shows a 'Mostra eventi precedenti' button only when hasMore is true", () => {
    const { rerender } = render(
      <DecisionTimeline
        items={[observation({})]}
        target={target}
        hasMore={false}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );
    expect(screen.queryByRole("button", { name: "Mostra eventi precedenti" })).toBeNull();

    rerender(
      <DecisionTimeline
        items={[observation({})]}
        target={target}
        hasMore={true}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );
    expect(screen.getByRole("button", { name: "Mostra eventi precedenti" })).not.toBeNull();
  });

  it("disables the load-more button while loading and calls onLoadMore when clicked", async () => {
    const onLoadMore = vi.fn();
    const user = userEvent.setup();
    render(
      <DecisionTimeline
        items={[observation({})]}
        target={target}
        hasMore={true}
        loadingMore={false}
        loadMoreError={false}
        onLoadMore={onLoadMore}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Mostra eventi precedenti" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
  });

  it("shows the load-more button disabled while a page is loading", () => {
    render(
      <DecisionTimeline
        items={[observation({})]}
        target={target}
        hasMore={true}
        loadingMore={true}
        loadMoreError={false}
        onLoadMore={noop}
      />,
    );

    const button = screen.getByRole("button", { name: "Caricamento…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("shows a load-more error without losing the already-loaded history", () => {
    render(
      <DecisionTimeline
        items={[observation({ observation_id: "already-loaded" })]}
        target={target}
        hasMore={true}
        loadingMore={false}
        loadMoreError={true}
        onLoadMore={noop}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("Non siamo riusciti a caricare altri eventi");
    expect(screen.getByText("Rilevata")).not.toBeNull(); // the already-loaded item is still there
  });
});
