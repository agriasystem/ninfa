// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportMapping } from "@ninfa/contracts";

import {
  bookingsInspection,
  canonicalInspection,
  checkOf,
  csvFile,
  failure,
  laborInspection,
  laborInspectionWithoutTeam,
  matchedResultOf,
  ok,
  PROPERTY_ID,
  recognizedInspection,
  unknownInspection,
  validationOf,
  xlsxFile,
} from "@/test/sources-support";

import { ImportaFileFlow } from "./importa-file-flow";

/**
 * "Abbina le colonne" on the "Importa file" page: the hotel's own CSV / Excel file, from the file to the result -
 * the way the person lives it when they match the columns themselves. Every answer comes from a mocked backend:
 * what a column probably means, what is still missing, how the whole file reads, what the import did. The page
 * decides none of it.
 */

const inspectFileMock = vi.fn();
const checkMappingMock = vi.fn();
const validateImportMock = vi.fn();
const importMatchedFileMock = vi.fn();
const onImportedMock = vi.fn();
const onAccessLostMock = vi.fn();

vi.mock("@/lib/api/data-sources", () => ({
  inspectFile: (...args: unknown[]) => inspectFileMock(...args),
  // Smart Import V3: the page asks NINFA to understand the document. These tests describe the classic
  // matching, so the mocked backend answers with a plain inspection - no `understanding` - and the page
  // falls back to matching the columns, exactly as before.
  understandFile: (args: { propertyId: string; domain: string; file: File; answers: { sheet_name?: string | null } }) =>
    inspectFileMock(args.propertyId, args.domain, args.file, args.answers.sheet_name ?? undefined),
  checkMapping: (...args: unknown[]) => checkMappingMock(...args),
  validateImport: (...args: unknown[]) => validateImportMock(...args),
  importMatchedFile: (...args: unknown[]) => importMatchedFileMock(...args),
}));

function textOf(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(textOf).join(" ");
}
const flat = (node: Node): string => textOf(node).replace(/\s+/gu, " ").trim();

const panel = () => screen.getByRole("region", { name: "Importazione del file" });

const meaningOf = (header: string) => within(panel()).getByLabelText(`Cosa significa la colonna ${header}`) as HTMLSelectElement;

function renderFlow() {
  render(
    <ImportaFileFlow
      propertyId={PROPERTY_ID}
      timeZone="Europe/Rome"
      onImported={onImportedMock}
      onAccessLost={onAccessLostMock}
    />,
  );
  return userEvent.setup({ applyAccept: false });
}

async function pick(user: ReturnType<typeof userEvent.setup>, file: File) {
  await user.upload(within(panel()).getByLabelText("Seleziona un file CSV o Excel"), file);
}

/** The backend's rule for the staff file: a team (column or fixed value) is what is still missing. */
function checkLikeTheBackend(_property: string, _domain: string, decision: ImportMapping) {
  const hasTeam =
    decision.columns.some((column) => column.field === "role" || column.field === "labor_category") ||
    "labor_category" in decision.constants;
  return Promise.resolve(
    ok(hasTeam ? checkOf() : checkOf({ valid: false, missing: [["labor_category", "role"]] })),
  );
}

