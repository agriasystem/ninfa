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
  resultOf,
  savedConfigurationOf,
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
const getRememberedAnswersMock = vi.fn();
const correctRememberedAnswerMock = vi.fn();
const forgetRememberedAnswerMock = vi.fn();
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
  getRememberedAnswers: (...args: unknown[]) => getRememberedAnswersMock(...args),
  correctRememberedAnswer: (...args: unknown[]) => correctRememberedAnswerMock(...args),
  forgetRememberedAnswer: (...args: unknown[]) => forgetRememberedAnswerMock(...args),
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
    getRememberedAnswersMock,
    correctRememberedAnswerMock,
    forgetRememberedAnswerMock,
    downloadTemplateMock,
    saveBlobMock,
    onPropertyInvalid,
  ]) {
    mock.mockReset();
  }
  // a source with no saved configuration: the manage dialog simply has nothing to show
  getImportConfigurationMock.mockResolvedValue(failure("DATA_SOURCE_NOT_FOUND", 404));
  getRememberedAnswersMock.mockResolvedValue(ok({ words: [], files: [] }));
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
    ["Contabilità", "Come vuoi fornire i dati dei costi?", "Scegli come NINFA riceverà le fatture e i costi della struttura.", /Registro dei costi/u],
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
    // a file comes in through its own page: here it is a link, never an uploader
    expect(within(box).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(
      `/importa-file?property=${PROPERTY_ID}`,
    );
    expect(box.querySelector("input[type='file']")).toBeNull();
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

    expect(within(dialog()).queryByRole("link", { name: "Importa un file" })).toBeNull();
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

describe("Fonti dati - a file comes in through the 'Importa file' page", () => {
  const importPage = `/importa-file?property=${PROPERTY_ID}`;

  it("says where a file goes from the block itself, and leaves the block's own work where it was", async () => {
    await renderBlock(nothingConfigured());

    expect(screen.getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(importPage);
    expect(screen.getByRole("button", { name: "Collega una nuova fonte" })).not.toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });

  it("'Collega fonte' leads to the page and creates nothing: no call at all is made", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" }));

    expect(within(dialog()).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(importPage);
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // only the first read: nothing changed, nothing re-read
    expect(previewImportMock).not.toHaveBeenCalled();
    expect(importFileMock).not.toHaveBeenCalled();
    expect(removeDataSourceMock).not.toHaveBeenCalled();
  });

  it("a configured card's 'Carica nuovo file' is a link to the page, not a dialog", async () => {
    await renderBlock(laborViaCsv());

    const link = within(cardOf("Personale")).getByRole("link", { name: "Carica nuovo file Personale" });

    expect(link.getAttribute("href")).toBe(importPage);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("an OTA that has nothing yet leads to the same page: its data come with the bookings", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());

    await user.click(within(cardOf("OTA")).getByRole("button", { name: "Configura fonte OTA" }));

    expect(within(dialog()).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(importPage);
  });

  it("with several sources of a kind it offers no file and says so", async () => {
    const user = userEvent.setup();
    await renderBlock(sources({ STAFF: { state: "CONFIGURED_FILE", several_sources: true, method: "CSV" } }));

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: /^Personale/u }));

    expect(within(dialog()).getByRole("alert").textContent).toBe("Hai già una fonte per questi dati.");
    expect(within(dialog()).queryByRole("link", { name: "Importa un file" })).toBeNull();
  });

  it("downloads the template of NINFA's own format for whoever wants it", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Collega fonte Personale" }));
    const blob = new Blob(["work_date\r\n"], { type: "text/csv" });
    downloadTemplateMock.mockResolvedValue(blob);

    await user.click(within(dialog()).getByRole("button", { name: "Scarica modello CSV" }));

    await waitFor(() => expect(saveBlobMock).toHaveBeenCalledWith(blob, "modello-personale.csv"));
    expect(downloadTemplateMock).toHaveBeenCalledWith(PROPERTY_ID, "LABOR");
  });

  it("says so when the template cannot be fetched", async () => {
    const user = userEvent.setup();
    await renderBlock(nothingConfigured());
    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Collega fonte PMS" }));
    downloadTemplateMock.mockResolvedValue(null);

    await user.click(within(dialog()).getByRole("button", { name: "Scarica modello CSV" }));

    expect(await within(dialog()).findByText("Il modello non è disponibile al momento.")).not.toBeNull();
    expect(saveBlobMock).not.toHaveBeenCalled();
  });
});

