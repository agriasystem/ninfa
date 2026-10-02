// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DecisionFeedResponse, FeedItemResponse } from "@ninfa/contracts";

import { FeedStateView } from "./feed-state-view";

const TIME_ZONE = "Europe/Rome";

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
    analysis_coverage: { summary: "FULL", domains: [] },
    input_freshness: { bookings: { status: "UNKNOWN", last_successful_import_finished_at: null } },
    last_successful_analysis: null,
    items: [],
    ...overrides,
  };
}

const partialCoverage: DecisionFeedResponse["analysis_coverage"] = {
  summary: "PARTIAL",
  domains: [
    { domain: "REVENUE", status: "EVALUATED", reason: null },
    { domain: "DISTRIBUTION", status: "EVALUATED", reason: null },
    { domain: "COSTS", status: "SKIPPED", reason: "NOT_REQUESTED" },
    { domain: "LABOR", status: "SKIPPED", reason: "NOT_REQUESTED" },
  ],
};

const unknownCoverage: DecisionFeedResponse["analysis_coverage"] = {
  summary: "UNKNOWN",
  domains: [],
};

const knownFreshness: DecisionFeedResponse["input_freshness"] = {
  bookings: { status: "KNOWN", last_successful_import_finished_at: "2026-09-29T07:15:00Z" },
};

