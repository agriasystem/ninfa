// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  checkOf,
  csvFile,
  DEPARTMENT_CHOICES,
  laborInspection,
  matchedResultOf,
  ok,
  PROPERTY_ID,
  proposalOf,
  questionOf,
  realisticValidation,
  understoodInspection,
  validationOf,
  xlsxFile,
} from "@/test/sources-support";

import { ImportaFileFlow } from "./importa-file-flow";

/**
 * Smart Import V3 on the "Importa file" page: the person hands over a file and, almost always, sees what
 * NINFA found and ONE button. When something is really ambiguous there is ONE question, never a form. When the
 * file cannot be imported, it says why. Every decision - what the file is, what is missing, which question -
 * is the mocked backend's: the page only shows it and carries the answer back.
 */

const understandFileMock = vi.fn();
const checkMappingMock = vi.fn();
const validateImportMock = vi.fn();
const importMatchedFileMock = vi.fn();
const onImportedMock = vi.fn();

vi.mock("@/lib/api/data-sources", () => ({
  understandFile: (...args: unknown[]) => understandFileMock(...args),
  checkMapping: (...args: unknown[]) => checkMappingMock(...args),
  validateImport: (...args: unknown[]) => validateImportMock(...args),
  importMatchedFile: (...args: unknown[]) => importMatchedFileMock(...args),
  getImportLimits: () => Promise.resolve({ ok: false, status: 500, code: "NO_ANSWER", message: "" }),
}));

vi.mock("@/lib/api/analysis", () => ({
  getAnalysisStatus: () => Promise.resolve({ ok: false, status: 500, code: "NO_ANSWER", message: "" }),
  requestAnalysisRefresh: vi.fn(),
}));

function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}
const flat = (node: Node): string => textOf(node).replace(/\s+/gu, " ").trim();
const panel = () => screen.getByRole("region", { name: "Importazione del file" });

function renderFlow() {
  render(
    <ImportaFileFlow propertyId={PROPERTY_ID} timeZone="Europe/Rome" onImported={onImportedMock} onAccessLost={vi.fn()} />,
  );
  return userEvent.setup({ applyAccept: false });
}

async function pick(user: ReturnType<typeof userEvent.setup>, file: File) {
  await user.upload(within(panel()).getByLabelText("Seleziona un file CSV o Excel"), file);
}

beforeEach(() => {
  for (const mock of [understandFileMock, checkMappingMock, validateImportMock, importMatchedFileMock, onImportedMock]) {
    mock.mockReset();
  }
  checkMappingMock.mockResolvedValue(ok(checkOf()));
});

afterEach(() => vi.useRealTimers());