beforeEach(() => {
  for (const mock of [
    inspectFileMock,
    checkMappingMock,
    validateImportMock,
    importMatchedFileMock,
    onImportedMock,
    onAccessLostMock,
  ]) {
    mock.mockReset();
  }
  checkMappingMock.mockImplementation(checkLikeTheBackend);
  // "Oggi" is always the same day: the date of the page never depends on the real clock
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-23T09:45:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

// --- "Abbina le colonne" ----------------------------------------------------------------------------------------

describe("Abbina le colonne: the staff file of the brief", () => {
  async function openMapping() {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspectionWithoutTeam()));
    await pick(user, csvFile("turni-settimana-43.csv"));
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });
    return user;
  }

  it("shows each column with examples and the meaning NINFA proposes, to confirm or correct", async () => {
    await openMapping();

    const box = panel();
    expect(within(box).getByText("File selezionato: turni-settimana-43.csv")).not.toBeNull();
    expect(
      within(box).getByText("NINFA ha analizzato le colonne del file. Controlla gli abbinamenti prima di continuare."),
    ).not.toBeNull();
    const table = within(box).getByRole("region", { name: "Colonne del file" });
    expect(within(table).getAllByRole("columnheader").map(flat)).toEqual([
      "Colonna nel tuo file",
      "Esempio",
      "Significato per NINFA",
    ]);
    expect(within(table).getByText("26/10/2026 · 27/10/2026")).not.toBeNull();
    expect(meaningOf("Giorno").value).toBe("work_date");
    expect(meaningOf("Ore turno").value).toBe("planned_hours");
    expect(flat(within(table).getByRole("row", { name: /^Giorno/u }))).toContain("Riconosciuto");
    // every meaning is in the hotelier's words, plus "Ignora questa colonna"
    const options = Array.from(meaningOf("Giorno").options).map((option) => option.textContent);
    expect(options).toEqual([
      "Ignora questa colonna",
      "Data",
      "Reparto o mansione",
      "Reparto (nome standard di NINFA)",
      "Ore previste",
      "Ore lavorate",
      "Costo previsto",
      "Costo effettivo",
      "Valuta",
    ]);
  });

  it("never offers a person's name or an hourly rate as anything: they can only be ignored", async () => {
    await openMapping();

    expect(meaningOf("Nome dipendente").disabled).toBe(true);
    expect(meaningOf("Nome dipendente").value).toBe("");
    expect(within(panel()).getByText("NINFA non importa i nomi delle persone.")).not.toBeNull();
    expect(meaningOf("Costo orario").disabled).toBe(true);
    expect(within(panel()).getByText("NINFA non utilizza il costo orario.")).not.toBeNull();
  });

  it("asks the backend what is still missing, shows it, and keeps 'Continua' disabled until it is enough", async () => {
    await openMapping();

    expect(await within(panel()).findByText("Manca ancora 1 informazione necessaria:")).not.toBeNull();
    expect(within(panel()).getByText("Reparto (nome standard di NINFA) oppure Reparto o mansione")).not.toBeNull();
    expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(true);
    expect(checkMappingMock).toHaveBeenCalled();
    expect(checkMappingMock.mock.calls[0]?.slice(0, 2)).toEqual([PROPERTY_ID, "LABOR"]);
    expect(validateImportMock).not.toHaveBeenCalled(); // nothing is tried until the person goes on
  });

  it("offers the same value for every row where the file has no column, and that completes the matching", async () => {
    const user = await openMapping();
    await within(panel()).findByText("Manca ancora 1 informazione necessaria:");

    expect(within(panel()).getByText("Se il file non ha una colonna per questa informazione")).not.toBeNull();
    const fixed = within(panel()).getByLabelText(/Reparto di tutte le righe/u);
    expect(flat(fixed.closest("label") as HTMLElement)).toContain("Necessario");
    await user.selectOptions(fixed, "Reception");

    expect(await within(panel()).findByText("Tutte le informazioni necessarie sono state abbinate.")).not.toBeNull();
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    const decision = checkMappingMock.mock.calls.at(-1)?.[2] as ImportMapping;
    expect(decision.constants).toEqual({ labor_category: "FRONT_OFFICE" });
  });

  it("a meaning belongs to one column: giving it to another takes it from the first", async () => {
    const user = await openMapping();

    await user.selectOptions(meaningOf("Ore turno"), "Data");

    expect(meaningOf("Ore turno").value).toBe("work_date");
    expect(meaningOf("Giorno").value).toBe(""); // it was "Data" a moment ago
    const decision = checkMappingMock.mock.calls.at(-1)?.[2] as ImportMapping;
    expect(decision.columns.filter((column) => column.field === "work_date")).toHaveLength(1);
  });

  it("choosing a column for a field that had a fixed value drops the fixed value", async () => {
    const user = await openMapping();
    await user.selectOptions(within(panel()).getByLabelText(/Reparto di tutte le righe/u), "Cucina");

    await user.selectOptions(meaningOf("Giorno"), "Reparto (nome standard di NINFA)");

    const decision = checkMappingMock.mock.calls.at(-1)?.[2] as ImportMapping;
    expect(decision.constants).toEqual({});
    expect(decision.columns.find((column) => column.header === "Giorno")?.field).toBe("labor_category");
  });

  it("after 'Continua' the whole file is tried with this matching, and nothing is written", async () => {
    const user = await openMapping();
    await user.selectOptions(await within(panel()).findByLabelText(/Reparto di tutte le righe/u), "Reception");
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValue(ok(validationOf()));

    await user.click(within(panel()).getByRole("button", { name: "Continua" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Anteprima importazione" })).not.toBeNull();
    expect(validateImportMock).toHaveBeenCalledTimes(1);
    const args = validateImportMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args).toMatchObject({ propertyId: PROPERTY_ID, domain: "LABOR" });
    expect((args.mapping as ImportMapping).constants).toEqual({ labor_category: "FRONT_OFFICE" });
    expect(importMatchedFileMock).not.toHaveBeenCalled();
    expect(onImportedMock).not.toHaveBeenCalled();
  });
});

