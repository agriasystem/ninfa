// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionFeedResponse } from "@ninfa/contracts";

import {
  GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS,
  GOLDEN_FIVE_DECISION_TYPES,
  UNKNOWN_FRESHNESS,
  actionRequired,
  coverageSkipping,
  feed,
  fullCoverage,
  itemOfType,
  knownFreshness,
  notProcessed,
  unknownCoverage,
} from "@/test/home-support";

import { HomeScreen } from "./home-screen";
import { ShellLogoContext } from "./shell-logo-context";

const useSessionMock = vi.fn();
const getDecisionFeedMock = vi.fn();
const askMiaHomeMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => useSessionMock(),
}));
vi.mock("@/lib/api/decisions", () => ({
  getDecisionFeed: (...args: unknown[]) => getDecisionFeedMock(...args),
}));
vi.mock("@/lib/api/ask-ninfa", () => ({
  askMiaHome: (...args: unknown[]) => askMiaHomeMock(...args),
}));

const TIME_ZONE = "Europe/Rome";

function signedInAs(displayName: string | null) {
  useSessionMock.mockReturnValue({
    session: {
      user: { id: "u1", email: "who@hotel.example", display_name: displayName },
      session: { expires_at: "2026-12-31T00:00:00Z" },
      workspaces: [],
    },
  });
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <ShellLogoContext.Provider value={{ slotRef: { current: null }, setHidden: vi.fn() }}>
      {children}
    </ShellLogoContext.Provider>
  );
}

function renderHome(onPropertyInvalid = vi.fn()) {
  const utils = render(
    <Shell>
      <HomeScreen propertyId="prop-1" timeZone={TIME_ZONE} onPropertyInvalid={onPropertyInvalid} />
    </Shell>,
  );
  return { ...utils, onPropertyInvalid };
}

function resolveFeed(data: DecisionFeedResponse) {
  getDecisionFeedMock.mockResolvedValue({ ok: true, data });
}

/** The Home's real hero <h1>: while the feed loads, the page's h1 is the hidden "Oggi" placeholder,
 * so "the h1" must mean the FIRST h1 that is not that placeholder. */
function heroHeading() {
  return screen.findByRole("heading", { level: 1, name: (name) => name !== "Oggi" });
}

