// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DataSourceDomain,
  FileInspectionResponse,
  RecentImport,
  SessionContextResponse,
  UnderstandAnswers,
} from "@ninfa/contracts";

import {
  csvFile,
  failure,
  matchedResultOf,
  ok,
  PROPERTY_ID,
  questionOf,
  realisticValidation,
  understoodInspection,
  xlsxFile,
} from "@/test/sources-support";

import { ImportaFileScreen } from "./importa-file-screen";

/**
 * The "Importa file" page, as the person lives it: the file is the only thing asked for; what it holds is the
 * engine's verdict, followed without a question when it points somewhere; only what the backend asks reaches the
 * screen. Every answer comes from a mocked backend - the page decides nothing about the data.
 */

const understandFileMock = vi.fn();
const validateImportMock = vi.fn();
const importMatchedFileMock = vi.fn();
const checkMappingMock = vi.fn();
const getRecentImportsMock = vi.fn();

vi.mock("@/lib/api/data-sources", () => ({
  understandFile: (...args: unknown[]) => understandFileMock(...args),
  validateImport: (...args: unknown[]) => validateImportMock(...args),
  importMatchedFile: (...args: unknown[]) => importMatchedFileMock(...args),
  checkMapping: (...args: unknown[]) => checkMappingMock(...args),
  getRecentImports: (...args: unknown[]) => getRecentImportsMock(...args),
}));

const refreshSessionMock = vi.fn();
let session: SessionContextResponse | null;