describe("Abbina le colonne: headers NINFA does not know", () => {
  it("says nothing was recognised and lets the person choose, column by column", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(unknownInspection()));
    checkMappingMock.mockResolvedValue(ok(checkOf({ valid: false, missing: [["work_date"], ["actual_hours", "planned_hours"], ["labor_category", "role"]] })));
    await pick(user, csvFile("export.csv"));
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });

    expect(
      within(panel()).getByText("NINFA ha analizzato le colonne del file. Controlla gli abbinamenti prima di continuare."),
    ).not.toBeNull();
    expect(meaningOf("Colonna A").value).toBe("");
    expect(within(panel()).queryByText("Riconosciuto")).toBeNull();
    expect(await within(panel()).findByText("Mancano ancora 3 informazioni necessarie:")).not.toBeNull();

    await user.selectOptions(meaningOf("Colonna A"), "Data");
    await user.selectOptions(meaningOf("Colonna B"), "Ore previste");
    await user.selectOptions(meaningOf("Colonna C"), "Reparto o mansione");

    const decision = checkMappingMock.mock.calls.at(-1)?.[2] as ImportMapping;
    expect(decision.columns).toEqual([
      { header: "Colonna A", field: "work_date" },
      { header: "Colonna B", field: "planned_hours" },
      { header: "Colonna C", field: "role" },
    ]);
  });

  it("a matching the backend refuses cannot go on, and says why in plain words", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    checkMappingMock.mockResolvedValue(
      ok(checkOf({ valid: false, missing: [], problems: [{ code: "FIELD_USED_TWICE", fields: ["work_date"] }] })),
    );
    await pick(user, csvFile());
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });

    expect(await within(panel()).findByText("Lo stesso significato è stato dato a due colonne.")).not.toBeNull();
    expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("an answer about a matching that is no longer on screen is ignored", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspectionWithoutTeam()));
    let release: (value: unknown) => void = () => undefined;
    checkMappingMock.mockImplementationOnce(() => new Promise((done) => (release = done)));
    checkMappingMock.mockImplementation(checkLikeTheBackend);
    await pick(user, csvFile());
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });

    await user.selectOptions(within(panel()).getByLabelText(/Reparto di tutte le righe/u), "Cucina"); // newer answer: valid
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    release(ok(checkOf({ valid: false, missing: [["labor_category", "role"]] }))); // the older, late answer

    await waitFor(() => expect(checkMappingMock).toHaveBeenCalledTimes(2));
    expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false);
    expect(within(panel()).queryByText("Manca ancora 1 informazione necessaria:")).toBeNull();
  });
});

describe("Abbina le colonne: how the file writes dates and numbers", () => {
  async function toTheQuestion() {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    await pick(user, csvFile());
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValueOnce(
      ok(
        validationOf({
          status: "NEEDS_CHOICE",
          can_import: false,
          format_hints: [
            { question: "DATE_ORDER", proven: null, columns: ["Giorno"] },
            { question: "DECIMAL_STYLE", proven: null, columns: ["Ore turno"] },
          ],
          rows_total: 0,
          rows_valid: 0,
          sample_fields: [],
          sample_rows: [],
        }),
      ),
    );
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await within(panel()).findByText("Come sono scritte le date?");
    return user;
  }

  it("asks only what the values do not prove, and waits for the answer before going on", async () => {
    await toTheQuestion();

    expect(within(panel()).getByText("Riguarda: Giorno")).not.toBeNull();
    expect(within(panel()).getByLabelText("Giorno/mese/anno (per esempio 31/12/2026)")).not.toBeNull();
    expect(within(panel()).getByLabelText("Mese/giorno/anno (per esempio 12/31/2026)")).not.toBeNull();
    expect(within(panel()).getByText("Come sono scritti i numeri con i decimali?")).not.toBeNull();
    expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("heading", { level: 3, name: "Anteprima importazione" })).toBeNull();
  });

  it("sends the answers with the matching and goes to the preview", async () => {
    const user = await toTheQuestion();

    await user.click(within(panel()).getByLabelText("Giorno/mese/anno (per esempio 31/12/2026)"));
    expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(true); // numbers too
    await user.click(within(panel()).getByLabelText("Con la virgola (per esempio 1.234,50)"));
    validateImportMock.mockResolvedValueOnce(ok(validationOf()));
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Anteprima importazione" })).not.toBeNull();
    const sent = validateImportMock.mock.calls.at(-1)?.[0] as { mapping: ImportMapping };
    expect(sent.mapping.date_order).toBe("DMY");
    expect(sent.mapping.decimal_style).toBe("COMMA");
  });

  it("changing the matching forgets the questions: they are asked again only if still needed", async () => {
    const user = await toTheQuestion();

    await user.selectOptions(meaningOf("Ore turno"), "Ore lavorate");

    expect(within(panel()).queryByText("Come sono scritte le date?")).toBeNull();
  });
});

describe("Abbina le colonne: a file the backend cannot use", () => {
  it("a file that writes its dates in several ways is said plainly", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    await pick(user, csvFile());
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValue(
      ok(
        validationOf({
          status: "BLOCKED",
          problem: "FORMAT_UNCLEAR",
          can_import: false,
          check: checkOf({ valid: false, problems: [{ code: "DATES_MIXED", fields: ["work_date"] }] }),
          rows_total: 0,
        }),
      ),
    );

    await user.click(within(panel()).getByRole("button", { name: "Continua" }));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("NINFA non riesce a capire come sono scritte le date o i numeri di questo file: indicalo tu.");
    expect(within(panel()).getByText("Le date di questo file non sono scritte sempre allo stesso modo.")).not.toBeNull();
    expect(screen.queryByRole("heading", { level: 3, name: "Anteprima importazione" })).toBeNull();
  });

  it("a request that fails on the way keeps the matching and says so, without a technical word", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    await pick(user, csvFile());
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValue(failure("NETWORK_ERROR", 0));

    await user.click(within(panel()).getByRole("button", { name: "Continua" }));

    expect(flat(await within(panel()).findByRole("alert"))).toContain("NINFA non è riuscita a leggere questa fonte.");
    expect(meaningOf("Giorno").value).toBe("work_date"); // nothing the person chose was lost
    expect(document.body.textContent).not.toContain("technical message");
  });
});

