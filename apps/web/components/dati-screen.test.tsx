// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DataOverviewResponse,
  DataPeriod,
  PropertyAccess,
  SessionContextResponse,
} from "@ninfa/contracts";

import { propertyLocalDate } from "@/lib/date/property-date";
import type { DatiTab } from "@/lib/data/tabs";
import {
  D_COST,
  D_LABOR,
  D_OCCUPANCY,
  D_OTA,
  D_PICKUP,
  fullOverview,
  fullOverviewSevenDays,
  nights,
  notProcessedOverview,
  partialOverview,
  unknownCoverageOverview,
} from "@/test/data-support";

import { DatiScreen } from "./dati-screen";

const useSessionMock = vi.fn();
const getDataOverviewMock = vi.fn();
const miaMock = vi.fn();

vi.mock("@/lib/session/session-context", () => ({ useSession: () => useSessionMock() }));
vi.mock("@/lib/api/data-overview", () => ({
  getDataOverview: (...args: unknown[]) => getDataOverviewMock(...args),
}));
// Dati is deterministic: it must never reach Mia or any model. Every entry point is a spy.
vi.mock("@/lib/api/ask-ninfa", () => ({
  askNinfa: (...args: unknown[]) => miaMock(...args),
  askMiaHome: (...args: unknown[]) => miaMock(...args),
}));

/** The readable text of a node: sibling elements are separated by a space (the plain `textContent` glues
 * them together), the non-breaking space Intl puts before "€" becomes a normal one, and runs collapse. */
function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}
const flat = (node: Node | string | null | undefined): string =>
  (typeof node === "string" ? node : node ? textOf(node) : "").replace(/ /gu, " ").replace(/\s+/gu, " ").trim();

function property(id: string, name: string, timezone = "Europe/Rome"): PropertyAccess {
  return { id, name, slug: name.toLowerCase().replace(/\s+/gu, "-"), timezone };
}

function signIn(properties: PropertyAccess[], refresh = vi.fn()) {
  const session: SessionContextResponse = {
    user: { id: "u1", email: "a@b.c", display_name: "Giulia Rossi" },
    session: { expires_at: "2026-12-31T00:00:00Z" },
    workspaces: [{ id: "ws1", name: "WS", slug: "ws", role: "MEMBER", properties }],
  };
  useSessionMock.mockReturnValue({ status: "authenticated", session, refresh, logout: vi.fn() });
  return refresh;
}

function ok(data: DataOverviewResponse) {
  return { ok: true as const, data };
}

interface HarnessProps {
  initialProperty?: string | null;
  initialTab?: DatiTab;
  initialPeriod?: DataPeriod;
  onSelectProperty?: (id: string) => void;
}

/** What `app/dati/page.tsx` does with the URL, with component state standing in for the router. */
function Harness({
  initialProperty = "p1",
  initialTab = "overview",
  initialPeriod = 30,
  onSelectProperty = () => undefined,
}: HarnessProps) {
  const [requested, setRequested] = useState<string | null>(initialProperty);
  const [tab, setTab] = useState<DatiTab>(initialTab);
  const [period, setPeriod] = useState<DataPeriod>(initialPeriod);
  return (
    <DatiScreen
      requestedPropertyId={requested}
      tab={tab}
      period={period}
      onSelectProperty={(id) => {
        setRequested(id);
        onSelectProperty(id);
      }}
      onSelectTab={setTab}
      onSelectPeriod={setPeriod}
      onNavigateToLogin={vi.fn()}
    />
  );
}

async function renderLoaded(data: DataOverviewResponse = fullOverview(), props: HarnessProps = {}) {
  getDataOverviewMock.mockResolvedValue(ok(data));
  const view = render(<Harness {...props} />);
  await waitFor(() => expect(view.container.querySelector(".dati-skeleton")).toBeNull());
  expect(screen.queryByRole("alert")).toBeNull();
  return view;
}

const region = (name: string | RegExp) => screen.getByRole("region", { name });

beforeEach(() => {
  getDataOverviewMock.mockReset();
  miaMock.mockReset();
  signIn([property("p1", "Residenza Alba")]);
});

