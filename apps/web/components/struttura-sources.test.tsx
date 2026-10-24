// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DataSourcesResponse } from "@ninfa/contracts";

import {
  bookingsViaFile,
  channelManagerConnected,
  costsViaXml,
  failure,
  laborViaCsv,
  nothingConfigured,
  ok,
  PROPERTY_ID,
  previewOf,
  sources,
  xmlFile,
} from "@/test/sources-support";

import { StrutturaSources } from "./struttura-sources";

const getDataSourcesMock = vi.fn();
const removeDataSourceMock = vi.fn();
const previewImportMock = vi.fn();
const importFileMock = vi.fn();
const getImportConfigurationMock = vi.fn();
const forgetImportConfigurationMock = vi.fn();
const downloadTemplateMock = vi.fn();
const saveBlobMock = vi.fn();

vi.mock("@/lib/api/data-sources", () => ({
  getDataSources: (...args: unknown[]) => getDataSourcesMock(...args),
  removeDataSource: (...args: unknown[]) => removeDataSourceMock(...args),
  previewImport: (...args: unknown[]) => previewImportMock(...args),
  importFile: (...args: unknown[]) => importFileMock(...args),
  inspectFile: vi.fn(),
  understandFile: vi.fn(),
  checkMapping: vi.fn(),
  validateImport: vi.fn(),
  importMatchedFile: vi.fn(),
  getImportConfiguration: (...args: unknown[]) => getImportConfigurationMock(...args),
  forgetImportConfiguration: (...args: unknown[]) => forgetImportConfigurationMock(...args),
  downloadTemplate: (...args: unknown[]) => downloadTemplateMock(...args),
}));
vi.mock("@/lib/sources/save-file", async (original) => ({
  ...(await original<typeof import("@/lib/sources/save-file")>()),
  saveBlob: (...args: unknown[]) => saveBlobMock(...args),
}));

/** The readable text of a node: siblings separated by a space, runs of white space collapsed. */
function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}
const flat = (node: Node): string => textOf(node).replace(/\s+/gu, " ").trim();

const onPropertyInvalid = vi.fn();

async function renderBlock(response: DataSourcesResponse = nothingConfigured()) {
  getDataSourcesMock.mockResolvedValue(ok(response));
  const view = render(
    <StrutturaSources propertyId={PROPERTY_ID} timeZone="Europe/Rome" onPropertyInvalid={onPropertyInvalid} />,
  );
  await screen.findByRole("list", { name: "Fonti dati collegate e collegabili" });
  return view;
}

const cardOf = (name: string) =>
  screen
    .getAllByRole("listitem")
    .find((item) => within(item).queryByRole("heading", { level: 3, name }) !== null) as HTMLElement;
const dialog = () => screen.getByRole("dialog");