/** 8 October 2026, 12:00 UTC = 14:00 in Rome: the property's "today" is 2026-10-08. */
const TODAY = "2026-10-08";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
  signedInAs("Giulia Rossi");
  getDecisionFeedMock.mockReset();
  askMiaHomeMock.mockReset();
  resolveFeed(feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: TODAY }));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Home - ACTION_REQUIRED", () => {
  const FIVE = (overrides: Partial<DecisionFeedResponse> = {}) =>
    actionRequired(GOLDEN_FIVE_DECISION_TYPES, {
      as_of_local_date: TODAY,
      input_freshness: knownFreshness("2026-10-08T10:42:00Z"), // 12:42 in Rome
      analysis_coverage: fullCoverage(),
      ...overrides,
    });

  it("opens the hero with the FIRST decision of the feed, as a real <h1>", async () => {
    resolveFeed(FIVE());
    renderHome();

    const h1 = await heroHeading();
    expect(h1.textContent).toBe("Le prenotazioni per il 5 ottobre stanno arrivando sotto il ritmo atteso.");
  });

  it("styles the hero as fragments: strong subject, accent state phrase - no HTML injection", async () => {
    resolveFeed(FIVE());
    const { container } = renderHome();
    await heroHeading();

    const h1 = container.querySelector("h1") as HTMLElement;
    expect(Array.from(h1.querySelectorAll(".hero-fragment--strong")).map((n) => n.textContent)).toEqual([
      "prenotazioni",
      "5 ottobre",
    ]);
    expect(h1.querySelector(".hero-fragment--accent")?.textContent).toBe("sotto il ritmo atteso.");
    expect(h1.innerHTML).not.toContain("&lt;");
  });

  it("NEVER re-sorts: the hero is items[0] even if its rank says otherwise", async () => {
    const reversed = [...GOLDEN_FIVE_DECISION_TYPES].reverse(); // labor first, pickup last
    resolveFeed(FIVE({ items: reversed }));
    renderHome();

    const h1 = await heroHeading();
    expect(h1.textContent).toBe("Le ore di personale programmate sono sopra il livello atteso.");
  });

  it("shows the real count as a link to /decisioni that keeps the property context", async () => {
    resolveFeed(FIVE());
    renderHome();

    const link = await screen.findByRole("link", { name: /decisioni richiedono attenzione/u });
    expect(link.textContent).toBe("5 decisioni richiedono attenzione");
    expect(link.getAttribute("href")).toBe("/decisioni?property=prop-1");
  });

  it("counts every triggered decision - 8 - never the 5 the list would show", async () => {
    resolveFeed({ ...GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS, as_of_local_date: TODAY });
    renderHome();

    expect(await screen.findByRole("link", { name: "8 decisioni richiedono attenzione" })).not.toBeNull();
  });

  it("uses the singular for exactly one decision", async () => {
    resolveFeed(FIVE({ items: [itemOfType("REV_OTA_DEPENDENCY")], triggered_count: 1 }));
    renderHome();

    expect(await screen.findByRole("link", { name: "1 decisione richiede attenzione" })).not.toBeNull();
  });

  it("shows the factual last import in the property's timezone - never 'Dati aggiornati'", async () => {
    resolveFeed(FIVE());
    const { container } = renderHome();
    await heroHeading();

    expect(screen.getByText("Ultimo import prenotazioni: oggi alle 12:42")).not.toBeNull();
    expect(container.textContent).not.toMatch(/Dati aggiornati|aggiornat/u);
  });

  it("draws the freshness dot NEUTRAL, never green and never a CURRENT/STALE badge", async () => {
    resolveFeed(FIVE());
    const { container } = renderHome();
    await heroHeading();

    const dot = container.querySelector(".home__freshness-dot");
    expect(dot?.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector("[data-freshness='known']")).not.toBeNull();
    expect(container.textContent).not.toMatch(/current|stale|attuale|obsolet/iu);
  });

  it("renders the four-area strip from real counts and coverage", async () => {
    resolveFeed(FIVE());
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(
      within(strip)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Ricavi2 attenzioni",
      "Distribuzione1 attenzione",
      "Costi1 attenzione",
      "Personale1 attenzione",
    ]);
  });

  it("writes 'not analysed' per area, with its own grammar, next to a real count", async () => {
    resolveFeed(
      FIVE({
        items: [itemOfType("REV_PICKUP_LOW"), itemOfType("REV_OCCUPANCY_RISK")],
        triggered_count: 2,
        analysis_coverage: coverageSkipping("COSTS", "LABOR"),
      }),
    );
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(
      within(strip)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Ricavi2 attenzioni",
      "DistribuzioneNessuna attenzione",
      "CostiNon analizzati",
      "PersonaleNon analizzato",
    ]);
  });

  it("the strip tiles are plain text, not links or buttons (no per-area destination exists)", async () => {
    resolveFeed(FIVE());
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(within(strip).queryAllByRole("link")).toHaveLength(0);
    expect(within(strip).queryAllByRole("button")).toHaveLength(0);
  });

  it("never says 'Tutto sotto controllo'", async () => {
    resolveFeed(FIVE());
    const { container } = renderHome();
    await heroHeading();

    expect(container.textContent).not.toContain("Tutto sotto controllo");
  });

  it("never shows a raw enum value or snake_case word anywhere", async () => {
    resolveFeed(FIVE());
    const { container } = renderHome();
    await heroHeading();

    expect(container.textContent).not.toMatch(
      /REV_[A-Z_]+|COST_CPOR|LABOR_OVER|ACTION_REQUIRED|EVALUATED|SKIPPED|NOT_REQUESTED|[a-z]+_[a-z]+/u,
    );
  });

  it("is built from runtime data only: none of the reference screenshot's demo strings appear", async () => {
    resolveFeed(
      FIVE({
        items: [itemOfType("REV_OCCUPANCY_RISK")],
        triggered_count: 1,
        input_freshness: knownFreshness("2026-10-08T10:42:00Z"),
      }),
    );
    const { container } = renderHome();
    await heroHeading();

    for (const demo of ["Hotel Villa Aurora", "Luca", "14 giorni", "09:31", "3 decisioni", "8 ottobre 2026"]) {
      expect(container.textContent, demo).not.toContain(demo);
    }
  });
});

