// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeedStateView } from "@/components/feed-state-view";

import {
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_ACTION_REQUIRED_FIVE_TYPES,
  GOLDEN_DATA_QUALITY_LIMITED,
  GOLDEN_NOT_PROCESSED,
  GOLDEN_NO_ACTION_REQUIRED,
} from "./fixtures";

/**
 * Golden Oggi UI states (Gate 14). Each fixture in `./fixtures.ts` is hand-authored against the
 * real Gate 12 contract, independently of the frontend adapters under test - this file only
 * checks RENDERING and STATE REPRESENTATION, never detector status, confidence, priority or
 * rank (those are copied verbatim from the fixture, exactly as `FeedStateView`/`DecisionCard`
 * would from a real API response).
 */

describe("Golden A: NOT_PROCESSED", () => {
  it("renders the not-processed copy and nothing resembling 'all clear'", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_NOT_PROCESSED} />);

    expect(screen.getByText("Analisi non ancora disponibile")).not.toBeNull();
    expect(container.textContent).not.toContain("Tutto sotto controllo");
  });
});

describe("Golden B: DATA_QUALITY_LIMITED", () => {
  it("renders the partial-analysis copy with the real insufficient/suppressed counts", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_DATA_QUALITY_LIMITED} />);

    expect(screen.getByText("Analisi parziale")).not.toBeNull();
    expect(container.textContent).toContain("3 in attesa di dati sufficienti");
    expect(container.textContent).toContain("1 con confidenza troppo bassa");
    expect(container.textContent).not.toContain("Tutto sotto controllo");
  });
});

describe("Golden C: NO_ACTION_REQUIRED", () => {
  it("is the only golden state allowed to say 'Tutto sotto controllo'", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_NO_ACTION_REQUIRED} />);

    expect(container.textContent).toContain("Tutto sotto controllo");
  });
});

describe("Golden D: ACTION_REQUIRED with the five MVP decision types", () => {
  it("renders all five static titles, in the backend's own priority_rank order", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_ACTION_REQUIRED_FIVE_TYPES} />);

    const titles = Array.from(container.querySelectorAll(".decision-card__title")).map(
      (element) => element.textContent,
    );
    expect(titles).toEqual([
      "Pickup sotto le attese",
      "Rischio occupazione",
      "Dipendenza OTA",
      "Costo per camera anomalo",
      "Ore di personale sopra l'atteso",
    ]);
  });

  it("renders each card's real facts, never raw JSON, never a recommendation", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_ACTION_REQUIRED_FIVE_TYPES} />);

    expect(container.textContent).toContain("2026-10-05"); // pickup stay date
    expect(container.textContent).toContain("HOUSEKEEPING"); // labor category
    expect(container.textContent).toContain("482,30"); // cost economic proxy, formatted
    expect(container.innerHTML).not.toMatch(/[{[]"[a-z_]+":/);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("shows no '+N altre decisioni' indicator - exactly 5 candidates, nothing hidden", () => {
    render(<FeedStateView feed={GOLDEN_ACTION_REQUIRED_FIVE_TYPES} />);

    expect(screen.queryByText(/altre decisioni/)).toBeNull();
  });
});

describe("Golden E: ACTION_REQUIRED with more than 5 triggered candidates", () => {
  it("presents only the top 5 and discloses the rest, without ever re-sorting them", () => {
    const { container } = render(<FeedStateView feed={GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS} />);

    const ranks = Array.from(container.querySelectorAll(".decision-card__rank")).map(
      (element) => element.textContent,
    );
    expect(ranks).toEqual(["#1", "#2", "#3", "#4", "#5"]);
    expect(screen.getByText("+ 3 altre decisioni")).not.toBeNull();
  });
});