vi.mock("@/lib/session/session-context", () => ({
  useSession: () => ({
    status: session === null ? "unauthenticated" : "authenticated",
    session,
    refresh: refreshSessionMock,
    setSession: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function sessionWith(ids: string[]): SessionContextResponse {
  return {
    user: { id: "u1", email: "persona@example.com", display_name: "Persona" },
    workspaces: [
      {
        workspace_id: "w1",
        workspace_name: "Workspace",
        role: "MEMBER",
        properties: ids.map((id) => ({ id, name: `Hotel ${id}`, timezone: "Europe/Rome" })),
      },
    ],
  } as unknown as SessionContextResponse;
}

const panel = () => screen.getByRole("region", { name: "Importazione del file" });
const zone = () => panel().querySelector(".importa-drop") as HTMLElement;
const picker = () => within(panel()).getByLabelText("Seleziona un file CSV o Excel") as HTMLInputElement;

function renderScreen(props: Partial<Parameters<typeof ImportaFileScreen>[0]> = {}) {
  render(
    <ImportaFileScreen
      requestedPropertyId={PROPERTY_ID}
      onSelectProperty={vi.fn()}
      onNavigateToLogin={vi.fn()}
      {...props}
    />,
  );
  return userEvent.setup({ applyAccept: false });
}

/** A backend whose verdict is the same whichever kind the file is read as, as the real one's is. */
function documentThatIs(kind: DataSourceDomain, level: "HIGH" | "MEDIUM" = "HIGH") {
  understandFileMock.mockImplementation(({ domain }: { domain: DataSourceDomain }) =>
    Promise.resolve(
      ok(
        understoodInspection(
          { detection: { domain: kind, level, scores: [{ domain: kind, score: 0.8 }], expected: domain } },
          { domain },
        ),
      ),
    ),
  );
}

function documentThatPointsNowhere(inspection: Partial<FileInspectionResponse> = {}) {
  const scores: { domain: DataSourceDomain; score: number }[] = [
    { domain: "BOOKINGS", score: 0.2 },
    { domain: "LABOR", score: 0.1 },
    { domain: "COSTS", score: 0.05 },
  ];
  understandFileMock.mockImplementation(({ domain }: { domain: DataSourceDomain }) =>
    Promise.resolve(
      ok(
        understoodInspection(
          { level: "MANUAL", detection: { domain: null, level: "LOW", scores, expected: domain } },
          { domain, ...inspection },
        ),
      ),
    ),
  );
}

function dragEvent(files: File[]) {
  return { dataTransfer: { files, dropEffect: "none", types: ["Files"] } };
}

beforeEach(() => {
  for (const mock of [
    understandFileMock,
    validateImportMock,
    importMatchedFileMock,
    checkMappingMock,
    getRecentImportsMock,
    refreshSessionMock,
  ]) {
    mock.mockReset();
  }
  session = sessionWith([PROPERTY_ID]);
  getRecentImportsMock.mockResolvedValue(ok({ imports: [] }));
  checkMappingMock.mockResolvedValue(ok({ valid: true, missing: [], problems: [] }));
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-23T09:45:00Z"));
});

afterEach(() => vi.useRealTimers());

describe("the page", () => {
  it("lives under its own section of the sidebar, keeps the others, and says what it does", async () => {
    renderScreen();

    const nav = screen.getByRole("navigation", { name: "Navigazione principale" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Oggi",
      "Decisioni",
      "Dati",
      "Importa file",
      "Struttura",
    ]);
    const link = within(nav).getByRole("link", { name: "Importa file" });
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(link.getAttribute("href")).toBe(`/importa-file?property=${PROPERTY_ID}`);
    expect(screen.getByRole("heading", { level: 1, name: "Importa file" })).not.toBeNull();
    expect(
      screen.getByText("NINFA riconosce automaticamente il contenuto del file e prepara i dati per l'analisi."),
    ).not.toBeNull();
    await screen.findByText("Qui troverai i file che hai importato.");
  });

  it("the drop zone is the thing on the page: it asks for the file, and for nothing else", async () => {
    renderScreen();

    expect(flat(zone())).toBe("Trascina qui il tuo file oppure Selezionalo dal computer CSV o Excel (.xlsx), fino a 10 MB");
    expect(picker().type).toBe("file");
    expect(picker().accept).toContain(".csv");
    expect(picker().accept).toContain(".xlsx");
    expect(picker().accept).not.toContain(".xml");
    expect(within(panel()).queryByRole("combobox")).toBeNull();
    expect(within(panel()).queryByText(/Prenotazioni|Personale|Costi/u)).toBeNull();
    expect(understandFileMock).not.toHaveBeenCalled();
    await screen.findByText("Qui troverai i file che hai importato.");
  });

  it("switching property starts over: a file chosen for one never reaches another", async () => {
    session = sessionWith([PROPERTY_ID, "p2"]);
    understandFileMock.mockReturnValue(new Promise(() => undefined));
    const screenOf = (id: string) => (
      <ImportaFileScreen requestedPropertyId={id} onSelectProperty={vi.fn()} onNavigateToLogin={vi.fn()} />
    );
    const view = render(screenOf(PROPERTY_ID));
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(picker(), csvFile());
    await within(panel()).findByText("Sto leggendo il file…");

    view.rerender(screenOf("p2"));

    expect(picker()).not.toBeNull();
    expect(within(panel()).queryByText("Sto leggendo il file…")).toBeNull();
    expect(understandFileMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(getRecentImportsMock).toHaveBeenLastCalledWith("p2"));
    await screen.findByText("Qui troverai i file che hai importato.");
  });

  it("with no property shows the empty state, not the zone", () => {
    session = sessionWith([]);
    renderScreen({ requestedPropertyId: null });

    expect(screen.queryByRole("region", { name: "Importazione del file" })).toBeNull();
    expect(getRecentImportsMock).not.toHaveBeenCalled();
  });
});

describe("handing over the file", () => {
  it("the file picker sends the file to Smart Import", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), csvFile("prenotazioni.csv"));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect((understandFileMock.mock.calls[0]?.[0] as { file: File }).file.name).toBe("prenotazioni.csv");
  });

  it("dragging shows on the zone, crossing its children does not flicker, and leaving clears it", () => {
    renderScreen();
    const box = zone();
    expect(box.getAttribute("data-dragging")).toBe("false");

    fireEvent.dragEnter(box, dragEvent([csvFile()]));
    expect(box.getAttribute("data-dragging")).toBe("true");
    fireEvent.dragEnter(box.querySelector(".importa-drop__title") as HTMLElement, dragEvent([csvFile()]));
    fireEvent.dragLeave(box, dragEvent([csvFile()]));
    expect(box.getAttribute("data-dragging")).toBe("true");
    fireEvent.dragLeave(box, dragEvent([csvFile()]));
    expect(box.getAttribute("data-dragging")).toBe("false");
  });

  it("dropping a file reads it; dragging over allows the drop", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    renderScreen();

    fireEvent.dragEnter(zone(), dragEvent([xlsxFile("export.xlsx")]));
    const allowed = !fireEvent.dragOver(zone(), dragEvent([xlsxFile("export.xlsx")]));
    expect(allowed).toBe(true);
    fireEvent.drop(zone(), dragEvent([xlsxFile("export.xlsx")]));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect((understandFileMock.mock.calls[0]?.[0] as { file: File }).file.name).toBe("export.xlsx");
  });

  it("something dragged that is not a file changes nothing", () => {
    renderScreen();

    fireEvent.drop(zone(), dragEvent([]));

    expect(understandFileMock).not.toHaveBeenCalled();
    expect(within(panel()).queryByRole("alert")).toBeNull();
    expect(zone()).not.toBeNull();
  });

  it("a file dropped beside the zone does not make the browser leave the page", () => {
    renderScreen();

    expect(fireEvent.dragOver(window, dragEvent([csvFile()]))).toBe(false);
    expect(fireEvent.drop(window, dragEvent([csvFile()]))).toBe(false);
  });

  it.each([
    ["turni.pdf", "x", "Questo formato non è supportato: scegli un file CSV o Excel (.xlsx)."],
    ["vecchio.xls", "x", "Questo formato non è supportato: scegli un file CSV o Excel (.xlsx)."],
    ["fattura.xml", "x", "Le fatture elettroniche XML si importano da Struttura, in Fonti dati."],
    ["vuoto.csv", "", "Il file è vuoto: non c'è nulla da importare."],
  ])("refuses %s in the browser, in plain words, and sends nothing", async (name, content, sentence) => {
    const user = renderScreen();

    await user.upload(picker(), new File([content], name));

    expect(within(panel()).getByRole("alert").textContent).toContain(sentence);
    expect(understandFileMock).not.toHaveBeenCalled();
    expect(picker()).not.toBeNull(); // the zone stays: the person just tries again
  });

  it("accepts the extension whatever its case", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), new File(["x"], "EXPORT.XLSX"));

    await waitFor(() => expect(understandFileMock).toHaveBeenCalled());
  });

  it("refuses a file over the limit without reading it into memory", async () => {
    const user = renderScreen();
    const huge = new File(["x"], "enorme.csv");
    Object.defineProperty(huge, "size", { value: 10 * 1024 * 1024 + 1 });

    await user.upload(picker(), huge);

    expect(within(panel()).getByRole("alert").textContent).toContain("Il file supera i 10 MB");
    expect(understandFileMock).not.toHaveBeenCalled();
  });

  it("one file at a time", () => {
    renderScreen();

    fireEvent.drop(zone(), dragEvent([csvFile("a.csv"), csvFile("b.csv")]));

    expect(within(panel()).getByRole("alert").textContent).toBe("Trascina un file alla volta.");
    expect(understandFileMock).not.toHaveBeenCalled();
  });
});