// --- the preview ---------------------------------------------------------------------------------------------------

describe("Anteprima importazione", () => {
  async function toThePreview(validation = validationOf(), inspection = laborInspection()) {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(inspection));
    await pick(user, csvFile("turni.csv"));
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValue(ok(validation));
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await within(panel()).findByRole("heading", { level: 3, name: "Anteprima importazione" });
    return user;
  }

  it("shows how many rows were found, how many are fine and the first ones in NINFA's own form", async () => {
    await toThePreview();

    const box = panel();
    expect(flat(box.querySelector(".struttura-preview__counts") as HTMLElement)).toBe("3 righe trovate 3 valide");
    const table = within(box).getByRole("region", { name: "Prime righe, nel formato di NINFA" });
    expect(within(table).getAllByRole("columnheader").map(flat)).toEqual(["Data", "Reparto", "Ore previste"]);
    expect(within(table).getAllByRole("row").slice(1).map(flat)).toEqual([
      "26/10/2026 Reception 8",
      "27/10/2026 Piani (housekeeping) 7,5",
      "28/10/2026 Cucina 8",
    ]);
    expect(within(box).getByText("Le date sono lette come giorno/mese/anno.")).not.toBeNull();
  });

  it("says, before importing, how many rows have a department NINFA does not recognise (they would be 'Altro')", async () => {
    await toThePreview(validationOf({ rows_unclassified: 2 }));

    const note = within(panel()).getByRole("note");
    expect(flat(note)).toContain(
      "Per 2 righe NINFA non riconosce il reparto: verranno importate come «Altro» e non potranno essere usate nelle analisi sul personale.",
    );
    expect(flat(note)).toContain("Se il reparto è scritto in un'altra colonna, usa «Controlla colonne».");
    expect(within(panel()).getByRole("button", { name: "Importa dati" })).not.toBeNull(); // information, not a block
  });

  it("uses the singular for a single row", async () => {
    await toThePreview(validationOf({ rows_unclassified: 1 }));

    expect(flat(within(panel()).getByRole("note"))).toContain("Per 1 riga NINFA non riconosce il reparto: verrà importata come «Altro»");
  });

  it("says nothing about departments when every one was recognised", async () => {
    await toThePreview(validationOf({ rows_unclassified: 0 }));
    expect(within(panel()).queryByRole("note")).toBeNull();
    expect(document.body.textContent).not.toContain("non riconosce il reparto");
  });

  it("offers to remember the matching, already ticked, and the import - and imports nothing yet", async () => {
    await toThePreview();

    const save = within(panel()).getByRole("checkbox", { name: /Salva questa configurazione per i prossimi file/u }) as HTMLInputElement;
    expect(save.checked).toBe(true);
    expect(within(panel()).getByRole("button", { name: "Importa dati" })).not.toBeNull();
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("imports with the matching and remembers it, and tells the page an import has ended", async () => {
    const user = await toThePreview();
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf()));

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" })).not.toBeNull();
    expect(importMatchedFileMock).toHaveBeenCalledTimes(1);
    const args = importMatchedFileMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args).toMatchObject({ propertyId: PROPERTY_ID, domain: "LABOR", saveConfiguration: true });
    expect(args.snapshotLocalDate).toBe("2026-10-23");
    expect(args).not.toHaveProperty("dataSourceId");
    expect((args.mapping as ImportMapping).columns.find((column) => column.header === "Giorno")?.field).toBe("work_date");
    expect(flat(panel())).toContain("Elementi: 3 nuovi.");
    expect(
      within(panel()).getByText("Configurazione salvata: la prossima volta NINFA riconoscerà il formato di questo file."),
    ).not.toBeNull();
    expect(onImportedMock).toHaveBeenCalledTimes(1);
  });

  it("unticking 'Salva questa configurazione' imports without remembering anything", async () => {
    const user = await toThePreview();
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ configuration_saved: false })));

    await user.click(within(panel()).getByRole("checkbox", { name: /Salva questa configurazione/u }));
    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    expect(importMatchedFileMock.mock.calls[0]?.[0]).toMatchObject({ saveConfiguration: false });
    expect(within(panel()).queryByText(/Configurazione salvata/u)).toBeNull();
  });

  it("rows that cannot be imported are counted, explained, and the import is not offered", async () => {
    const user = await toThePreview(
      validationOf({
        can_import: false,
        rows_total: 147,
        rows_valid: 143,
        rows_invalid: 4,
        row_problems: [
          { field: "planned_hours", code: "INVALID_NUMBER", count: 3 },
          { field: "", code: "REQUIRED_VALUE_MISSING", count: 1 },
        ],
        invalid_rows: [
          { row: 12, issues: [{ field: "planned_hours", code: "INVALID_NUMBER" }] },
          { row: 40, issues: [{ field: "work_date", code: "REQUIRED_VALUE_MISSING" }] },
        ],
      }),
    );

    const box = panel();
    expect(flat(box.querySelector(".struttura-preview__counts") as HTMLElement)).toBe("147 righe trovate 143 valide 4 da verificare");
    const alert = within(box).getByRole("alert");
    expect(flat(alert)).toContain("Alcune righe non possono essere importate");
    expect(flat(alert)).toContain("Ore previste: numero non valido (3 righe)");
    expect(flat(alert)).toContain("manca un valore necessario (1 riga)");
    expect(flat(alert)).toContain("Riga 12: Ore previste: numero non valido");
    expect(flat(alert)).toContain("Riga 40: Data: manca un valore necessario");
    expect(flat(alert)).toContain("finché non le correggi nel file, non viene importato nulla");
    expect(within(box).queryByRole("button", { name: "Importa dati" })).toBeNull();
    expect(within(box).queryByRole("checkbox")).toBeNull();
    expect(within(box).queryByRole("region", { name: "Prime righe, nel formato di NINFA" })).toBeNull();

    await user.click(within(box).getByRole("button", { name: "Controlla colonne" }));
    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(importMatchedFileMock).not.toHaveBeenCalled();
  });

  it("says when the same file was already imported, and which way it read the dates", async () => {
    await toThePreview(
      validationOf({
        already_imported: true,
        format_hints: [{ question: "DATE_ORDER", proven: null, columns: ["Giorno"] }],
      }),
    );

    expect(within(panel()).getByText("Questo file è già stato importato: caricarlo di nuovo non duplica i dati.")).not.toBeNull();
    expect(within(panel()).queryByText(/Le date sono lette come/u)).toBeNull(); // not proven, not chosen: not claimed
  });

  it("the person can go back to the columns and forward again", async () => {
    const user = await toThePreview();

    await user.click(within(panel()).getByRole("button", { name: "Controlla colonne" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(meaningOf("Giorno").value).toBe("work_date"); // the matching is where it was left
  });
});

// --- a layout NINFA already knows ---------------------------------------------------------------------------

describe("a format NINFA already knows", () => {
  async function recognized() {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(recognizedInspection()));
    validateImportMock.mockResolvedValue(ok(validationOf()));
    await pick(user, csvFile("turni-settimana-44.csv"));
    await within(panel()).findByRole("heading", { level: 3, name: "Abbiamo riconosciuto il formato del tuo file" });
    return user;
  }

  it("goes straight to the preview, with no matching: the file is tried with the saved configuration", async () => {
    await recognized();

    expect(validateImportMock).toHaveBeenCalledTimes(1);
    expect((validateImportMock.mock.calls[0]?.[0] as { mapping: unknown }).mapping).toBeNull();
    expect(checkMappingMock).not.toHaveBeenCalled();
    expect(within(panel()).getByText("NINFA lo leggerà con le stesse colonne dell'ultima volta: non devi abbinarle di nuovo.")).not.toBeNull();
    expect(within(panel()).getByText("Ultimo utilizzo: 22 ottobre 2026")).not.toBeNull();
    expect(within(panel()).getByRole("heading", { level: 3, name: "Anteprima importazione" })).not.toBeNull();
    expect(within(panel()).queryByRole("checkbox")).toBeNull(); // nothing new to remember
  });

  it("imports with the saved configuration: no matching is sent, nothing new is saved", async () => {
    const user = await recognized();
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ configuration_saved: false })));

    await user.click(within(panel()).getByRole("button", { name: "Importa con questa configurazione" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    expect(importMatchedFileMock.mock.calls[0]?.[0]).toMatchObject({
      domain: "LABOR",
      mapping: null,
      saveConfiguration: false,
    });
  });

  it("'Controlla colonne' opens the matching, starting from the saved one", async () => {
    const user = await recognized();

    await user.click(within(panel()).getByRole("button", { name: "Controlla colonne" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(meaningOf("Giorno").value).toBe("work_date");
    expect(meaningOf("Reparto").value).toBe("role");
    expect(checkMappingMock).toHaveBeenCalled();
  });

  it("if the saved configuration cannot read this file after all, the person is asked to match the columns", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(recognizedInspection()));
    validateImportMock.mockResolvedValue(ok(validationOf({ status: "BLOCKED", problem: "PROFILE_NOT_USABLE", can_import: false, rows_total: 0 })));

    await pick(user, csvFile());

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(screen.queryByText("Abbiamo riconosciuto il formato del tuo file")).toBeNull();
  });

  it("a configuration that needs a second look opens the matching, with a hint of what changed in the columns", async () => {
    const user = renderFlow();
    const changed = recognizedInspection();
    inspectFileMock.mockResolvedValue(
      ok({
        ...changed,
        profile: { ...changed.profile, status: "NEEDS_REVIEW", reason: "COLUMNS_CHANGED", missing_columns: ["Ore turno"] },
      }),
    );

    await pick(user, csvFile());

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(within(panel()).getByText(/colonne diverse dall'ultima volta.*non è stata applicata/u)).not.toBeNull();
    expect(validateImportMock).not.toHaveBeenCalled(); // never applied silently
  });

  it("a configuration written for an older way of reading says so", async () => {
    const user = renderFlow();
    const old = recognizedInspection();
    inspectFileMock.mockResolvedValue(
      ok({ ...old, profile: { ...old.profile, status: "NEEDS_REVIEW", reason: "VERSION_CHANGED", missing_columns: [] } }),
    );

    await pick(user, csvFile());

    expect(await within(panel()).findByText(/ha aggiornato il modo di leggere questi file/u)).not.toBeNull();
  });
});

describe("a file already in NINFA's own format", () => {
  it("needs no matching: the preview comes straight away, and the configuration is offered", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(canonicalInspection()));
    validateImportMock.mockResolvedValue(ok(validationOf({ format_hints: [] })));

    await pick(user, csvFile("modello.csv"));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Anteprima importazione" })).not.toBeNull();
    expect(screen.queryByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).toBeNull();
    expect(checkMappingMock).not.toHaveBeenCalled();
    expect(within(panel()).getByRole("button", { name: "Importa dati" })).not.toBeNull();
    expect((within(panel()).getByRole("checkbox", { name: /Salva questa configurazione/u }) as HTMLInputElement).checked).toBe(true);
  });

  it("if its dates or numbers still need a choice, the matching screen asks", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(canonicalInspection()));
    validateImportMock.mockResolvedValue(
      ok(validationOf({ status: "NEEDS_CHOICE", can_import: false, format_hints: [{ question: "DATE_ORDER", proven: null, columns: ["work_date"] }], rows_total: 0 })),
    );

    await pick(user, csvFile("modello.csv"));

    expect(await within(panel()).findByText("Come sono scritte le date?")).not.toBeNull();
  });
});

