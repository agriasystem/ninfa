// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PropertyAccess,
  RoomInventoryResponse,
  RoomInventorySavedResponse,
  SessionContextResponse,
} from "@ninfa/contracts";

import { STRUTTURA_INVENTORY_ANCHOR, strutturaInventoryRoute } from "@/lib/routes";
import { demoStructureOverview } from "@/lib/structure/demo-structure";
import { nothingConfigured, ok } from "@/test/sources-support";

import type { StrutturaActions } from "./struttura-parts";
import { StrutturaScreen, type StructureOverviewSource } from "./struttura-screen";

const useSessionMock = vi.fn();
const miaMock = vi.fn();
const fetchMock = vi.fn();
const getDataSourcesMock = vi.fn();
const getRoomInventoryMock = vi.fn();
const saveRoomInventoryMock = vi.fn();
const getAnalysisStatusMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({ useSession: () => useSessionMock() }));
// The inventory block reads and writes its own API: here it answers "nothing configured" until a test says.
vi.mock("@/lib/api/room-inventory", () => ({
  getRoomInventory: (...args: unknown[]) => getRoomInventoryMock(...args),
  saveRoomInventory: (...args: unknown[]) => saveRoomInventoryMock(...args),
}));
vi.mock("@/lib/api/analysis", () => ({
  getAnalysisStatus: (...args: unknown[]) => getAnalysisStatusMock(...args),
  requestAnalysisRefresh: vi.fn(),
}));
// "Fonti dati" is the ONE block that asks the backend something (its own API, deep-tested in
// `struttura-sources.test.tsx`); here it just answers "nothing configured", like a real property today.
vi.mock("@/lib/api/data-sources", () => ({
  getDataSources: (...args: unknown[]) => getDataSourcesMock(...args),
}));
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
const demoOverview: StructureOverviewSource = () => demoStructureOverview();
const renderDemoPage = (options: Omit<RenderOptions, "getOverview"> = {}) =>
  renderPage({ ...options, getOverview: demoOverview });

const region = (name: string) => screen.getByRole("region", { name });

const NOT_CONFIGURED_INVENTORY: RoomInventoryResponse = {
  configured: false,
  rooms_available: null,
  varies: false,
  first_night: null,
  last_night: null,
  known_since: null,
  today: "2026-11-09",
  earliest_valid_from: "2016-11-08",
  min_rooms: 1,
  max_rooms: 5000,
};
const inventoryOf = (rooms: number, varies = false): RoomInventoryResponse => ({
  configured: true,
  rooms_available: rooms,
  varies,
  first_night: "2026-11-09",
  last_night: "2036-11-08",
  known_since: "2026-11-09",
  today: "2026-11-09",
  earliest_valid_from: "2016-11-08",
  min_rooms: 1,
  max_rooms: 5000,
});
const savedOf = (
  rooms: number,
  overrides: Partial<RoomInventorySavedResponse> = {},
): RoomInventorySavedResponse => ({
  ...inventoryOf(rooms),
  changed_nights: 3653,
  analysis_requested: true,
  ...overrides,
});
const analysisIs = (state: string) =>
  ok({
    state,
    imported_domains: ["BOOKINGS"],
    latest_import_at: null,
    last_analysis_at: null,
    next_attempt_at: null,
    can_retry: state === "FAILED",
  });
/** The cards of "Fonti dati" arrive from the backend: wait for them. */
const sourcesLoaded = () => screen.findByRole("list", { name: "Fonti dati collegate e collegabili" });

/** Every value of the demo dataset: none may ever reach the page the real route renders. */
const DEMO_VALUES =
  /Villa Seren|Bellagio|\bHotel\b|\b32\b|Classic|Deluxe|Junior|Suite|\bCLS\b|\bDLX\b|Marzo|Novembre|Giugno|Settembre|\bEuro\b|\b92\b|\b82\b|stell[ae]|adult|bambin|Mews|SiteMinder|Booking|TeamSystem|Collegato|aperto tutto|Alta stagione|Capacità massima/iu;