describe("Home - greeting", () => {
  it("greets by the first token of the display name", async () => {
    signedInAs("Giulia Rossi");
    renderHome();

    expect(await screen.findByText("Ciao Giulia,")).not.toBeNull();
  });

  it("greets with a bare 'Ciao,' when there is no display name - never from the e-mail", async () => {
    signedInAs(null);
    const { container } = renderHome();

    expect(await screen.findByText("Ciao,")).not.toBeNull();
    expect(container.textContent).not.toContain("who");
  });

  it("greets with a bare 'Ciao,' for a blank display name", async () => {
    signedInAs("    ");
    renderHome();

    expect(await screen.findByText("Ciao,")).not.toBeNull();
  });
});

describe("Home - NO_ACTION_REQUIRED", () => {
  it("is the ONLY state that says 'Tutto sotto controllo', with the existing truthful body", async () => {
    resolveFeed(feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: TODAY }));
    renderHome();

    const h1 = await heroHeading();
    expect(h1.textContent).toBe("Tutto sotto controllo");
    expect(screen.getByText("Nessuna decisione richiede la tua attenzione in questo momento.")).not.toBeNull();
  });

  it("has no decisions link (there is nothing to open), but keeps the freshness line", async () => {
    resolveFeed(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        as_of_local_date: TODAY,
        input_freshness: knownFreshness("2026-10-07T20:15:00Z"),
      }),
    );
    renderHome();
    await heroHeading();

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Ultimo import prenotazioni: ieri alle 22:15")).not.toBeNull();
  });

  it("keeps the domain strip visible when coverage is available", async () => {
    resolveFeed(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        as_of_local_date: TODAY,
        analysis_coverage: coverageSkipping("COSTS", "LABOR"),
      }),
    );
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(within(strip).getAllByText("Nessuna attenzione")).toHaveLength(2);
    expect(within(strip).getByText("Non analizzati")).not.toBeNull(); // Costi
    expect(within(strip).getByText("Non analizzato")).not.toBeNull(); // Personale
  });

  it("never lets 'Tutto sotto controllo' imply every area was checked (Gate 22 note kept)", async () => {
    resolveFeed(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        as_of_local_date: TODAY,
        analysis_coverage: coverageSkipping("COSTS", "LABOR"),
      }),
    );
    renderHome();
    await heroHeading();

    expect(screen.getByText("Non analizzati: Costi, Personale.")).not.toBeNull();
  });

  it("names the distribution area 'Distribuzione' (not the old 'Canali') in that note", async () => {
    resolveFeed(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        as_of_local_date: TODAY,
        analysis_coverage: coverageSkipping("DISTRIBUTION"),
      }),
    );
    renderHome();

    expect(await screen.findByText("Non analizzati: Distribuzione.")).not.toBeNull();
    expect(document.body.textContent).not.toContain("Canali");
  });

  it("says coverage is unavailable (never FULL) when the run recorded none", async () => {
    resolveFeed(
      feed({
        feed_state: "NO_ACTION_REQUIRED",
        as_of_local_date: TODAY,
        analysis_coverage: unknownCoverage(),
      }),
    );
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(within(strip).getAllByText("Non disponibile")).toHaveLength(4);
    expect(screen.getByText("Copertura dell'analisi non disponibile per questo run.")).not.toBeNull();
  });

  it("shows a neutral line for an UNKNOWN freshness - no invented time", async () => {
    resolveFeed(
      feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: TODAY, input_freshness: UNKNOWN_FRESHNESS }),
    );
    const { container } = renderHome();

    expect(await screen.findByText("Ultimo import prenotazioni non disponibile")).not.toBeNull();
    expect(container.querySelector("[data-freshness='unknown']")).not.toBeNull();
    expect(container.textContent).not.toMatch(/\d{2}:\d{2}/u);
  });
});

