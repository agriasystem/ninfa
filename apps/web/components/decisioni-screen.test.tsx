// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionFeedResponse, PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

import {
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_FIVE_DECISION_TYPES,
  actionRequired,
  feed,
  notProcessed,
} from "@/test/home-support";

import { DecisioniScreen } from "./decisioni-screen";
import { HomeScreen } from "./home-screen";
import { ShellLogoContext } from "./shell-logo-context";

const useSessionMock = vi.fn();
const getDecisionFeedMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("@/lib/api/decisions", () => ({
  getDecisionFeed: (...args: unknown[]) => getDecisionFeedMock(...args),
}));
vi.mock("@/lib/api/ask-ninfa", () => ({ askMiaHome: vi.fn() }));

// A decision card's accessible name starts with its rank span's aria-label ("Priorità 1").
const CARD = { name: /^Priorità \d/u };

function property(id: string, name: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name, slug: name.toLowerCase().replace(/\s+/g, "-"), timezone };
}

function session(properties: PropertyAccess[]): SessionContextResponse {
  return {
    user: { id: "u1", email: "a@b.c", display_name: "Giulia Rossi" },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces: [{ id: "ws1", name: "WS", slug: "ws", role: "MEMBER", properties }],
  };
}

function signIn(properties: PropertyAccess[], refresh = vi.fn()) {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    session: session(properties),
    refresh,
    logout: vi.fn(),
  });
}

function renderScreen(requestedPropertyId: string | null = "p1", onSelectProperty = vi.fn()) {
  return render(
    <DecisioniScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={onSelectProperty}
      onNavigateToLogin={vi.fn()}
    />,
  );
}

function resolve(data: DecisionFeedResponse) {
  getDecisionFeedMock.mockResolvedValue({ ok: true, data });
}

async function cards(count: number) {
  await waitFor(() => expect(screen.getAllByRole("link", CARD)).toHaveLength(count));
  return screen.getAllByRole("link", CARD);
}

beforeEach(() => {
  getDecisionFeedMock.mockReset();
  signIn([property("p1", "Hotel Quercia")]);
  resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES));
});

describe("/decisioni - today's feed, every decision", () => {
  it("lists ALL triggered decisions - 8, not the 5 of the historical top-5 limit", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    renderScreen();

    await cards(8);
    expect(screen.queryByText(/altre decisioni/u)).toBeNull(); // nothing hidden, so no "+N altre"
  });

  it("keeps the backend order exactly (never re-sorted)", async () => {
    resolve(actionRequired([...GOLDEN_FIVE_DECISION_TYPES].reverse()));
    renderScreen();

    const ranks = (await cards(5)).map((link) => link.querySelector(".decision-card__rank")?.textContent);
    expect(ranks).toEqual(["#5", "#4", "#3", "#2", "#1"]); // the reversed order, untouched
  });

  it("every card links to the EXISTING Decision Detail, keeping the property context", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { property_id: "p1" }));
    renderScreen();

    for (const [index, link] of (await cards(5)).entries()) {
      const id = GOLDEN_FIVE_DECISION_TYPES[index]?.decision_id;
      expect(link.getAttribute("href")).toBe(`/oggi/decisioni/${id}?property=p1`);
    }
  });

  it("matches the Home's count: the number a user clicks is the list they land on", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    const { unmount } = renderScreen();
    await cards(8);
    unmount();

    render(
      <ShellLogoContext.Provider value={{ slotRef: { current: null }, setHidden: vi.fn() }}>
        <HomeScreen propertyId="p1" timeZone="Europe/Rome" onPropertyInvalid={vi.fn()} />
      </ShellLogoContext.Provider>,
    );
    const link = await screen.findByRole("link", { name: /decisioni richiedono attenzione/u });
    expect(link.textContent).toBe("8 decisioni richiedono attenzione");
    expect(link.getAttribute("href")).toBe("/decisioni?property=p1");
  });

  it("uses the sidebar shell with 'Decisioni' as the current page", async () => {
    renderScreen();
    await screen.findByRole("heading", { level: 1, name: "Decisioni" });

    expect(screen.getByRole("link", { name: "Decisioni" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Oggi" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("navigation", { name: "Navigazione principale" })).not.toBeNull();
  });

  it("shows the small logo from the start (this is not the Home)", async () => {
    const { container } = renderScreen();
    await cards(5);

    expect(container.querySelector(".app-sidebar__logo-slot")?.getAttribute("data-hidden")).toBe("false");
  });

  it("has no charts or graphs - icons and logo only", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    const { container } = renderScreen();
    await cards(8);

    expect(container.querySelector("canvas")).toBeNull();
    const main = container.querySelector("main") as HTMLElement;
    for (const svg of Array.from(main.querySelectorAll("svg"))) {
      expect(svg.getAttribute("aria-hidden")).toBe("true"); // icons only, never content
    }
  });
});

