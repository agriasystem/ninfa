import { describe, expect, it } from "vitest";

import { formatLocalDateItalian } from "./local-date";

describe("formatLocalDateItalian", () => {
  it("formats day + Italian month, no year by default", () => {
    expect(formatLocalDateItalian("2026-10-15")).toBe("15 ottobre");
  });

  it("includes the year when withYear is true", () => {
    expect(formatLocalDateItalian("2026-10-15", { withYear: true })).toBe("15 ottobre 2026");
  });

  it("never shifts the day near a UTC/local timezone boundary (no off-by-one)", () => {
    // The classic bug: new Date("2026-01-01") is UTC midnight, which a negative-offset host
    // timezone would render as "31 dicembre" (the previous day). This helper never goes near
    // that path at all.
    expect(formatLocalDateItalian("2026-01-01")).toBe("1 gennaio");
    expect(formatLocalDateItalian("2026-12-31")).toBe("31 dicembre");
  });

  it("handles every month name correctly", () => {
    expect(formatLocalDateItalian("2026-01-05")).toBe("5 gennaio");
    expect(formatLocalDateItalian("2026-02-05")).toBe("5 febbraio");
    expect(formatLocalDateItalian("2026-03-05")).toBe("5 marzo");
    expect(formatLocalDateItalian("2026-04-05")).toBe("5 aprile");
    expect(formatLocalDateItalian("2026-05-05")).toBe("5 maggio");
    expect(formatLocalDateItalian("2026-06-05")).toBe("5 giugno");
    expect(formatLocalDateItalian("2026-07-05")).toBe("5 luglio");
    expect(formatLocalDateItalian("2026-08-05")).toBe("5 agosto");
    expect(formatLocalDateItalian("2026-09-05")).toBe("5 settembre");
    expect(formatLocalDateItalian("2026-10-05")).toBe("5 ottobre");
    expect(formatLocalDateItalian("2026-11-05")).toBe("5 novembre");
    expect(formatLocalDateItalian("2026-12-05")).toBe("5 dicembre");
  });

  it("rejects a value that is not a plain YYYY-MM-DD LocalDate", () => {
    expect(() => formatLocalDateItalian("2026-10-15T10:00:00Z")).toThrow();
    expect(() => formatLocalDateItalian("not-a-date")).toThrow();
  });
});
