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
  GOLDEN_DETAIL_RECOMMENDATION_INSUFFICIENT_CONTEXT,
  GOLDEN_DETAIL_REOPENED,
  GOLDEN_DETAIL_RESOLVED,
  GOLDEN_FIVE_DECISION_TYPES,
  GOLDEN_HISTORY_INSUFFICIENT_LATEST,
  GOLDEN_HISTORY_OPEN_TRIGGERED,
  GOLDEN_HISTORY_PAGE_1,
  GOLDEN_HISTORY_PAGE_2,
  GOLDEN_HISTORY_REOPENED,
  GOLDEN_HISTORY_RESOLVED,
  recommendationFor,
} from "./fixtures";

/** The exact forbidden phrases the Gate 17 spec names, plus the broader autonomous-action
 * vocabulary it forbids everywhere - scanned across every rendered golden scenario below. */
const FORBIDDEN_RECOMMENDATION_PHRASES = [
  "abbassa il prezzo",
  "fai uno sconto",
  "chiudi ota",
  "cambia fornitore",
  "riduci personale",
  "manda a casa",
  "applica",
  "esegui",
  "approva",
];

function expectNoForbiddenRecommendationLanguage(container: HTMLElement) {
  const text = (container.textContent ?? "").toLowerCase();
  for (const phrase of FORBIDDEN_RECOMMENDATION_PHRASES) {
    expect(text, `expected "${phrase}" to be absent`).not.toContain(phrase);
  }
}

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
    const { container: content } = render(<DecisionDetailContent detail={GOLDEN_DETAIL_OPEN_TRIGGERED} />);
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

    // AVAILABLE (Pickup): "Cosa puoi valutare" renders, after Evidenze, with the real primary
    // action and supporting checks pickup_rule would compute from these exact facts.
    expect(screen.getByText("Cosa puoi valutare")).not.toBeNull();
    expect(screen.getByText("Rivedi prezzi e disponibilità")).not.toBeNull();
    expect(screen.getByText("Verifica la visibilità sui canali")).not.toBeNull();
    expect(screen.getByText("Verifica le restrizioni di prenotazione")).not.toBeNull();
    const text = content.textContent ?? "";
    expect(text.indexOf("Evidenze")).toBeLessThan(text.indexOf("Cosa puoi valutare"));
    expectNoForbiddenRecommendationLanguage(content);
  });
});

describe("Golden B: RESOLVED", () => {
  it("shows no current priority for a CLEAR latest observation, the resolved date, and RESOLVED in the timeline", () => {
    render(<DecisionDetailContent detail={GOLDEN_DETAIL_RESOLVED} />);

    expect(screen.queryByText(/Priorità #/)).toBeNull();
    expect(screen.getAllByText(/Risolta/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Risolta il 24 settembre 2026/)).not.toBeNull();
    // F. NOT_AVAILABLE: no stale recommendation from before the problem cleared.
    expect(screen.queryByText("Cosa puoi valutare")).toBeNull();

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
    const { container: content } = render(<DecisionDetailContent detail={GOLDEN_DETAIL_REOPENED} />);
    expect(screen.getByText("2 episodi")).not.toBeNull();
    // H. REOPENED/TRIGGERED -> AVAILABLE again, built from THIS observation's own facts only.
    expect(screen.getByText("Cosa puoi valutare")).not.toBeNull();
    expect(screen.getByText("Rivedi il mix distributivo")).not.toBeNull();
    expectNoForbiddenRecommendationLanguage(content);

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
    // OPEN with a non-TRIGGERED latest observation still hides the recommendation.
    expect(screen.queryByText("Cosa puoi valutare")).toBeNull();

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

describe("Golden G: Recommendation INSUFFICIENT_CONTEXT", () => {
  it("shows a discreet, neutral 'Cosa puoi valutare' when TRIGGERED but facts are insufficient - never a fabricated action", () => {
    const { container } = render(
      <DecisionDetailContent detail={GOLDEN_DETAIL_RECOMMENDATION_INSUFFICIENT_CONTEXT} />,
    );

    expect(screen.getByText("Cosa puoi valutare")).not.toBeNull();
    expect(
      screen.getByText("Non ci sono ancora elementi sufficienti per proporti una verifica affidabile."),
    ).not.toBeNull();
    expect(screen.queryByText("Rivedi prezzi e disponibilità")).toBeNull();
    expect(container.textContent?.toLowerCase()).not.toMatch(/errore|bug|fallimento/);
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
    "renders %s without raw JSON, with only safe recommendation copy, without a graph",
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
        recommendation: recommendationFor(item),
        decision_api_version: "decision-api-v1",
      };

      const { container } = render(<DecisionDetailContent detail={detail} />);

      expect(container.innerHTML).not.toMatch(/[{[]"[a-z_]+":/);
      expect(container.querySelector("svg")).toBeNull();
      expect(container.querySelector("canvas")).toBeNull();
      // Scenarios B/C/D/E: every one of the five real decision types produces a safe, AVAILABLE
      // recommendation from its own real facts, with no autonomous-action vocabulary anywhere.
      expect(screen.getByText("Cosa puoi valutare")).not.toBeNull();
      expectNoForbiddenRecommendationLanguage(container);
      // Technical identifiers stay out of the DOM, recommendation included.
      expect(container.textContent).not.toContain("recommendation-engine-v1");
      expect(container.textContent).not.toContain("a".repeat(64));
    },
  );
});

describe("Golden: safety scan across every Recommendation scenario", () => {
  it("never renders any forbidden autonomous-action phrase, across AVAILABLE/NOT_AVAILABLE/INSUFFICIENT_CONTEXT/REOPENED", () => {
    const scenarios = [
      GOLDEN_DETAIL_OPEN_TRIGGERED,
      GOLDEN_DETAIL_RESOLVED,
      GOLDEN_DETAIL_REOPENED,
      GOLDEN_DETAIL_INSUFFICIENT_LATEST,
      GOLDEN_DETAIL_RECOMMENDATION_INSUFFICIENT_CONTEXT,
    ];
    for (const detail of scenarios) {
      const { container, unmount } = render(<DecisionDetailContent detail={detail} />);
      expectNoForbiddenRecommendationLanguage(container);
      unmount();
    }
  });
});