// --- Excel and bookings -------------------------------------------------------------------------------------------------

describe("Excel and bookings", () => {
  it("an Excel file with several sheets asks which one, then reads it", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValueOnce(
      ok({ ...laborInspection(), problem: "SHEET_REQUIRED", sheet_names: ["Riepilogo", "Turni"], requires_sheet_selection: true, columns: [] }),
    );
    await pick(user, xlsxFile("turni.xlsx"));

    expect(await within(panel()).findByText("Quale foglio vuoi importare?")).not.toBeNull();
    expect(within(panel()).getByText("Questo file Excel ha più fogli con dati.")).not.toBeNull();
    inspectFileMock.mockResolvedValueOnce(ok({ ...laborInspectionWithoutTeam(), sheet_name: "Turni", file_type: "XLSX" }));
    await user.click(within(panel()).getByRole("button", { name: "Turni" }));

    expect(await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" })).not.toBeNull();
    expect(inspectFileMock.mock.calls[1]?.[3]).toBe("Turni");
    const decision = checkMappingMock.mock.calls.at(-1)?.[2] as ImportMapping;
    expect(decision.sheet_name).toBe("Turni");
  });

  it("a bookings file is not dated by the page, and its fixed values are the backend's to offer", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(bookingsInspection()));
    checkMappingMock.mockResolvedValue(ok(checkOf()));
    validateImportMock.mockResolvedValue(
      ok(
        validationOf({
          format_hints: [{ question: "DATE_ORDER", proven: "DMY", columns: ["Data arrivo"] }],
          sample_fields: ["source_record_id", "check_in", "check_out", "rooms", "room_revenue", "channel", "status"],
          sample_rows: [["IT-0001", "2026-11-12", "2026-11-14", "1", "150.00", "Booking.com", "CONFIRMED"]],
          rows_total: 1,
          rows_valid: 1,
        }),
      ),
    );
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ rows_total: 1, created: 1 })));

    await user.upload(within(panel()).getByLabelText("Seleziona un file CSV o Excel"), csvFile("prenotazioni.csv"));
    await within(panel()).findByRole("heading", { level: 3, name: "Abbina le colonne del tuo file" });
    // every field has its column, so the fixed values stay out of the way
    expect(within(panel()).queryByText("Se il file non ha una colonna per questa informazione")).toBeNull();
    await user.click(await within(panel()).findByRole("button", { name: "Continua" }));
    const table = await within(panel()).findByRole("region", { name: "Prime righe, nel formato di NINFA" });
    expect(within(table).getAllByRole("row").slice(1).map(flat)).toEqual([
      "IT-0001 12/11/2026 14/11/2026 1 150,00 Booking.com Confermata",
    ]);
    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });
    const args = importMatchedFileMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(args.domain).toBe("BOOKINGS");
    expect(args.snapshotLocalDate).toBeUndefined();
  });
});