beforeEach(() => {
  for (const mock of [
    getDataSourcesMock,
    removeDataSourceMock,
    previewImportMock,
    importFileMock,
    getImportConfigurationMock,
    forgetImportConfigurationMock,
    downloadTemplateMock,
    saveBlobMock,
    onPropertyInvalid,
  ]) {
    mock.mockReset();
  }
  // a source with no saved configuration: the manage dialog simply has nothing to show
  getImportConfigurationMock.mockResolvedValue(failure("DATA_SOURCE_NOT_FOUND", 404));
  // "Oggi" is always the same day: the cards say "Oggi alle 11:31" whatever the real date is
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-23T09:45:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

// --- loading, error ------------------------------------------------------------------------------------

describe("Fonti dati - loading and failure are said, never papered over", () => {
  it("shows a loading state and a disabled 'Collega una nuova fonte' until the backend answers", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    getDataSourcesMock.mockReturnValue(new Promise((done) => (resolve = done)));
    render(<StrutturaSources propertyId={PROPERTY_ID} timeZone="Europe/Rome" onPropertyInvalid={onPropertyInvalid} />);

    expect(screen.getByText("Caricamento delle fonti dati in corso")).not.toBeNull();
    expect((screen.getByRole("button", { name: "Collega una nuova fonte" }) as HTMLButtonElement).disabled).toBe(true);
    // no card is claimed before the backend says what is true
    expect(screen.queryByText("Non configurato")).toBeNull();

    resolve(ok(nothingConfigured()));
    expect(await screen.findByRole("list", { name: "Fonti dati collegate e collegabili" })).not.toBeNull();
    expect((screen.getByRole("button", { name: "Collega una nuova fonte" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("on failure says so (no 'Non configurato' it has not verified) and offers 'Riprova'", async () => {
    const user = userEvent.setup();
    getDataSourcesMock.mockResolvedValueOnce(failure("INTERNAL_ERROR", 500));
    render(<StrutturaSources propertyId={PROPERTY_ID} timeZone="Europe/Rome" onPropertyInvalid={onPropertyInvalid} />);

    const alert = await screen.findByRole("alert");
    expect(flat(alert)).toContain("Non siamo riusciti a caricare le fonti dati.");
    expect(screen.queryByText("Non configurato")).toBeNull();
    expect(screen.queryByText("technical message that must never reach the page")).toBeNull();

    getDataSourcesMock.mockResolvedValueOnce(ok(laborViaCsv()));
    await user.click(screen.getByRole("button", { name: "Riprova" }));
    expect(await screen.findByRole("list", { name: "Fonti dati collegate e collegabili" })).not.toBeNull();
  });

  it("asks the caller to re-resolve the property when the backend says it no longer exists", async () => {
    getDataSourcesMock.mockResolvedValue(failure("PROPERTY_NOT_FOUND", 404));
    render(<StrutturaSources propertyId={PROPERTY_ID} timeZone="Europe/Rome" onPropertyInvalid={onPropertyInvalid} />);

    await waitFor(() => expect(onPropertyInvalid).toHaveBeenCalledTimes(1));
  });
});

// --- what every state looks like -------------------------------------------------------------------------

describe("Fonti dati - every card says what the backend says", () => {
  it("nothing configured: five neutral cards, the introduction, no vendor and no date", async () => {
    await renderBlock(nothingConfigured());

    const cards = screen.getAllByRole("listitem").map((item) => flat(item));
    expect(cards).toEqual([
      "PMS Nessuna fonte collegata Non configurato Collega fonte",
      "Channel Manager Nessuna fonte collegata Non configurato Collega fonte",
      "OTA Nessun dato canale disponibile Non configurato Configura fonte",
      "Contabilità Nessuna fonte collegata Non configurato Collega fonte",
      "Personale Nessuna fonte collegata Non configurato Collega fonte",
    ]);
    expect(
      screen.getByText(
        "Collega le fonti utilizzate dalla struttura per permettere a NINFA di analizzare prenotazioni, distribuzione, costi e personale.",
      ),
    ).not.toBeNull();
    expect(document.body.textContent).not.toMatch(/Mews|SiteMinder|Cloudbeds|TeamSystem|Booking\.com/u);
  });

  it("configured through a file: the method, the real last update and the actions", async () => {
    await renderBlock(laborViaCsv("2026-10-18T10:00:00Z"));

    expect(flat(cardOf("Personale"))).toBe(
      "Personale Import file Configurato Ultimo aggiornamento 18 ottobre 2026 Carica nuovo file Gestisci",
    );
    // the introduction is only for an empty section
    expect(screen.queryByText(/Collega le fonti utilizzate dalla struttura/u)).toBeNull();
  });

  it("a source that never completed an import is NOT shown as configured, and never as 'Mai importato'", async () => {
    await renderBlock(laborViaCsv(null));

    expect(flat(cardOf("Personale"))).toBe("Personale Nessuna fonte collegata Non configurato Collega fonte");
    expect(document.body.textContent).not.toMatch(/Mai importato|Configurato|Import file/u);
    expect(within(cardOf("Personale")).getByRole("button", { name: "Collega fonte Personale" })).not.toBeNull();
    expect(screen.getByText(/Collega le fonti utilizzate dalla struttura/u)).not.toBeNull(); // still an empty section
  });

  it("costs through invoices", async () => {
    await renderBlock(costsViaXml());

    expect(flat(cardOf("Contabilità"))).toContain("Import fatture XML");
    expect(flat(cardOf("Contabilità"))).toContain("Configurato");
  });

  it("OTA and Channel Manager are received through the bookings: no 'Collega fonte', a real link instead", async () => {
    await renderBlock(bookingsViaFile());

    const ota = cardOf("OTA");
    expect(flat(ota)).toBe(
      "OTA Booking.com · Expedia Già ricevuto Ricevuti tramite Prenotazioni importate Visualizza canali",
    );
    expect(within(ota).queryByText(/Collega fonte|Configura fonte/u)).toBeNull();
    expect(within(ota).getByRole("link", { name: "Visualizza canali" }).getAttribute("href")).toBe(
      "/dati?property=p1&tab=distribution",
    );
    const channelManager = cardOf("Channel Manager");
    expect(flat(channelManager)).toContain("Prenotazioni già ricevute");
    expect(within(channelManager).getByRole("link", { name: "Visualizza Channel Manager" }).getAttribute("href")).toBe(
      "/dati?property=p1&tab=bookings",
    );
    expect(flat(cardOf("PMS"))).toContain("Configurato");
  });

  it("renders an automatic connection when (and only when) the backend reports one", async () => {
    await renderBlock(channelManagerConnected());

    expect(flat(cardOf("Channel Manager"))).toBe(
      "Channel Manager Fixture Channel Manager Connesso Ultimo aggiornamento Oggi alle 11:31 Gestisci",
    );
    expect(flat(cardOf("OTA"))).toContain("Ricevuti tramite Channel Manager");
  });

  it("several sources of a kind: nothing to do here, so no menu and no button", async () => {
    await renderBlock(sources({ STAFF: { state: "CONFIGURED_FILE", several_sources: true, method: "CSV" } }));

    const staff = cardOf("Personale");
    expect(flat(staff)).toBe("Personale Più fonti configurate Configurato");
    expect(within(staff).queryByRole("button")).toBeNull();
  });
});

// --- "Collega fonte": a real dialog per card ----------------------------------------------------------------

describe("Fonti dati - 'Collega fonte' opens a real dialog for each card", () => {
  const cases: [string, string, string, RegExp][] = [
    ["PMS", "Collega il tuo PMS", "Indica da quale sistema NINFA riceverà i dati della struttura.", /Importa da file/u],
    [
      "Channel Manager",
      "Collega il tuo Channel Manager",
      "Se il tuo Channel Manager raccoglie già le prenotazioni provenienti da Booking.com, Expedia e altri portali, NINFA può utilizzare quella fonte senza richiedere collegamenti separati per ogni OTA.",
      /Importa da file/u,
    ],
    [
      "OTA",
      "Configura la fonte dei canali",
      "Normalmente NINFA riceve questi dati dal PMS o dal Channel Manager. Non è necessario collegare ogni portale separatamente se il tuo gestionale li raccoglie già.",
      /Importa da file/u,
    ],
    ["Contabilità", "Come vuoi fornire i dati dei costi?", "Scegli come NINFA riceverà le fatture e i costi della struttura.", /Importa fatture/u],
    ["Personale", "Come vuoi fornire i dati del personale?", "Scegli come NINFA riceverà le ore e i costi del personale.", /Importa da file/u],
  ];

  it.each(cases)("%s: title, plain explanation, the real option and 'Prossimamente'", async (name, title, intro, option) => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf(name)).getByRole("button", { name: /^(Collega|Configura) fonte/u }));

    const box = dialog();
    expect(within(box).getByRole("heading", { level: 2, name: title })).not.toBeNull();
    expect(within(box).getByText(intro)).not.toBeNull();
    expect(within(box).getByRole("heading", { level: 3, name: option })).not.toBeNull();
    expect(within(box).getByRole("button", { name: "Importa file" })).not.toBeNull();
    // automatic integrations: said plainly, not clickable, not named
    expect(within(box).getByText("Integrazioni automatiche")).not.toBeNull();
    expect(within(box).getByText("Prossimamente")).not.toBeNull();
    expect(within(box).queryByRole("button", { name: /Prossimamente|Integrazioni/u })).toBeNull();
    expect(box.textContent).not.toMatch(/Mews|SiteMinder|Cloudbeds|TeamSystem|API|webhook|token|endpoint|JSON/iu);
  });

  it("offers only what the backend says NINFA can really do", async () => {
    const user = userEvent.setup();
    await renderBlock(sources({}, { capabilities: [{ domain: "BOOKINGS", methods: ["CSV"] }] }));

    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Collega fonte Personale" }));

    expect(within(dialog()).queryByRole("button", { name: "Importa file" })).toBeNull();
    expect(within(dialog()).getByText("Questa modalità non è disponibile al momento.")).not.toBeNull();
  });

  it("closes with the close button and with Escape, handing the focus back to what opened it", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());
    const opener = within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" });

    await user.click(opener);
    expect(dialog()).not.toBeNull();
    await user.click(within(dialog()).getByRole("button", { name: "Chiudi" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);

    await user.click(opener);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("stops the page behind from scrolling while a dialog is open, and gives the scroll back", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());
    expect(document.body.style.overflow).toBe("");

    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" }));
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps the keyboard inside the dialog (Tab wraps around)", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());
    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" }));
    const box = dialog();
    const focusable = Array.from(box.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]"));
    const last = focusable[focusable.length - 1] as HTMLElement;

    last.focus();
    await user.tab();

    expect(box.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(focusable[0]);
  });
});

// --- setting up a source and importing a file ------------------------------------------------------------------

describe("Fonti dati - from 'Importa file' to the result", () => {
  it("opens the import of the right kind of data and creates nothing: no call at all is made", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" }));
    await user.click(within(dialog()).getByRole("button", { name: "Importa file" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Importa le prenotazioni" })).not.toBeNull();
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // only the first read: nothing changed, nothing re-read
    expect(previewImportMock).not.toHaveBeenCalled();
    expect(importFileMock).not.toHaveBeenCalled();
    expect(removeDataSourceMock).not.toHaveBeenCalled();
  });

  it("a configured card goes straight to the import of its kind of data", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv());

    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Carica nuovo file Personale" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Importa i dati del personale" })).not.toBeNull();
  });

  it("a Channel Manager or OTA import goes into the same bookings source: the hotelier links nothing twice", async () => {
    const user = userEvent.setup();
    await renderBlock(bookingsViaFile());

    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Carica nuovo file PMS" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Importa le prenotazioni" })).not.toBeNull();
    expect(importFileMock).not.toHaveBeenCalled();
  });

  it("an OTA that has nothing yet leads to the bookings import, the one source of its data", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf("OTA")).getByRole("button", { name: "Configura fonte OTA" }));
    await user.click(within(dialog()).getByRole("button", { name: "Importa file" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Importa le prenotazioni" })).not.toBeNull();
  });

  it("with several sources of a kind it refuses to pick one and says so", async () => {
    const user = userEvent.setup();
    await renderBlock(sources({ STAFF: { state: "CONFIGURED_FILE", several_sources: true, method: "CSV" } }));

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: /^Personale/u }));
    await user.click(within(dialog()).getByRole("button", { name: "Carica nuovo file" }));

    expect(within(dialog()).getAllByText("Hai già una fonte per questi dati.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("dialog", { name: "Importa i dati del personale" })).toBeNull();
  });

  it("costs take FatturaPA XML or a register: their own hint, no template, no labor date", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(costsViaXml());
    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Carica nuovo file Contabilità" }));

    const box = await screen.findByRole("dialog", { name: "Importa le fatture" });
    expect(
      within(box).getByText(
        "Carica le fatture elettroniche (XML) oppure il registro dei costi che hai già, in formato CSV o Excel (.xlsx).",
      ),
    ).not.toBeNull();
    expect(within(box).queryByRole("button", { name: /modello/iu })).toBeNull();
    expect(within(box).queryByText(/data di oggi/u)).toBeNull();

    await user.upload(within(box).getByLabelText("Seleziona file"), new File(["x"], "costi.txt"));
    expect(within(box).getByRole("alert").textContent).toBe(
      "Scegli un file XML, CSV o Excel (con estensione .xml, .csv o .xlsx).",
    );

    previewImportMock.mockResolvedValue(ok(previewOf({ method: "XML", rows_total: 1, sample_columns: [], sample_rows: [] })));
    await user.upload(within(box).getByLabelText("Seleziona file"), xmlFile());
    expect(await within(box).findByText("1 fattura trovata")).not.toBeNull();
  });

});