beforeEach(() => {
  miaMock.mockReset();
  fetchMock.mockReset();
  getDataSourcesMock.mockReset();
  getDataSourcesMock.mockResolvedValue(ok(nothingConfigured()));
  getRoomInventoryMock.mockReset();
  getRoomInventoryMock.mockResolvedValue(ok(NOT_CONFIGURED_INVENTORY));
  saveRoomInventoryMock.mockReset();
  getAnalysisStatusMock.mockReset();
  getAnalysisStatusMock.mockResolvedValue(analysisIs("UP_TO_DATE"));
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
        "Quante camere può vendere la struttura: è il numero su cui NINFA calcola l'occupazione.",
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

  it("never reaches Mia or a model; its only request is the data-source API of Fonti dati", async () => {
    renderPage();
    await sourcesLoaded();

    expect(miaMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);
    expect(getDataSourcesMock.mock.calls[0]?.[0]).toBe("p1");
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

  it("2. Inventario: an empty state with 'Configura inventario', no table, no 'Modifica inventario'", async () => {
    renderPage();

    const rooms = region("2. Inventario camere");
    expect(await within(rooms).findByText("L'inventario camere non è ancora configurato")).not.toBeNull();
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

  it("4. Fonti: every source reads what the backend says - here, nothing is configured", async () => {
    const { container } = renderPage();
    await sourcesLoaded();

    const cards = within(region("4. Fonti dati")).getAllByRole("listitem");
    expect(cards.map((card) => flat(card))).toEqual([
      "PMS Nessuna fonte collegata Non configurato Collega fonte",
      "Channel Manager Nessuna fonte collegata Non configurato Collega fonte",
      "OTA Nessun dato canale disponibile Non configurato Configura fonte",
      "Contabilità Nessuna fonte collegata Non configurato Collega fonte",
      "Personale Nessuna fonte collegata Non configurato Collega fonte",
    ]);
    for (const card of Array.from(container.querySelectorAll(".struttura-source"))) {
      expect(card.getAttribute("data-state")).toBe("NOT_CONFIGURED");
    }
    expect(
      within(region("4. Fonti dati")).getByRole("button", { name: "Collega una nuova fonte" }),
    ).not.toBeNull();
  });

  it("says nothing about data quality: only whether a system is connected (that is Dati)", async () => {
    renderPage();
    await sourcesLoaded();

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

  it("4. Fonti: the fixture does not touch the data sources - they still read what the API says", async () => {
    renderDemoPage();
    await sourcesLoaded();

    const text = flat(region("4. Fonti dati"));
    expect(text).not.toMatch(/Mews|SiteMinder|Booking|TeamSystem|Collegato/u);
    expect(text).toContain("Non configurato");
  });
});

describe("/struttura - the profile and parameter buttons are ready but not wired", () => {
  it("clicking them without handlers does nothing and does not throw", async () => {
    const user = userEvent.setup();
    renderPage();
    await sourcesLoaded();
    const sources = region("4. Fonti dati");
    const inventory = region("2. Inventario camere");

    for (const button of screen.getAllByRole("button")) {
      // the shell's profile menu and the (fully wired) Fonti dati and inventory blocks are not under test here
      if (button.closest(".app-sidebar") || sources.contains(button) || inventory.contains(button)) continue;
      await user.click(button);
    }
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("calls the handler it was given, with what the button acts on", async () => {
    const user = userEvent.setup();
    const actions: StrutturaActions = {
      onEditStructure: vi.fn(),
      onEditInventory: vi.fn(),
      onEditParameters: vi.fn(),
      onRoomMenu: vi.fn(),
    };

    const real = renderPage({ actions });
    await user.click(screen.getByRole("button", { name: "Modifica struttura" }));
    await user.click(screen.getByRole("button", { name: "Modifica parametri" }));
    real.unmount();

    // the demo fixture: an inventory exists, so "Modifica inventario" and the row menus are there
    renderDemoPage({ actions });
    await user.click(screen.getByRole("button", { name: "Modifica inventario" }));
    await user.click(screen.getByRole("button", { name: "Azioni per Suite" }));

    expect(actions.onEditStructure).toHaveBeenCalledTimes(1);
    expect(actions.onEditInventory).toHaveBeenCalledTimes(1);
    expect(actions.onEditParameters).toHaveBeenCalledTimes(1);
    expect(actions.onRoomMenu).toHaveBeenCalledWith("suite");
    await waitFor(() => expect(getDataSourcesMock).toHaveBeenCalled());
  });
});

describe("/struttura - the way in from Dati's 'Configura inventario'", () => {
  const scrolled: Element[] = [];
  const original = Element.prototype.scrollIntoView;

  beforeEach(() => {
    scrolled.length = 0;
    // jsdom lays nothing out and has no scrollIntoView: record which element is brought into view
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolled.push(this);
    };
  });

  afterEach(() => {
    Element.prototype.scrollIntoView = original;
    window.history.replaceState(null, "", "/");
  });

  it("the inventory block is the anchor the link names - no new page, no second setting", () => {
    renderPage();

    expect(region("2. Inventario camere").id).toBe(STRUTTURA_INVENTORY_ANCHOR);
    expect(strutturaInventoryRoute("p1")).toBe("/struttura?property=p1#struttura-rooms");
  });

  it("arriving with that anchor brings the inventory block into view once the page is on screen", async () => {
    window.history.replaceState(null, "", "/struttura?property=p1#struttura-rooms");
    renderPage();

    await waitFor(() => expect(scrolled).toHaveLength(1));
    expect(scrolled[0]).toBe(region("2. Inventario camere"));
  });

  it("without it the page opens where it always did", async () => {
    renderPage();
    await sourcesLoaded();

    expect(scrolled).toHaveLength(0);
  });
});

describe("/struttura - the room inventory, for real", () => {
  const rooms = () => region("2. Inventario camere");
  const openForm = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
    await user.click(await within(rooms()).findByRole("button", { name }));
    return screen.findByRole("dialog");
  };

  it("nothing configured: it says so and 'Configura inventario' opens a real form", async () => {
    const user = userEvent.setup();
    renderPage();

    const form = await openForm(user, "Configura inventario");

    expect(within(form).getByRole("heading", { name: "Configura inventario" })).not.toBeNull();
    expect(within(form).getByLabelText("Numero di camere disponibili")).not.toBeNull();
    expect(flat(form)).toContain("Vale da oggi in poi. Le analisi già fatte non cambiano.");
    expect(flat(form)).not.toMatch(/RoomInventoryDaily|snapshot|riga|osservazione/iu);
  });

  it("saving sends one number and the page shows it, in both blocks, with the analysis following", async () => {
    const user = userEvent.setup();
    saveRoomInventoryMock.mockResolvedValue(ok(savedOf(24)));
    getAnalysisStatusMock.mockResolvedValue(analysisIs("IN_PROGRESS"));
    renderPage();
    const form = await openForm(user, "Configura inventario");

    await user.type(within(form).getByLabelText("Numero di camere disponibili"), "24");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(saveRoomInventoryMock).toHaveBeenCalledWith("p1", 24);
    expect(flat(rooms())).toContain("Camere disponibili 24 camere");
    expect(flat(rooms())).toContain("Inventario salvato: 24 camere.");
    expect(flat(await within(rooms()).findByRole("status"))).toContain("sta aggiornando l'occupazione");
    expect(within(rooms()).getByRole("button", { name: "Modifica inventario" })).not.toBeNull();
    expect(flat(region("1. Profilo struttura"))).toContain("Numero camere 24");
  });

  it("the way back to Dati is there, and the page says when the occupancy has followed", async () => {
    const user = userEvent.setup();
    saveRoomInventoryMock.mockResolvedValue(ok(savedOf(24)));
    getAnalysisStatusMock.mockResolvedValue(analysisIs("UP_TO_DATE"));
    renderPage();
    const form = await openForm(user, "Configura inventario");
    await user.type(within(form).getByLabelText("Numero di camere disponibili"), "24");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    await within(rooms()).findByText(/Occupazione aggiornata/u);
    expect(within(rooms()).getByRole("link", { name: "Vai a Dati" }).getAttribute("href")).toContain(
      "property=p1",
    );
  });

  it("with no bookings yet it says when the occupancy will come, and asks the analysis nothing", async () => {
    const user = userEvent.setup();
    saveRoomInventoryMock.mockResolvedValue(ok(savedOf(24, { analysis_requested: false })));
    renderPage();
    const form = await openForm(user, "Configura inventario");
    await user.type(within(form).getByLabelText("Numero di camere disponibili"), "24");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    await within(rooms()).findByText(/dopo il primo import dal PMS/u);
  });

  it.each(["0", "-3", "abc", "2.5", "5001", ""])("refuses %j before asking the backend", async (typed) => {
    const user = userEvent.setup();
    renderPage();
    const form = await openForm(user, "Configura inventario");

    if (typed !== "") await user.type(within(form).getByLabelText("Numero di camere disponibili"), typed);
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    expect(within(form).getByRole("alert").textContent).toBe(
      "Inserisci un numero intero di camere, da 1 a 5000.",
    );
    expect(saveRoomInventoryMock).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).not.toBeNull();
  });

  it("the limits it checks are the ones the backend sent", async () => {
    const user = userEvent.setup();
    getRoomInventoryMock.mockResolvedValue(ok({ ...NOT_CONFIGURED_INVENTORY, max_rooms: 40 }));
    renderPage();
    const form = await openForm(user, "Configura inventario");

    await user.type(within(form).getByLabelText("Numero di camere disponibili"), "41");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    expect(within(form).getByRole("alert").textContent).toContain("da 1 a 40");
  });

  it("a save that fails keeps the form open and says so", async () => {
    const user = userEvent.setup();
    saveRoomInventoryMock.mockResolvedValue({ ok: false, status: 500, code: "x", message: "x" });
    renderPage();
    const form = await openForm(user, "Configura inventario");
    await user.type(within(form).getByLabelText("Numero di camere disponibili"), "24");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    expect(await within(form).findByRole("alert")).not.toBeNull();
    expect(screen.getByRole("dialog")).not.toBeNull();
    expect(flat(rooms())).not.toContain("Inventario salvato");
  });

  it("configured: it shows the number and 'Modifica inventario' opens the form with it", async () => {
    const user = userEvent.setup();
    getRoomInventoryMock.mockResolvedValue(ok(inventoryOf(24)));
    saveRoomInventoryMock.mockResolvedValue(ok(savedOf(30)));
    getAnalysisStatusMock.mockResolvedValue(analysisIs("IN_PROGRESS"));
    renderPage();

    const form = await openForm(user, "Modifica inventario");

    const input = within(form).getByLabelText<HTMLInputElement>("Numero di camere disponibili");
    expect(input.value).toBe("24");
    expect(within(form).getByRole("heading", { name: "Modifica inventario" })).not.toBeNull();
    await user.clear(input);
    await user.type(input, "30");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    await waitFor(() => expect(saveRoomInventoryMock).toHaveBeenCalledWith("p1", 30));
    expect(await within(rooms()).findByText("30 camere")).not.toBeNull();
  });

  it("the same number again says nothing changed, and nothing follows", async () => {
    const user = userEvent.setup();
    getRoomInventoryMock.mockResolvedValue(ok(inventoryOf(24)));
    saveRoomInventoryMock.mockResolvedValue(
      ok(savedOf(24, { changed_nights: 0, analysis_requested: false })),
    );
    renderPage();
    const form = await openForm(user, "Modifica inventario");
    await user.click(within(form).getByRole("button", { name: "Salva" }));

    await within(rooms()).findByText(/Il numero era già questo/u);
  });

  it("nights that vary are said to vary, and saving says what it does to them", async () => {
    const user = userEvent.setup();
    getRoomInventoryMock.mockResolvedValue(ok(inventoryOf(24, true)));
    renderPage();

    expect(await within(rooms()).findByText(/Il numero varia nei prossimi mesi/u)).not.toBeNull();
    const form = await openForm(user, "Modifica inventario");
    expect(flat(form)).toContain("vale lo stesso numero per tutte le notti da oggi in poi");
  });

  describe("valid from", () => {
    const dateOf = (form: HTMLElement) => within(form).getByLabelText<HTMLInputElement>("Valido dal");

    it("is today by default, between the limits the backend sent, and says what that means", async () => {
      const user = userEvent.setup();
      renderPage();
      const form = await openForm(user, "Configura inventario");

      const field = dateOf(form);
      expect(field.type).toBe("date");
      expect(field.value).toBe("2026-11-09");
      expect(field.max).toBe("2026-11-09");
      expect(field.min).toBe("2016-11-08");
      expect(flat(form)).toContain("Di default è oggi.");
    });

    it("a plain save, with the day left as it is, sends the number alone", async () => {
      const user = userEvent.setup();
      saveRoomInventoryMock.mockResolvedValue(ok(savedOf(10)));
      renderPage();
      const form = await openForm(user, "Configura inventario");

      await user.type(within(form).getByLabelText("Numero di camere disponibili"), "10");
      await user.click(within(form).getByRole("button", { name: "Salva" }));

      await waitFor(() => expect(saveRoomInventoryMock).toHaveBeenCalledWith("p1", 10));
    });

    it("an earlier day is sent with the number, and the page says what happens to what was analysed", async () => {
      const user = userEvent.setup();
      saveRoomInventoryMock.mockResolvedValue(
        ok(savedOf(10, { known_since: "2026-10-01", changed_nights: 3692 })),
      );
      getAnalysisStatusMock.mockResolvedValue(analysisIs("IN_PROGRESS"));
      renderPage();
      const form = await openForm(user, "Configura inventario");
      await user.type(within(form).getByLabelText("Numero di camere disponibili"), "10");

      fireEvent.change(dateOf(form), { target: { value: "2026-10-01" } });

      expect(flat(form)).toContain("Le analisi già fatte non cambiano: NINFA ne farà una nuova");
      // the number's own "from today on" would now contradict the day chosen
      expect(flat(form)).not.toContain("Vale da oggi in poi");
      await user.click(within(form).getByRole("button", { name: "Salva" }));
      await waitFor(() => expect(saveRoomInventoryMock).toHaveBeenCalledWith("p1", 10, "2026-10-01"));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(flat(rooms())).toContain("Vale dal 1 ottobre 2026 in poi. Le analisi già fatte non cambiano.");
    });

    it("a day after today is refused before asking the backend, with the limits in words", async () => {
      const user = userEvent.setup();
      renderPage();
      const form = await openForm(user, "Configura inventario");
      await user.type(within(form).getByLabelText("Numero di camere disponibili"), "10");

      fireEvent.change(dateOf(form), { target: { value: "2026-11-10" } });
      await user.click(within(form).getByRole("button", { name: "Salva" }));

      expect(within(form).getByRole("alert").textContent).toBe(
        "Scegli un giorno tra il 8 novembre 2016 e il 9 novembre 2026: un inventario non può valere da un giorno futuro.",
      );
      expect(saveRoomInventoryMock).not.toHaveBeenCalled();
    });

    it.each(["2016-11-07", ""])("a day outside the limits (%j) is refused too", async (typed) => {
      const user = userEvent.setup();
      renderPage();
      const form = await openForm(user, "Configura inventario");
      await user.type(within(form).getByLabelText("Numero di camere disponibili"), "10");

      fireEvent.change(dateOf(form), { target: { value: typed } });
      await user.click(within(form).getByRole("button", { name: "Salva" }));

      expect(within(form).getByRole("alert").textContent).toContain("Scegli un giorno tra il");
      expect(saveRoomInventoryMock).not.toHaveBeenCalled();
    });

    it("once saved from an earlier day, the block says since when the number holds", async () => {
      getRoomInventoryMock.mockResolvedValue(ok({ ...inventoryOf(10), known_since: "2026-10-01" }));
      renderPage();

      expect(await within(rooms()).findByText(/Vale dal 1 ottobre 2026 in poi/u)).not.toBeNull();
    });
  });

  it("an inventory that cannot be read is not called 'not configured'", async () => {
    getRoomInventoryMock.mockResolvedValue({ ok: false, status: 500, code: "x", message: "x" });
    renderPage();

    expect(await within(rooms()).findByRole("alert")).not.toBeNull();
    expect(within(rooms()).queryByRole("button", { name: "Configura inventario" })).toBeNull();
    expect(flat(rooms())).not.toContain("non è ancora configurato");
  });
});