describe("Fonti dati - an invoice (XML), the one file that page does not read", () => {
  async function openInvoiceImport(response: DataSourcesResponse = costsViaXml()) {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(response);
    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Carica nuovo file Contabilità" }));
    await user.click(within(dialog()).getByRole("button", { name: "Importa fatture XML" }));
    await screen.findByRole("dialog", { name: "Importa le fatture" });
    return user;
  }
  const pickInvoice = (user: ReturnType<typeof userEvent.setup>, file: File) =>
    user.upload(within(dialog()).getByLabelText("Seleziona file"), file);

  it("Contabilità offers both: the invoice here, the register on the page", async () => {
    const user = userEvent.setup();
    await renderBlock(costsViaXml());

    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Carica nuovo file Contabilità" }));

    const box = screen.getByRole("dialog", { name: "Come vuoi fornire i dati dei costi?" });
    expect(within(box).getByRole("heading", { level: 3, name: "Fatture elettroniche" })).not.toBeNull();
    expect(within(box).getByRole("button", { name: "Importa fatture XML" })).not.toBeNull();
    expect(within(box).getByRole("heading", { level: 3, name: "Registro dei costi" })).not.toBeNull();
    expect(within(box).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(
      `/importa-file?property=${PROPERTY_ID}`,
    );
    expect(within(box).queryByRole("button", { name: /modello/iu })).toBeNull();
  });

  it("'Gestisci' of Contabilità leads to the same choice: an invoice here, a register on the page", async () => {
    const user = userEvent.setup();
    await renderBlock(costsViaXml());
    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Gestisci Contabilità" }));

    await user.click(within(dialog()).getByRole("button", { name: "Carica nuovo file" }));

    expect(screen.getByRole("dialog", { name: "Come vuoi fornire i dati dei costi?" })).not.toBeNull();
  });

  it("takes an XML and nothing else: a spreadsheet is sent to the page, with no call", async () => {
    const user = await openInvoiceImport();
    const box = dialog();
    expect(within(box).getByText(/Carica una fattura elettronica in formato XML/u)).not.toBeNull();
    expect((within(box).getByLabelText("Seleziona file") as HTMLInputElement).accept).toBe(".xml,text/xml,application/xml");

    await pickInvoice(user, new File(["x"], "registro.xlsx"));

    expect(within(box).getByRole("alert").textContent).toBe("Scegli un file XML di fattura elettronica (con estensione .xml).");
    expect(previewImportMock).not.toHaveBeenCalled();
  });

  it("looks at the invoice, imports it only on confirmation, and re-reads the cards", async () => {
    const user = await openInvoiceImport();
    previewImportMock.mockResolvedValue(ok(previewOf({ method: "XML", rows_total: 1, sample_columns: [], sample_rows: [] })));
    importFileMock.mockResolvedValue(ok(resultOf({ rows_total: 1, created: 1 })));

    await pickInvoice(user, xmlFile());

    expect(await within(dialog()).findByText("1 fattura trovata")).not.toBeNull();
    expect(previewImportMock).toHaveBeenCalledWith(PROPERTY_ID, "COSTS", expect.any(File));
    expect(importFileMock).not.toHaveBeenCalled();

    await user.click(within(dialog()).getByRole("button", { name: "Conferma importazione" }));

    expect(await within(dialog()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    expect(importFileMock.mock.calls[0]?.[0]).toMatchObject({ propertyId: PROPERTY_ID, domain: "COSTS" });
    await waitFor(() => expect(getDataSourcesMock).toHaveBeenCalledTimes(2));
  });

  it("an invoice NINFA cannot read says why, and imports nothing", async () => {
    const user = await openInvoiceImport();
    previewImportMock.mockResolvedValue(ok(previewOf({ method: "XML", can_import: false, problem: "UNSUPPORTED_FORMAT" })));

    await pickInvoice(user, xmlFile());

    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("Questa fattura non è in un formato che NINFA sa leggere.");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(within(dialog()).queryByRole("button", { name: "Conferma importazione" })).toBeNull();
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);
  });

  it("a request that fails says so plainly, and the dialog cannot be dismissed while it is out", async () => {
    const user = await openInvoiceImport();
    let answer: (value: unknown) => void = () => undefined;
    previewImportMock.mockReturnValue(new Promise((resolve) => (answer = resolve)));

    await pickInvoice(user, xmlFile());

    expect(await within(dialog()).findByText("Controllo del file in corso…")).not.toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeNull();

    answer(failure("NETWORK_ERROR", 0));
    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("Importazione non riuscita");
    expect(document.body.textContent).not.toMatch(/NETWORK_ERROR|technical message/u);
  });
});

// --- "Gestisci": what NINFA remembers from the person's answers ---------------------------------------------------------------

describe("Gestisci > Risposte ricordate", () => {
  const MODIFICATA = {
    id: "w-1",
    document: "status_mapping",
    field: "status",
    label: "modificata",
    value: "NO_SHOW",
    choices: ["CONFIRMED", "CANCELLED", "NO_SHOW", "CHECKED_IN", "CHECKED_OUT"],
  };
  const PMS_EXPORT = {
    id: "f-1",
    columns: ["giorno", "ore a", "ore b"],
    answers: { date_order: "DMY" },
    file_scope: "PARTIAL",
    column_decisions: 2,
  };

  async function openManage(words: unknown[] = [MODIFICATA], files: unknown[] = []) {
    getRememberedAnswersMock.mockResolvedValue(ok({ words, files }));
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(bookingsViaFile());
    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Gestisci PMS" }));
    return user;
  }
  const section = () => screen.findByRole("region", { name: "Risposte ricordate" });

  it("says what is remembered in the hotelier's words, reading the source it is open on", async () => {
    await openManage();

    const shown = await section();
    expect(getRememberedAnswersMock).toHaveBeenCalledWith(PROPERTY_ID, "src-bookings");
    expect(flat(shown)).toContain("Stato «modificata» → Non presentato");
    expect(flat(shown)).not.toMatch(/NO_SHOW|status_mapping|family|famiglia/u);
    expect(within(shown).getByRole("button", { name: "Correggi" })).not.toBeNull();
    expect(within(shown).getByRole("button", { name: "Dimentica" })).not.toBeNull();
  });

  it("with nothing remembered the section is not there", async () => {
    await openManage([]);

    await waitFor(() => expect(getRememberedAnswersMock).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Risposte ricordate" })).toBeNull();
  });

  it("forgetting asks first, then the answer is gone and the page says what happens next", async () => {
    const user = await openManage();
    forgetRememberedAnswerMock.mockResolvedValue(ok({ words: [], files: [] }));
    const shown = await section();

    await user.click(within(shown).getByRole("button", { name: "Dimentica" }));
    expect(forgetRememberedAnswerMock).not.toHaveBeenCalled();
    await user.click(within(shown).getByRole("button", { name: "Dimentica questa risposta" }));

    await waitFor(() =>
      expect(forgetRememberedAnswerMock).toHaveBeenCalledWith(PROPERTY_ID, "src-bookings", "w-1"),
    );
    const note = await within(shown).findByRole("status");
    expect(flat(note)).toContain("al prossimo file NINFA te la chiederà di nuovo");
    expect(flat(note)).toContain("I dati già importati non cambiano");
    expect(flat(shown)).not.toContain("modificata");
  });

  it("forgetting can be called off", async () => {
    const user = await openManage();
    const shown = await section();

    await user.click(within(shown).getByRole("button", { name: "Dimentica" }));
    await user.click(within(shown).getByRole("button", { name: "Annulla" }));

    expect(forgetRememberedAnswerMock).not.toHaveBeenCalled();
    expect(flat(shown)).toContain("modificata");
  });

  it("correcting offers only what the backend allows, in plain words, and saves the choice", async () => {
    const user = await openManage();
    correctRememberedAnswerMock.mockResolvedValue(
      ok({ words: [{ ...MODIFICATA, value: "CONFIRMED" }], files: [] }),
    );
    const shown = await section();

    await user.click(within(shown).getByRole("button", { name: "Correggi" }));
    const select = within(shown).getByLabelText<HTMLSelectElement>("Che cosa significa");
    expect(Array.from(select.options).map((option) => option.text)).toEqual([
      "Confermata",
      "Cancellata",
      "Non presentato (risposta attuale)",
      "Arrivato",
      "Partito",
    ]);
    await user.selectOptions(select, "CONFIRMED");
    await user.click(within(shown).getByRole("button", { name: "Salva correzione" }));

    await waitFor(() =>
      expect(correctRememberedAnswerMock).toHaveBeenCalledWith(
        PROPERTY_ID,
        "src-bookings",
        "w-1",
        "CONFIRMED",
      ),
    );
    expect(flat(await section())).toContain("Stato «modificata» → Confermata");
    expect(flat(await within(shown).findByRole("status"))).toContain("vale dal prossimo file");
  });

  it("a word with no list can only be forgotten", async () => {
    await openManage([{ ...MODIFICATA, field: "channel", document: "channel_mapping", value: "OTA", choices: [] }]);
    const shown = await section();

    expect(within(shown).queryByRole("button", { name: "Correggi" })).toBeNull();
    expect(within(shown).getByRole("button", { name: "Dimentica" })).not.toBeNull();
  });

  it("a kind of file is said by its columns, with what was said about it, and can only be forgotten", async () => {
    const user = await openManage([], [PMS_EXPORT]);
    forgetRememberedAnswerMock.mockResolvedValue(ok({ words: [], files: [] }));
    const shown = await section();

    const text = flat(shown);
    expect(text).toContain("File con le colonne: giorno, ore a, ore b");
    expect(text).toContain("Date scritte giorno/mese/anno");
    expect(text).toContain("Il file contiene solo una parte del periodo");
    expect(text).toContain("2 colonne abbinate da te");
    expect(within(shown).queryByRole("button", { name: "Correggi" })).toBeNull();

    await user.click(within(shown).getByRole("button", { name: "Dimentica" }));
    await user.click(within(shown).getByRole("button", { name: "Dimentica questa risposta" }));

    await waitFor(() =>
      expect(forgetRememberedAnswerMock).toHaveBeenCalledWith(PROPERTY_ID, "src-bookings", "f-1"),
    );
  });

  it("a request that fails says so and keeps the answer", async () => {
    const user = await openManage();
    forgetRememberedAnswerMock.mockResolvedValue(failure("X", 500));
    const shown = await section();

    await user.click(within(shown).getByRole("button", { name: "Dimentica" }));
    await user.click(within(shown).getByRole("button", { name: "Dimentica questa risposta" }));

    expect(await within(shown).findByRole("alert")).not.toBeNull();
    expect(flat(shown)).toContain("modificata");
  });

  it("an answer that cannot be read is said, and the rest of the dialog works", async () => {
    getRememberedAnswersMock.mockResolvedValue(failure("X", 500));
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(bookingsViaFile());
    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Gestisci PMS" }));

    expect(await screen.findByText("Non siamo riusciti a leggere le risposte ricordate.")).not.toBeNull();
    expect(within(dialog()).getByRole("link", { name: "Carica nuovo file" })).not.toBeNull();
  });
});

// --- "Gestisci": the saved configuration ------------------------------------------------------------------------------------

describe("Gestisci > Configurazione import", () => {
  async function openManage(response: DataSourcesResponse = laborViaCsv("2026-10-18T10:00:00Z")) {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(response);
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Gestisci Personale" }));
    return user;
  }

  it("shows what each column of the file means, the last use, and the ways to change or forget it", async () => {
    getImportConfigurationMock.mockResolvedValue(ok(savedConfigurationOf()));
    await openManage();

    const section = await screen.findByRole("region", { name: "Configurazione import" });
    expect(getImportConfigurationMock).toHaveBeenCalledWith(PROPERTY_ID, "src-labor");
    expect(within(section).getByText("Come NINFA legge i file di questa fonte.")).not.toBeNull();
    expect(within(section).getAllByRole("listitem").map(flat)).toEqual([
      "Giorno → Data",
      "Ore turno → Ore previste",
      "Reparto → Reparto o mansione",
    ]);
    expect(within(section).getByText(/Ultimo utilizzo: 22 ottobre 2026/u)).not.toBeNull();
    expect(within(section).getByRole("link", { name: "Modifica associazioni" })).not.toBeNull();
    expect(within(section).getByRole("button", { name: "Dimentica configurazione" })).not.toBeNull();
    expect(within(section).queryByText(/regole di NINFA diverse/u)).toBeNull();
  });

  it("shows a fixed value in the hotelier's words", async () => {
    getImportConfigurationMock.mockResolvedValue(
      ok(savedConfigurationOf({ constants: [{ field: "labor_category", value: "KITCHEN" }] })),
    );
    await openManage();

    const section = await screen.findByRole("region", { name: "Configurazione import" });
    expect(flat(section)).toContain("Reparto (nome standard di NINFA): sempre Cucina");
  });

  it("says when a configuration was made for other rules of NINFA", async () => {
    getImportConfigurationMock.mockResolvedValue(ok(savedConfigurationOf({ schema_current: false })));
    await openManage();

    const section = await screen.findByRole("region", { name: "Configurazione import" });
    expect(
      within(section).getByText("Questa configurazione è stata salvata con regole di NINFA diverse: al prossimo file controlla di nuovo le colonne."),
    ).not.toBeNull();
  });

  it("with nothing saved says so, and offers no change", async () => {
    await openManage();

    const section = await screen.findByRole("region", { name: "Configurazione import" });
    expect(
      await within(section).findByText("Nessuna configurazione salvata: al prossimo file potrai abbinare le colonne e salvarle."),
    ).not.toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("if the configuration cannot be loaded it says so and the rest of the dialog still works", async () => {
    getImportConfigurationMock.mockResolvedValue(failure("INTERNAL_ERROR", 500));
    await openManage();

    expect(await screen.findByText("Non siamo riusciti a caricare la configurazione.")).not.toBeNull();
    expect(within(dialog()).getByRole("link", { name: "Carica nuovo file" })).not.toBeNull();
    expect(document.body.textContent).not.toContain("technical message");
  });

  it("invoices (XML) have no columns to match, so no configuration is asked for", async () => {
    const user = userEvent.setup();
    await renderBlock({ ...nothingConfigured(), cards: nothingConfigured().cards.map((item) => item.card === "ACCOUNTING" ? { ...item, state: "CONFIGURED_FILE" as const, data_source_id: "src-costs", method: "XML" as const, last_update_at: "2026-10-22T16:04:00Z" } : item) });

    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Gestisci Contabilità" }));

    expect(screen.queryByRole("region", { name: "Configurazione import" })).toBeNull();
    expect(getImportConfigurationMock).not.toHaveBeenCalled();
  });

  it("forgetting asks first, says what stays, and then forgets: the source and its data are untouched", async () => {
    getImportConfigurationMock.mockResolvedValue(ok(savedConfigurationOf()));
    forgetImportConfigurationMock.mockResolvedValue(ok(undefined));
    const user = await openManage();
    await user.click(await screen.findByRole("button", { name: "Dimentica configurazione" }));

    const box = screen.getByRole("dialog", { name: "Dimenticare la configurazione?" });
    expect(
      within(box).getByText(/I dati già importati restano in NINFA\./u),
    ).not.toBeNull();
    expect(forgetImportConfigurationMock).not.toHaveBeenCalled(); // asking is not forgetting
    await user.click(within(box).getByRole("button", { name: "Annulla" }));
    expect(forgetImportConfigurationMock).not.toHaveBeenCalled();

    await user.click(await screen.findByRole("button", { name: "Dimentica configurazione" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dimentica configurazione" }));

    expect(await screen.findByText("Configurazione dimenticata. I dati già importati sono rimasti in NINFA.")).not.toBeNull();
    expect(forgetImportConfigurationMock).toHaveBeenCalledWith(PROPERTY_ID, "src-labor");
    expect(removeDataSourceMock).not.toHaveBeenCalled();
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // the source is still there: nothing to re-read
  });

  it("a failure to forget is said plainly and the configuration stays", async () => {
    getImportConfigurationMock.mockResolvedValue(ok(savedConfigurationOf()));
    forgetImportConfigurationMock.mockResolvedValue(failure("INTERNAL_ERROR", 500));
    const user = await openManage();
    await user.click(await screen.findByRole("button", { name: "Dimentica configurazione" }));

    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dimentica configurazione" }));

    expect(flat(await within(screen.getByRole("dialog")).findByRole("alert"))).toContain("NINFA non è riuscita a leggere questa fonte.");
    expect(document.body.textContent).not.toContain("technical message");
  });

  it("'Modifica associazioni' leads to the page, on the columns of this kind of source", async () => {
    getImportConfigurationMock.mockResolvedValue(ok(savedConfigurationOf()));
    await openManage();

    const link = await screen.findByRole("link", { name: "Modifica associazioni" });

    expect(link.getAttribute("href")).toBe(`/importa-file?property=${PROPERTY_ID}&review=LABOR`);
    expect(dialog().querySelector("input[type='file']")).toBeNull();
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

  it("'Gestisci' opens the manage dialog; 'Carica nuovo file' is a link to the page; 'Rimuovi fonte' opens the confirmation", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv("2026-10-18T10:00:00Z"));
    const open = () => within(cardOf("Personale")).getByRole("button", { name: "Azioni per Personale" });

    await user.click(open());
    await user.click(screen.getByRole("menuitem", { name: "Gestisci" }));
    expect(screen.getByRole("dialog", { name: "Gestisci Personale" })).not.toBeNull();
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    await user.click(open());
    const upload = screen.getByRole("menuitem", { name: "Carica nuovo file" });
    expect(upload.tagName).toBe("A");
    expect(upload.getAttribute("href")).toBe(`/importa-file?property=${PROPERTY_ID}`);
    await user.keyboard("{Escape}");

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
    expect(within(box).getByRole("link", { name: "Carica nuovo file" }).getAttribute("href")).toBe(
      `/importa-file?property=${PROPERTY_ID}`,
    );
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
    expect(within(dialog()).queryByRole("link", { name: /Carica/u })).toBeNull();
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
    expect(within(how).getByRole("heading", { level: 3, name: "Fatture elettroniche" })).not.toBeNull();
    expect(within(how).getByRole("heading", { level: 3, name: "Registro dei costi" })).not.toBeNull();
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
    expect(within(dialog()).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(
      `/importa-file?property=${PROPERTY_ID}`,
    );
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // nothing was created, so nothing was re-read
  });

  it("for data that already have a source it offers a new file, not a second connection", async () => {
    const user = userEvent.setup();
    await renderBlock(laborViaCsv());

    await user.click(screen.getByRole("button", { name: "Collega una nuova fonte" }));
    await user.click(within(dialog()).getByRole("button", { name: /^Personale/u }));

    const box = screen.getByRole("dialog", { name: "Personale" });
    expect(within(box).getByText("Hai già una fonte per questi dati. Puoi caricare un nuovo file per aggiornarli.")).not.toBeNull();
    expect(within(box).getByRole("link", { name: "Importa un file" }).getAttribute("href")).toBe(
      `/importa-file?property=${PROPERTY_ID}`,
    );
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