// --- the "..." menu ------------------------------------------------------------------------------------------

describe("Fonti dati - the '...' menu works and lists only usable actions", () => {
  it("opens, lists the actions of a configured source, closes on Escape and on a click outside", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv());
    const trigger = within(cardOf("Personale")).getByRole("button", { name: "Azioni per Personale" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    await user.click(trigger);

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("menu", { name: "Azioni per Personale" });
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Gestisci",
      "Carica nuovo file",
      "Rimuovi fonte",
    ]);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);

    await user.click(trigger);
    await user.click(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("moves with the arrow keys", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv());
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Azioni per Personale" }));
    const items = screen.getAllByRole("menuitem");

    expect(document.activeElement).toBe(items[0]);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(items[1]);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(document.activeElement).toBe(items[2]);
  });

  it("'Gestisci' opens the manage dialog; 'Carica nuovo file' opens the import; 'Rimuovi fonte' opens the confirmation", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv("2026-10-18T10:00:00Z"));
    const open = () => within(cardOf("Personale")).getByRole("button", { name: "Azioni per Personale" });

    await user.click(open());
    await user.click(screen.getByRole("menuitem", { name: "Gestisci" }));
    expect(screen.getByRole("dialog", { name: "Gestisci Personale" })).not.toBeNull();
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    await user.click(open());
    await user.click(screen.getByRole("menuitem", { name: "Carica nuovo file" }));
    expect(await screen.findByRole("dialog", { name: "Importa i dati del personale" })).not.toBeNull();
    await user.click(within(dialog()).getByRole("button", { name: "Chiudi" }));

    await user.click(open());
    await user.click(screen.getByRole("menuitem", { name: "Rimuovi fonte" }));
    expect(screen.getByRole("dialog", { name: "Rimuovere questa fonte?" })).not.toBeNull();
  });

  it("an unconfigured card's menu offers to connect it; a derived card's menu is a link", async () => {
    const user = userEvent.setup();
    await renderBlock(bookingsViaFile());
    await user.click(within(cardOf("OTA")).getByRole("button", { name: "Azioni per OTA" }));
    const item = screen.getByRole("menuitem", { name: "Visualizza canali" });
    expect(item.tagName).toBe("A");
    expect(item.getAttribute("href")).toBe("/dati?property=p1&tab=distribution");
  });

  it("an unconfigured card's menu opens the same dialog as its button", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Azioni per Contabilità" }));
    await user.click(screen.getByRole("menuitem", { name: "Collega fonte" }));

    expect(screen.getByRole("dialog", { name: "Come vuoi fornire i dati dei costi?" })).not.toBeNull();
  });
});