const unknownFreshness: DecisionFeedResponse["input_freshness"] = {
  bookings: { status: "UNKNOWN", last_successful_import_finished_at: null },
};

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
      confidence_score: "90",
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
    const { container } = render(
      <FeedStateView feed={feed({ feed_state: "NOT_PROCESSED" })} timeZone={TIME_ZONE} />,
    );

    expect(screen.getByText("Analisi non ancora disponibile")).not.toBeNull();
    expect(container.textContent).not.toContain("Tutto sotto controllo");
    expect(renderedStates(container)).toEqual(["NOT_PROCESSED"]);
  });

  it("renders the DATA_QUALITY_LIMITED copy and never 'Tutto sotto controllo'", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "DATA_QUALITY_LIMITED", insufficient_count: 2, suppressed_count: 1 })}
        timeZone={TIME_ZONE}
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
    const { container } = render(
      <FeedStateView feed={feed({ feed_state: "NO_ACTION_REQUIRED" })} timeZone={TIME_ZONE} />,
    );

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
        timeZone={TIME_ZONE}
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
      const { container, unmount } = render(
        <FeedStateView feed={feed({ feed_state: state })} timeZone={TIME_ZONE} />,
      );
      expect(renderedStates(container)).toEqual([state]);
      unmount();
    }
  });

  // --- Gate 22: analysis coverage ---------------------------------------------------------------

  it("FULL coverage adds no extra line", () => {
    const { container } = render(
      <FeedStateView feed={feed({ feed_state: "NO_ACTION_REQUIRED" })} timeZone={TIME_ZONE} />,
    );

    expect(container.querySelector(".feed-state__coverage")).toBeNull();
  });

  it("PARTIAL coverage shows the skipped domains with Italian labels, never raw enum names", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: partialCoverage })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("Non analizzati: Costi, Personale.");
    expect(container.textContent).not.toContain("COSTS");
    expect(container.textContent).not.toContain("LABOR");
    expect(container.textContent).not.toContain("NOT_REQUESTED");
  });

  it("NO_ACTION_REQUIRED + PARTIAL still says 'Tutto sotto controllo' but visibly qualifies it", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: partialCoverage })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("Tutto sotto controllo");
    expect(container.textContent).toContain("Non analizzati: Costi, Personale.");
  });

  it("DATA_QUALITY_LIMITED + PARTIAL shows both the insufficient-data note and the skipped domains, without confusion", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({
          feed_state: "DATA_QUALITY_LIMITED",
          insufficient_count: 2,
          analysis_coverage: partialCoverage,
        })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("2 in attesa di dati sufficienti");
    expect(container.textContent).toContain("Non analizzati: Costi, Personale.");
  });

  it("UNKNOWN coverage shows the neutral note, not FULL or PARTIAL copy", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: unknownCoverage })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("Copertura dell'analisi non disponibile per questo run.");
    expect(container.textContent).not.toContain("Non analizzati");
  });

  it("a historical/null-shaped coverage payload never crashes the render", () => {
    expect(() =>
      render(
        <FeedStateView
          feed={feed({ feed_state: "NO_ACTION_REQUIRED", analysis_coverage: unknownCoverage })}
          timeZone={TIME_ZONE}
        />,
      ),
    ).not.toThrow();
  });

  // --- Gate 23B: booking input freshness ---------------------------------------------------------

  it("KNOWN freshness renders the factual 'Ultimo import prenotazioni' line", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", input_freshness: knownFreshness })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("Ultimo import prenotazioni:");
    expect(container.textContent).toContain("29 settembre");
    expect(container.textContent).toContain("09:15"); // 07:15 UTC -> 09:15 Europe/Rome (CEST)
  });

  it("respects the property's own timezone, never the browser's", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", input_freshness: knownFreshness })}
        timeZone="America/New_York"
      />,
    );

    expect(container.textContent).toContain("03:15"); // 07:15 UTC -> 03:15 America/New_York
    expect(container.textContent).not.toContain("09:15");
  });

  it("UNKNOWN freshness shows the neutral unavailable copy, never a timestamp", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", input_freshness: unknownFreshness })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain(
      "Informazione sull'ultimo import prenotazioni non disponibile per questo run.",
    );
    expect(container.textContent).not.toContain("Ultimo import prenotazioni:");
  });

  it("never shows a CURRENT/STALE label or raw ids", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NO_ACTION_REQUIRED", input_freshness: knownFreshness })}
        timeZone={TIME_ZONE}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).not.toContain("CURRENT");
    expect(text).not.toContain("STALE");
    expect(text.toLowerCase()).not.toContain("aggiornat"); // never "Prenotazioni aggiornate al ..."
  });

  it("a historical run (UNKNOWN freshness) never crashes the render", () => {
    expect(() =>
      render(
        <FeedStateView
          feed={feed({ feed_state: "NO_ACTION_REQUIRED", input_freshness: unknownFreshness })}
          timeZone={TIME_ZONE}
        />,
      ),
    ).not.toThrow();
  });

  it("coverage and freshness lines render together without confusion", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({
          feed_state: "DATA_QUALITY_LIMITED",
          insufficient_count: 2,
          analysis_coverage: partialCoverage,
          input_freshness: knownFreshness,
        })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("2 in attesa di dati sufficienti");
    expect(container.textContent).toContain("Non analizzati: Costi, Personale.");
    expect(container.textContent).toContain("Ultimo import prenotazioni:");
    expect(container.querySelector(".feed-state__coverage")).not.toBeNull();
    expect(container.querySelector(".feed-state__freshness")).not.toBeNull();
  });

  it("ACTION_REQUIRED / DATA_QUALITY_LIMITED / NO_ACTION_REQUIRED all preserve the freshness line", () => {
    const states: DecisionFeedResponse["feed_state"][] = [
      "ACTION_REQUIRED",
      "DATA_QUALITY_LIMITED",
      "NO_ACTION_REQUIRED",
    ];
    for (const state of states) {
      const { container, unmount } = render(
        <FeedStateView
          feed={feed({
            feed_state: state,
            triggered_count: state === "ACTION_REQUIRED" ? 1 : 0,
            items: state === "ACTION_REQUIRED" ? [triggeredItem(1, "dec-1")] : [],
            input_freshness: knownFreshness,
          })}
          timeZone={TIME_ZONE}
        />,
      );
      expect(container.querySelector(".feed-state__freshness")).not.toBeNull();
      unmount();
    }
  });

  it("NOT_PROCESSED never shows a freshness line", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", input_freshness: knownFreshness })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.querySelector(".feed-state__freshness")).toBeNull();
  });

  // --- Gate 24B: last successful analysis ----------------------------------------------------

  const priorRun: DecisionFeedResponse["last_successful_analysis"] = {
    as_of_local_date: "2026-10-01",
    completed_at: "2026-10-01T09:15:00Z",
  };

  it("NOT_PROCESSED + null renders the 'never analysed' copy, not the generic 'per oggi' one", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: null })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("NINFA non ha ancora completato una prima analisi.");
    expect(container.textContent).not.toContain("NINFA non ha ancora completato l'analisi per oggi.");
    expect(container.querySelector(".feed-state__last-successful")).toBeNull();
  });

  it("NOT_PROCESSED + a prior run renders the business-date line, in Italian, no year", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: priorRun })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("NINFA non ha ancora completato l'analisi per oggi.");
    expect(container.textContent).toContain("L'ultima analisi completata risale al 1 ottobre.");
    expect(container.textContent).not.toContain("2026"); // no year, like the headline date
  });

  it("uses as_of_local_date for the sentence, never completed_at's own instant", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({
          feed_state: "NOT_PROCESSED",
          last_successful_analysis: {
            as_of_local_date: "2026-01-05",
            completed_at: "2026-10-01T09:15:00Z", // deliberately a very different instant
          },
        })}
        timeZone={TIME_ZONE}
      />,
    );

    expect(container.textContent).toContain("L'ultima analisi completata risale al 5 gennaio.");
    expect(container.textContent).not.toContain("1 ottobre");
  });

  it("the business-date line never leaks run_sequence, ids or raw timestamps", () => {
    const { container } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: priorRun })}
        timeZone={TIME_ZONE}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).not.toContain("2026-10-01T09:15:00Z");
    expect(container.innerHTML).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/); // no UUID
  });

  it("a processed state never shows the last-successful line, even if the feed carries one", () => {
    const states: DecisionFeedResponse["feed_state"][] = [
      "ACTION_REQUIRED",
      "DATA_QUALITY_LIMITED",
      "NO_ACTION_REQUIRED",
    ];
    for (const state of states) {
      const { container, unmount } = render(
        <FeedStateView
          feed={feed({
            feed_state: state,
            triggered_count: state === "ACTION_REQUIRED" ? 1 : 0,
            items: state === "ACTION_REQUIRED" ? [triggeredItem(1, "dec-1")] : [],
            last_successful_analysis: priorRun,
          })}
          timeZone={TIME_ZONE}
        />,
      );
      expect(container.querySelector(".feed-state__last-successful")).toBeNull();
      expect(container.textContent).not.toContain("L'ultima analisi completata risale al");
      unmount();
    }
  });

  it("never claims today's own analysis failed or was never started", () => {
    const { container: withPrior } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: priorRun })}
        timeZone={TIME_ZONE}
      />,
    );
    const { container: withoutPrior } = render(
      <FeedStateView
        feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: null })}
        timeZone={TIME_ZONE}
      />,
    );

    for (const text of [withPrior.textContent ?? "", withoutPrior.textContent ?? ""]) {
      expect(text.toLowerCase()).not.toContain("fallit"); // "fallita"/"fallito"
      expect(text.toLowerCase()).not.toContain("errore");
      expect(text).not.toContain("non è stata avviata");
    }
  });

  it("a historical/legacy feed shape (no last_successful_analysis at all) never crashes", () => {
    expect(() =>
      render(
        <FeedStateView
          feed={feed({ feed_state: "NOT_PROCESSED", last_successful_analysis: null })}
          timeZone={TIME_ZONE}
        />,
      ),
    ).not.toThrow();
  });
});
