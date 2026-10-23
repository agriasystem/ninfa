// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionFeedResponse, PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

import {
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_FIVE_DECISION_TYPES,
  UNKNOWN_FRESHNESS,
  actionRequired,
  coverageSkipping,
  feed,
  itemOfType,
  knownFreshness,
  notProcessed,
  unknownCoverage,
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

// A decision row's only link is "Apri dettaglio", named after the decision it opens.
const ROW_LINK = { name: /^Apri dettaglio: / };

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

async function rowLinks(count: number) {
  await waitFor(() => expect(screen.getAllByRole("link", ROW_LINK)).toHaveLength(count));
  return screen.getAllByRole("link", ROW_LINK);
}

/** The rank pill text of every row on screen, top to bottom. */
function ranks(container: HTMLElement): (string | null | undefined)[] {
  return Array.from(container.querySelectorAll(".decision-row__rank")).map((node) => node.textContent);
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

    await rowLinks(8);
    expect(screen.queryByText(/altre decisioni/u)).toBeNull(); // nothing hidden, so no "+N altre"
  });

  it("keeps the backend order exactly (never re-sorted)", async () => {
    resolve(actionRequired([...GOLDEN_FIVE_DECISION_TYPES].reverse()));
    const { container } = renderScreen();

    await rowLinks(5);
    expect(ranks(container)).toEqual(["Priorità 5", "Priorità 4", "Priorità 3", "Priorità 2", "Priorità 1"]);
  });

  it("every row links to the EXISTING Decision Detail, keeping the property context", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { property_id: "p1" }));
    renderScreen();

    for (const [index, link] of (await rowLinks(5)).entries()) {
      const id = GOLDEN_FIVE_DECISION_TYPES[index]?.decision_id;
      expect(link.getAttribute("href")).toBe(`/oggi/decisioni/${id}?property=p1`);
    }
  });

  it("matches the Home's count: the number a user clicks is the list they land on", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    const { unmount } = renderScreen();
    await rowLinks(8);
    expect(screen.getByText("8 decisioni richiedono attenzione")).not.toBeNull();
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
    await rowLinks(5);

    expect(container.querySelector(".app-sidebar__logo-slot")?.getAttribute("data-hidden")).toBe("false");
  });

  it("draws no chart: the row visuals are decorative, every number is also written in text", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    const { container } = renderScreen();
    await rowLinks(8);

    expect(container.querySelector("canvas")).toBeNull();
    const main = container.querySelector("main") as HTMLElement;
    for (const svg of Array.from(main.querySelectorAll("svg"))) {
      expect(svg.getAttribute("aria-hidden")).toBe("true"); // icons only, never content
    }
    const visuals = Array.from(main.querySelectorAll(".decision-row__pair, .decision-row__donut"));
    expect(visuals.length).toBeGreaterThan(0);
    for (const visual of visuals) expect(visual.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders the decisions as a real list inside the main landmark", async () => {
    renderScreen();
    await rowLinks(5);

    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("listitem").length).toBeGreaterThanOrEqual(5);
  });
});

describe("/decisioni - the decision rows", () => {
  it("each row is an article named by its title, with its area and the engine's priority", async () => {
    renderScreen();
    await rowLinks(5);

    const first = screen.getByRole("article", {
      name: "Le prenotazioni per il 5 ottobre stanno arrivando sotto il ritmo atteso",
    });
    expect(within(first).getByText("Ricavi")).not.toBeNull();
    expect(within(first).getByText("Priorità 1")).not.toBeNull();
    expect(within(first).getByText("Pickup rilevato")).not.toBeNull();
    expect(within(first).getByText("3 camere")).not.toBeNull();
    expect(within(first).getByText("−60,0%")).not.toBeNull();
    expect(within(first).getByText("Camere mancanti")).not.toBeNull();
    expect(within(first).getByText("Affidabilità 81%")).not.toBeNull();
  });

  it("shows the recorded estimate on cost and labor rows only, and calls it an estimate", async () => {
    renderScreen();
    await rowLinks(5);

    const articles = screen.getAllByRole("article");
    const estimates = articles.filter((article) => within(article).queryByText("Impatto stimato") !== null);
    expect(estimates).toHaveLength(2); // COST_CPOR_ANOMALY + LABOR_OVERSTAFFING
    for (const article of estimates) {
      expect(within(article).getByText(/stima indicativa/u)).not.toBeNull();
    }
  });

  it("never shows Alta / Media / Bassa, never a raw enum, never a recommendation", async () => {
    resolve(GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS);
    const { container } = renderScreen();
    await rowLinks(8);

    const text = (container.querySelector("main") as HTMLElement).textContent ?? "";
    expect(text).not.toMatch(/\b(Alta|Media|Bassa)\b/u);
    expect(text).not.toMatch(/[A-Z]{2,}_[A-Z_]+/u);
    expect(text).not.toMatch(/\b(Raccomandazione|Consigliamo|Suggerimento)\b/iu);
  });

  it("opens through the link named after the decision", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { property_id: "p1" }));
    renderScreen();

    const link = await screen.findByRole("link", {
      name: "Apri dettaglio: La dipendenza dalle OTA è sopra il livello atteso",
    });
    expect(link.getAttribute("href")).toBe(`/oggi/decisioni/${itemOfType("REV_OTA_DEPENDENCY").decision_id}?property=p1`);
  });
});

