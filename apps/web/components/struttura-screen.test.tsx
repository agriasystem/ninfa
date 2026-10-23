// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PropertyAccess, SessionContextResponse } from "@ninfa/contracts";

import { demoStructureOverview } from "@/lib/structure/demo-structure";

import type { StrutturaActions } from "./struttura-parts";
import { StrutturaScreen, type StructureOverviewSource } from "./struttura-screen";

const useSessionMock = vi.fn();
const miaMock = vi.fn();
const fetchMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({ useSession: () => useSessionMock() }));
// Struttura is deterministic: it must never reach Mia or any model. Every entry point is a spy.
vi.mock("@/lib/api/ask-ninfa", () => ({
  askNinfa: (...args: unknown[]) => miaMock(...args),
  askMiaHome: (...args: unknown[]) => miaMock(...args),
}));

/** The readable text of a node: sibling elements are separated by a space (the plain `textContent` glues
 * them together) and runs of white space collapse. */
function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}
const flat = (node: Node): string => textOf(node).replace(/\s+/gu, " ").trim();

function property(id: string, name: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name, slug: name.toLowerCase().replace(/\s+/gu, "-"), timezone };
}

function signIn(properties: PropertyAccess[]) {
  const session: SessionContextResponse = {
    user: { id: "u1", email: "a@b.c", display_name: "Giulia Rossi" },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces: [{ id: "ws1", name: "WS", slug: "ws", role: "MEMBER", properties }],
  };
  useSessionMock.mockReturnValue({
    status: "authenticated",
    session,
    refresh: vi.fn(),
    logout: vi.fn(),
  });
}

interface RenderOptions {
  actions?: StrutturaActions;
  requested?: string | null;
  getOverview?: StructureOverviewSource;
}

/** What the real route renders: no `getOverview`, so no demo data. */
function renderPage({ actions, requested = "p1", getOverview }: RenderOptions = {}) {
  return render(
    <StrutturaScreen
      requestedPropertyId={requested}
      onSelectProperty={vi.fn()}
      onNavigateToLogin={vi.fn()}
      actions={actions}
      getOverview={getOverview}
    />,
  );
}

/** The complete example page of the approved reference: an EXPLICIT fixture, the way development looks at it. */
const demoOverview: StructureOverviewSource = (_property, now) => demoStructureOverview(now);
const renderDemoPage = (options: Omit<RenderOptions, "getOverview"> = {}) =>
  renderPage({ ...options, getOverview: demoOverview });

const region = (name: string) => screen.getByRole("region", { name });

/** Every value of the demo dataset: none may ever reach the page the real route renders. */
const DEMO_VALUES =
  /Villa Seren|Bellagio|\bHotel\b|\b32\b|Classic|Deluxe|Junior|Suite|\bCLS\b|\bDLX\b|Marzo|Novembre|Giugno|Settembre|\bEuro\b|\b92\b|\b82\b|stell[ae]|adult|bambin|Mews|SiteMinder|Booking|TeamSystem|Collegato|aperto tutto|Alta stagione|Capacità massima/iu;