// --- managing and removing ---------------------------------------------------------------------------------------

describe("Fonti dati - 'Gestisci' and 'Rimuovi fonte'", () => {
  async function openManage() {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv("2026-10-18T10:00:00Z"));
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Gestisci Personale" }));
    return user;
  }

  it("shows how the data arrive and when they last did, with the ways to load a file or remove the source", async () => {
    await openManage();

    const box = screen.getByRole("dialog", { name: "Gestisci Personale" });
    expect(flat(box.querySelector("dl") as HTMLElement)).toBe(
      "Come arrivano i dati Import file Ultimo aggiornamento 18 ottobre 2026",
    );
    expect(within(box).getByRole("button", { name: "Carica nuovo file" })).not.toBeNull();
    expect(within(box).getByRole("button", { name: "Rimuovi fonte" })).not.toBeNull();
  });

  it("asks before removing and says exactly what happens: new data stop, the imported ones stay", async () => {
    const user = await openManage();

    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));

    const box = screen.getByRole("dialog", { name: "Rimuovere questa fonte?" });
    expect(
      within(box).getByText("NINFA non riceverà più nuovi dati da questa fonte. I dati già importati restano in NINFA."),
    ).not.toBeNull();
    expect(removeDataSourceMock).not.toHaveBeenCalled(); // asking is not removing

    await user.click(within(box).getByRole("button", { name: "Annulla" }));
    expect(removeDataSourceMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Rimuovere questa fonte?" })).toBeNull();
  });

  it("removes the source through the API, re-reads the cards and closes", async () => {
    const user = await openManage();
    removeDataSourceMock.mockResolvedValue(ok(undefined));
    getDataSourcesMock.mockResolvedValue(ok(nothingConfigured()));

    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(removeDataSourceMock).toHaveBeenCalledWith(PROPERTY_ID, "src-labor");
    await waitFor(() => expect(flat(cardOf("Personale"))).toContain("Non configurato"));
  });

  it("a source that is already gone ends the same way", async () => {
    const user = await openManage();
    removeDataSourceMock.mockResolvedValue(failure("DATA_SOURCE_NOT_FOUND", 404));
    getDataSourcesMock.mockResolvedValue(ok(nothingConfigured()));

    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a failure to remove is said plainly and the source is left as it was", async () => {
    const user = await openManage();
    removeDataSourceMock.mockResolvedValue(failure("INTERNAL_ERROR", 500));

    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: "Rimuovi fonte" }));

    expect(flat(await within(dialog()).findByRole("alert"))).toBe(
      "NINFA non è riuscita a leggere questa fonte. Riprova oppure carica un altro file.",
    );
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);
  });

  it("an automatic connection has no 'Rimuovi fonte' here (nothing to switch off yet)", async () => {
    const user = userEvent.setup();
    await renderBlock(channelManagerConnected());

    await user.click(within(cardOf("Channel Manager")).getByRole("button", { name: "Gestisci Channel Manager" }));

    expect(within(dialog()).queryByRole("button", { name: "Rimuovi fonte" })).toBeNull();
    expect(within(dialog()).queryByRole("button", { name: /Carica/u })).toBeNull();
  });
});