describe("while NINFA reads", () => {
  it("says what it is really doing: no percentage, and a step is done only when its request has come back", async () => {
    let answerReading: (value: unknown) => void = () => undefined;
    let answerVerifying: (value: unknown) => void = () => undefined;
    understandFileMock.mockReturnValue(new Promise((resolve) => (answerReading = resolve)));
    validateImportMock.mockReturnValue(new Promise((resolve) => (answerVerifying = resolve)));
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    expect(within(panel()).getByRole("status").textContent).toContain("Sto leggendo il file…");
    expect(panel().getAttribute("aria-busy")).toBe("true");
    const steps = () =>
      within(panel())
        .getAllByRole("listitem")
        .map((item) => item.getAttribute("data-state"));
    expect(steps()).toEqual(["current", "pending"]);
    expect(panel().textContent).not.toMatch(/\d+\s?%/u);
    expect(panel().querySelector("[role='progressbar'], progress")).toBeNull();

    answerReading(ok(understoodInspection({}, { domain: "BOOKINGS" })));

    await within(panel()).findByText("Sto controllando tutte le righe…");
    expect(steps()).toEqual(["done", "current"]);

    answerVerifying(ok(realisticValidation()));
    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(panel().getAttribute("aria-busy")).toBe("false");
  });
});