describe("/decisioni - the other feed states keep their semantics", () => {
  it("NO_ACTION_REQUIRED: 'Tutto sotto controllo' and no decision cards", async () => {
    resolve(feed({ feed_state: "NO_ACTION_REQUIRED" }));
    renderScreen();

    expect(await screen.findByText("Tutto sotto controllo")).not.toBeNull();
    expect(screen.queryAllByRole("link", CARD)).toHaveLength(0);
  });

  it("NOT_PROCESSED: 'Analisi non ancora disponibile', never 'Tutto sotto controllo'", async () => {
    resolve(notProcessed());
    renderScreen();

    expect(await screen.findByText("Analisi non ancora disponibile")).not.toBeNull();
    expect(screen.queryByText("Tutto sotto controllo")).toBeNull();
  });

  it("DATA_QUALITY_LIMITED: 'Analisi parziale', never 'Tutto sotto controllo'", async () => {
    resolve(feed({ feed_state: "DATA_QUALITY_LIMITED", insufficient_count: 2, suppressed_count: 0 }));
    renderScreen();

    expect(await screen.findByText("Analisi parziale")).not.toBeNull();
    expect(screen.queryByText("Tutto sotto controllo")).toBeNull();
  });
});

describe("/decisioni - loading, error, refresh, properties", () => {
  it("shows a skeleton while the feed loads", () => {
    getDecisionFeedMock.mockReturnValue(new Promise(() => undefined));
    const { container } = renderScreen();

    expect(container.querySelector(".today-screen__skeleton")?.getAttribute("aria-busy")).toBe("true");
  });

  it("shows the existing error copy with a retry that repeats the same GET", async () => {
    getDecisionFeedMock.mockResolvedValueOnce({ ok: false, status: 500, code: "X", message: "boom" });
    const user = userEvent.setup();
    renderScreen();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Non siamo riusciti a caricare l'analisi. Riprova.",
    );
    expect(screen.queryByText("boom")).toBeNull();
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await cards(5);
  });

  it("keeps the 'Aggiorna analisi' refresh", async () => {
    const user = userEvent.setup();
    renderScreen();
    const refresh = await screen.findByRole("button", { name: "Aggiorna analisi" });

    await user.click(refresh);

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledTimes(2));
  });

  it("shows the empty state, with no feed request, when the account has no property", async () => {
    signIn([]);
    renderScreen(null);

    expect(await screen.findByText("Nessuna struttura disponibile")).not.toBeNull();
    expect(getDecisionFeedMock).not.toHaveBeenCalled();
  });

  it("with several properties shows the selector, and corrects a foreign id to a real one", async () => {
    signIn([property("p1", "Hotel A"), property("p2", "Hotel B")]);
    const onSelectProperty = vi.fn();
    renderScreen("someone-elses-property", onSelectProperty);

    expect(await screen.findByLabelText("Struttura attiva")).not.toBeNull();
    await waitFor(() => expect(onSelectProperty).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", expect.any(String)));
    expect(getDecisionFeedMock).not.toHaveBeenCalledWith("someone-elses-property", expect.any(String));
  });

  it("asks for the property-local 'today' of the selected property's own timezone", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-07T22:30:00Z")); // 8 Oct in Rome, 7 Oct in Honolulu
    try {
      signIn([property("p1", "Hotel Roma", "Europe/Rome")]);
      renderScreen("p1");
      await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("p1", "2026-10-08"));
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the decisions as a real list inside the main landmark", async () => {
    renderScreen();
    await cards(5);

    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("listitem").length).toBeGreaterThanOrEqual(5);
  });
});