beforeEach(() => {
  miaMock.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  signIn([property("p1", "Residenza Alba")]);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("/struttura - route, shell and header", () => {
  it("renders inside the shell with Struttura as the current section, and the sidebar names it Oggi, not Home", () => {
    renderPage();

    const nav = screen.getByRole("navigation", { name: "Navigazione principale" });
    expect(within(nav).getByRole("link", { name: "Struttura" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Oggi" })).not.toBeNull();
    expect(within(nav).queryByText("Home")).toBeNull();
  });

  it("shows the title, the subtitle and 'Modifica struttura' as a button", () => {
    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Struttura" })).not.toBeNull();
    expect(
      screen.getByText("Informazioni e configurazioni operative della tua struttura."),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Modifica struttura" })).not.toBeNull();
  });

  it("has exactly the four numbered blocks, in the approved order, each a labelled region with its description", () => {
    renderPage();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual([
      "1. Profilo struttura",
      "2. Inventario camere",
      "3. Parametri operativi",
      "4. Fonti dati",
    ]);
    expect(
      within(region("1. Profilo struttura")).getByText(
        "Informazioni generali che NINFA utilizza come contesto operativo.",
      ),
    ).not.toBeNull();
    expect(
      within(region("2. Inventario camere")).getByText(
        "Le tipologie di camere e la loro configurazione operativa.",
      ),
    ).not.toBeNull();
    expect(
      within(region("3. Parametri operativi")).getByText(
        "Informazioni operative che influenzano l'analisi e l'interpretazione dei dati.",
      ),
    ).not.toBeNull();
    expect(
      within(region("4. Fonti dati")).getByText(
        "Sistemi collegati alla struttura da cui NINFA riceve i dati.",
      ),
    ).not.toBeNull();
  });

  it("never reaches Mia, a model or the network", () => {
    renderPage();

    expect(miaMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the empty state, not the page, when the account has no property", () => {
    signIn([]);
    renderPage({ requested: null });

    expect(screen.getByText("Nessuna struttura disponibile")).not.toBeNull();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });
});

describe("/struttura - the real route, with no real data: nothing is invented", () => {
  it("shows no value of the demo dataset anywhere on the page", () => {
    renderPage();

    expect(flat(screen.getByRole("main"))).not.toMatch(DEMO_VALUES);
  });

  it("1. Profilo: only the name and the timezone are known; every other fact is 'Non configurata'", () => {
    renderPage();

    const facts = Array.from(region("1. Profilo struttura").querySelectorAll("dl > div")).map((fact) =>
      flat(fact),
    );
    expect(facts).toEqual([
      "Nome struttura Residenza Alba",
      "Tipologia Non configurata",
      "Categoria Non configurata",
      "Località Non configurata",
      "Numero camere Non configurato",
      "Timezone Europe/Rome (CET)",
      "Valuta Non configurata",
      "Stagionalità principale Non configurata",
    ]);
  });

  it("1. Profilo: the name and the timezone are the REAL property's, and the unset facts are marked neutral", () => {
    signIn([property("p1", "Hotel Quercia Pilot", "Europe/London")]);
    const { container } = renderPage();

    const profile = region("1. Profilo struttura");
    expect(within(profile).getByText("Hotel Quercia Pilot")).not.toBeNull();
    expect(within(profile).getByText(/^Europe\/London \(/u)).not.toBeNull();
    expect(container.querySelectorAll('.struttura-fact dd[data-state="not-configured"]')).toHaveLength(6);
  });

  it("1. Profilo: no photo and no stars - a neutral tile in the photo's place", () => {
    const { container } = renderPage();

    expect(container.querySelector(".struttura-profile__photo img")).toBeNull();
    expect(container.querySelector(".struttura-profile__photo")?.getAttribute("data-empty")).toBe("true");
    expect(container.querySelector(".struttura-stars")).toBeNull();
  });

  it("2. Inventario: an empty state with 'Configura inventario', no table, no 'Modifica inventario'", () => {
    renderPage();

    const rooms = region("2. Inventario camere");
    expect(within(rooms).getByText("L'inventario camere non è ancora configurato")).not.toBeNull();
    expect(within(rooms).getByRole("button", { name: "Configura inventario" })).not.toBeNull();
    expect(within(rooms).queryByRole("table")).toBeNull();
    expect(within(rooms).queryByRole("button", { name: "Modifica inventario" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Tabella scorrevole: Inventario camere" })).toBeNull();
  });

  it("3. Parametri: all three read 'Non configurato/a', with no detail line", () => {
    const { container } = renderPage();

    const tiles = within(region("3. Parametri operativi")).getAllByRole("listitem");
    expect(tiles.map((tile) => flat(tile))).toEqual([
      "Periodo di apertura Non configurato",
      "Stagionalità Non configurata",
      "Capacità operativa rilevante Non configurata",
    ]);
    expect(container.querySelectorAll(".struttura-tile__detail")).toHaveLength(0);
    expect(container.querySelectorAll('.struttura-tile__value[data-state="not-configured"]')).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Modifica parametri" })).not.toBeNull();
  });

  it("4. Fonti: every source is neutral - not configured, no system named, a way to connect it", () => {
    const { container } = renderPage();

    const categories = ["PMS", "Channel Manager", "OTA", "Contabilità", "Personale"];
    const cards = within(region("4. Fonti dati")).getAllByRole("listitem");
    expect(cards.map((card) => flat(card))).toEqual(
      categories.map((category) => `${category} Nessuna fonte collegata Non configurata Collega fonte`),
    );
    for (const card of Array.from(container.querySelectorAll(".struttura-source"))) {
      expect(card.getAttribute("data-connection")).toBe("not-connected");
    }
    const sources = region("4. Fonti dati");
    expect(
      within(sources)
        .getAllByRole("button", { name: /^Collega fonte / })
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(categories.map((category) => `Collega fonte ${category}`));
    expect(
      within(sources)
        .getAllByRole("button", { name: /^Azioni per / })
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(categories.map((category) => `Azioni per ${category}`));
    expect(within(sources).getByRole("button", { name: "Collega una nuova fonte" })).not.toBeNull();
  });

  it("says nothing about data quality: only whether a system is connected (that is Dati)", () => {
    renderPage();

    expect(flat(region("4. Fonti dati"))).not.toMatch(/copertura|qualit|complet|mesi di storico/iu);
  });
});

describe("/struttura - the explicit demo fixture (development and tests only)", () => {
  it("1. Profilo: shows the complete example profile, with the fixture's own name", () => {
    renderDemoPage();

    const facts = Array.from(region("1. Profilo struttura").querySelectorAll("dl > div")).map((fact) =>
      flat(fact),
    );
    expect(facts).toEqual([
      "Nome struttura Villa Serenità",
      "Tipologia Hotel",
      "Categoria 4 stelle",
      "Località Bellagio (CO), Italia",
      "Numero camere 32",
      "Timezone Europe/Rome (CET)",
      "Valuta Euro (€)",
      "Stagionalità principale Marzo – Novembre",
    ]);
  });

  it("1. Profilo: draws five stars of which four are earned, and the placeholder photo as a decorative image", () => {
    const { container } = renderDemoPage();

    const stars = Array.from(container.querySelectorAll(".struttura-stars__star"));
    expect(stars.map((star) => star.getAttribute("data-earned"))).toEqual([
      "true",
      "true",
      "true",
      "true",
      "false",
    ]);
    expect(container.querySelector(".struttura-stars__row")?.getAttribute("aria-hidden")).toBe("true");
    const photo = container.querySelector(".struttura-profile__photo img");
    expect(photo?.getAttribute("alt")).toBe("");
    expect(photo?.getAttribute("src")).toContain("/placeholders/struttura-placeholder.jpg");
  });

  it("2. Inventario: the six columns and one row per room type, with the status and the actions", () => {
    renderDemoPage();

    const table = within(region("2. Inventario camere")).getByRole("table", { name: "Inventario camere" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => flat(header)),
    ).toEqual(["Tipologia di camera", "Codice", "Camere", "Occupazione max", "Stato", "Azioni"]);
    expect(
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => flat(row)),
    ).toEqual([
      "Classic CLS 8 2 adulti Attiva",
      "Deluxe DLX 12 2 adulti + 1 bambino Attiva",
      "Junior Suite JSU 8 3 adulti Attiva",
      "Suite STE 4 4 adulti Attiva",
    ]);
    expect(
      within(table)
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["Azioni per Classic", "Azioni per Deluxe", "Azioni per Junior Suite", "Azioni per Suite"]);
    expect(screen.getByRole("button", { name: "Modifica inventario" })).not.toBeNull();
    expect(screen.queryByText("L'inventario camere non è ancora configurato")).toBeNull();
  });

  it("2. Inventario: an active room type has a green indicator, and the table scrolls inside a named region", () => {
    const { container } = renderDemoPage();

    const statuses = Array.from(container.querySelectorAll(".struttura-status"));
    expect(statuses).toHaveLength(4);
    for (const status of statuses) {
      expect(status.getAttribute("data-status")).toBe("active");
      expect(status.querySelector(".struttura-status__dot")).not.toBeNull();
    }
    expect(
      screen.getByRole("region", { name: "Tabella scorrevole: Inventario camere" }).getAttribute("tabindex"),
    ).toBe("0");
  });

  it("2. Inventario: is an inventory only - no booking, rate, availability or calendar", () => {
    renderDemoPage();

    expect(flat(region("2. Inventario camere"))).not.toMatch(
      /prenotazion|tariff|prezz|disponibilit|calendar|housekeeping|assegnaz/iu,
    );
  });

  it("3. Parametri: the three tiles of the reference, the capacity being the rooms' 92 ospiti", () => {
    renderDemoPage();

    const tiles = within(region("3. Parametri operativi")).getAllByRole("listitem");
    expect(tiles.map((tile) => flat(tile))).toEqual([
      "Periodo di apertura Aperto tutto l'anno Chiusura annuale: nessuna",
      "Stagionalità Alta stagione Giugno – Settembre",
      "Capacità operativa rilevante Capacità massima 92 ospiti",
    ]);
  });

  it("4. Fonti: a source is 'Collegato' ONLY because the data says so, with its system and last update", () => {
    renderDemoPage();

    const cards = within(region("4. Fonti dati")).getAllByRole("listitem");
    expect(cards.map((card) => flat(card))).toEqual([
      "PMS Mews Collegato Ultimo aggiornamento 4 min fa",
      "Channel Manager SiteMinder Collegato Ultimo aggiornamento 6 min fa",
      "OTA Booking.com Collegato Ultimo aggiornamento 7 min fa",
      "Contabilità Nessuna fonte collegata Non configurata Collega fonte",
      "Personale Nessuna fonte collegata Non configurata Collega fonte",
    ]);
  });

  it("4. Fonti: connected and not connected differ by state attribute, wording and action, not by colour alone", () => {
    const { container } = renderDemoPage();

    const cards = Array.from(container.querySelectorAll(".struttura-source"));
    expect(cards.map((card) => card.getAttribute("data-connection"))).toEqual([
      "connected",
      "connected",
      "connected",
      "not-connected",
      "not-connected",
    ]);
    expect(within(cards[0] as HTMLElement).queryByRole("button", { name: /Collega fonte/u })).toBeNull();
    expect(within(cards[3] as HTMLElement).queryByText("Ultimo aggiornamento")).toBeNull();
    for (const card of cards.slice(3)) {
      expect(card.querySelector(".struttura-source__detail")?.textContent).toBe("Nessuna fonte collegata");
    }
  });
});

describe("/struttura - the buttons are ready but not wired", () => {
  it("clicking any button without handlers does nothing and does not throw", async () => {
    const user = userEvent.setup();
    renderPage();

    for (const button of screen.getAllByRole("button")) {
      // the profile menu of the shell is a real control: only the page's own buttons are under test
      if (button.closest(".app-sidebar")) continue;
      await user.click(button);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("calls the handler it was given, with what the button acts on", async () => {
    const user = userEvent.setup();
    const actions: StrutturaActions = {
      onEditStructure: vi.fn(),
      onEditInventory: vi.fn(),
      onConfigureInventory: vi.fn(),
      onEditParameters: vi.fn(),
      onConnectSource: vi.fn(),
      onRoomMenu: vi.fn(),
      onSourceMenu: vi.fn(),
    };

    // the real route: no inventory yet, so "Configura inventario" is the action
    const real = renderPage({ actions });
    await user.click(screen.getByRole("button", { name: "Modifica struttura" }));
    await user.click(screen.getByRole("button", { name: "Configura inventario" }));
    await user.click(screen.getByRole("button", { name: "Modifica parametri" }));
    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(screen.getByRole("button", { name: "Collega fonte Personale" }));
    await user.click(screen.getByRole("button", { name: "Azioni per OTA" }));
    real.unmount();

    // the demo fixture: an inventory exists, so "Modifica inventario" and the row menus are there
    renderDemoPage({ actions });
    await user.click(screen.getByRole("button", { name: "Modifica inventario" }));
    await user.click(screen.getByRole("button", { name: "Azioni per Suite" }));

    expect(actions.onEditStructure).toHaveBeenCalledTimes(1);
    expect(actions.onConfigureInventory).toHaveBeenCalledTimes(1);
    expect(actions.onEditInventory).toHaveBeenCalledTimes(1);
    expect(actions.onEditParameters).toHaveBeenCalledTimes(1);
    expect(actions.onConnectSource).toHaveBeenNthCalledWith(1);
    expect(actions.onConnectSource).toHaveBeenNthCalledWith(2, "STAFF");
    expect(actions.onRoomMenu).toHaveBeenCalledWith("suite");
    expect(actions.onSourceMenu).toHaveBeenCalledWith("OTA");
  });
});
