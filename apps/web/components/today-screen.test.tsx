// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionFeedResponse } from "@ninfa/contracts";

import { TodayScreen } from "./today-screen";

const getDecisionFeedMock = vi.fn();

vi.mock("@/lib/api/decisions", () => ({
  getDecisionFeed: (...args: unknown[]) => getDecisionFeedMock(...args),
}));

function feed(overrides: Partial<DecisionFeedResponse>): DecisionFeedResponse {
  return {
    property_id: "prop-1",
    as_of_local_date: "2026-09-26",
    feed_state: "NO_ACTION_REQUIRED",
    decision_run_id: "run-1",
    run_sequence: 1,
    triggered_count: 0,
    clear_count: 3,
    insufficient_count: 0,
    not_applicable_count: 0,
    suppressed_count: 0,
    items: [],
    ...overrides,
  };
}

beforeEach(() => {
  getDecisionFeedMock.mockReset();
});

describe("TodayScreen", () => {
  it("shows a loading skeleton before the feed resolves", () => {
    getDecisionFeedMock.mockReturnValue(new Promise(() => {})); // never resolves
    const { container } = render(
      <TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />,
    );

    expect(container.querySelector(".today-screen__skeleton")).not.toBeNull();
    expect(container.querySelector(".today-screen__skeleton [role='status']")).toBeNull();
  });

  it("requests the feed with the property's own local today as an explicit as_of", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: true, data: feed({}) });
    // 23:30 UTC on the 25th is already 2026-09-26 in Europe/Rome.
    vi.setSystemTime(new Date("2026-09-25T23:30:00Z"));

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("prop-1", "2026-09-26"));
    vi.useRealTimers();
  });

  it("renders the feed state once loaded", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: true, data: feed({ feed_state: "NO_ACTION_REQUIRED" }) });

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);

    await screen.findByText("Tutto sotto controllo");
  });

  it("shows a generic error with a retry CTA on a network/500 failure - never raw backend text", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: false, status: 500, code: "internal_error", message: "boom" });

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non siamo riusciti a caricare l'analisi. Riprova.");
    expect(alert.textContent).not.toContain("boom");
    expect(screen.getByRole("button", { name: "Riprova" })).not.toBeNull();
  });

  it("retry re-fetches the feed only - never a second, different kind of call", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);
    await screen.findByRole("alert");
    expect(getDecisionFeedMock).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledTimes(2));
    expect(getDecisionFeedMock.mock.calls[1]).toEqual(getDecisionFeedMock.mock.calls[0]);
  });

  it("on PROPERTY_NOT_FOUND, calls onPropertyInvalid and shows a neutral state, never a raw 404", async () => {
    getDecisionFeedMock.mockResolvedValue({
      ok: false,
      status: 404,
      code: "PROPERTY_NOT_FOUND",
      message: "Property not found",
    });
    const onPropertyInvalid = vi.fn();

    const { container } = render(
      <TodayScreen propertyId="stale-prop" timeZone="Europe/Rome" onPropertyInvalid={onPropertyInvalid} />,
    );

    await waitFor(() => expect(onPropertyInvalid).toHaveBeenCalledOnce());
    expect(container.textContent).not.toContain("Property not found");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("the 'Aggiorna' button in the header re-fetches the feed", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: true, data: feed({}) });
    const user = userEvent.setup();

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);
    await screen.findByText("Tutto sotto controllo");
    expect(getDecisionFeedMock).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Aggiorna" }));

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledTimes(2));
  });

  it("shows the Italian long-form date in the property's own timezone", async () => {
    getDecisionFeedMock.mockResolvedValue({ ok: true, data: feed({}) });
    vi.setSystemTime(new Date("2026-09-26T10:00:00Z"));

    render(<TodayScreen propertyId="prop-1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />);

    expect(await screen.findByText("Sabato 26 settembre")).not.toBeNull();
    vi.useRealTimers();
  });
});