describe("the kind of data is what the document says it is", () => {
  it("a document that says it is the first kind read needs one reading", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock).toHaveBeenCalledTimes(1);
    expect(validateImportMock.mock.calls[0]?.[0]).toMatchObject({ domain: "BOOKINGS" });
  });

  it.each(["LABOR", "COSTS"] as const)(
    "a document that says it is %s is read again as that, with no question and nothing to confirm",
    async (kind) => {
      documentThatIs(kind);
      validateImportMock.mockResolvedValue(ok(realisticValidation()));
      importMatchedFileMock.mockResolvedValue(ok(matchedResultOf()));
      const user = renderScreen();

      await user.upload(picker(), xlsxFile());

      const heading = await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
      expect(heading).not.toBeNull();
      expect(understandFileMock).toHaveBeenCalledTimes(2);
      expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ domain: kind, confirmedDomain: false, answers: {} });
      expect(validateImportMock.mock.calls[0]?.[0]).toMatchObject({ domain: kind });
      expect(within(panel()).queryByRole("combobox")).toBeNull();

      await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

      await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
      expect(importMatchedFileMock.mock.calls[0]?.[0]).toMatchObject({ propertyId: PROPERTY_ID, domain: kind });
    },
  );

  it("a verdict that only leads is followed too: the summary names the kind and only the button imports", async () => {
    documentThatIs("LABOR", "MEDIUM");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), xlsxFile());

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(flat(panel())).toContain("NINFA ha riconosciuto un file del personale");
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("a document that points nowhere is never read as a kind on its own: the person says, or chooses another file", async () => {
    documentThatPointsNowhere();
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), xlsxFile("listino.xlsx"));

    await within(panel()).findByRole("heading", {
      level: 3,
      name: "Non riesco a capire che tipo di dati contiene questo file",
    });
    expect(validateImportMock).not.toHaveBeenCalled();
    expect(within(panel()).getByRole("button", { name: "Scegli un altro file" })).not.toBeNull();
    expect(understandFileMock).toHaveBeenCalledTimes(1);

    // the kinds on offer are the ones the backend scored
    understandFileMock.mockResolvedValue(ok(understoodInspection({}, { domain: "COSTS" })));
    await user.click(within(panel()).getByRole("button", { name: "Costi" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ domain: "COSTS", confirmedDomain: true });
  });

  it("a document with no table at all has nothing to choose: it says so", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection(
          {
            level: "BLOCKED",
            detection: { domain: null, level: "LOW", scores: [], expected: "BOOKINGS" },
            blockers: [{ code: "NO_TABLE", groups: [] }],
          },
          { domain: "BOOKINGS", problem: "NO_ROWS", proposal: null },
        ),
      ),
    );
    const user = renderScreen();

    await user.upload(picker(), xlsxFile("regole.xlsx"));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Questo file non può essere importato così com'è");
    expect(flat(alert)).toContain("Non riesco a trovare una tabella di dati in questo file.");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(within(panel()).queryByRole("button", { name: "Costi" })).toBeNull();
  });

  it("a suggestion of the assistant is a question of the backend's: the person's answer is what counts", async () => {
    const choices = ["BOOKINGS", "LABOR", "COSTS"].map((value) => ({ value, count: null, sheets: [], columns: [] }));
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection(
          {
            level: "ASK",
            detection: { domain: null, level: "LOW", scores: [{ domain: "COSTS", score: 0.2 }], expected: "BOOKINGS" },
            questions: [questionOf("DOMAIN", { candidate: "COSTS", origin: "ASSISTANT", choices })],
          },
          { domain: "BOOKINGS" },
        ),
      ),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection({}, { domain: "LABOR" })));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), xlsxFile());

    await within(panel()).findByText("Questo sembra un file dei costi. Corretto?");
    expect(within(panel()).getByText("Suggerimento di NINFA, da controllare.")).not.toBeNull();
    expect(within(panel()).getByRole("button", { name: "Sì, è un file dei costi" })).not.toBeNull();
    expect(within(panel()).getByRole("button", { name: "No, è un file di prenotazioni" })).not.toBeNull();
    await user.click(within(panel()).getByRole("button", { name: "No, è un file del personale" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ domain: "LABOR", confirmedDomain: true });
  });

  it("a file that cannot be read at all is the same whatever it might have been", async () => {
    understandFileMock.mockResolvedValue(
      ok(understoodInspection({}, { domain: "BOOKINGS", problem: "UNREADABLE_FILE", understanding: null, proposal: null })),
    );
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("NINFA non riesce a leggere questo file.");
    expect(understandFileMock).toHaveBeenCalledTimes(1);
  });
});