describe("a file NINFA understands by itself", () => {
  it("says what the file does not state and how NINFA reads it: one room per row, never hidden", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection({ assumed: ["rooms"] })));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();

    await pick(user, xlsxFile("prenotazioni.xlsx"));

    const box = panel();
    await within(box).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(flat(box)).toContain("Il file non dice quante camere ha ogni prenotazione: NINFA ne conta una per riga.");
    expect(within(box).getByRole("button", { name: "Importa dati" })).not.toBeNull();
    expect(flat(box)).not.toContain("Numero di camere");
  });

  it("says nothing about the rooms when the file counts them", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection({ assumed: [] })));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();

    await pick(user, xlsxFile("prenotazioni.xlsx"));

    const box = panel();
    await within(box).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(flat(box)).not.toContain("una per riga");
  });

  it("shows what it found and ONE button - no question, no matching table", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();

    await pick(user, xlsxFile("turni-ottobre.xlsx"));

    const box = panel();
    expect(await within(box).findByRole("heading", { level: 3, name: "File riconosciuto" })).not.toBeNull();
    const text = flat(box);
    expect(text).toContain("NINFA ha riconosciuto un file del personale");
    // the facts come from the backend (the rows that passed validation) and are written in Italian
    for (const fact of ["13 persone", "6 reparti", "410 ore previste", "420,5 ore effettive", "€6.304,60 di costo previsto"]) {
      expect(text).toContain(fact);
    }
    expect(text).toContain("dal 26 ottobre 2026 al 1 novembre 2026");
    expect(text).toContain("NINFA conta le persone ma non ne salva i nomi.");
    expect(text).toContain("Ho lasciato fuori 1 riga di totale.");
    expect(text).toContain("I totali del file tornano con le righe.");
    // one primary button; nothing to answer, nothing to match
    expect(within(box).getByRole("button", { name: "Importa dati" })).not.toBeNull();
    expect(within(box).queryAllByRole("combobox")).toHaveLength(0);
    expect(within(box).queryByText("Abbina le colonne del tuo file")).toBeNull();
    // the file was read as a whole document, with no answer given yet
    expect(understandFileMock).toHaveBeenCalledTimes(1);
    expect(understandFileMock.mock.calls[0]?.[0]).toMatchObject({
      propertyId: PROPERTY_ID,
      answers: {},
      confirmedDomain: false,
    });
  });

  it("imports with the proposal exactly as the backend built it, and remembers it", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ rows_total: 52, created: 52 })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await user.click(await within(panel()).findByRole("button", { name: "Importa dati" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    const args = importMatchedFileMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args.mapping).toEqual(proposalOf()); // the layout travels with it
    // ...and so does the reference of the understanding it comes from: the server verifies it
    expect(args.mapping).toMatchObject({ smart_import: { answers: {}, confirmed_domain: false } });
    expect(args.saveConfiguration).toBe(true);
    expect(args.snapshotLocalDate).toMatch(/^\d{4}-\d{2}-\d{2}$/u);
    expect(validateImportMock.mock.calls[0]?.[0]).toMatchObject({ mapping: proposalOf() });
  });

  it("explains itself on request: field, value and where each one comes from", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection({
          recognized: [
            { field: "role", origin: { kind: "COLUMN", detail: "Reparto o mansione" }, level: "HIGH", example: "Reception" },
            { field: "work_date", origin: { kind: "SHEET", detail: null }, level: "HIGH", example: null },
            { field: "planned_hours", origin: { kind: "ASSISTANT", detail: "Impegno" }, level: "MEDIUM", example: "8" },
            { field: "currency", origin: { kind: "PROPERTY", detail: null }, level: "HIGH", example: "EUR" },
          ],
        }),
      ),
    );
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());
    await user.click(await within(panel()).findByRole("button", { name: "Controlla cosa ho riconosciuto" }));

    const table = within(panel()).getByRole("region", { name: "Cosa ha riconosciuto NINFA" });
    const text = flat(table);
    for (const header of ["Campo", "Valore", "Origine"]) expect(text).toContain(header);
    expect(text).toContain("Reparto o mansione Reception colonna «Reparto o mansione»");
    expect(text).toContain("nome del foglio");
    expect(text).toContain("suggerito da NINFA, da controllare (colonna «Impegno»)");
    expect(text).toContain("impostazioni della struttura");
    expect(within(table).getAllByText("Da controllare")).toHaveLength(1); // only the suggested one
    expect(flat(panel())).toContain("Alcuni abbinamenti sono suggerimenti di NINFA");
    // a column that is only "da controllare" (not a suggestion of the assistant) does not say so
  });

  it("does not call a column to check a suggestion", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection({
          recognized: [
            { field: "role", origin: { kind: "COLUMN", detail: "Reparto" }, level: "MEDIUM", example: "Cucina" },
          ],
        }),
      ),
    );
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(flat(panel())).not.toContain("suggerimenti di NINFA");
  });

  it("says when a file is read as last time and then saves nothing new", async () => {
    understandFileMock.mockResolvedValue(
      ok(understoodInspection({}, { profile: { status: "RECOGNIZED", reason: null, mapping: proposalOf(), last_used_at: "2026-10-22T08:15:00Z", missing_columns: [] } })),
    );
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ configuration_saved: false })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    expect(await within(panel()).findByText(/come l'ultima volta/u)).not.toBeNull();
    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));
    await waitFor(() => expect(importMatchedFileMock).toHaveBeenCalledTimes(1));
    expect((importMatchedFileMock.mock.calls[0]?.[0] as { saveConfiguration: boolean }).saveConfiguration).toBe(false);
  });

  it("remembers by default what the person answered, even for a source it already knows", async () => {
    const confirmQuestion = questionOf("COLUMN_MEANING", {
      id: "CONFIRM:Ore A",
      column: "Ore A",
      field: "planned_hours",
      candidate: "planned_hours",
      choices: [{ value: "planned_hours", count: null, sheets: [], columns: [] }],
    });
    const known = { profile: { status: "RECOGNIZED" as const, reason: null, mapping: proposalOf(), last_used_at: "2026-10-22T08:15:00Z", missing_columns: [] } };
    understandFileMock
      .mockResolvedValueOnce(ok(understoodInspection({ level: "ASK", questions: [confirmQuestion] }, known)))
      .mockResolvedValue(ok(understoodInspection({}, known)));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ configuration_saved: true })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("La colonna «Ore A» è «Ore previste»?");
    await user.click(within(panel()).getByRole("button", { name: "Sì" }));
    await user.click(await within(panel()).findByRole("button", { name: "Importa dati" }));

    await waitFor(() => expect(importMatchedFileMock).toHaveBeenCalledTimes(1));
    expect((importMatchedFileMock.mock.calls[0]?.[0] as { saveConfiguration: boolean }).saveConfiguration).toBe(true);
  });

  it("offers no import when the backend says a row cannot be imported", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(
      ok(realisticValidation({ can_import: false, rows_invalid: 2, rows_valid: 50, row_problems: [{ field: "work_date", code: "INVALID_DATE", count: 2 }] })),
    );
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(within(panel()).queryByRole("button", { name: "Importa dati" })).toBeNull();
  });
});

