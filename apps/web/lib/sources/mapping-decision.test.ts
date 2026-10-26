import type { FileInspectionResponse, ImportMapping } from "@ninfa/contracts";
import { describe, expect, it } from "vitest";

import {
  laborInspection,
  laborInspectionWithoutTeam,
  recognizedInspection,
  savedLaborMapping,
} from "@/test/sources-support";

import {
  decisionFromSuggestions,
  fieldOfColumn,
  fieldsInUse,
  isLockedColumn,
  personAnswered,
  sameDecision,
  startingDecision,
  withColumnField,
  withConstant,
  withDateOrder,
  withDecimalStyle,
} from "./mapping-decision";

const fieldsOf = (decision: ImportMapping) =>
  Object.fromEntries(decision.columns.map((column) => [column.header, column.field]));

describe("a decision about the columns of a file", () => {
  it("starts from NINFA's proposal, and a column NINFA never reads stays ignored", () => {
    const decision = decisionFromSuggestions(laborInspection());

    expect(fieldsOf(decision)).toEqual({
      Giorno: "work_date",
      "Nome dipendente": null,
      "Ore turno": "planned_hours",
      "Costo orario": null,
      Reparto: "role",
    });
    expect(decision.constants).toEqual({});
    expect(decision.date_order).toBeUndefined(); // nothing is chosen on the person's behalf
  });

  it("locks the columns NINFA deliberately never reads, whatever was proposed for them", () => {
    const inspection = laborInspection();
    const [, person, , rate] = inspection.columns;
    expect(isLockedColumn(person!) && isLockedColumn(rate!)).toBe(true);
    expect(isLockedColumn(inspection.columns[0]!)).toBe(false);

    const tampered: FileInspectionResponse = {
      ...inspection,
      columns: inspection.columns.map((column) =>
        column.header === "Nome dipendente" ? { ...column, field: "role" } : column,
      ),
    };

    expect(fieldOfColumn(decisionFromSuggestions(tampered), "Nome dipendente")).toBeNull();
  });

  it("gives a meaning to ONE column: choosing it again moves it", () => {
    const start = decisionFromSuggestions(laborInspection());

    const moved = withColumnField(start, "Ore turno", "work_date");

    expect(fieldsOf(moved)).toMatchObject({ Giorno: null, "Ore turno": "work_date" });
    expect(fieldsInUse(moved)).toEqual(new Set(["work_date", "role"]));
    expect(start.columns.find((column) => column.header === "Giorno")?.field).toBe("work_date"); // not mutated
  });

  it("ignoring a column frees its meaning", () => {
    const decision = withColumnField(decisionFromSuggestions(laborInspection()), "Reparto", null);

    expect(fieldOfColumn(decision, "Reparto")).toBeNull();
    expect(fieldsInUse(decision).has("role")).toBe(false);
  });

  it("a fixed value and a column never stand for the same field", () => {
    const start = decisionFromSuggestions(laborInspection());

    const fixed = withConstant(start, "role", "Cucina");
    const column = withColumnField(fixed, "Giorno", "role");

    expect(fixed.constants).toEqual({ role: "Cucina" });
    expect(fieldOfColumn(fixed, "Reparto")).toBeNull(); // the column that stood for it is ignored
    expect(column.constants).toEqual({}); // and a column takes the fixed value away
    expect(fieldOfColumn(column, "Giorno")).toBe("role");
  });

  it("an emptied fixed value is no value at all", () => {
    const fixed = withConstant(decisionFromSuggestions(laborInspection()), "labor_category", "KITCHEN");

    expect(withConstant(fixed, "labor_category", null).constants).toEqual({});
    expect(withConstant(fixed, "labor_category", "").constants).toEqual({});
    expect(withConstant(fixed, "rooms", 2).constants).toEqual({ labor_category: "KITCHEN", rooms: 2 });
  });

  it("keeps the answers about dates and numbers apart from the columns", () => {
    const start = decisionFromSuggestions(laborInspection());

    const answered = withDecimalStyle(withDateOrder(start, "MDY"), "POINT");

    expect(answered).toMatchObject({ date_order: "MDY", decimal_style: "POINT" });
    expect(answered.columns).toEqual(start.columns);
  });

  it("tells whether two decisions are the same", () => {
    const start = decisionFromSuggestions(laborInspection());

    expect(sameDecision(start, decisionFromSuggestions(laborInspection()))).toBe(true);
    expect(sameDecision(start, withColumnField(start, "Giorno", null))).toBe(false);
  });
});

describe("where 'Controlla colonne' starts", () => {
  it("is the saved matching where it still applies", () => {
    const decision = startingDecision(recognizedInspection());

    expect(decision).toMatchObject({ ...savedLaborMapping(), sheet_name: null });
  });

  it("completes it, for a column the saved matching knows nothing about, with NINFA's proposal - but never a meaning already taken", () => {
    const inspection = recognizedInspection();
    const withNewColumn: FileInspectionResponse = {
      ...inspection,
      columns: [
        ...inspection.columns,
        { position: 5, header: "Giorno bis", examples: ["27/10/2026"], field: "work_date", level: "TO_CHECK", not_used_reason: null, date_order: "DMY", number_style: null },
        { position: 6, header: "Ore effettive", examples: ["7"], field: "actual_hours", level: "RECOGNIZED", not_used_reason: null, date_order: null, number_style: null },
      ],
      profile: {
        ...inspection.profile,
        mapping: {
          ...savedLaborMapping(),
          columns: [...savedLaborMapping().columns],
        },
      },
    };

    const decision = startingDecision(withNewColumn);

    expect(fieldOfColumn(decision, "Giorno")).toBe("work_date");
    expect(fieldOfColumn(decision, "Giorno bis")).toBeNull(); // work_date is already taken
    expect(fieldOfColumn(decision, "Ore effettive")).toBe("actual_hours"); // free: NINFA's proposal stands
  });

  it("without a saved matching it is simply the proposal", () => {
    expect(startingDecision(laborInspectionWithoutTeam())).toEqual(
      decisionFromSuggestions(laborInspectionWithoutTeam()),
    );
  });
});

describe("did the person answer anything?", () => {
  it("is false for no answers, and for answers that decide nothing", () => {
    expect(personAnswered({})).toBe(false);
    expect(personAnswered({ column_fields: {}, labels: {} })).toBe(false);
    expect(personAnswered({ period_start: "2026-11-02" })).toBe(false); // the week of THIS file only
    expect(personAnswered({ sheet_name: null, date_order: null })).toBe(false);
  });

  it("is true as soon as the person decided a column, a basis, a department or how dates are written", () => {
    expect(personAnswered({ column_fields: { "Ore A": "planned_hours" } })).toBe(true);
    expect(personAnswered({ grid_hours: "actual_hours" })).toBe(true);
    expect(personAnswered({ amount_basis: "NET" })).toBe(true);
    expect(personAnswered({ date_order: "DMY" })).toBe(true);
    expect(personAnswered({ decimal_style: "COMMA" })).toBe(true);
    expect(personAnswered({ department_value: "RECEPTION" })).toBe(true);
    expect(personAnswered({ table_key: "T2" })).toBe(true);
  });
});