describe("/dati - route, shell and tabs", () => {
  it("renders the Dati workspace inside the shell, with Dati as the current sidebar section", async () => {
    await renderLoaded();

    expect(screen.getByRole("heading", { level: 1, name: "Dati" })).not.toBeNull();
    expect(screen.getByText("I numeri operativi della struttura.")).not.toBeNull();
    const nav = screen.getByRole("navigation", { name: "Navigazione principale" });
    const dati = within(nav).getByRole("link", { name: "Dati" });
    expect(dati.getAttribute("aria-current")).toBe("page");
    expect(dati.getAttribute("href")).toBe("/dati?property=p1");
    expect(within(nav).queryByText("Oggi")?.closest("a")?.getAttribute("aria-current")).toBeNull();
  });

  it("shows the REAL property name from the session, never a demo name", async () => {
    await renderLoaded();

    expect(screen.getByText("Residenza Alba")).not.toBeNull();
    expect(document.body.textContent).not.toMatch(/Masseria|Villa Aurora|Vertix|Code XR/u);
  });

  it("opens on Panoramica, with the five tabs as a labelled tablist", async () => {
    await renderLoaded();

    const tablist = screen.getByRole("tablist", { name: "Sezioni di Dati" });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Panoramica",
      "Prenotazioni",
      "Distribuzione",
      "Costi",
      "Personale",
    ]);
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual(["true", "false", "false", "false", "false"]);
    const panel = screen.getByRole("tabpanel");
    expect(panel.getAttribute("aria-labelledby")).toBe(tabs[0]?.id);
    expect(tabs[0]?.getAttribute("aria-controls")).toBe(panel.id);
  });

  it("has a heading outline that never skips a level, on every tab", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    for (const tab of ["Panoramica", "Prenotazioni", "Distribuzione", "Costi", "Personale"]) {
      await user.click(screen.getByRole("tab", { name: tab }));
      const levels = screen.getAllByRole("heading").map((heading) => Number(heading.tagName.slice(1)));
      expect(levels[0], tab).toBe(1);
      for (let index = 1; index < levels.length; index += 1) {
        expect(levels[index]! - levels[index - 1]!, `${tab}: ${levels.join(",")}`).toBeLessThanOrEqual(1);
      }
      expect(levels.filter((level) => level === 1), tab).toHaveLength(1);
    }
  });

  it("uses no duplicate element id", async () => {
    const { container } = await renderLoaded();

    const ids = Array.from(container.querySelectorAll("[id]")).map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("is a second layer of navigation only inside the page: it adds no application navbar", async () => {
    await renderLoaded();

    expect(screen.getAllByRole("navigation")).toHaveLength(1); // the sidebar's, nothing else
  });

  it("switches tab and keeps the other tabs' data request out of it (one overview for all five)", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole("tab", { name: "Costi" }));

    expect(screen.getByRole("tab", { name: "Costi" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(screen.getByRole("tab", { name: "Costi" }).id);
    expect(getDataOverviewMock).toHaveBeenCalledTimes(1); // a tab is a view, not a request
  });

  it("opens straight on the tab the URL names", async () => {
    await renderLoaded(fullOverview(), { initialTab: "labor" });

    expect(screen.getByRole("tab", { name: "Personale" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("region", { name: "Ore pianificate per ruolo" })).not.toBeNull();
  });
});

describe("/dati - loading and error", () => {
  it("shows card-shaped skeletons under the header and tabs - never a page spinner", async () => {
    getDataOverviewMock.mockReturnValue(new Promise(() => undefined));
    const { container } = render(<Harness />);

    expect(await screen.findByRole("heading", { level: 1, name: "Dati" })).not.toBeNull();
    expect(screen.getByRole("tablist")).not.toBeNull(); // the page frame is already there
    const skeleton = container.querySelector(".dati-skeleton");
    expect(skeleton?.getAttribute("aria-busy")).toBe("true");
    expect(skeleton?.querySelectorAll(".dati-skeleton__card").length).toBeGreaterThanOrEqual(8);
    expect(within(skeleton as HTMLElement).getByRole("status").textContent).toBe("Caricamento dei dati in corso");
    expect(container.querySelector(".root-page__loading")).toBeNull();
  });

  it("keeps the shell and the tabs on a failure, with a contained error and a 'Riprova' that works", async () => {
    const user = userEvent.setup();
    getDataOverviewMock.mockResolvedValueOnce({ ok: false, status: 500, code: "INTERNAL_ERROR", message: "boom" });
    render(<Harness />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non siamo riusciti a caricare i dati. Riprova.");
    expect(alert.textContent).not.toMatch(/boom|INTERNAL/u); // the raw backend error never shows
    expect(screen.getByRole("tablist")).not.toBeNull();
    expect(screen.getByRole("navigation", { name: "Navigazione principale" })).not.toBeNull();

    getDataOverviewMock.mockResolvedValueOnce(ok(fullOverview()));
    await user.click(within(alert).getByRole("button", { name: "Riprova" }));

    expect(await screen.findByRole("region", { name: "Occupazione" })).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("re-resolves the property (no error shown) when the request answers PROPERTY_NOT_FOUND", async () => {
    const refresh = signIn([property("p1", "Residenza Alba")]);
    getDataOverviewMock.mockResolvedValue({ ok: false, status: 404, code: "PROPERTY_NOT_FOUND", message: "x" });
    render(<Harness />);

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("the refresh button repeats the same GET and is named for the data it reloads", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.click(screen.getByRole("button", { name: "Aggiorna dati" }));

    await waitFor(() => expect(getDataOverviewMock).toHaveBeenCalledTimes(2));
    expect(getDataOverviewMock.mock.calls[1]).toEqual(getDataOverviewMock.mock.calls[0]);
  });

  it("asks for the property-local business date, 30 nights by default", async () => {
    await renderLoaded();

    expect(getDataOverviewMock).toHaveBeenCalledWith("p1", propertyLocalDate(new Date(), "Europe/Rome"), 30);
  });
});

describe("Panoramica - the large occupancy card", () => {
  it("leads with the backend's on-books occupancy and the room-nights it rests on", async () => {
    await renderLoaded();

    const card = region("Occupazione");
    expect(within(card).getByText("62,7%", { selector: ".dati-occupancy__value" })).not.toBeNull();
    expect(flat(card)).toContain("prossimi 30 giorni · 764 camere-notte prenotate");
    expect(flat(card)).toContain("sulle prenotazioni attuali");
  });

  it("says so when the capacity is known for only some nights - never pretending it is known for all", async () => {
    await renderLoaded();

    expect(flat(region("Occupazione"))).toContain("Capienza nota per 29 di 30 notti");
  });

  it("does not mention capacity when every night has one", async () => {
    const data = fullOverview();
    const month = { ...(data.occupancy.days_30 as NonNullable<typeof data.occupancy.days_30>), nights_with_capacity: 30 };
    await renderLoaded({ ...data, occupancy: { ...data.occupancy, days_30: month, selected: month } });

    expect(flat(region("Occupazione"))).not.toContain("Capienza nota");
  });

  it("states when no night has a known capacity: no percentage, no zero", async () => {
    const data = fullOverview();
    const month = {
      ...(data.occupancy.days_30 as NonNullable<typeof data.occupancy.days_30>),
      nights_with_capacity: 0,
      occupancy_pct: null,
      rooms_available: null,
    };
    await renderLoaded({ ...data, occupancy: { ...data.occupancy, days_30: month, selected: month } });

    const card = region("Occupazione");
    expect(flat(card)).toContain("Capienza non nota per questo periodo");
    expect(within(card).getByText("Non disponibile", { selector: ".dati-occupancy__value" })).not.toBeNull();
    expect(card.querySelector(".dati-occupancy__value")?.textContent).not.toMatch(/0[,.]0/u);
  });

  it("states when some nights have no booking data at all", async () => {
    const data = fullOverview();
    const month = { ...(data.occupancy.days_30 as NonNullable<typeof data.occupancy.days_30>), nights_with_data: 27, nights_with_capacity: 27 };
    await renderLoaded({ ...data, occupancy: { ...data.occupancy, days_30: month, selected: month } });

    expect(flat(region("Occupazione"))).toContain("Prenotazioni registrate per 27 di 30 notti");
  });

  it("shows the three temporal mini summaries: Oggi, 7 giorni, 30 giorni", async () => {
    await renderLoaded();

    const tiles = within(region("Occupazione")).getByRole("list", { name: "Occupazione per periodo" });
    const items = within(tiles).getAllByRole("listitem").map((item) => flat(item));
    expect(items).toEqual([
      "Oggi 42,5% 17 / 40 camere",
      "7 giorni 63,9% 179 camere-notte",
      "30 giorni 62,7% 764 camere-notte",
    ]);
  });

  it("shows 'Non disponibile' in a mini tile whose period cannot be calculated", async () => {
    const data = fullOverview();
    await renderLoaded({ ...data, occupancy: { ...data.occupancy, today: null } });

    const items = within(region("Occupazione")).getAllByRole("listitem");
    expect(flat(items[0])).toBe("Oggi Non disponibile");
  });

  it("offers 7 and 30 days, with the pressed one exposed to assistive technology", async () => {
    await renderLoaded();

    const group = within(region("Occupazione")).getByRole("group", { name: "Periodo" });
    expect(within(group).getByRole("button", { name: "30 giorni" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(group).getByRole("button", { name: "7 giorni" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("states the last booking import as a FACT in the property's timezone - never 'Dati aggiornati'", async () => {
    await renderLoaded();

    const card = region("Occupazione");
    expect(flat(card)).toContain("Ultimo import prenotazioni: oggi alle 09:15");
    expect(document.body.textContent).not.toMatch(/aggiornat/iu);
  });
});

describe("Panoramica - the 2x2 KPI block", () => {
  const kpi = (name: string) => within(screen.getByRole("group", { name: "Indicatori del periodo" })).getByRole("article", { name });

  it("has the four cards in order, the first one highlighted", async () => {
    await renderLoaded();

    const articles = within(screen.getByRole("group", { name: "Indicatori del periodo" })).getAllByRole("article");
    expect(articles.map((article) => article.querySelector("h3")?.textContent)).toEqual([
      "Ricavi camera",
      "ADR",
      "Camere-notte",
      "Costi di febbraio",
    ]);
    expect(articles[0]?.className).toContain("dati-kpi--highlight");
    expect(articles.slice(1).every((article) => !article.className.includes("highlight"))).toBe(true);
  });

  it("formats each figure as the backend sent it, with the right unit", async () => {
    await renderLoaded();

    expect(flat(kpi("Ricavi camera"))).toContain("76.400 €");
    expect(flat(kpi("ADR"))).toContain("100,00 €");
    expect(flat(kpi("Camere-notte"))).toContain("764");
    expect(flat(kpi("Costi di febbraio"))).toContain("17.445 €");
  });

  it("calls room revenue what it is: on the books - never fatturato, incassi or margine", async () => {
    await renderLoaded();

    const revenue = flat(kpi("Ricavi camera"));
    expect(revenue).toContain("prenotazioni già a sistema");
    expect(flat(kpi("ADR"))).toContain("tariffa media on-books");
    expect(document.body.textContent).not.toMatch(/fatturat|incass|margine|utile|RevPAR/iu);
  });

  it("never calls room-nights 'prenotazioni'", async () => {
    await renderLoaded();

    const card = kpi("Camere-notte");
    expect(card.textContent).toMatch(/camere-notte/iu);
    expect(within(card).queryByText(/^prenotazioni$/iu)).toBeNull();
  });

  it("shows a delta ONLY where a comparison exists, and always says what it is compared with", async () => {
    await renderLoaded();

    // the 30-night room-nights have no comparison (the older snapshot does not reach that far): no chip
    expect(within(kpi("Camere-notte")).queryByText(/vs 7 giorni fa/u)).toBeNull();
    // the cost has one - and it names the month
    expect(flat(kpi("Costi di febbraio"))).toContain("+18,4% vs gennaio");
    for (const chip of document.querySelectorAll(".dati-delta")) expect(chip.textContent).toMatch(/vs /u);
  });

  it("omits the cost delta when there is no positive previous month", async () => {
    const data = fullOverview();
    await renderLoaded({ ...data, costs: { ...data.costs, delta_pct: null, previous_total_net_cost: null } });

    expect(flat(kpi("Costi di febbraio"))).not.toContain("vs ");
  });

  it("shows 'Non disponibile' (not 0 euro) when the costs of the month cannot be calculated", async () => {
    const data = fullOverview();
    await renderLoaded({
      ...data,
      costs: { ...data.costs, state: "NOT_AVAILABLE", reason: "NO_DATA", total_net_cost: null, delta_pct: null, categories: [], decision: null },
    });

    const card = kpi("Costi di febbraio");
    expect(flat(card)).toContain("Non disponibile");
    expect(flat(card)).toContain("Non ci sono dati di costo sufficienti per questo periodo.");
    expect(card.textContent).not.toMatch(/0 €|0,00/u);
  });
});

describe("Panoramica - the occupancy chart", () => {
  it("is titled for the number of nights and draws one column per night", async () => {
    const { container } = await renderLoaded();

    const chart = region("Occupazione prossimi 30 giorni");
    expect(chart).not.toBeNull();
    expect(container.querySelectorAll(".dati-chart__col")).toHaveLength(30);
    expect(container.querySelectorAll(".dati-chart__bar")).toHaveLength(29); // one night has no capacity: no bar
  });

  it("scales each bar to its night's stored occupancy on a 0-100 % axis", async () => {
    const { container } = await renderLoaded();

    const bars = Array.from(container.querySelectorAll<HTMLElement>(".dati-chart__bar"));
    expect(bars[0]?.style.height).toBe("92.5%"); // Saturday: 37 of 40 rooms
    expect(bars[2]?.style.height).toBe("50%"); // Monday: 20 of 40 rooms
    const axis = Array.from(container.querySelectorAll(".dati-chart__axis li")).map((li) => li.textContent);
    expect(axis).toEqual(["100%", "75%", "50%", "25%", "0%"]);
  });

  it("lets the axis grow past 100 % when a night is overbooked - occupancy is never clamped", async () => {
    const data = fullOverview();
    const rows = nights(30, { 1: { occupancy_pct: "112.50", rooms_on_books: 45 } });
    const { container } = await renderLoaded({ ...data, occupancy: { ...data.occupancy, nights: rows } });

    const axis = Array.from(container.querySelectorAll(".dati-chart__axis li")).map((li) => li.textContent);
    expect(axis[0]).toBe("125%");
    const bars = Array.from(container.querySelectorAll<HTMLElement>(".dati-chart__bar"));
    expect(bars[1]?.style.height).toBe("90%"); // 112.5 / 125
  });

  it("marks a night that has an actual NINFA decision - and nothing else", async () => {
    const { container } = await renderLoaded();

    const markers = container.querySelectorAll(".dati-chart__col .dati-chart__marker");
    expect(markers).toHaveLength(2); // the pickup night and the occupancy-risk night
    const flagged = Array.from(container.querySelectorAll(".dati-chart__col")).filter((col) => col.querySelector(".dati-chart__marker"));
    for (const col of flagged) expect(col.getAttribute("title")).toContain("Richiede attenzione");
    expect(flat(region("Occupazione prossimi 30 giorni"))).toContain("Richiede attenzione");
  });

  it("draws a night whose capacity is unknown as a hatched slot with its own legend - never as 0 %", async () => {
    const { container } = await renderLoaded();

    const slot = container.querySelector(".dati-chart__col--unknown-capacity");
    expect(slot).not.toBeNull();
    expect(slot?.querySelector(".dati-chart__bar")).toBeNull();
    expect(slot?.getAttribute("title")).toContain("Capienza non nota");
    expect(flat(region("Occupazione prossimi 30 giorni"))).toContain("Capienza non nota");
  });

  it("has an accessible name and a complete text equivalent", async () => {
    const { container } = await renderLoaded();

    const plot = container.querySelector(".dati-chart__plot");
    expect(plot?.getAttribute("role")).toBe("img");
    expect(plot?.getAttribute("aria-label")).toContain("30 notti");
    const table = within(region("Occupazione prossimi 30 giorni")).getByRole("table", { name: /equivalente testuale/u });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(31); // header + 30 nights
    expect(within(table).getAllByText("Attenzione")).toHaveLength(2); // status is text, not only colour
    expect(within(table).getAllByText("Non disponibile").length).toBeGreaterThanOrEqual(1);
    // the table must not widen the page (a bare <table> ignores width:1px)
    expect(table.closest(".visually-hidden")).not.toBeNull();
  });

  it("draws no target and no expected line: none exists deterministically", async () => {
    const { container } = await renderLoaded();

    expect(container.querySelector(".dati-chart__target, .dati-chart__expected")).toBeNull();
    expect(flat(region("Occupazione prossimi 30 giorni"))).not.toMatch(/obiettivo|target|previsione|atteso/iu);
  });

  it("shows a designed empty state - never a blank chart - when there is no figure", async () => {
    const { container } = await renderLoaded(notProcessedOverview());

    const chart = region("Occupazione prossimi 30 giorni");
    expect(within(chart).getByText("Nessun dato di occupazione")).not.toBeNull();
    expect(within(chart).getByText("L'analisi di oggi non è ancora disponibile.")).not.toBeNull();
    expect(container.querySelector(".dati-chart__ghost")?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("Panoramica - the OTA card", () => {
  it("shows the OTA share against the direct share, NINFA's reference and a link to the decision", async () => {
    await renderLoaded();

    const card = region("Dipendenza OTA");
    const text = flat(card);
    expect(text).toContain("72,2%");
    expect(text).toContain("27,8%");
    expect(text).toContain("Riferimento NINFA: 50,0%");
    expect(text).toContain("dal 14 marzo al 12 aprile");
    const link = within(card).getByRole("link", { name: "Richiede attenzione" });
    expect(link.getAttribute("href")).toBe(`/oggi/decisioni/${D_OTA}?property=p1`);
  });

  it("calls the reference a 'riferimento', never a target", async () => {
    await renderLoaded();

    expect(flat(region("Dipendenza OTA"))).not.toMatch(/target|obiettivo/iu);
  });

  it("lists the channels with their group and their weight - a different metric from the OTA share", async () => {
    await renderLoaded();

    const card = region("Dipendenza OTA");
    const rows = within(card).getAllByRole("listitem").map((item) => flat(item));
    expect(rows[0]).toContain("Booking.com");
    expect(rows[0]).toContain("OTA");
    expect(rows[0]).toContain("44,8%");
    expect(rows[1]).toContain("Diretto");
    expect(rows.some((row) => row.includes("Altro canale"))).toBe(true);
    expect(flat(card)).not.toMatch(/OTA_|DIRECT\b/u);
  });

  it("shows no commission amount: NINFA does not know them", async () => {
    await renderLoaded();

    expect(document.body.textContent).not.toMatch(/commission/iu);
  });

  it("limits the compact card to the top channels and says how many more there are", async () => {
    const data = fullOverview();
    const extra = ["Airbnb", "Hotels.com", "Agoda"].map((name) => ({ name, group: "OTA", room_nights: 10, share_pct: "1.00" }));
    await renderLoaded({
      ...data,
      distribution: {
        ...data.distribution,
        channel_mix: { total_room_nights: 900, channels: [...(data.distribution.channel_mix?.channels ?? []), ...extra] },
      },
    });

    const card = region("Dipendenza OTA");
    expect(within(card).getAllByRole("listitem")).toHaveLength(4);
    expect(flat(card)).toContain("+ altri 3 canali");
  });

  it("says plainly when there is no channel breakdown to show", async () => {
    const data = fullOverview();
    await renderLoaded({ ...data, distribution: { ...data.distribution, channel_mix: null } });

    expect(flat(region("Dipendenza OTA"))).toContain("Nessuna prenotazione certa da cui ricavare il peso dei canali.");
  });

  it("when the area was not analysed, says so - with no share and no breakdown", async () => {
    const data = fullOverview();
    await renderLoaded({
      ...data,
      distribution: { ...data.distribution, state: "NOT_AVAILABLE", reason: "NOT_ANALYZED", outcome: null, ota_share_pct: null, direct_share_pct: null, reference_ota_share_pct: null, decision_id: null, channel_mix: null },
    });

    const card = region("Dipendenza OTA");
    expect(within(card).getByText("Distribuzione non analizzata")).not.toBeNull();
    expect(flat(card)).not.toMatch(/%/u);
  });

  it("a clean evaluation never reads 'va tutto bene', and carries no attention indicator", async () => {
    const data = fullOverview();
    await renderLoaded({ ...data, distribution: { ...data.distribution, outcome: "CLEAR", decision_id: null } });

    const card = region("Dipendenza OTA");
    expect(flat(card)).toContain("Per quanto analizzato oggi, NINFA non rileva criticità sulla dipendenza OTA.");
    expect(within(card).queryByRole("link")).toBeNull();
    expect(card.querySelector(".dati-ota__attention-dot")).toBeNull();
  });

  it("explains an inconclusive OTA check in plain Italian, with a safe fallback for an unknown reason", async () => {
    await renderLoaded(partialOverview());

    const text = flat(region("Dipendenza OTA"));
    expect(text).toContain("I dati non bastano per valutare la dipendenza OTA.");
    expect(text).toContain("le prenotazioni classificate come OTA o dirette sono troppo poche; dati insufficienti");
    expect(text).not.toMatch(/OTA_BOOKING|SOME_FUTURE_CODE/u);
  });
});

describe("Panoramica - the detail table", () => {
  const table = () => within(region("Dettaglio soggiorni")).getByRole("table");

  it("has the specified columns - and NO OTA column: no day-level OTA share exists", async () => {
    await renderLoaded();

    const headers = within(table()).getAllByRole("columnheader").map((header) => flat(header));
    expect(headers).toEqual(["Data", "Camere prenotate", "Disponibili", "Occupazione", "Ricavi camera", "ADR", "Stato"]);
    expect(headers.some((header) => /OTA/u.test(header))).toBe(false);
  });

  it("has one row per stay night, with the figures the backend sent", async () => {
    await renderLoaded();

    const rows = within(table()).getAllByRole("row");
    expect(rows).toHaveLength(31);
    const first = flat(rows[1]);
    expect(first).toContain("sab 14 mar");
    expect(first).toContain("37");
    expect(first).toContain("40");
    expect(first).toContain("92,5%");
    expect(first).toContain("Regolare");
  });

  it("shows a dash (read as 'non disponibile') where a figure could not be calculated - never 0", async () => {
    await renderLoaded();

    const row = within(table()).getAllByRole("row")[10]; // the night whose capacity is unknown
    const dashes = within(row as HTMLElement).getAllByLabelText("Non disponibile");
    expect(dashes.length).toBeGreaterThanOrEqual(2); // capacity and occupancy
    expect(flat(row)).not.toMatch(/\b0,0%/u);
  });

  it("states each night's status as a WORD, never colour alone", async () => {
    await renderLoaded();

    const statuses = within(table()).getAllByRole("row").slice(1).map((row) => flat(row.querySelector(".dati-status")));
    expect(statuses.filter((status) => status === "Attenzione")).toHaveLength(2);
    expect(statuses.filter((status) => status === "Regolare")).toHaveLength(28);
    for (const mark of document.querySelectorAll(".dati-status__mark")) expect(mark.getAttribute("aria-hidden")).toBe("true");
  });

  it("makes ONLY a night with a decision interactive, linking to that decision's detail page", async () => {
    await renderLoaded();

    const links = within(table()).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `/oggi/decisioni/${D_PICKUP}?property=p1`,
      `/oggi/decisioni/${D_OCCUPANCY}?property=p1`,
    ]);
    expect(links[0]?.getAttribute("aria-label")).toMatch(/Apri la decisione: /u);
    // no row is clickable otherwise
    for (const row of within(table()).getAllByRole("row").slice(1)) expect(row.getAttribute("onclick")).toBeNull();
  });

  it("searches by date, in any way a person might type it", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    await user.type(screen.getByRole("searchbox", { name: "Cerca per data" }), "sab");

    const days = within(table()).getAllByRole("row").slice(1).map((row) => flat(row.querySelector("th")));
    expect(days).toEqual(["sab 14 mar", "sab 21 mar", "sab 28 mar", "sab 4 apr", "sab 11 apr"]);
    expect(flat(region("Dettaglio soggiorni"))).toContain("5 di 30 notti");
  });

  it("filters to the nights that need attention, and says when none matches", async () => {
    const user = userEvent.setup();
    await renderLoaded();

    const filter = screen.getByRole("button", { name: "Solo attenzione" });
    expect(filter.getAttribute("aria-pressed")).toBe("false");
    await user.click(filter);
    expect(filter.getAttribute("aria-pressed")).toBe("true");
    expect(within(table()).getAllByRole("row").slice(1)).toHaveLength(2);

    await user.type(screen.getByRole("searchbox", { name: "Cerca per data" }), "domenica");
    expect(within(table()).getByText("Nessuna notte corrisponde alla ricerca.")).not.toBeNull();
  });

  it("is a keyboard-reachable, named scroll region", async () => {
    await renderLoaded();

    const scroll = within(region("Dettaglio soggiorni")).getByRole("region", { name: "Tabella scorrevole: dettaglio per notte" });
    expect(scroll.getAttribute("tabindex")).toBe("0");
    expect(within(scroll).getByRole("table")).not.toBeNull();
    const headers = within(table()).getAllByRole("columnheader");
    for (const header of headers) expect(header.getAttribute("scope")).toBe("col");
  });

  it("explains that the status reflects NINFA's decisions only", async () => {
    await renderLoaded();

    expect(flat(region("Dettaglio soggiorni"))).toContain("Lo stato riflette solo le decisioni di NINFA per la notte: non è un giudizio sui numeri.");
  });

  it("shows a designed empty state when there are no nights", async () => {
    await renderLoaded(notProcessedOverview());

    const card = region("Dettaglio soggiorni");
    expect(within(card).getByText("Occupazione non disponibile")).not.toBeNull();
    expect(within(card).queryByRole("table")).toBeNull();
  });
});

describe("Coverage and freshness", () => {
  const chips = () => within(region("Copertura dell'analisi")).getAllByRole("listitem").map((item) => flat(item));

  it("shows the four areas as analysed, with the freshness of each domain's own data", async () => {
    await renderLoaded();

    expect(chips().slice(0, 4)).toEqual([
      "Ricavi Analizzati",
      "Distribuzione Analizzata",
      "Costi Analizzati",
      "Personale Analizzato",
    ]);
    const text = flat(region("Copertura dell'analisi"));
    expect(text).toContain("Ultimo import costi: ieri alle 18:05");
    expect(text).toContain("Ultimo import personale:"); // its OWN timestamp, never the bookings one
    expect(text).not.toContain("09:15");
  });

  it("a partial run reads 'Analisi parziale' and a skipped area 'Non analizzato' - never clear", async () => {
    await renderLoaded(partialOverview());

    expect(chips().slice(0, 4)).toEqual([
      "Ricavi Analisi parziale",
      "Distribuzione Analisi parziale",
      "Costi Non analizzati",
      "Personale Non analizzato",
    ]);
    const statuses = within(region("Dettaglio soggiorni")).getAllByRole("row").slice(1).map((row) => flat(row.querySelector(".dati-status")));
    expect(new Set(statuses)).toEqual(new Set(["Analisi parziale"]));
  });

  it("an unrecorded coverage reads 'Non disponibile' and no night is 'Regolare'", async () => {
    await renderLoaded(unknownCoverageOverview());

    expect(chips().slice(0, 4).every((chip) => chip.endsWith("Non disponibile"))).toBe(true);
    const statuses = within(region("Dettaglio soggiorni")).getAllByRole("row").slice(1).map((row) => flat(row.querySelector(".dati-status")));
    expect(new Set(statuses)).toEqual(new Set(["Non valutato"]));
    expect(flat(region("Dipendenza OTA"))).toContain("La copertura dell'analisi non è registrata per questa analisi.");
  });

  it("states the last completed analysis when today has none, or that there never was one", async () => {
    const view = await renderLoaded(notProcessedOverview("2026-03-12"));
    expect(flat(region("Copertura dell'analisi"))).toContain("L'ultima analisi completata risale al 12 marzo.");
    view.unmount();

    await renderLoaded(notProcessedOverview(null));
    expect(flat(region("Copertura dell'analisi"))).toContain("NINFA non ha ancora completato una prima analisi.");
  });
});

describe("no data / not processed - designed states, never broken blanks", () => {
  it("explains why nothing can be shown, in every block, in plain Italian", async () => {
    await renderLoaded(notProcessedOverview());

    const card = region("Occupazione");
    expect(within(card).getByText("Occupazione non disponibile")).not.toBeNull();
    expect(within(card).getByText("L'analisi di oggi non è ancora disponibile.")).not.toBeNull();
    for (const label of ["Ricavi camera", "ADR", "Camere-notte"]) {
      const article = within(screen.getByRole("group", { name: "Indicatori del periodo" })).getByRole("article", { name: label });
      expect(flat(article)).toContain("Non disponibile");
    }
    expect(flat(region("Dipendenza OTA"))).toContain("Distribuzione non disponibile");
    expect(document.body.textContent).not.toMatch(/NO_ANALYSIS|NOT_PROCESSED|undefined|NaN/u);
  });

  it("keeps the last-import line as an honest 'non disponibile'", async () => {
    await renderLoaded(notProcessedOverview());

    expect(flat(region("Occupazione"))).toContain("Ultimo import prenotazioni non disponibile");
  });
});

describe("Prenotazioni tab", () => {
  it("compares today, 7 and 30 days, with the 7-day change only where it exists", async () => {
    await renderLoaded(fullOverview(), { initialTab: "bookings" });

    const table = within(region("Riepilogo per periodo")).getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1).map((row) => flat(row));
    expect(rows[0]).toBe("Oggi 42,5% 17 40 1.700 € 100,00 € —");
    expect(rows[1]).toBe("7 giorni 63,9% 179 280 17.900 € 100,00 € +20");
    expect(rows[2]).toBe("30 giorni 62,7% 764 1.160 76.400 € 100,00 € —");
    expect(flat(region("Riepilogo per periodo"))).toContain("La capienza disponibile conta solo le notti con capienza nota.");
  });

  it("adds the booking count and the comparison with a week ago to every night", async () => {
    await renderLoaded(fullOverview(), { initialTab: "bookings" });

    const nightsTable = within(region("Dettaglio soggiorni")).getByRole("table");
    const headers = within(nightsTable).getAllByRole("columnheader").map((header) => flat(header));
    expect(headers).toEqual([
      "Data", "Prenotazioni", "Camere prenotate", "Disponibili", "Occupazione", "Ricavi camera", "ADR", "7 giorni fa", "Variazione", "Stato",
    ]);
    const first = flat(within(nightsTable).getAllByRole("row")[1]);
    expect(first).toContain("sab 14 mar");
    expect(first).toContain("35"); // 7 days ago
    expect(first).toContain("+2");
  });

  it("changes the period from this tab too", async () => {
    const user = userEvent.setup();
    getDataOverviewMock.mockImplementation((_p: string, _d: string, period: number) =>
      Promise.resolve(ok(period === 7 ? fullOverviewSevenDays() : fullOverview())),
    );
    render(<Harness initialTab="bookings" />);
    await screen.findByRole("region", { name: "Riepilogo per periodo" });

    await user.click(within(region("Riepilogo per periodo")).getByRole("button", { name: "7 giorni" }));

    await waitFor(() => expect(region("Occupazione prossimi 7 giorni")).not.toBeNull());
  });
});

describe("Distribuzione tab", () => {
  it("shows every channel with its room-nights and the three definitions", async () => {
    await renderLoaded(fullOverview(), { initialTab: "distribution" });

    const card = region("Dipendenza OTA");
    const rows = within(card).getAllByRole("listitem").map((item) => flat(item));
    expect(rows).toHaveLength(4);
    expect(rows[0]).toContain("390 camere-notte");
    expect(flat(card)).toContain("Prenotazioni su canali classificati: 100,0%");
    const info = region("Come leggere i numeri");
    for (const term of ["Quota OTA", "Peso di un canale", "Riferimento NINFA"]) {
      expect(within(info).getByText(term)).not.toBeNull();
    }
    expect(flat(info)).toContain("Non è un obiettivo.");
  });

  it("states this area's analysis state and the freshness of its source", async () => {
    await renderLoaded(fullOverview(), { initialTab: "distribution" });

    const info = flat(region("Come leggere i numeri"));
    expect(info).toContain("Distribuzione Analizzata");
    expect(info).toContain("Ultimo import prenotazioni: oggi alle 09:15");
  });
});

describe("Costi tab", () => {
  it("shows the last concluded month's cost, in Italian categories - never a raw code", async () => {
    await renderLoaded(fullOverview(), { initialTab: "costs" });

    const summary = region("Costi di febbraio");
    expect(flat(summary)).toContain("17.445 €");
    expect(flat(summary)).toContain("+18,4% vs gennaio");
    expect(flat(summary)).toContain("Costi in una categoria riconosciuta: 98,1%");
    expect(flat(summary)).toContain("Ultimo mese concluso, per data fattura. Il mese in corso non è mostrato.");
    const categories = within(region("Costi per categoria")).getAllByRole("row").slice(1).map((row) => flat(row));
    expect(categories[0]).toContain("Cibo");
    expect(categories[1]).toContain("Utenze");
    expect(categories[3]).toContain("Non classificato");
    expect(document.body.textContent).not.toMatch(/\b(FOOD|UTILITIES|LAUNDRY|OTHER)\b/u);
  });

  it("shows the cost per occupied room where it is calculable and the reason where it is not", async () => {
    await renderLoaded(fullOverview(), { initialTab: "costs" });

    const rows = within(region("Costi per categoria")).getAllByRole("row").slice(1).map((row) => flat(row));
    expect(rows[0]).toContain("7,68 €");
    expect(rows[2]).toContain("Occupazione del mese incompleta");
    expect(rows[3]).toContain("Non applicabile");
  });

  it("links a cost decision to its category and shows its own figures", async () => {
    await renderLoaded(fullOverview(), { initialTab: "costs" });

    const link = within(region("Costi per categoria")).getByRole("link", { name: /Richiede attenzione/u });
    expect(link.getAttribute("href")).toBe(`/oggi/decisioni/${D_COST}?property=p1`);
    const decision = region("Costo per camera sopra il normale");
    expect(flat(decision)).toContain("Cibo, febbraio");
    expect(flat(decision)).toContain("Costo per camera occupata 7,68 €, atteso 6,10 €");
  });

  it("states that costs were not part of today's analysis, while still showing the recorded data", async () => {
    const data = fullOverview();
    await renderLoaded(
      { ...data, analysis: { ...data.analysis, domain_states: data.analysis.domain_states.map((item) => (item.domain === "COSTS" ? { ...item, state: "NOT_ANALYZED" as const } : item)) } },
      { initialTab: "costs" },
    );

    expect(flat(region("Costi di febbraio"))).toContain("I costi non fanno parte dell'analisi di oggi: qui sono mostrati i dati registrati.");
  });

  it("flags costs in another currency instead of silently adding or dropping them", async () => {
    const data = fullOverview();
    await renderLoaded({ ...data, costs: { ...data.costs, other_currencies_present: true } }, { initialTab: "costs" });

    expect(flat(region("Costi di febbraio"))).toContain("Sono presenti costi in un'altra valuta: non sono inclusi.");
  });

  it("shows an honest coverage state - not zero - when there is no cost data", async () => {
    await renderLoaded(partialOverview(), { initialTab: "costs" });

    const summary = region("Costi di febbraio");
    expect(within(summary).getByText("Costi non disponibili")).not.toBeNull();
    expect(flat(summary)).toContain("Non ci sono dati di costo sufficienti per questo periodo.");
    expect(summary.textContent).not.toMatch(/\b0 €/u);
    expect(flat(summary)).toContain("Ultimo import costi: nessuna origine dati configurata");
  });
});

describe("Personale tab", () => {
  it("shows planned hours by role - Italian names, hours and cost only when known", async () => {
    await renderLoaded(fullOverview(), { initialTab: "labor" });

    const rows = within(region("Ore pianificate per ruolo")).getAllByRole("row").slice(1).map((row) => flat(row));
    expect(rows[0]).toContain("Governanza");
    expect(rows[0]).toContain("112,0 h");
    expect(rows[0]).toContain("1.680,00 €");
    expect(rows[1]).toContain("Cucina");
    expect(rows[1]).toContain("77,0 h");
    expect(rows[1]).toContain("1 giorno incompleto");
    expect(document.body.textContent).not.toMatch(/HOUSEKEEPING|KITCHEN/u);
  });

  it("shows the overstaffing decision's own facts and a link to it", async () => {
    await renderLoaded(fullOverview(), { initialTab: "labor" });

    const decision = region("Possibile sovradimensionamento del personale");
    expect(flat(decision)).toContain("Governanza");
    expect(flat(decision)).toContain("Programmate 32,0 h, attese 24,0 h: 8,0 h in più");
    expect(within(decision).getByRole("link", { name: "Apri la decisione" }).getAttribute("href")).toBe(`/oggi/decisioni/${D_LABOR}?property=p1`);
  });

  it("invents no incidence, productivity, FTE or labor-cost ratio - and says so", async () => {
    await renderLoaded(fullOverview(), { initialTab: "labor" });

    expect(flat(region("Ore pianificate"))).toContain("NINFA non calcola incidenza, produttività o rapporto con i ricavi.");
    expect(document.body.textContent).not.toMatch(/FTE|incidenza %|produttività \d/iu);
  });

  it("says plainly when no labor source or no data exists", async () => {
    await renderLoaded(partialOverview(), { initialTab: "labor" });

    const summary = region("Ore pianificate");
    expect(within(summary).getByText("Personale non disponibile")).not.toBeNull();
    expect(flat(summary)).toContain("Nessuna origine dati disponibile.");
    expect(flat(summary)).toContain("Ultimo import personale: nessuna origine dati configurata");
  });
});

describe("property selection - 0 / 1 / N", () => {
  it("shows the empty state, and requests nothing, when the account has no property", async () => {
    signIn([]);
    render(<Harness />);

    expect(await screen.findByText("Nessuna struttura disponibile")).not.toBeNull();
    expect(getDataOverviewMock).not.toHaveBeenCalled();
  });

  it("with one property shows its name as plain text - no selector that promises a choice", async () => {
    await renderLoaded();

    expect(screen.queryByLabelText("Struttura attiva")).toBeNull();
    expect(screen.getByText("Residenza Alba")).not.toBeNull();
  });

  it("with several properties offers a selector, and a switch replaces EVERY displayed figure", async () => {
    const user = userEvent.setup();
    signIn([property("p1", "Residenza Alba"), property("p2", "Villa Solare")]);
    const second = partialOverview();
    getDataOverviewMock.mockImplementation((propertyId: string) =>
      Promise.resolve(ok(propertyId === "p2" ? { ...second, property_id: "p2" } : fullOverview())),
    );
    render(<Harness />);
    await within(await screen.findByRole("region", { name: "Occupazione" })).findByText("62,7%", { selector: ".dati-occupancy__value" });

    await user.selectOptions(screen.getByLabelText("Struttura attiva"), "p2");

    await waitFor(() => expect(getDataOverviewMock).toHaveBeenCalledWith("p2", expect.any(String), 30));
    const card = await screen.findByText("60,7%", { selector: ".dati-occupancy__value" });
    expect(card).not.toBeNull();
    expect(screen.queryByText("62,7%", { selector: ".dati-occupancy__value" })).toBeNull(); // nothing of p1 survives
    expect(flat(region("Dipendenza OTA"))).toContain("I dati non bastano per valutare la dipendenza OTA.");
    expect(screen.getByText("Villa Solare")).not.toBeNull();
  });

  it("never shows the previous property's data while the new one loads", async () => {
    const user = userEvent.setup();
    signIn([property("p1", "Residenza Alba"), property("p2", "Villa Solare")]);
    let resolveSecond: (value: ReturnType<typeof ok>) => void = () => undefined;
    getDataOverviewMock.mockImplementation((propertyId: string) =>
      propertyId === "p2" ? new Promise((resolve) => { resolveSecond = resolve; }) : Promise.resolve(ok(fullOverview())),
    );
    const { container } = render(<Harness />);
    await screen.findByText("62,7%", { selector: ".dati-occupancy__value" });

    await user.selectOptions(screen.getByLabelText("Struttura attiva"), "p2");

    await waitFor(() => expect(container.querySelector(".dati-skeleton")).not.toBeNull());
    expect(screen.queryByText("62,7%", { selector: ".dati-occupancy__value" })).toBeNull();
    await act(async () => resolveSecond(ok({ ...partialOverview(), property_id: "p2" })));
    expect(await screen.findByText("60,7%", { selector: ".dati-occupancy__value" })).not.toBeNull();
  });

  it("corrects an unknown or foreign property id to a real one without calling the API with it", async () => {
    signIn([property("p1", "Residenza Alba"), property("p2", "Villa Solare")]);
    getDataOverviewMock.mockResolvedValue(ok(fullOverview()));
    const onSelectProperty = vi.fn();
    render(<Harness initialProperty="someone-elses-property" onSelectProperty={onSelectProperty} />);

    await waitFor(() => expect(onSelectProperty).toHaveBeenCalledWith("p1"));
    expect(getDataOverviewMock).not.toHaveBeenCalledWith("someone-elses-property", expect.any(String), expect.anything());
  });

  it("asks for each property's own local date (its timezone, not the browser's)", async () => {
    signIn([property("p1", "Residenza Alba", "Pacific/Auckland")]);
    getDataOverviewMock.mockResolvedValue(ok(fullOverview()));
    render(<Harness />);

    await waitFor(() => expect(getDataOverviewMock).toHaveBeenCalled());
    expect(getDataOverviewMock.mock.calls[0]?.[1]).toBe(propertyLocalDate(new Date(), "Pacific/Auckland"));
  });
});

describe("period control", () => {
  it("fetches the 7-night overview and redraws the chart, the KPIs and the table for 7 nights", async () => {
    const user = userEvent.setup();
    getDataOverviewMock.mockImplementation((_p: string, _d: string, period: number) =>
      Promise.resolve(ok(period === 7 ? fullOverviewSevenDays() : fullOverview())),
    );
    const { container } = render(<Harness />);
    await screen.findByRole("region", { name: "Occupazione prossimi 30 giorni" });

    await user.click(within(region("Occupazione")).getByRole("button", { name: "7 giorni" }));

    await waitFor(() => expect(getDataOverviewMock).toHaveBeenCalledWith("p1", expect.any(String), 7));
    await screen.findByRole("region", { name: "Occupazione prossimi 7 giorni" });
    expect(container.querySelectorAll(".dati-chart__col")).toHaveLength(7);
    expect(within(region("Dettaglio soggiorni")).getAllByRole("row")).toHaveLength(8);
    const card = region("Occupazione");
    expect(within(card).getByText("63,9%", { selector: ".dati-occupancy__value" })).not.toBeNull();
    expect(flat(card)).toContain("prossimi 7 giorni · 179 camere-notte prenotate");
    expect(within(card).getByRole("button", { name: "7 giorni" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows the 7-day change against a week ago as a stated comparison", async () => {
    const user = userEvent.setup();
    getDataOverviewMock.mockImplementation((_p: string, _d: string, period: number) =>
      Promise.resolve(ok(period === 7 ? fullOverviewSevenDays() : fullOverview())),
    );
    render(<Harness />);
    await screen.findByRole("region", { name: "Occupazione prossimi 30 giorni" });

    await user.click(within(region("Occupazione")).getByRole("button", { name: "7 giorni" }));
    await screen.findByRole("region", { name: "Occupazione prossimi 7 giorni" });

    const kpi = within(screen.getByRole("group", { name: "Indicatori del periodo" })).getByRole("article", { name: "Camere-notte" });
    expect(flat(kpi)).toContain("+20 vs 7 giorni fa");
  });

  it("keeps the previous figures on screen (dimmed) while the other period loads - the page never blanks", async () => {
    const user = userEvent.setup();
    let resolveSeven: (value: ReturnType<typeof ok>) => void = () => undefined;
    getDataOverviewMock.mockImplementation((_p: string, _d: string, period: number) =>
      period === 7 ? new Promise((resolve) => { resolveSeven = resolve; }) : Promise.resolve(ok(fullOverview())),
    );
    const { container } = render(<Harness />);
    await screen.findByRole("region", { name: "Occupazione prossimi 30 giorni" });

    await user.click(within(region("Occupazione")).getByRole("button", { name: "7 giorni" }));

    await waitFor(() => expect(container.querySelector("[data-period-busy='true']")).not.toBeNull());
    expect(container.querySelector(".dati-skeleton")).toBeNull();
    expect(region("Occupazione prossimi 30 giorni")).not.toBeNull(); // still the previous figures
    expect(within(region("Occupazione")).getByRole("button", { name: "7 giorni" }).getAttribute("aria-pressed")).toBe("true");
    await act(async () => resolveSeven(ok(fullOverviewSevenDays())));
    await screen.findByRole("region", { name: "Occupazione prossimi 7 giorni" });
    expect(container.querySelector("[data-period-busy='true']")).toBeNull();
  });
});

describe("Dati is deterministic: it never reaches Mia or a model", () => {
  it("calls no Mia / Ask endpoint while loading, switching tabs or period", async () => {
    const user = userEvent.setup();
    getDataOverviewMock.mockResolvedValue(ok(fullOverview()));
    render(<Harness />);
    await screen.findByRole("region", { name: "Occupazione" });

    for (const tab of ["Prenotazioni", "Distribuzione", "Costi", "Personale", "Panoramica"]) {
      await user.click(screen.getByRole("tab", { name: tab }));
    }

    expect(miaMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: /Mia/u })).toBeNull();
    expect(document.body.textContent).not.toMatch(/Chiedi a Mia/u);
  });
});