describe("a file NINFA cannot import as it is", () => {
  it("says plainly that a weekly summary has no days, and imports nothing", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection({
          level: "BLOCKED",
          blockers: [{ code: "PERIOD_SUMMARY_ONLY", groups: [] }],
        }),
      ),
    );
    const user = renderFlow();

    await pick(user, xlsxFile("riepilogo.xlsx"));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain(
      "Questo file contiene un riepilogo settimanale. Per le analisi del personale NINFA ha bisogno del dettaglio giorno per giorno.",
    );
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(validateImportMock).not.toHaveBeenCalled();
    expect(importMatchedFileMock).not.toHaveBeenCalled();
    expect(within(panel()).queryByRole("button", { name: "Importa dati" })).toBeNull();
  });

  it("names what a file lacks, in the hotelier's words", async () => {
    understandFileMock.mockResolvedValue(
      ok(
        understoodInspection({
          level: "BLOCKED",
          blockers: [{ code: "MISSING_REQUIRED", groups: [["check_out"], ["planned_hours", "actual_hours"]] }],
        }),
      ),
    );
    const user = renderFlow();

    await pick(user, xlsxFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Nel file non ho trovato:");
    expect(flat(alert)).toContain("Data di partenza");
    expect(flat(alert)).toContain("Ore previste oppure Ore lavorate");
  });

});