// --- when something goes wrong ------------------------------------------------------------------------------------------

describe("when a file cannot be used, or the import fails", () => {
  it.each([
    ["UNREADABLE_FILE", "NINFA non riesce a leggere questo file. Controlla che sia un file CSV (in formato UTF-8) o Excel (.xlsx) valido."],
    ["EMPTY_FILE", "Il file è vuoto."],
    ["DUPLICATE_COLUMNS", "Il file ha colonne con lo stesso nome: rinomina o elimina quelle duplicate."],
    ["UNSUPPORTED_FILE", "Questo tipo di file non è supportato. Usa un file CSV o Excel (.xlsx)."],
    ["FILE_TOO_LARGE", "Il file è troppo grande."],
  ] as const)("a file that cannot be read (%s) is explained in one plain sentence", async (problem, sentence) => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok({ ...laborInspection(), problem, columns: [] }));

    await pick(user, csvFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain(sentence);
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(checkMappingMock).not.toHaveBeenCalled();
  });

  it("a network or server error never shows technical text", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(failure("NETWORK_ERROR", 0));

    await pick(user, csvFile());

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("NINFA non è riuscita a leggere questa fonte. Riprova oppure carica un altro file.");
    expect(document.body.textContent).not.toContain("technical message");
    expect(document.body.textContent).not.toMatch(/422|500|NETWORK_ERROR|validation error|connector failed/iu);
  });

  it("a file over the maximum and a source that disappeared each have their own sentence", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValueOnce(failure("FILE_TOO_LARGE", 413));
    await pick(user, csvFile());
    expect(flat(await within(panel()).findByRole("alert"))).toContain("Il file è troppo grande.");

    await user.click(within(panel()).getByRole("button", { name: "Scegli un altro file" }));
    inspectFileMock.mockResolvedValueOnce(failure("PROPERTY_NOT_FOUND", 404));
    await pick(user, csvFile());
    expect(flat(await within(panel()).findByRole("alert"))).toContain("Questa fonte non è più disponibile. Aggiorna la pagina.");
    expect(onAccessLostMock).toHaveBeenCalledTimes(1); // the session re-resolves which properties are still there
  });

  it("a session that has ended says so, and the page goes back through the session check", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(failure("UNAUTHENTICATED", 401));

    await pick(user, csvFile());

    expect(flat(await within(panel()).findByRole("alert"))).toContain("La sessione è scaduta. Accedi di nuovo per continuare.");
    expect(onAccessLostMock).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toMatch(/401|UNAUTHENTICATED/u);
  });

  it("more than one source of this kind of data: NINFA does not pick one, and says so", async () => {
    const user = await toTheImport();
    importMatchedFileMock.mockResolvedValue(failure("SEVERAL_SOURCES", 409));

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    expect(flat(await within(panel()).findByRole("alert"))).toContain(
      "Per questi dati risultano più fonti attive e NINFA non ne sceglie una da sola.",
    );
    expect(document.body.textContent).not.toMatch(/SEVERAL_SOURCES|409/u);
  });

  async function toTheImport() {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    await pick(user, csvFile());
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    validateImportMock.mockResolvedValue(ok(validationOf()));
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await within(panel()).findByRole("button", { name: "Importa dati" });
    return user;
  }

  it("an import that fails tells why, says nothing was imported, and lets the user choose another file", async () => {
    const user = await toTheImport();
    importMatchedFileMock.mockResolvedValue(
      ok(matchedResultOf({ succeeded: false, problem: "INVALID_ROWS", created: 0, rows_invalid: 1, configuration_saved: false })),
    );

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("Importazione non riuscita");
    expect(flat(alert)).toContain("Alcune righe del file non sono valide, quindi non è stato importato nulla.");
    expect(flat(alert)).toContain("Non è stato importato nulla.");
    expect(onImportedMock).not.toHaveBeenCalled(); // nothing changed: the page has nothing to re-read
    await user.click(within(panel()).getByRole("button", { name: "Scegli un altro file" }));
    expect(within(panel()).getByLabelText("Seleziona un file CSV o Excel")).not.toBeNull();
  });

  it("an import that finds another import of the same data still running says to wait and try again", async () => {
    const user = await toTheImport();
    importMatchedFileMock.mockResolvedValueOnce(failure("IMPORT_IN_PROGRESS", 409));

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    const alert = await within(panel()).findByRole("alert");
    expect(flat(alert)).toContain("È già in corso un altro import di questi dati. Attendi qualche istante e riprova.");
    expect(document.body.textContent).not.toMatch(/409|IMPORT_IN_PROGRESS/u);
    expect(onImportedMock).not.toHaveBeenCalled();
  });

  it("a same-day staff conflict says to upload the updated version tomorrow", async () => {
    const user = await toTheImport();
    importMatchedFileMock.mockResolvedValue(
      ok(matchedResultOf({ succeeded: false, problem: "SAME_DAY_CONFLICT", created: 0, configuration_saved: false })),
    );

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    expect(flat(await within(panel()).findByRole("alert"))).toContain(
      "Per oggi hai già caricato un file del personale diverso: carica la versione aggiornata domani.",
    );
  });

  it("a saved configuration that does not fit the file is said in one sentence", async () => {
    const user = await toTheImport();
    importMatchedFileMock.mockResolvedValue(
      ok(matchedResultOf({ succeeded: false, problem: "PROFILE_NOT_USABLE", created: 0, configuration_saved: false })),
    );

    await user.click(within(panel()).getByRole("button", { name: "Importa dati" }));

    expect(flat(await within(panel()).findByRole("alert"))).toContain(
      "La configurazione salvata non funziona con questo file: controlla le colonne e abbinale di nuovo.",
    );
  });
});

