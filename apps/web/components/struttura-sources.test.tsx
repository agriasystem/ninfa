// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DataSourcesResponse } from "@ninfa/contracts";

import {
  bookingsViaFile,
  channelManagerConnected,
  costsViaXml,
  csvFile,
  failure,
  laborViaCsv,
  nothingConfigured,
  ok,
  PROPERTY_ID,
  previewOf,
  resultOf,
  sources,
  xmlFile,
} from "@/test/sources-support";

import { StrutturaSources } from "./struttura-sources";

const getDataSourcesMock = vi.fn();
const removeDataSourceMock = vi.fn();
const previewImportMock = vi.fn();
const importFileMock = vi.fn();
const downloadTemplateMock = vi.fn();
const saveBlobMock = vi.fn();

vi.mock("@/lib/api/data-sources", () => ({
  getDataSources: (...args: unknown[]) => getDataSourcesMock(...args),
  removeDataSource: (...args: unknown[]) => removeDataSourceMock(...args),
  previewImport: (...args: unknown[]) => previewImportMock(...args),
  importFile: (...args: unknown[]) => importFileMock(...args),
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
    downloadTemplateMock,
    saveBlobMock,
    onPropertyInvalid,
  ]) {
    mock.mockReset();
  }
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

  it("a failed re-read keeps the last cards and the dialog that is open on top of them", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(nothingConfigured());
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Collega fonte Personale" }));
    await user.click(within(dialog()).getByRole("button", { name: "Importa file" }));
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf()));
    getDataSourcesMock.mockResolvedValue(failure("INTERNAL_ERROR", 500)); // the re-read after the import

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));

    expect(await within(dialog()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    await waitFor(() => expect(getDataSourcesMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Non siamo riusciti a caricare le fonti dati.")).toBeNull();
    expect(cardOf("Personale")).not.toBeNull();
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
      "Personale Import CSV Configurato Ultimo aggiornamento 18 ottobre 2026 Carica nuovo file Gestisci",
    );
    // the introduction is only for an empty section
    expect(screen.queryByText(/Collega le fonti utilizzate dalla struttura/u)).toBeNull();
  });

  it("a source that never completed an import is NOT shown as configured, and never as 'Mai importato'", async () => {
    await renderBlock(laborViaCsv(null));

    expect(flat(cardOf("Personale"))).toBe("Personale Nessuna fonte collegata Non configurato Collega fonte");
    expect(document.body.textContent).not.toMatch(/Mai importato|Configurato|Import CSV/u);
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
    ["PMS", "Collega il tuo PMS", "Indica da quale sistema NINFA riceverà i dati della struttura.", /Importa tramite CSV/u],
    [
      "Channel Manager",
      "Collega il tuo Channel Manager",
      "Se il tuo Channel Manager raccoglie già le prenotazioni provenienti da Booking.com, Expedia e altri portali, NINFA può utilizzare quella fonte senza richiedere collegamenti separati per ogni OTA.",
      /Importa tramite CSV/u,
    ],
    [
      "OTA",
      "Configura la fonte dei canali",
      "Normalmente NINFA riceve questi dati dal PMS o dal Channel Manager. Non è necessario collegare ogni portale separatamente se il tuo gestionale li raccoglie già.",
      /Importa tramite CSV/u,
    ],
    ["Contabilità", "Come vuoi fornire i dati dei costi?", "Scegli come NINFA riceverà le fatture e i costi della struttura.", /Importa fatture/u],
    ["Personale", "Come vuoi fornire i dati del personale?", "Scegli come NINFA riceverà le ore e i costi del personale.", /Importa CSV/u],
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

  async function openLaborImport() {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(laborViaCsv());
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Carica nuovo file Personale" }));
    await screen.findByRole("heading", { level: 2, name: "Importa i dati del personale" });
    return user;
  }

  it("explains the format in plain words and dates a labor file with the property's today", async () => {
    await openLaborImport();

    const box = dialog();
    expect(within(box).getByText(/Utilizza il formato compatibile con NINFA/u)).not.toBeNull();
    expect(within(box).getByText(/I dati vengono registrati con la data di oggi \(\d{1,2} \w+ \d{4}\)/u)).not.toBeNull();
    expect(within(box).getByLabelText("Seleziona file")).not.toBeNull();
    expect(within(box).getByRole("button", { name: "Scarica modello CSV" })).not.toBeNull();
  });

  it("refuses a file of the wrong type without sending it anywhere", async () => {
    const user = await openLaborImport();

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), new File(["x"], "personale.xlsx"));

    expect(within(dialog()).getByRole("alert").textContent).toBe("Scegli un file con estensione .csv.");
    expect(previewImportMock).not.toHaveBeenCalled();
  });

  it("looks at the file, shows what it found and imports only after the user confirms", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(
      ok(previewOf({ unrecognized_columns: ["note"], already_imported: true })),
    );
    importFileMock.mockResolvedValue(ok(resultOf({ created: 2 })));
    getDataSourcesMock.mockResolvedValue(ok(laborViaCsv("2026-10-23T09:00:00Z")));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());

    expect(await within(dialog()).findByText("2 righe trovate")).not.toBeNull();
    const box = dialog();
    expect(previewImportMock).toHaveBeenCalledWith(PROPERTY_ID, "LABOR", expect.any(File));
    expect(importFileMock).not.toHaveBeenCalled(); // looking is not importing
    expect(within(box).getByText("File selezionato: personale.csv")).not.toBeNull();
    expect(within(box).getByText("Queste colonne non verranno utilizzate: note.")).not.toBeNull();
    expect(within(box).getByText("Questo file è già stato importato: caricarlo di nuovo non duplica i dati.")).not.toBeNull();
    expect(within(box).getByText(/I controlli sulle singole righe avvengono durante l'importazione/u)).not.toBeNull();
    expect(
      within(within(box).getByRole("region", { name: "Prime righe del file" })).getAllByText("HOUSEKEEPING", { selector: "td" }),
    ).toHaveLength(2);

    await user.click(within(box).getByRole("button", { name: "Conferma importazione" }));

    expect(await within(dialog()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    expect(importFileMock).toHaveBeenCalledTimes(1);
    const args = importFileMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args).toMatchObject({ propertyId: PROPERTY_ID, domain: "LABOR" });
    expect(args).not.toHaveProperty("dataSourceId");
    expect(args.snapshotLocalDate).toMatch(/^\d{4}-\d{2}-\d{2}$/u);
    expect(within(dialog()).getByText("Elementi: 2 nuovi.")).not.toBeNull();
    // the cards were re-read, so the new last update shows
    await waitFor(() => expect(getDataSourcesMock).toHaveBeenCalledTimes(2));
  });

  it("a bookings file is not dated by the page: no snapshot date is sent", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(bookingsViaFile());
    await user.click(within(cardOf("PMS")).getByRole("button", { name: "Carica nuovo file PMS" }));
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf()));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile("prenotazioni.csv"));
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));

    await waitFor(() => expect(importFileMock).toHaveBeenCalled());
    expect((importFileMock.mock.calls[0]?.[0] as Record<string, unknown>).snapshotLocalDate).toBeUndefined();
  });

  it("names the missing columns, offers the template and blocks the import", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(
      ok(
        previewOf({
          can_import: false,
          problem: "MISSING_COLUMNS",
          rows_total: 1,
          missing_columns: [["work_date"], ["actual_hours", "planned_hours"]],
          sample_rows: [],
        }),
      ),
    );

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());

    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("Il file non contiene alcune colonne richieste da NINFA.");
    expect(flat(alert)).toContain("work_date");
    expect(flat(alert)).toContain("actual_hours oppure planned_hours");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(within(dialog()).queryByRole("button", { name: "Conferma importazione" })).toBeNull();
    expect(within(dialog()).getByRole("button", { name: "Scarica modello CSV" })).not.toBeNull();
    expect(importFileMock).not.toHaveBeenCalled();
  });

  it.each([
    ["UNREADABLE_FILE", "NINFA non riesce a leggere questo file. Controlla che sia un CSV in formato UTF-8."],
    ["EMPTY_FILE", "Il file è vuoto."],
    ["NO_ROWS", "Il file contiene solo l'intestazione, senza righe di dati."],
    ["DUPLICATE_COLUMNS", "Il file ha colonne con lo stesso nome: rinomina o elimina quelle duplicate."],
  ] as const)("a file that cannot be used (%s) is explained in one plain sentence", async (problem, sentence) => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(ok(previewOf({ can_import: false, problem, rows_total: 0, sample_rows: [] })));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());

    expect(flat(await within(dialog()).findByRole("alert"))).toContain(sentence);
  });

  it("an import that fails tells why, says nothing was imported, and lets the user choose another file", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf({ succeeded: false, problem: "INVALID_ROWS", created: 0, rows_invalid: 1 })));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("Importazione non riuscita");
    expect(flat(alert)).toContain("Alcune righe del file non sono valide, quindi non è stato importato nulla.");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    // the cards are not re-read for a failure: nothing changed
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);

    await user.click(within(dialog()).getByRole("button", { name: "Scegli un altro file" }));
    expect(within(dialog()).getByLabelText("Seleziona file")).not.toBeNull();
  });

  it("an import that finds another import of the same data still running says to wait and try again", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValueOnce(failure("IMPORT_IN_PROGRESS", 409));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("È già in corso un altro import di questi dati. Attendi qualche istante e riprova.");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(document.body.textContent).not.toMatch(/409|IMPORT_IN_PROGRESS|NINFA non è riuscita a leggere/u);
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // nothing changed: the cards are not re-read

    // the user simply tries again, and this time it goes through
    await user.click(within(dialog()).getByRole("button", { name: "Scegli un altro file" }));
    importFileMock.mockResolvedValueOnce(ok(resultOf()));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));
    expect(await within(dialog()).findByText("Importazione completata")).not.toBeNull();
  });

  it("a same-day labor conflict says to upload the updated version tomorrow", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf({ succeeded: false, problem: "SAME_DAY_CONFLICT", created: 0 })));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));

    expect(flat(await within(dialog()).findByRole("alert"))).toContain(
      "Per oggi hai già caricato un file del personale diverso: carica la versione aggiornata domani.",
    );
  });

  it("a network or server error never shows technical text", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValue(failure("NETWORK_ERROR", 0));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());

    const alert = await within(dialog()).findByRole("alert");
    expect(flat(alert)).toContain("NINFA non è riuscita a leggere questa fonte. Riprova oppure utilizza un file CSV.");
    expect(document.body.textContent).not.toContain("technical message");
    expect(document.body.textContent).not.toMatch(/422|500|NETWORK_ERROR|validation error|connector failed/iu);
  });

  it("a file over the maximum and a source that disappeared each have their own sentence", async () => {
    const user = await openLaborImport();
    previewImportMock.mockResolvedValueOnce(failure("FILE_TOO_LARGE", 413));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    expect(flat(await within(dialog()).findByRole("alert"))).toContain("Il file è troppo grande.");

    await user.click(within(dialog()).getByRole("button", { name: "Scegli un altro file" }));
    previewImportMock.mockResolvedValueOnce(failure("PROPERTY_NOT_FOUND", 404));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    expect(flat(await within(dialog()).findByRole("alert"))).toContain(
      "Questa fonte non è più disponibile. Aggiorna la pagina.",
    );
  });

  it("downloads the CSV template through the backend", async () => {
    const user = await openLaborImport();
    const blob = new Blob(["work_date\r\n"], { type: "text/csv" });
    downloadTemplateMock.mockResolvedValue(blob);

    await user.click(within(dialog()).getByRole("button", { name: "Scarica modello CSV" }));

    await waitFor(() => expect(saveBlobMock).toHaveBeenCalledWith(blob, "modello-personale.csv"));
    expect(downloadTemplateMock).toHaveBeenCalledWith(PROPERTY_ID, "LABOR");
  });

  it("says so when the template cannot be fetched", async () => {
    const user = await openLaborImport();
    downloadTemplateMock.mockResolvedValue(null);

    await user.click(within(dialog()).getByRole("button", { name: "Scarica modello CSV" }));

    expect(await within(dialog()).findByText("Il modello non è disponibile al momento.")).not.toBeNull();
    expect(saveBlobMock).not.toHaveBeenCalled();
  });

  it("costs take FatturaPA XML only: its own hint, no template, no labor date", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(costsViaXml());
    await user.click(within(cardOf("Contabilità")).getByRole("button", { name: "Carica nuovo file Contabilità" }));

    const box = await screen.findByRole("dialog", { name: "Importa le fatture" });
    expect(within(box).getByText("Utilizza fatture elettroniche in formato XML (FatturaPA).")).not.toBeNull();
    expect(within(box).queryByRole("button", { name: /modello/iu })).toBeNull();
    expect(within(box).queryByText(/data di oggi/u)).toBeNull();

    await user.upload(within(box).getByLabelText("Seleziona file"), csvFile("costi.csv"));
    expect(within(box).getByRole("alert").textContent).toBe("Scegli un file con estensione .xml.");

    previewImportMock.mockResolvedValue(ok(previewOf({ method: "XML", rows_total: 1, sample_columns: [], sample_rows: [] })));
    await user.upload(within(box).getByLabelText("Seleziona file"), xmlFile());
    expect(await within(box).findByText("1 fattura trovata")).not.toBeNull();
  });

  it("cannot be dismissed while a file is being checked", async () => {
    const user = await openLaborImport();
    previewImportMock.mockReturnValue(new Promise(() => undefined));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());

    expect(await within(dialog()).findByText("Controllo del file in corso…")).not.toBeNull();
    expect((within(dialog()).getByRole("button", { name: "Chiudi" }) as HTMLButtonElement).disabled).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeNull();
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
      "Come arrivano i dati Import CSV Ultimo aggiornamento 18 ottobre 2026",
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
      "NINFA non è riuscita a leggere questa fonte. Riprova oppure utilizza un file CSV.",
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

// --- a source exists only after a SUCCESSFUL import --------------------------------------------------------------

describe("Fonti dati - a source exists only after a successful import", () => {
  const NOT_CONFIGURED_PERSONALE = "Personale Nessuna fonte collegata Non configurato Collega fonte";

  async function openStaffImport() {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(nothingConfigured());
    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Collega fonte Personale" }));
    await user.click(within(dialog()).getByRole("button", { name: "Importa file" }));
    await screen.findByRole("heading", { level: 2, name: "Importa i dati del personale" });
    return user;
  }

  it("1. opening the dialog without choosing a file writes nothing, and closing it leaves the card as it was", async () => {
    const user = await openStaffImport();

    expect(previewImportMock).not.toHaveBeenCalled();
    expect(importFileMock).not.toHaveBeenCalled();
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(flat(cardOf("Personale"))).toBe(NOT_CONFIGURED_PERSONALE);
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);
  });

  it("2. a file that was looked at but not confirmed configures nothing", async () => {
    const user = await openStaffImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    expect(await within(dialog()).findByRole("button", { name: "Conferma importazione" })).not.toBeNull();
    expect(previewImportMock).toHaveBeenCalledTimes(1);
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement); // the user walks away

    expect(importFileMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(flat(cardOf("Personale"))).toBe(NOT_CONFIGURED_PERSONALE);
    expect(document.body.textContent).not.toMatch(/Configurato|Mai importato/u);
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1); // no re-read: nothing changed
  });

  it("3. an import that fails configures nothing", async () => {
    const user = await openStaffImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf({ succeeded: false, problem: "INVALID_ROWS", created: 0, rows_invalid: 1 })));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));
    expect(flat(await within(dialog()).findByRole("alert"))).toContain("Non è stato importato nulla.");
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    expect(importFileMock).toHaveBeenCalledTimes(1);
    expect(flat(cardOf("Personale"))).toBe(NOT_CONFIGURED_PERSONALE);
    expect(document.body.textContent).not.toMatch(/Configurato|Mai importato/u);
    expect(getDataSourcesMock).toHaveBeenCalledTimes(1);
  });

  it("3b. a request that fails on the way configures nothing either", async () => {
    const user = await openStaffImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(failure("NETWORK_ERROR", 0));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));
    await within(dialog()).findByRole("alert");
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    expect(flat(cardOf("Personale"))).toBe(NOT_CONFIGURED_PERSONALE);
  });

  it("4. an import that succeeds configures the source: the cards are re-read and show the real update", async () => {
    const user = await openStaffImport();
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf({ created: 1 })));
    getDataSourcesMock.mockResolvedValue(ok(laborViaCsv("2026-10-18T10:00:00Z")));

    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));
    expect(await within(dialog()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    await waitFor(() => expect(getDataSourcesMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(flat(cardOf("Personale"))).toBe(
        "Personale Import CSV Configurato Ultimo aggiornamento 18 ottobre 2026 Carica nuovo file Gestisci",
      ),
    );
  });

  it("5. a later import goes into the same source: a configured card imports again and is re-read", async () => {
    const user = userEvent.setup({ applyAccept: false });
    await renderBlock(laborViaCsv("2026-10-18T10:00:00Z"));
    previewImportMock.mockResolvedValue(ok(previewOf()));
    importFileMock.mockResolvedValue(ok(resultOf({ created: 1 })));
    getDataSourcesMock.mockResolvedValue(ok(laborViaCsv("2026-10-23T09:00:00Z")));

    await user.click(within(cardOf("Personale")).getByRole("button", { name: "Carica nuovo file Personale" }));
    await user.upload(within(dialog()).getByLabelText("Seleziona file"), csvFile());
    await user.click(await within(dialog()).findByRole("button", { name: "Conferma importazione" }));
    await within(dialog()).findByRole("heading", { level: 3, name: "Importazione completata" });
    await user.click(within(dialog()).getAllByRole("button", { name: "Chiudi" })[0] as HTMLElement);

    // the SAME kind of data is sent; the page names no source and creates none
    expect(importFileMock).toHaveBeenCalledTimes(1);
    expect(importFileMock.mock.calls[0]?.[0]).toMatchObject({ propertyId: PROPERTY_ID, domain: "LABOR" });
    await waitFor(() => expect(flat(cardOf("Personale"))).toContain("Ultimo aggiornamento Oggi alle 11:00"));
    expect(screen.getAllByRole("listitem")).toHaveLength(5); // still five cards, no second one
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