describe("ONE question at a time", () => {
  it("asks which department the title talks about, and carries the answer back", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection({
          level: "ASK",
          questions: [
            questionOf("DEPARTMENT_CONFIRM", {
              candidate: "HOUSEKEEPING",
              choices: DEPARTMENT_CHOICES,
              labels: [{ label: "HOUSEKEEPING", count: 1 }],
            }),
          ],
        }),
      ),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile("turni-hk.xlsx"));

    const question = await within(panel()).findByRole("region", { name: /Il titolo del file parla di «Piani \(housekeeping\)»/u });
    expect(within(panel()).queryAllByRole("combobox")).toHaveLength(0); // never a form of dropdowns
    await user.click(within(question).getByRole("button", { name: "Sì, sono righe di Piani (housekeeping)" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" })).not.toBeNull();
    expect(understandFileMock).toHaveBeenCalledTimes(2);
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { department_from: "TITLE" } });
  });

  it("asks for a department when nothing in the file says it, with the departments as choices", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(understoodInspection({ level: "ASK", questions: [questionOf("DEPARTMENT_ROWS", { choices: DEPARTMENT_CHOICES })] })),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("A quale reparto appartengono le righe di questo file?");
    await user.click(within(panel()).getByRole("button", { name: "Reception" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { department_value: "FRONT_OFFICE" } });
  });

  it("asks about unknown words ONE word at a time and sends them all together", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection({
          level: "ASK",
          questions: [
            questionOf("VALUE_LABELS", {
              id: "LABELS:role_mapping",
              document: "role_mapping",
              choices: DEPARTMENT_CHOICES,
              labels: [
                { label: "HK", count: 3 },
                { label: "Turno A", count: 2 },
              ],
              total_labels: 2,
            }),
          ],
        }),
      ),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("Che reparto è «HK»? (3 righe)");
    expect(within(panel()).queryByText(/Turno A/u)).toBeNull(); // one word on screen at a time
    expect(flat(panel())).toContain("Ne resta 1");
    await user.click(within(panel()).getByRole("button", { name: "Piani (housekeeping)" }));
    await within(panel()).findByText("Che reparto è «Turno A»? (2 righe)");
    expect(understandFileMock).toHaveBeenCalledTimes(1); // not asked again between words
    await user.click(within(panel()).getByRole("button", { name: "Reception" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({
      answers: { labels: { role_mapping: { HK: "HOUSEKEEPING", "Turno A": "FRONT_OFFICE" } } },
    });
  });

  it("asks which week a grid is about with a date, and sends the day as chosen", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(understoodInspection({ level: "ASK", questions: [questionOf("PERIOD")] })),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("A quale settimana si riferisce il file?");
    const confirm = within(panel()).getByRole("button", { name: "Conferma la settimana" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    const date = within(panel()).getByLabelText("Un giorno qualsiasi della settimana");
    await user.type(date, "2026-10-28");
    await user.click(confirm);

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { period_start: "2026-10-28" } });
  });

  it("tells two tables with the same columns apart by the line above each", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection({
          level: "ASK",
          questions: [
            questionOf("TABLE", {
              choices: [
                { value: "Foglio1#3", count: 5, sheets: ["Foglio1"], columns: ["Data", "Reparto"], title: "Turni mattina", first_row: 3 },
                { value: "Foglio1#11", count: 5, sheets: ["Foglio1"], columns: ["Data", "Reparto"], title: "Turni sera", first_row: 11 },
              ],
            }),
          ],
        }),
      ),
    );
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("Ho trovato più di una tabella nel file. Quale devo leggere?");
    const evening = within(panel()).getByRole("button", { name: /«Turni sera»/u });
    expect(evening.textContent).toContain("dalla riga 11");
    await user.click(evening);

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { table_key: "Foglio1#11" } });
  });

  it("confirms a column it is only fairly sure about, or opens the matching on request", async () => {
    const confirmQuestion = questionOf("COLUMN_MEANING", {
      id: "CONFIRM:Codice",
      column: "Codice",
      field: "source_record_id",
      candidate: "source_record_id",
      choices: [{ value: "source_record_id", count: null, sheets: [], columns: [] }],
    });
    understandFileMock.mockResolvedValue(ok(understoodInspection({ level: "ASK", questions: [confirmQuestion] })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("La colonna «Codice» è «Numero della prenotazione»?");
    await user.click(within(panel()).getByRole("button", { name: "No, controllo le colonne" }));

    // the classic matching, starting from NINFA's proposal (the layout is kept)
    expect(await within(panel()).findByText("Abbina le colonne del tuo file")).not.toBeNull();
    expect(checkMappingMock.mock.calls[0]?.[2]).toMatchObject({ layout: { version: 1 } });
  });

  it("hands the decision to the person with no reference to the server's reading when they match by hand", async () => {
    const confirmQuestion = questionOf("COLUMN_MEANING", {
      id: "CONFIRM:Codice",
      column: "Codice",
      field: "source_record_id",
      candidate: "source_record_id",
      choices: [{ value: "source_record_id", count: null, sheets: [], columns: [] }],
    });
    understandFileMock.mockResolvedValue(ok(understoodInspection({ level: "ASK", questions: [confirmQuestion] })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("La colonna «Codice» è «Numero della prenotazione»?");
    await user.click(within(panel()).getByRole("button", { name: "No, controllo le colonne" }));

    // the classic matching works on a copy of the proposal that the person now owns: a matching built by
    // hand is judged on its merits, and the reference the server put on ITS decision is not part of it
    expect(await within(panel()).findByText("Abbina le colonne del tuo file")).not.toBeNull();
    expect(checkMappingMock.mock.calls[0]?.[2]).toMatchObject({ smart_import: null });
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("says that the arrival and the departure look swapped, and opens the matching to look", async () => {
    const swapped = questionOf("DATES_REVERSED", {
      id: "DATES_REVERSED",
      column: "Arrivo",
      choices: [{ value: "Partenza", count: null, sheets: [], columns: [] }],
    });
    understandFileMock.mockResolvedValue(ok(understoodInspection({ level: "ASK", questions: [swapped] })));
    const user = renderFlow();
    await pick(user, xlsxFile());

    await within(panel()).findByText("Le colonne «Arrivo» e «Partenza» sembrano invertite. Vuoi controllarle?");
    expect(flat(panel())).toContain("NINFA non le scambia da sola");
    await user.click(within(panel()).getByRole("button", { name: "Controlla le colonne" }));

    expect(await within(panel()).findByText("Abbina le colonne del tuo file")).not.toBeNull();
    expect(understandFileMock).toHaveBeenCalledTimes(1); // nothing was swapped or answered for the person
  });

  it("asks whether an amount is net of VAT, and a 'no' ends in the plain explanation", async () => {
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection(
          { level: "ASK", questions: [questionOf("AMOUNT_BASIS", { column: "Importo", choices: ["NET", "GROSS"].map((value) => ({ value, count: null, sheets: [], columns: [] })) })] },
          { domain: "COSTS" },
        ),
      ),
    );
    understandFileMock.mockResolvedValueOnce(
      ok(understoodInspection({ level: "BLOCKED", blockers: [{ code: "AMOUNT_NOT_NET", groups: [] }] }, { domain: "COSTS" })),
    );
    const user = renderFlow();

    await pick(user, xlsxFile("registro.xlsx"));
    await within(panel()).findByText("L'importo della colonna «Importo» è al netto di IVA?");
    await user.click(within(panel()).getByRole("button", { name: "No, comprende l'IVA" }));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("L'importo comprende l'IVA.");
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ domain: "COSTS", answers: { amount_basis: "GROSS" } });
  });
});