describe("READY: if NINFA knows, NINFA goes on", () => {
  it("a summary and one button: no column, no percentage, no field name, no identifier", async () => {
    documentThatIs("LABOR");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), xlsxFile("turni.xlsx"));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    const text = flat(panel());
    expect(text).toContain("13 persone");
    expect(text).toContain("6 campi riconosciuti");
    expect(text).toContain("dal 26 ottobre 2026 al 1 novembre 2026");
    expect(text).toContain("I dati vengono registrati con la data di oggi (23 ottobre 2026)");
    expect(within(panel()).getAllByRole("button", { name: "Importa dati" })).toHaveLength(1);
    expect(within(panel()).queryByRole("combobox")).toBeNull();
    expect(within(panel()).queryByRole("table")).toBeNull();
    expect(text).not.toMatch(/work_date|planned_hours|source_record_id|READY|HIGH|0\.\d|%|\{|smart_import/u);
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("the file's rows that cannot be imported are explained, and the import is not offered", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(
      ok(
        realisticValidation({
          can_import: false,
          rows_invalid: 2,
          rows_valid: 50,
          row_problems: [{ field: "check_in", code: "INVALID_DATE", count: 2 }],
          invalid_rows: [{ row: 7, issues: [{ field: "check_in", code: "INVALID_DATE" }] }],
        }),
      ),
    );
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Alcune righe non possono essere importate");
    expect(flat(alert)).toContain("Data di arrivo: data non valida (2 righe)");
    expect(flat(alert)).toContain("Riga 7: Data di arrivo: data non valida");
    expect(within(panel()).queryByRole("button", { name: "Importa dati" })).toBeNull();
  });
});

describe("ASK: only what the engine asks", () => {
  it("one question from the backend, its answer carried back, and then the summary", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection({
          level: "ASK",
          questions: [questionOf("AMOUNT_BASIS", { column: "Importo" })],
        }),
      ),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    await user.upload(picker(), xlsxFile());

    expect(await within(panel()).findByText("Mi serve solo una conferma")).not.toBeNull();
    expect(within(panel()).getByText("L'importo della colonna «Importo» è al netto di IVA?")).not.toBeNull();
    expect(within(panel()).queryByRole("combobox")).toBeNull();
    await user.click(within(panel()).getByRole("button", { name: "Sì, è al netto di IVA" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { amount_basis: "NET" } });
  });

  it("says how many confirmations remain when the backend has more than one", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection({
          level: "ASK",
          questions: [questionOf("AMOUNT_BASIS", { column: "Importo" }), questionOf("DATE_ORDER", { column: "Data" })],
        }),
      ),
    );
    const user = renderScreen();

    await user.upload(picker(), xlsxFile());

    expect(await within(panel()).findByText("Mi servono 2 conferme")).not.toBeNull();
    // one at a time: the second is not on the screen yet
    expect(within(panel()).queryByText("Come sono scritte le date di questo file?")).toBeNull();
  });
});

describe("the import", () => {
  async function toTheSummary(kind: DataSourceDomain = "BOOKINGS") {
    documentThatIs(kind);
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();
    await user.upload(picker(), csvFile("prenotazioni.csv"));
    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    return user;
  }

  it("ends in a real summary, with Oggi as an offer and no navigation of its own", async () => {
    const user = await toTheSummary();
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ rows_total: 1284, created: 1280, unchanged: 4 })));
    getRecentImportsMock.mockResolvedValue(
      ok({ imports: [{ file_name: "prenotazioni.csv", domain: "BOOKINGS", status: "SUCCEEDED", at: "2026-10-23T09:40:00Z" }] }),
    );
    expect(getRecentImportsMock).toHaveBeenCalledTimes(1);

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    const text = flat(panel());
    expect(text).toContain("File prenotazioni.csv");
    expect(text).toContain("Tipo di dati Prenotazioni");
    expect(text).toContain("1.284 righe");
    expect(text).toContain("Elementi: 1280 nuovi, 4 già presenti.");
    expect(text).toContain("dal 26 ottobre 2026 al 1 novembre 2026");
    expect(text).toContain("I nuovi dati entreranno nella prossima analisi di NINFA.");
    expect(within(panel()).getByRole("link", { name: "Vai a Oggi" }).getAttribute("href")).toBe(
      `/oggi?property=${PROPERTY_ID}`,
    );
    await waitFor(() => expect(getRecentImportsMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("cell", { name: "prenotazioni.csv" })).not.toBeNull();

    await user.click(within(panel()).getByRole("button", { name: "Importa un altro file" }));
    expect(picker()).not.toBeNull();
    expect(document.activeElement).toBe(picker());
  });

  it("dates a staff file with the property's own day, and only a staff file", async () => {
    const user = await toTheSummary("LABOR");
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf()));

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    expect(importMatchedFileMock.mock.calls[0]?.[0]).toMatchObject({ domain: "LABOR", snapshotLocalDate: "2026-10-23" });
  });

  it("sends the file through the existing import, with the decision as the backend built it", async () => {
    const user = await toTheSummary();
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf()));
    const answers: UnderstandAnswers = {};

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    const args = importMatchedFileMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args.mapping).toEqual(understoodInspection().proposal);
    expect(args).not.toHaveProperty("dataSourceId");
    expect(understandFileMock.mock.calls[0]?.[0]).toMatchObject({ answers });
  });

  it("a request that fails while the whole file is tried says so plainly, and writes nothing", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(failure("INTERNAL_ERROR", 500));
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Importazione non riuscita");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(document.body.textContent).not.toMatch(/500|INTERNAL_ERROR|technical message/u);
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("a file the browser can no longer read is said in the same plain words", async () => {
    understandFileMock.mockResolvedValue(failure("FILE_NOT_READABLE", 0));
    const user = renderScreen();

    await user.upload(picker(), csvFile());

    expect(flat(await within(panel()).findByRole("alert"))).toContain("NINFA non riesce a leggere questo file.");
    expect(document.body.textContent).not.toContain("FILE_NOT_READABLE");
  });
});

