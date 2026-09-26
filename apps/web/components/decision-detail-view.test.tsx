// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionDetailResponse, ObservationDetail } from "@ninfa/contracts";

import { DecisionDetailView } from "./decision-detail-view";

const getDecisionDetailMock = vi.fn();
const getDecisionHistoryMock = vi.fn();

vi.mock("@/lib/api/decisions", () => ({
  getDecisionDetail: (...args: unknown[]) => getDecisionDetailMock(...args),
  getDecisionHistory: (...args: unknown[]) => getDecisionHistoryMock(...args),
}));

function observation(overrides: Partial<ObservationDetail> = {}): ObservationDetail {
  return {
    observation_id: "obs-latest",
    as_of_local_date: "2026-09-26",
    source_status: "TRIGGERED",
    lifecycle_transition: "OPENED",
    source_evaluation_fingerprint: "should-not-render-fp",
    source_target_key: "should-not-render-key",
    reason_codes: ["TRIGGER_PICKUP_SHORTFALL"],
    confidence_score: "0.82",
    priority: {
      rank: 2,
      impact_score: "1",
      urgency_score: "1",
      confidence_score: "0.82",
      actionability_score: "1",
      priority_score: "1",
      candidate_fingerprint: "fp",
    },
    facts: {
      stay_date: "2026-10-01",
      window_days: 7,
      actual_pickup: 4,
      expected_pickup: "7.00",
      delta_rooms: "-3.00",
      missing_rooms: "3.00",
    },
    evidence: { pattern_pair_count: 8 },
    economic_proxy: null,
    memory_version: "should-not-render-memver",
    ...overrides,
  };
}

function detail(overrides: Partial<DecisionDetailResponse> = {}): DecisionDetailResponse {
  return {
    decision_id: "dec-1",
    decision_type: "REV_PICKUP_LOW",
    status: "OPEN",
    first_seen_local_date: "2026-09-20",
    last_seen_local_date: "2026-09-26",
    last_evaluated_local_date: "2026-09-26",
    resolved_local_date: null,
    episode_count: 1,
    triggered_observation_count: 1,
    target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
    latest_observation: observation(),
    decision_api_version: "decision-api-v1",
    ...overrides,
  };
}

beforeEach(() => {
  getDecisionDetailMock.mockReset();
  getDecisionHistoryMock.mockReset().mockResolvedValue({
    ok: true,
    data: { items: [], next_cursor: null },
  });
});

describe("DecisionDetailView - happy path", () => {
  it("fetches detail and the first history page in parallel (no waterfall)", async () => {
    let detailResolved = false;
    let historyStartedBeforeDetailResolved = false;
    getDecisionDetailMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            detailResolved = true;
            resolve({ ok: true, data: detail() });
          }, 10);
        }),
    );
    getDecisionHistoryMock.mockImplementation(() => {
      if (!detailResolved) historyStartedBeforeDetailResolved = true;
      return Promise.resolve({ ok: true, data: { items: [], next_cursor: null } });
    });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    await waitFor(() => expect(screen.getByText("Pickup sotto le attese")).not.toBeNull());
    expect(historyStartedBeforeDetailResolved).toBe(true);
  });

  it("renders the static title, target subtitle and 'Aperta' status", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    expect(await screen.findByText("Pickup sotto le attese")).not.toBeNull();
    expect(screen.getByText(/Aperta/)).not.toBeNull();
    expect(screen.getByText("1 ottobre")).not.toBeNull();
  });

  it("shows the deterministic 'why' sentence built from real facts", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    expect(
      await screen.findByText("Negli ultimi 7 giorni sono entrate 4 camere, contro le 7 normalmente attese."),
    ).not.toBeNull();
  });

  it("shows the evidence rows and the current priority rank line", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    await screen.findByText("Pickup sotto le attese");
    expect(screen.getByText("Attuale")).not.toBeNull();
    expect(screen.getByText("Affidabilità")).not.toBeNull();
    expect(screen.getByText("Priorità #2 nell'analisi del giorno")).not.toBeNull();
  });

  it("never renders technical audit ids/fingerprints/memory version", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });

    const { container } = render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");

    expect(container.textContent).not.toContain("should-not-render-fp");
    expect(container.textContent).not.toContain("should-not-render-key");
    expect(container.textContent).not.toContain("should-not-render-memver");
    expect(container.textContent).not.toContain("obs-latest");
  });

  it("never renders raw JSON or a recommendation", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });

    const { container } = render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");

    expect(container.innerHTML).not.toMatch(/[{[]"[a-z_]+":/);
    expect(container.textContent).not.toMatch(/Abbassa il prezzo|Riduci il personale/);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("canvas")).toBeNull();
  });
});