describe("a file that leaves out something NINFA holds", () => {
  const scopeChoices = ["FULL", "PARTIAL", "DELTA"].map((value) => ({ value, count: null, sheets: [], columns: [] }));
  const asked = (domain: "BOOKINGS" | "LABOR", absent: number) =>
    ok(
      understoodInspection(
        { level: "ASK", questions: [questionOf("FILE_SCOPE", { absent_records: absent, choices: scopeChoices })] },
        { domain },
      ),
    );

  it("asks once what the file is, in plain words, and carries the answer to the import", async () => {
    understandFileMock.mockResolvedValueOnce(asked("BOOKINGS", 3));
    understandFileMock.mockResolvedValueOnce(
      ok(
        understoodInspection(
          { removes: 3 },
          {
            domain: "BOOKINGS",
            proposal: proposalOf({ file_scope: "FULL" }),
            profile: { status: "RECOGNIZED", reason: null, mapping: proposalOf(), last_used_at: "2026-10-22T08:15:00Z", missing_columns: [] },
          },
        ),
      ),
    );
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ created: 0, updated: 2, removed: 3 })));
    const user = renderFlow();

    await pick(user, xlsxFile("prenotazioni.xlsx"));

    const question = await within(panel()).findByText(
      "Questo file contiene tutte le prenotazioni del periodo oppure soltanto quelle nuove o modificate?",
    );
    expect(question).not.toBeNull();
    const text = flat(panel());
    expect(text).toContain("In NINFA ci sono 3 prenotazioni di questo periodo che in questo file non compaiono.");
    expect(text).toContain("NINFA lo ricorderà per i prossimi file fatti così.");
    for (const technical of ["FULL", "PARTIAL", "DELTA", "snapshot", "tombstone", "scope"]) {
      expect(text).not.toContain(technical);
    }
    expect(validateImportMock).not.toHaveBeenCalled(); // nothing is tried before the person answers

    await user.click(within(panel()).getByRole("button", { name: "Tutte le prenotazioni del periodo" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { file_scope: "FULL" } });
    // said BEFORE anything is imported, and that the history stays
    expect(flat(panel())).toContain(
      "3 prenotazioni che in questo file non compaiono non saranno più contate. Restano nello storico di NINFA.",
    );

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    const sent = importMatchedFileMock.mock.calls[0]?.[0] as {
      mapping: { file_scope: string };
      saveConfiguration: boolean;
    };
    expect(sent.mapping.file_scope).toBe("FULL");
    expect(sent.saveConfiguration).toBe(true); // an answer about a source NINFA knows is worth remembering
    expect(flat(panel())).toContain("3 non più nel file");
  });

  it("speaks of departments for a staff file, and a file that is a part of it takes nothing away", async () => {
    understandFileMock.mockResolvedValueOnce(asked("LABOR", 7));
    understandFileMock.mockResolvedValueOnce(
      ok(understoodInspection({}, { domain: "LABOR", proposal: proposalOf({ file_scope: "PARTIAL" }) })),
    );
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();

    await pick(user, xlsxFile("turni.xlsx"));

    await within(panel()).findByText("Questo file contiene tutti i reparti del periodo oppure solo alcuni?");
    expect(flat(panel())).toContain("In NINFA ci sono 7 giornate di reparto di questo periodo");

    await user.click(within(panel()).getByRole("button", { name: "Solo alcuni reparti" }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { file_scope: "PARTIAL" } });
    expect(flat(panel())).not.toContain("non saranno più contate");
  });

  it.each([
    ["Solo una parte (per esempio un canale)", "PARTIAL"],
    ["Solo quelle nuove o modificate", "DELTA"],
  ])("«%s» is sent as it is", async (label, value) => {
    understandFileMock.mockResolvedValueOnce(asked("BOOKINGS", 1));
    understandFileMock.mockResolvedValueOnce(ok(understoodInspection({}, { domain: "BOOKINGS" })));
    validateImportMock.mockResolvedValue(ok(realisticValidation()));
    const user = renderFlow();

    await pick(user, xlsxFile("prenotazioni.xlsx"));
    await within(panel()).findByText("In NINFA c'è 1 prenotazione di questo periodo che in questo file non compare.");
    await user.click(within(panel()).getByRole("button", { name: label }));

    await within(panel()).findByRole("heading", { level: 3, name: "File riconosciuto" });
    expect(understandFileMock.mock.calls[1]?.[0]).toMatchObject({ answers: { file_scope: value } });
  });
});