describe("Home - DATA_QUALITY_LIMITED", () => {
  const limited = (overrides: Partial<DecisionFeedResponse> = {}) =>
    feed({
      feed_state: "DATA_QUALITY_LIMITED",
      as_of_local_date: TODAY,
      insufficient_count: 3,
      suppressed_count: 1,
      analysis_coverage: fullCoverage(),
      ...overrides,
    });

  it("reads 'Analisi parziale' and NEVER 'Tutto sotto controllo' nor a made-up main decision", async () => {
    resolveFeed(limited());
    const { container } = renderHome();

    const h1 = await heroHeading();
    expect(h1.textContent).toBe("Analisi parziale");
    expect(container.textContent).not.toContain("Tutto sotto controllo");
    expect(container.textContent).not.toMatch(/stanno arrivando|sopra il livello|sotto il livello/u);
  });

  it("keeps the existing honest body and counts", async () => {
    resolveFeed(limited());
    renderHome();

    expect(
      await screen.findByText(
        "Alcuni controlli non dispongono ancora di dati sufficienti. NINFA non mostra conclusioni incerte.",
      ),
    ).not.toBeNull();
    expect(screen.getByText("3 in attesa di dati sufficienti")).not.toBeNull();
    expect(screen.getByText("1 con confidenza troppo bassa")).not.toBeNull();
  });

  it("shows coverage prudently: evaluated areas are 'Analisi parziale', never 'Nessuna attenzione'", async () => {
    resolveFeed(limited({ analysis_coverage: coverageSkipping("COSTS", "LABOR") }));
    renderHome();
    const strip = await screen.findByRole("list", { name: "Riepilogo per area" });

    expect(within(strip).getAllByText("Analisi parziale")).toHaveLength(2);
    expect(within(strip).queryByText("Nessuna attenzione")).toBeNull();
    expect(within(strip).getByText("Non analizzati")).not.toBeNull();
  });

  it("has no decisions link", async () => {
    resolveFeed(limited());
    renderHome();
    await heroHeading();

    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("Home - NOT_PROCESSED (Gate 24 preserved)", () => {
  it("never analysed: says so, with no last-analysis line", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY }));
    renderHome();

    const h1 = await heroHeading();
    expect(h1.textContent).toBe("Analisi non ancora disponibile");
    expect(screen.getByText("NINFA non ha ancora completato una prima analisi.")).not.toBeNull();
    expect(screen.queryByText(/ultima analisi completata/iu)).toBeNull();
  });

  it("analysed before: names the business date of the last successful analysis", async () => {
    resolveFeed(
      notProcessed({
        as_of_local_date: TODAY,
        last_successful_analysis: { as_of_local_date: "2026-10-01", completed_at: "2026-10-01T06:00:00Z" },
      }),
    );
    renderHome();

    expect(await screen.findByText("NINFA non ha ancora completato l'analisi per oggi.")).not.toBeNull();
    expect(screen.getByText("L'ultima analisi completata risale al 1 ottobre.")).not.toBeNull();
  });

  it("hides the domain strip - no invented coverage", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY }));
    renderHome();
    await heroHeading();

    expect(screen.queryByRole("list", { name: "Riepilogo per area" })).toBeNull();
    expect(screen.queryByText("Non disponibile")).toBeNull();
  });

  it("shows no freshness line at all - no invented import", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY, input_freshness: knownFreshness("2026-10-08T10:42:00Z") }));
    const { container } = renderHome();
    await heroHeading();

    expect(container.textContent).not.toContain("Ultimo import prenotazioni");
    expect(container.querySelector(".home__freshness")).toBeNull();
  });

  it("has no decisions link and never says 'Tutto sotto controllo'", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY }));
    const { container } = renderHome();
    await heroHeading();

    expect(screen.queryByRole("link")).toBeNull();
    expect(container.textContent).not.toContain("Tutto sotto controllo");
  });

  it("still offers Mia - she answers from whatever context exists (or says it is not enough)", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY }));
    renderHome();
    await heroHeading();

    expect(screen.getByRole("textbox", { name: "La tua domanda per Mia" })).not.toBeNull();
  });
});