describe("the keyboard", () => {
  it("reaches the picker, and goes on from what takes its place", async () => {
    documentThatIs("BOOKINGS");
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderScreen();

    expect(picker().tabIndex).toBe(0);
    await user.upload(picker(), csvFile());

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(document.activeElement).toBe(panel().querySelector(".importa-panel"));
  });
});

describe("looking again at how a source is read ('Modifica associazioni')", () => {
  it("goes to the columns of THAT kind of source, and nothing is applied on its own", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection({}, { domain: "LABOR" })));
    const user = renderScreen({ review: "LABOR" });

    expect(screen.getByText("Carica un file di questa fonte per rivedere come NINFA ne legge le colonne.")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Torna a Fonti dati" }).getAttribute("href")).toBe(
      `/struttura?property=${PROPERTY_ID}`,
    );
    await user.upload(picker(), xlsxFile());

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(understandFileMock).toHaveBeenCalledTimes(1);
    expect(understandFileMock.mock.calls[0]?.[0]).toMatchObject({ domain: "LABOR" });
    expect(validateImportMock).not.toHaveBeenCalled();
  });
});

describe("Importazioni recenti", () => {
  const imports: RecentImport[] = [
    { file_name: "prenotazioni-ottobre.xlsx", domain: "BOOKINGS", status: "SUCCEEDED", at: "2026-10-23T09:31:00Z" },
    { file_name: "turni.csv", domain: "LABOR", status: "FAILED", at: "2026-10-22T16:04:00Z" },
    { file_name: null, domain: "COSTS", status: "RUNNING", at: "2026-10-18T10:00:00Z" },
  ];

  it("shows what the backend recorded, in the property's time zone and in plain words", async () => {
    getRecentImportsMock.mockResolvedValue(ok({ imports }));
    renderScreen();

    const table = await screen.findByRole("table");
    expect(getRecentImportsMock).toHaveBeenCalledWith(PROPERTY_ID);
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "File",
      "Tipo",
      "Data",
      "Stato",
    ]);
    expect(within(table).getAllByRole("row").slice(1).map(flat)).toEqual([
      "prenotazioni-ottobre.xlsx Prenotazioni Oggi alle 11:31 Completata",
      "turni.csv Personale Ieri alle 18:04 Non riuscita",
      "File senza nome Costi 18 ottobre 2026 In corso",
    ]);
    expect(document.body.textContent).not.toMatch(/SUCCEEDED|FAILED|RUNNING|LABOR/u);
  });

  it("says when it is empty", async () => {
    renderScreen();

    expect(await screen.findByText("Qui troverai i file che hai importato.")).not.toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a failure does not get in the way of importing, says so, and can be retried", async () => {
    getRecentImportsMock.mockResolvedValueOnce(failure("INTERNAL_ERROR", 500));
    const user = renderScreen();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non siamo riusciti a caricare le importazioni recenti.");
    expect(picker()).not.toBeNull();
    getRecentImportsMock.mockResolvedValue(ok({ imports }));
    await user.click(within(alert).getByRole("button", { name: "Riprova" }));

    expect(await screen.findByRole("table")).not.toBeNull();
  });

  it("a session that has ended goes back through the session check", async () => {
    getRecentImportsMock.mockResolvedValue(failure("UNAUTHENTICATED", 401));
    renderScreen();

    await waitFor(() => expect(refreshSessionMock).toHaveBeenCalledTimes(1));
    expect(document.body.textContent).not.toMatch(/401|UNAUTHENTICATED/u);
  });
});

function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}

function flat(node: Node): string {
  return textOf(node).replace(/\s+/gu, " ").trim();
}