// --- nothing is written before the person confirms ---------------------------------------------------------------------------

describe("nothing is written before the person confirms", () => {
  async function toTheMapping() {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspection()));
    await pick(user, csvFile("turni.csv"));
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    return user;
  }

  it("a file that was only read and matched, then abandoned, imports nothing", async () => {
    const user = await toTheMapping();

    await user.click(within(panel()).getByRole("button", { name: "Scegli un altro file" }));

    expect(importMatchedFileMock).not.toHaveBeenCalled();
    expect(onImportedMock).not.toHaveBeenCalled();
  });

  it("a file that reached the preview but was not confirmed imports nothing", async () => {
    const user = await toTheMapping();
    validateImportMock.mockResolvedValue(ok(validationOf()));
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await within(panel()).findByRole("button", { name: "Importa dati" });

    await user.click(within(panel()).getByRole("button", { name: "Scegli un altro file" }));

    expect(importMatchedFileMock).not.toHaveBeenCalled();
    expect(onImportedMock).not.toHaveBeenCalled();
  });

  it("an import that fails, or a request that fails on the way, tells the page nothing has changed", async () => {
    const user = await toTheMapping();
    validateImportMock.mockResolvedValue(ok(validationOf()));
    importMatchedFileMock.mockResolvedValue(
      ok(matchedResultOf({ succeeded: false, problem: "INVALID_ROWS", created: 0, rows_invalid: 1, configuration_saved: false })),
    );
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await user.click(await within(panel()).findByRole("button", { name: "Importa dati" }));
    expect(flat(await within(panel()).findByRole("alert"))).toContain("Non è stato importato nulla.");

    expect(importMatchedFileMock).toHaveBeenCalledTimes(1);
    expect(onImportedMock).not.toHaveBeenCalled();
  });

  it("a later file of a kind NINFA already reads goes in with the saved configuration, and the page is told", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(recognizedInspection()));
    validateImportMock.mockResolvedValue(ok(validationOf()));
    importMatchedFileMock.mockResolvedValue(ok(matchedResultOf({ configuration_saved: false })));

    await pick(user, csvFile("turni-44.csv"));
    await user.click(await within(panel()).findByRole("button", { name: "Importa con questa configurazione" }));
    await within(panel()).findByRole("heading", { level: 3, name: "Importazione completata" });

    expect(importMatchedFileMock.mock.calls[0]?.[0]).toMatchObject({ propertyId: PROPERTY_ID, domain: "LABOR", mapping: null });
    expect(onImportedMock).toHaveBeenCalledTimes(1);
  });
});

