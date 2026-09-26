import { describe, expect, it } from "vitest";

import { formatPropertyLocalDateItalian, propertyLocalDate } from "./property-date";

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
