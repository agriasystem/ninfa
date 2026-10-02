import { afterEach, describe, expect, it } from "vitest";

import {
  formatBusinessDateItalian,
  formatPropertyLocalDateItalian,
  formatPropertyLocalDateTimeItalian,
  propertyLocalDate,
} from "./property-date";

describe("propertyLocalDate", () => {
  it("uses the property's own timezone, not UTC", () => {
    // 23:30 UTC is already the next day in Europe/Rome (UTC+1 in January).
    const now = new Date("2026-01-15T23:30:00Z");
    expect(propertyLocalDate(now, "Europe/Rome")).toBe("2026-01-16");
  });

  it("ignores the runtime/browser timezone entirely - only the property's timezone matters", () => {
    const now = new Date("2026-06-10T12:00:00Z");
    // Same instant, two different property timezones, two different answers - never one shared
    // "browser" answer.
    expect(propertyLocalDate(now, "Europe/Rome")).toBe("2026-06-10");
    expect(propertyLocalDate(now, "Pacific/Honolulu")).toBe("2026-06-10");
  });

  it("rolls back to the PREVIOUS day for a negative-offset property near UTC midnight", () => {
    // 02:00 UTC is still 21:00 the PREVIOUS day in America/New_York (UTC-5 in January).
    const now = new Date("2026-01-15T02:00:00Z");
    expect(propertyLocalDate(now, "America/New_York")).toBe("2026-01-14");
  });

  it("rolls forward to the NEXT day for a positive-offset property near UTC midnight", () => {
    // 23:30 UTC is already 00:30 the NEXT day in Europe/Rome (UTC+1 in January) - the exact
    // boundary example from the Gate 14 spec.
    const now = new Date("2026-01-15T23:30:00Z");
    expect(propertyLocalDate(now, "Europe/Rome")).toBe("2026-01-16");
  });

  it("applies the real DST offset of the day, not a fixed UTC offset", () => {
    // Same UTC clock time (22:30), two seasons: winter CET (+1) keeps it on the SAME day, summer
    // CEST (+2) rolls it onto the NEXT day - proving the offset used is the REAL one for that
    // calendar day, not a year-round constant.
    expect(propertyLocalDate(new Date("2026-01-15T22:30:00Z"), "Europe/Rome")).toBe("2026-01-15");
    expect(propertyLocalDate(new Date("2026-07-15T22:30:00Z"), "Europe/Rome")).toBe("2026-07-16");
  });

  it("always returns YYYY-MM-DD, zero-padded", () => {
    const now = new Date("2026-01-05T10:00:00Z");
    const result = propertyLocalDate(now, "Europe/Rome");
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(result).toBe("2026-01-05");
  });
});

describe("formatPropertyLocalDateItalian", () => {
  it("formats a capitalised Italian weekday + day + month, no year", () => {
    // 2026-09-26 is a Saturday.
    const now = new Date("2026-09-26T10:00:00Z");
    const formatted = formatPropertyLocalDateItalian(now, "Europe/Rome");
    expect(formatted).toBe("Sabato 26 settembre");
  });

  it("uses the property's timezone for the printed day, like propertyLocalDate", () => {
    // 23:30 UTC on the 15th is already the 16th in Europe/Rome.
    const now = new Date("2026-01-15T23:30:00Z");
    expect(formatPropertyLocalDateItalian(now, "Europe/Rome")).toContain("16");
    expect(formatPropertyLocalDateItalian(now, "Europe/Rome")).not.toContain("15");
  });
});

describe("formatPropertyLocalDateTimeItalian", () => {
  it("formats the day, month and time in Italian prose, no year", () => {
    // 07:15 UTC is 09:15 in Europe/Rome (CEST, UTC+2 in September).
    const instant = new Date("2026-09-29T07:15:00Z");
    const formatted = formatPropertyLocalDateTimeItalian(instant, "Europe/Rome");
    expect(formatted).toContain("29");
    expect(formatted).toContain("settembre");
    expect(formatted).toContain("09:15");
    expect(formatted).not.toContain("2026"); // no year, like formatPropertyLocalDateItalian
  });

  it("uses the property's own timezone, not UTC and not the browser's", () => {
    const instant = new Date("2026-09-29T07:15:00Z");
    expect(formatPropertyLocalDateTimeItalian(instant, "Europe/Rome")).toContain("09:15");
    expect(formatPropertyLocalDateTimeItalian(instant, "America/New_York")).toContain("03:15");
  });

  it("applies the real DST offset of the day, not a fixed UTC offset", () => {
    // Winter CET (+1): 08:15 UTC -> 09:15. Summer CEST (+2): 07:15 UTC -> 09:15.
    expect(formatPropertyLocalDateTimeItalian(new Date("2026-01-15T08:15:00Z"), "Europe/Rome")).toContain(
      "09:15",
    );
    expect(formatPropertyLocalDateTimeItalian(new Date("2026-07-15T07:15:00Z"), "Europe/Rome")).toContain(
      "09:15",
    );
  });
});

describe("formatBusinessDateItalian", () => {
  const ORIGINAL_TZ = process.env.TZ;

  afterEach(() => {
    process.env.TZ = ORIGINAL_TZ;
  });

  it("formats a bare business date as Italian day + month, no year", () => {
    expect(formatBusinessDateItalian("2026-10-01")).toBe("1 ottobre");
  });

  it("does not zero-pad the day, and lower-cases the month like Italian prose", () => {
    expect(formatBusinessDateItalian("2026-01-05")).toBe("5 gennaio");
    expect(formatBusinessDateItalian("2026-12-31")).toBe("31 dicembre");
  });

  it("rejects a malformed input rather than guessing", () => {
    expect(() => formatBusinessDateItalian("not-a-date")).toThrow();
    expect(() => formatBusinessDateItalian("2026-13-01")).toThrow(); // month 13 does not exist
  });

  it(
    "never shifts the printed day regardless of the runtime's own timezone - it never " +
      "constructs a Date from the bare string at all",
    () => {
      // `new Date("2026-10-01")` parses as UTC midnight; reading it back in a negative-offset
      // runtime (here, Pacific/Honolulu, UTC-10) prints the PREVIOUS day (30 September) - the
      // exact bug class this function exists to avoid. Proven by actually flipping the
      // runtime's own TZ, not just by construction.
      process.env.TZ = "Pacific/Honolulu";
      expect(formatBusinessDateItalian("2026-10-01")).toBe("1 ottobre");
      expect(new Date("2026-10-01").getDate()).toBe(30); // sanity check: the naive bug is real

      process.env.TZ = "Pacific/Kiritimati"; // UTC+14, the opposite extreme
      expect(formatBusinessDateItalian("2026-10-01")).toBe("1 ottobre");
    },
  );

  it("is independent of the property's own timezone too - a bare business date has none", () => {
    // formatBusinessDateItalian deliberately takes no timeZone parameter at all.
    expect(formatBusinessDateItalian("2026-10-01")).toBe("1 ottobre");
  });
});