// --- nothing technical -------------------------------------------------------------------------------------------------------

describe("the hotelier never meets a technical word while matching columns", () => {
  it("through the whole flow", async () => {
    const user = renderFlow();
    inspectFileMock.mockResolvedValue(ok(laborInspectionWithoutTeam()));
    await pick(user, csvFile());
    await within(panel()).findByText("Manca ancora 1 informazione necessaria:");
    const seen = [document.body.textContent ?? ""];
    await user.selectOptions(within(panel()).getByLabelText(/Reparto di tutte le righe/u), "Cucina");
    validateImportMock.mockResolvedValue(ok(validationOf({ rows_invalid: 1, can_import: false, row_problems: [{ field: "", code: "SOMETHING_NEW", count: 1 }] })));
    await waitFor(() =>
      expect((within(panel()).getByRole("button", { name: "Continua" }) as HTMLButtonElement).disabled).toBe(false),
    );
    await user.click(within(panel()).getByRole("button", { name: "Continua" }));
    await within(panel()).findByRole("alert");
    seen.push(document.body.textContent ?? "");

    for (const text of seen) {
      expect(text).not.toMatch(/API key|webhook|endpoint|payload|\bJSON\b|token|database|schema|OAuth|credential|mapping|parser|canonical|normalized/iu);
      expect(text).not.toMatch(/SOMETHING_NEW|HOURLY_RATE|PERSON|FIELD_USED_TWICE|work_date|planned_hours/u);
    }
    // an error code that NINFA has no sentence for is a plain "valore non valido", never the code
    expect(within(panel()).getByText(/valore non valido \(1 riga\)/u)).not.toBeNull();
  });
});
