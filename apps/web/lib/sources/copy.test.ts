import { describe, expect, it } from "vitest";

import { sourcesCopy } from "./copy";

/**
 * What the person is told about the files NINFA reads. A bookings or staff source takes a CSV or an Excel
 * (.xlsx) file, so no label, hint or error may name CSV alone; costs stay XML (FatturaPA).
 */
describe("the formats of the files, as the person reads them", () => {
  it("every place that offers to import bookings or staff says CSV or Excel (.xlsx)", () => {
    const offered = [
      sourcesCopy.methods.bookingsCsv.body,
      sourcesCopy.methods.channelCsv.body,
      sourcesCopy.methods.laborCsv.body,
      sourcesCopy.importFlow.hints.CSV,
    ];
    for (const text of offered) expect(text).toMatch(/CSV o Excel \(\.xlsx\)/u);
    expect(sourcesCopy.importFlow.wrongType.CSV).toContain("CSV o Excel");
    expect(sourcesCopy.problemHints.UNSUPPORTED_FILE.CSV).toContain("CSV o Excel (.xlsx)");
    expect(sourcesCopy.problemHints.UNREADABLE_FILE.CSV).toContain("Excel (.xlsx)");
  });

  it("the label of a file source names no single format, because a source can receive both over time", () => {
    expect(sourcesCopy.methodLabels.CSV).toBe("Import file");
    expect(sourcesCopy.methodLabels.XML).toBe("Import fatture XML");
  });

  it("no general error sends the person to CSV only", () => {
    expect(sourcesCopy.problems.GENERIC).not.toMatch(/CSV/u);
  });

  it("the only CSV-only text is the template NINFA itself offers to download", () => {
    expect(sourcesCopy.importFlow.template).toBe("Scarica modello CSV");
  });
});

describe("what a staff file's department column is called", () => {
  it("a department or a job as the file writes it, never 'ruolo' alone (the model keeps a free label, not a job title)", () => {
    expect(sourcesCopy.fields.role).toBe("Reparto o mansione");
    expect(sourcesCopy.fields.labor_category).toBe("Reparto (nome standard di NINFA)");
  });

  it("the sentence above the columns is true whether or not anything was recognised", () => {
    expect(sourcesCopy.match.intro).toBe(
      "NINFA ha analizzato le colonne del file. Controlla gli abbinamenti prima di continuare.",
    );
    expect(sourcesCopy.match).not.toHaveProperty("introNothing");
  });
});
