// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

import { OggiScreen } from "./oggi-screen";

const useSessionMock = vi.fn();
const getDecisionFeedMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("@/lib/api/decisions", () => ({
  getDecisionFeed: (...args: unknown[]) => getDecisionFeedMock(...args),
}));

function property(id: string, name: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name, slug: name.toLowerCase().replace(/\s+/g, "-"), timezone };
}

function session(properties: PropertyAccess[]): SessionContextResponse {
  return {
    user: { id: "u1", email: "a@b.c", display_name: null },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces: [{ id: "ws1", name: "WS", slug: "ws", role: "MEMBER", properties }],
  };
}

beforeEach(() => {
  getDecisionFeedMock.mockReset().mockResolvedValue({
    ok: true,
    data: {
      property_id: "p",
      as_of_local_date: "2026-09-26",
      feed_state: "NO_ACTION_REQUIRED",
      decision_run_id: "run-1",
      run_sequence: 1,
      triggered_count: 0,
      clear_count: 1,
      insufficient_count: 0,
      not_applicable_count: 0,
      suppressed_count: 0,
      items: [],
    },
  });
});

describe("OggiScreen", () => {
  it("shows the empty state when the user has zero accessible properties", async () => {
    useSessionMock.mockReturnValue({ status: "authenticated", session: session([]), refresh: vi.fn() });

    render(
      <OggiScreen requestedPropertyId={null} onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );

    expect(await screen.findByText("Nessuna struttura disponibile")).not.toBeNull();
    expect(getDecisionFeedMock).not.toHaveBeenCalled();
  });

  it("auto-selects the single property, with no selector rendered, and loads its feed", async () => {
    const prop = property("p1", "Masseria Ninfa");
    useSessionMock.mockReturnValue({
      status: "authenticated",
      session: session([prop]),
      refresh: vi.fn(),
    });

    render(
      <OggiScreen requestedPropertyId={null} onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );

    expect(screen.queryByLabelText("Struttura")).toBeNull();
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", expect.any(String)));
  });

  it("shows the property selector when there is more than one property", () => {
    const props = [property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(props), refresh: vi.fn() });

    render(
      <OggiScreen requestedPropertyId="p1" onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );

    expect(screen.getByLabelText("Struttura")).not.toBeNull();
  });

  it("switching property (via onSelectProperty) refetches the feed for the new property", async () => {
    const props = [property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(props), refresh: vi.fn() });

    const { rerender } = render(
      <OggiScreen requestedPropertyId="p1" onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", expect.any(String)));

    rerender(
      <OggiScreen requestedPropertyId="p2" onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p2", expect.any(String)));
  });

  it("rejects an unknown/foreign property id client-side and corrects it to a real one", async () => {
    const props = [property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(props), refresh: vi.fn() });
    const onSelectProperty = vi.fn();

    render(
      <OggiScreen
        requestedPropertyId="some-other-workspace-property"
        onSelectProperty={onSelectProperty}
        onNavigateToLogin={vi.fn()}
      />,
    );

    await waitFor(() => expect(onSelectProperty).toHaveBeenCalledWith("p1"));
    // The API is only ever called with a REAL, accessible property id.
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", expect.any(String)));
    expect(getDecisionFeedMock).not.toHaveBeenCalledWith(
      "some-other-workspace-property",
      expect.any(String),
    );
  });

  it("uses the newly selected property's own timezone for the as_of date, not the previous one", async () => {
    vi.setSystemTime(new Date("2026-09-25T23:30:00Z")); // 00:30 in Europe/Rome, 19:30 in Honolulu
    const props = [
      property("p1", "Masseria Ninfa", "Europe/Rome"),
      property("p2", "Resort Honolulu", "Pacific/Honolulu"),
    ];
    useSessionMock.mockReturnValue({ status: "authenticated", session: session(props), refresh: vi.fn() });

    const { rerender } = render(
      <OggiScreen requestedPropertyId="p1" onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", "2026-09-26"));

    rerender(
      <OggiScreen requestedPropertyId="p2" onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />,
    );
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p2", "2026-09-25"));

    vi.useRealTimers();
  });
});