describe("/decisioni - the hero", () => {
  it("says how many decisions need attention, with the Home's own sentence", async () => {
    renderScreen();

    expect(await screen.findByText("5 decisioni richiedono attenzione")).not.toBeNull();
  });

  it("states the booking import as a FACT, never as 'Dati aggiornati'", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, {
      as_of_local_date: "2026-09-26",
      input_freshness: knownFreshness("2026-09-26T07:15:00Z"), // 09:15 in Rome
    }));
    renderScreen();

    expect(await screen.findByText("Ultimo import prenotazioni: oggi alle 09:15")).not.toBeNull();
    expect(screen.queryByText(/Dati aggiornati/u)).toBeNull();
  });

  it("with no known import it says so plainly instead of implying freshness", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { input_freshness: UNKNOWN_FRESHNESS }));
    renderScreen();

    await screen.findByText("5 decisioni richiedono attenzione");
    expect(screen.queryByText(/Ultimo import prenotazioni: oggi/u)).toBeNull();
    expect(screen.queryByText(/Dati aggiornati/u)).toBeNull();
  });

  it("'Prima decisione' is the one the engine ranks first, and 'Aree coinvolte' counts the analysed areas", async () => {
    renderScreen();
    await rowLinks(5);

    const first = screen.getByRole("article", { name: /^Prima decisione/u });
    expect(within(first).getByText("Ricavi")).not.toBeNull();
    expect(within(first).getByText(/Le prenotazioni per il 5 ottobre/u)).not.toBeNull();

    const areas = screen.getByRole("article", { name: /^Aree coinvolte/u });
    expect(within(areas).getByText("4 di 4")).not.toBeNull();
    expect(within(areas).getByText("Ricavi, Distribuzione, Costi, Personale")).not.toBeNull();
  });

  it("with part of the run skipped the denominator is what was really analysed", async () => {
    resolve(
      actionRequired([itemOfType("REV_PICKUP_LOW"), itemOfType("COST_CPOR_ANOMALY")], {
        analysis_coverage: coverageSkipping("DISTRIBUTION", "LABOR"),
      }),
    );
    renderScreen();

    const areas = await screen.findByRole("article", { name: /^Aree coinvolte/u });
    expect(within(areas).getByText("2 di 2")).not.toBeNull();
  });

  it("with no coverage on record it states only how many areas have a decision - no invented total", async () => {
    resolve(
      actionRequired([itemOfType("REV_PICKUP_LOW"), itemOfType("COST_CPOR_ANOMALY")], {
        analysis_coverage: unknownCoverage(),
      }),
    );
    renderScreen();

    const areas = await screen.findByRole("article", { name: /^Aree coinvolte/u });
    expect(within(areas).getByText("2")).not.toBeNull();
    expect(within(areas).queryByText(/ di /u)).toBeNull();
  });

  it("sums no money: there is no 'impatto totale' anywhere", async () => {
    renderScreen();
    await rowLinks(5);

    expect(screen.queryByText(/totale/iu)).toBeNull();
  });
});

