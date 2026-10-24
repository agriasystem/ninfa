import type { ImportFieldSpec } from "@ninfa/contracts";
import { describe, expect, it } from "vitest";

import { formatDay, formatDecimal, formatSampleCell } from "./sample-format";

const spec = (key: ImportFieldSpec["key"], kind: ImportFieldSpec["kind"]): ImportFieldSpec => ({
  key,
  kind,
  constant: null,
});

describe("how a cell of the preview is written", () => {
  it("writes a day the way a hotelier reads it", () => {
    expect(formatDay("2026-10-21")).toBe("21/10/2026");
    expect(formatDay("2026-10-21T14:30:00+02:00")).toBe("21/10/2026");
    expect(formatDay("non è una data")).toBe("non è una data"); // never invented
  });

  it("writes a number with Italian separators and the decimals it already has", () => {
    expect(formatDecimal("8")).toBe("8");
    expect(formatDecimal("7.5")).toBe("7,5");
    expect(formatDecimal("1234.50")).toBe("1234,50"); // Italian grouping starts at five digits
    expect(formatDecimal("12345.50")).toBe("12.345,50");
    expect(formatDecimal("abc")).toBe("abc");
  });

  it("formats by what the backend says the field is, and a missing value as a dash", () => {
    expect(formatSampleCell(spec("work_date", "DATE"), "2026-10-26")).toBe("26/10/2026");
    expect(formatSampleCell(spec("booked_at", "DATETIME"), "2026-10-01T07:30:00+00:00")).toBe("01/10/2026");
    expect(formatSampleCell(spec("planned_hours", "DECIMAL"), "7.5")).toBe("7,5");
    expect(formatSampleCell(spec("channel", "TEXT"), "Booking.com")).toBe("Booking.com");
    expect(formatSampleCell(spec("planned_cost", "DECIMAL"), null)).toBe("–");
    expect(formatSampleCell(undefined, "x")).toBe("x");
  });

  it("names a standard value in the hotelier's words, and leaves an unknown one as it is", () => {
    expect(formatSampleCell(spec("labor_category", "CHOICE"), "FRONT_OFFICE")).toBe("Reception");
    expect(formatSampleCell(spec("labor_category", "CHOICE"), "SOMETHING_ELSE")).toBe("SOMETHING_ELSE");
    expect(formatSampleCell(spec("status", "CHOICE"), "CONFIRMED")).toBe("Confermata");
  });
});