describe("Home - loading, error, refresh", () => {
  it("shows a skeleton and a hidden h1 while the feed loads, with the logo and Mia already there", async () => {
    getDecisionFeedMock.mockReturnValue(new Promise(() => undefined));
    const { container } = renderHome();

    expect(container.querySelector(".home__skeleton")).not.toBeNull();
    expect(container.querySelector(".home__feed")?.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("heading", { level: 1, name: "Oggi" })).not.toBeNull();
    expect(container.querySelector(".home__logo")).not.toBeNull();
    expect(screen.getByRole("textbox", { name: "La tua domanda per Mia" })).not.toBeNull();
  });

  it("shows the existing error copy with 'Riprova', which repeats the same GET", async () => {
    getDecisionFeedMock.mockResolvedValueOnce({ ok: false, status: 500, code: "INTERNAL", message: "boom" });
    const user = userEvent.setup();
    renderHome();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non siamo riusciti a caricare l'analisi. Riprova.");
    expect(screen.queryByText("boom")).toBeNull(); // never the raw backend message
    resolveFeed(feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: TODAY }));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Tutto sotto controllo")).not.toBeNull();
    expect(getDecisionFeedMock).toHaveBeenCalledTimes(2);
    expect(getDecisionFeedMock).toHaveBeenLastCalledWith("prop-1", TODAY);
  });

  it("keeps Gate 14's refresh as a discreet 'Aggiorna analisi' control that repeats the same GET", async () => {
    const user = userEvent.setup();
    renderHome();
    const refresh = await screen.findByRole("button", { name: "Aggiorna analisi" });
    expect(getDecisionFeedMock).toHaveBeenCalledTimes(1);

    await user.click(refresh);

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledTimes(2));
    expect(getDecisionFeedMock).toHaveBeenLastCalledWith("prop-1", TODAY);
  });

  it("keeps the content on screen while refreshing, with the control disabled and busy", async () => {
    const user = userEvent.setup();
    renderHome();
    const refresh = await screen.findByRole("button", { name: "Aggiorna analisi" });
    let resolveRefresh: (value: unknown) => void = () => undefined;
    getDecisionFeedMock.mockReturnValue(new Promise((r) => (resolveRefresh = r)));

    await user.click(refresh);

    expect((screen.getByRole("button", { name: "Aggiorna analisi" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Tutto sotto controllo");
    resolveRefresh({ ok: true, data: feed({ feed_state: "NO_ACTION_REQUIRED", as_of_local_date: TODAY }) });
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Aggiorna analisi" }) as HTMLButtonElement).disabled).toBe(false),
    );
  });

  it("offers the refresh in NOT_PROCESSED too (the analysis may have arrived since)", async () => {
    resolveFeed(notProcessed({ as_of_local_date: TODAY }));
    renderHome();

    expect(await screen.findByRole("button", { name: "Aggiorna analisi" })).not.toBeNull();
  });

  it("asks for the property-local 'today' (the property's own timezone), explicitly", async () => {
    renderHome();

    await waitFor(() => expect(getDecisionFeedMock).toHaveBeenCalledWith("prop-1", TODAY));
  });

  it("treats 404 PROPERTY_NOT_FOUND as 'resolve the property again' - never a raw error", async () => {
    getDecisionFeedMock.mockResolvedValue({
      ok: false,
      status: 404,
      code: "PROPERTY_NOT_FOUND",
      message: "Property not found",
    });
    const { onPropertyInvalid } = renderHome();

    await waitFor(() => expect(onPropertyInvalid).toHaveBeenCalled());
    expect(screen.queryByText(/Property not found/u)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Home - Mia is wired to the Home context", () => {
  it("asks about the SAME property-local business date as the feed on screen", async () => {
    askMiaHomeMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Una decisione.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderHome();
    await heroHeading();

    await user.type(screen.getByRole("textbox", { name: "La tua domanda per Mia" }), "Quali dati ha usato NINFA oggi?{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", TODAY, "Quali dati ha usato NINFA oggi?");
    expect(await screen.findByText("Una decisione.")).not.toBeNull();
  });

  it("keeps the hero context visible after an answer (no navigation away, no chat takeover)", async () => {
    resolveFeed(actionRequired(GOLDEN_FIVE_DECISION_TYPES, { as_of_local_date: TODAY }));
    askMiaHomeMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Sì, ce ne sono altre.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderHome();
    await heroHeading();

    await user.type(screen.getByRole("textbox", { name: "La tua domanda per Mia" }), "Altri problemi?{Enter}");
    await screen.findByText("Sì, ce ne sono altre.");

    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("sotto il ritmo atteso");
    expect(screen.getByRole("link", { name: "5 decisioni richiedono attenzione" })).not.toBeNull();
    expect(screen.getByRole("list", { name: "Riepilogo per area" })).not.toBeNull();
  });
});