describe("/decisioni - filter by area", () => {
  it("offers 'Tutte' and every area with its own count, 'Tutte' pressed by default", async () => {
    renderScreen();
    await rowLinks(5);

    const group = screen.getByRole("group", { name: "Filtra per area" });
    expect(within(group).getByRole("button", { name: "Tutte, 5 decisioni" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(group).getByRole("button", { name: "Ricavi, 2 decisioni" }).getAttribute("aria-pressed")).toBe("false");
    expect(within(group).getByRole("button", { name: "Distribuzione, 1 decisione" })).not.toBeNull();
    expect(within(group).getByRole("button", { name: "Costi, 1 decisione" })).not.toBeNull();
    expect(within(group).getByRole("button", { name: "Personale, 1 decisione" })).not.toBeNull();
  });

  it("narrows the list to the chosen area and back, keeping the backend order", async () => {
    const user = userEvent.setup();
    const { container } = renderScreen();
    await rowLinks(5);

    await user.click(screen.getByRole("button", { name: "Ricavi, 2 decisioni" }));

    expect(screen.getByRole("button", { name: "Ricavi, 2 decisioni" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Tutte, 5 decisioni" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getAllByRole("link", ROW_LINK)).toHaveLength(2);
    expect(ranks(container)).toEqual(["Priorità 1", "Priorità 2"]);

    await user.click(screen.getByRole("button", { name: "Tutte, 5 decisioni" }));
    expect(screen.getAllByRole("link", ROW_LINK)).toHaveLength(5);
  });

  it("an area with no decision says what the run knows: analysed and clear...", async () => {
    resolve(actionRequired([itemOfType("REV_PICKUP_LOW")]));
    const user = userEvent.setup();
    renderScreen();
    await rowLinks(1);

    await user.click(screen.getByRole("button", { name: "Costi, 0 decisioni" }));

    expect(screen.queryAllByRole("link", ROW_LINK)).toHaveLength(0);
    expect((await screen.findByRole("status")).textContent).toBe(
      "Per quanto analizzato oggi, NINFA non ha decisioni in quest'area.",
    );
  });

  it("...or NOT analysed - never read as 'all fine'", async () => {
    resolve(actionRequired([itemOfType("REV_PICKUP_LOW")], { analysis_coverage: coverageSkipping("COSTS") }));
    const user = userEvent.setup();
    renderScreen();
    await rowLinks(1);

    await user.click(screen.getByRole("button", { name: "Costi, 0 decisioni" }));

    expect((await screen.findByRole("status")).textContent).toBe("Quest'area non è stata analizzata oggi.");
  });

  it("shows a coverage note under the list when part of the run was skipped", async () => {
    resolve(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { analysis_coverage: coverageSkipping("LABOR") }));
    const { container } = renderScreen();
    await rowLinks(5);

    expect(container.querySelector(".decisioni-coverage")?.textContent ?? "").not.toBe("");
  });
});

describe("/decisioni - sort", () => {
  it("defaults to 'Priorità' - the backend order", async () => {
    renderScreen();
    await rowLinks(5);

    const select = screen.getByLabelText("Ordina per:") as HTMLSelectElement;
    expect(select.value).toBe("priority");
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Priorità",
      "Più recenti",
      "Aperte da più tempo",
    ]);
  });

  it("'Più recenti' and 'Aperte da più tempo' reorder by the date the decision was first detected", async () => {
    const user = userEvent.setup();
    const { container } = renderScreen();
    await rowLinks(5);
    const select = screen.getByLabelText("Ordina per:");

    await user.selectOptions(select, "recent");
    // first seen: occupancy 25 Sep, pickup 24 Sep, labor 24 Sep (rank tiebreak), cost 1 Sep, OTA 20 Aug... newest first
    expect(ranks(container)).toEqual(["Priorità 2", "Priorità 1", "Priorità 5", "Priorità 4", "Priorità 3"]);

    await user.selectOptions(select, "oldest");
    expect(ranks(container)).toEqual(["Priorità 3", "Priorità 4", "Priorità 1", "Priorità 5", "Priorità 2"]);

    await user.selectOptions(select, "priority");
    expect(ranks(container)).toEqual(["Priorità 1", "Priorità 2", "Priorità 3", "Priorità 4", "Priorità 5"]);
  });

  it("sorting keeps the area filter", async () => {
    const user = userEvent.setup();
    const { container } = renderScreen();
    await rowLinks(5);

    await user.click(screen.getByRole("button", { name: "Ricavi, 2 decisioni" }));
    await user.selectOptions(screen.getByLabelText("Ordina per:"), "recent");

    expect(ranks(container)).toEqual(["Priorità 2", "Priorità 1"]);
  });
});

describe("/decisioni - the other feed states keep their semantics", () => {
  it("NO_ACTION_REQUIRED: 'Tutto sotto controllo' and no decision rows, no filters", async () => {
    resolve(feed({ feed_state: "NO_ACTION_REQUIRED" }));
    renderScreen();

    expect(await screen.findByText("Tutto sotto controllo")).not.toBeNull();
    expect(screen.queryAllByRole("link", ROW_LINK)).toHaveLength(0);
    expect(screen.queryByRole("group", { name: "Filtra per area" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Decisioni" })).not.toBeNull();
  });

  it("NOT_PROCESSED: 'Analisi non ancora disponibile', never 'Tutto sotto controllo'", async () => {
    resolve(notProcessed());
    renderScreen();

    expect(await screen.findByText("Analisi non ancora disponibile")).not.toBeNull();
    expect(screen.queryByText("Tutto sotto controllo")).toBeNull();
    expect(screen.queryByText(/richiedono attenzione/u)).toBeNull();
  });

  it("DATA_QUALITY_LIMITED: 'Analisi parziale', never 'Tutto sotto controllo'", async () => {
    resolve(feed({ feed_state: "DATA_QUALITY_LIMITED", insufficient_count: 2, suppressed_count: 0 }));
    renderScreen();

    expect(await screen.findByText("Analisi parziale")).not.toBeNull();
    expect(screen.queryByText("Tutto sotto controllo")).toBeNull();
  });
});

describe("/decisioni - loading, error, refresh, properties", () => {
  it("shows a skeleton of the final list while the feed loads", () => {
    getDecisionFeedMock.mockReturnValue(new Promise(() => undefined));
    const { container } = renderScreen();

    const skeleton = container.querySelector(".decisioni-skeleton");
    expect(skeleton?.getAttribute("aria-busy")).toBe("true");
    expect(skeleton?.querySelectorAll(".decisioni-skeleton__row").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { level: 1, name: "Decisioni" })).not.toBeNull();
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

    await rowLinks(5);
  });

  it("keeps the 'Aggiorna analisi' refresh", async () => {
    const user = userEvent.setup();
    renderScreen();
    await rowLinks(5); // the title-only header gives way to the hero once the feed is in
    const refresh = screen.getByRole("button", { name: "Aggiorna analisi" });

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
});