// --- "Collega una nuova fonte" -------------------------------------------------------------------------------------

describe("Fonti dati - 'Collega una nuova fonte'", () => {
  it("asks what data, then how, offering only real methods", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));

    const box = screen.getByRole("dialog", { name: "Collega una fonte dati" });
    expect(within(box).getByText("Quali dati vuoi collegare a NINFA?")).not.toBeNull();
    expect(within(box).getAllByRole("button").map((button) => flat(button)).slice(1)).toEqual([
      "Prenotazioni Le prenotazioni della struttura.",
      "Distribuzione I canali di vendita: Booking.com, Expedia e altri.",
      "Costi Le fatture e i costi della struttura.",
      "Personale Ore e costi del personale.",
    ]);

    await user.click(within(box).getByRole("button", { name: /^Costi/u }));
    const how = screen.getByRole("dialog", { name: "Costi" });
    expect(within(how).getByText("Come vuoi fornire questi dati?")).not.toBeNull();
    expect(within(how).getByRole("heading", { level: 3, name: "Importa fatture" })).not.toBeNull();
    expect(within(how).getByText("Prossimamente")).not.toBeNull();

    await user.click(within(how).getByRole("button", { name: "Indietro" }));
    expect(screen.getByRole("dialog", { name: "Collega una fonte dati" })).not.toBeNull();
  });

  it("Distribuzione explains that the channels come with the bookings and leads to the bookings file", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: /^Distribuzione/u }));

    expect(within(dialog()).getByText(/I canali di vendita arrivano insieme alle prenotazioni: non serve collegarli separatamente/u)).not.toBeNull();
    await user.click(within(dialog()).getByRole("button", { name: "Importa file" }));
    expect(await screen.findByRole("dialog", { name: "Importa le prenotazioni" })).not.toBeNull();
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // nothing was created, so nothing was re-read
  });

  it("for data that already have a source it offers a new file, not a second connection", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv());

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: /^Personale/u }));

    const box = screen.getByRole("dialog", { name: "Personale" });
    expect(within(box).getByText("Hai già una fonte per questi dati. Puoi caricare un nuovo file per aggiornarli.")).not.toBeNull();
    await user.click(within(box).getByRole("button", { name: "Carica nuovo file" }));
    expect(await screen.findByRole("dialog", { name: "Importa i dati del personale" })).not.toBeNull();
  });
});

// --- nothing technical, nothing invented ------------------------------------------------------------------------------

describe("Fonti dati - the hotelier never meets a technical word or a made-up integration", () => {
  it.each([
    ["nothing configured", nothingConfigured()],
    ["labor via csv", laborViaCsv()],
    ["costs via xml", costsViaXml()],
    ["bookings via file", bookingsViaFile()],
  ])("%s", async (_name, response) => {
    const user = userEvent.setup();
    await renderBlock(response);
    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/API key|webhook|endpoint|payload|\bJSON\b|token|database|schema|OAuth|credential/iu);
    expect(text).not.toMatch(/Mews|SiteMinder|Cloudbeds|TeamSystem|Fixture/u);
  });
});