describe("when NINFA is not sure enough", () => {
  it("says so first, shows no column, and opens the matching only if the person asks", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection({ level: "MANUAL" })));
    const user = renderFlow();

    await pick(user, xlsxFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Non posso importare questo file da sola");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(within(panel()).queryByRole("combobox")).toBeNull();
    expect(within(panel()).queryByText("Abbina le colonne del tuo file")).toBeNull();
    expect(validateImportMock).not.toHaveBeenCalled();

    await user.click(within(panel()).getByRole("button", { name: "Abbina le colonne" }));

    expect(await within(panel()).findByText("Abbina le colonne del tuo file")).not.toBeNull();
    expect(flat(panel())).toContain("NINFA ha letto il file ma non è sicura di tutto.");
    expect(validateImportMock).not.toHaveBeenCalled();
  });

  it("names what the file lacks in the same plain words, and lets the person choose another file", async () => {
    understandFileMock.mockResolvedValue(
      ok(understoodInspection({ level: "MANUAL", blockers: [{ code: "MISSING_REQUIRED", groups: [["check_in"]] }] })),
    );
    const user = renderFlow();

    await pick(user, xlsxFile());

    expect(flat(await within(panel()).findByRole("alert"))).toContain("Nel file non ho trovato: Data di arrivo");
    await user.click(within(panel()).getByRole("button", { name: "Scegli un altro file" }));
    expect(within(panel()).getByLabelText("Seleziona un file CSV o Excel")).not.toBeNull();
  });

  it("falls back to the matching when dates must still be chosen", async () => {
    understandFileMock.mockResolvedValue(ok(understoodInspection()));
    validateImportMock.mockResolvedValue(
      ok(
        validationOf({
          status: "NEEDS_CHOICE",
          can_import: false,
          format_hints: [{ question: "DATE_ORDER", proven: null, columns: ["Data"] }],
        }),
      ),
    );
    const user = renderFlow();

    await pick(user, xlsxFile());

    await user.click(await within(panel()).findByRole("button", { name: "Abbina le colonne" }));
    expect(await within(panel()).findByText("Come sono scritte le date?")).not.toBeNull();
  });

  it("falls back to the classic flow when the backend sends no understanding at all", async () => {
    understandFileMock.mockResolvedValue(ok(laborInspection()));
    const user = renderFlow();

    await pick(user, csvFile("turni.csv"));

    expect(await within(panel()).findByText("Abbina le colonne del tuo file")).not.toBeNull();
  });
});