describe("DecisionDetailView - RESOLVED / episodes", () => {
  it("shows 'Risolta', the resolved date, and no priority line when latest is CLEAR", async () => {
    getDecisionDetailMock.mockResolvedValue({
      ok: true,
      data: detail({
        status: "RESOLVED",
        resolved_local_date: "2026-09-25",
        latest_observation: observation({
          source_status: "CLEAR",
          lifecycle_transition: "RESOLVED",
          priority: null,
        }),
      }),
    });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    await screen.findByText("Pickup sotto le attese");
    expect(screen.getAllByText(/Risolta/).length).toBeGreaterThan(0);
    expect(screen.getByText("Risolta il 25 settembre 2026")).not.toBeNull();
    expect(screen.queryByText(/Priorità #/)).toBeNull();
  });

  it("shows no noisy episode copy when episode_count is 1", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail({ episode_count: 1 }) });

    const { container } = render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");

    expect(container.textContent).not.toContain("episod");
  });

  it("shows episode/reappearance info when episode_count is greater than 1", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail({ episode_count: 2 }) });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    expect(await screen.findByText("2 episodi")).not.toBeNull();
  });
});

describe("DecisionDetailView - INSUFFICIENT latest observation", () => {
  it("keeps the decision OPEN and shows insufficient-data copy, never implying resolved", async () => {
    getDecisionDetailMock.mockResolvedValue({
      ok: true,
      data: detail({
        status: "OPEN",
        latest_observation: observation({
          source_status: "INSUFFICIENT_DATA",
          lifecycle_transition: "NO_STATE_CHANGE",
          priority: null,
        }),
      }),
    });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    await screen.findByText("Pickup sotto le attese");
    expect(screen.getByText(/Aperta/)).not.toBeNull();
    expect(screen.getByText("Dati non sufficienti per una nuova conclusione")).not.toBeNull();
    expect(screen.queryByText(/Risolta/)).toBeNull();
    expect(screen.queryByText(/Priorità #/)).toBeNull();
  });
});

describe("DecisionDetailView - errors", () => {
  it("shows the safe not-available state on DECISION_NOT_FOUND, never raw backend text", async () => {
    getDecisionDetailMock.mockResolvedValue({
      ok: false,
      status: 404,
      code: "DECISION_NOT_FOUND",
      message: "Decision not found",
    });

    const { container } = render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    expect(await screen.findByText("Decisione non disponibile")).not.toBeNull();
    expect(screen.getByText(/Questa decisione non è disponibile/)).not.toBeNull();
    expect(screen.getByRole("link", { name: "Torna a Oggi" })).not.toBeNull();
    expect(container.textContent).not.toContain("dec-1");
    expect(container.textContent).not.toContain("Decision not found");
  });

  it("shows a generic error with retry on a network/500 failure for the detail", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "boom" });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non siamo riusciti a caricare la decisione.");
    expect(alert.textContent).not.toContain("boom");
  });

  it("retries only the detail fetch, not history, and recovers on success", async () => {
    getDecisionDetailMock
      .mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "boom" })
      .mockResolvedValueOnce({ ok: true, data: detail() });
    const user = userEvent.setup();

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByRole("alert");
    expect(getDecisionHistoryMock).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await screen.findByText("Pickup sotto le attese");
    expect(getDecisionDetailMock).toHaveBeenCalledTimes(2);
    expect(getDecisionHistoryMock).toHaveBeenCalledOnce(); // retrying detail never re-fetches history
  });

  it("history failure is independent: detail still renders even if history fails", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });
    getDecisionHistoryMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);

    await screen.findByText("Pickup sotto le attese");
    expect(await screen.findByRole("alert")).not.toBeNull();
  });
});

describe("DecisionDetailView - history pagination", () => {
  it("loads the first page, then appends a second page on load-more, preserving order and no duplicates", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });
    getDecisionHistoryMock
      .mockResolvedValueOnce({
        ok: true,
        data: { items: [observation({ observation_id: "newest" })], next_cursor: "cursor-1" },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { items: [observation({ observation_id: "older" })], next_cursor: null },
      });
    const user = userEvent.setup();

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");
    expect(screen.getByRole("button", { name: "Mostra eventi precedenti" })).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Mostra eventi precedenti" }));

    await waitFor(() => expect(getDecisionHistoryMock).toHaveBeenCalledTimes(2));
    expect(getDecisionHistoryMock.mock.calls[1]).toEqual(["prop-1", "dec-1", { cursor: "cursor-1" }]);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Mostra eventi precedenti" })).toBeNull(),
    );
  });

  it("disables the load-more button and shows a generic retry on a load-more failure, keeping loaded items", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });
    getDecisionHistoryMock
      .mockResolvedValueOnce({
        ok: true,
        data: { items: [observation({ observation_id: "already-loaded" })], next_cursor: "cursor-1" },
      })
      .mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");

    await user.click(screen.getByRole("button", { name: "Mostra eventi precedenti" }));

    await waitFor(() => expect(screen.getByRole("alert")).not.toBeNull());
    // the already-loaded history item stays visible in the timeline itself
    expect(document.querySelector(".decision-timeline__event")?.textContent).toBe("Rilevata");
    expect(screen.getByRole("button", { name: "Mostra eventi precedenti" })).not.toBeNull();
  });

  it("shows no load-more button when there is no next_cursor", async () => {
    getDecisionDetailMock.mockResolvedValue({ ok: true, data: detail() });
    getDecisionHistoryMock.mockResolvedValue({
      ok: true,
      data: { items: [observation({})], next_cursor: null },
    });

    render(<DecisionDetailView propertyId="prop-1" decisionId="dec-1" />);
    await screen.findByText("Pickup sotto le attese");

    expect(screen.queryByRole("button", { name: "Mostra eventi precedenti" })).toBeNull();
  });
});
