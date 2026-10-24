import { describe, expect, it } from "vitest";

import {
  formatCurrencyLabel,
  formatMaxOccupancy,
  formatMonthRange,
  formatTimeZoneLabel,
} from "./format";

describe("formatMonthRange", () => {
  it("writes the capitalised months with an en dash", () => {
    expect(formatMonthRange({ fromMonth: 3, toMonth: 11 })).toBe("Marzo – Novembre");
    expect(formatMonthRange({ fromMonth: 6, toMonth: 9 })).toBe("Giugno – Settembre");
  });

  it("writes a one-month range as that month alone, and a wrapping range as given", () => {
    expect(formatMonthRange({ fromMonth: 8, toMonth: 8 })).toBe("Agosto");
    expect(formatMonthRange({ fromMonth: 11, toMonth: 2 })).toBe("Novembre – Febbraio");
  });

  it("never prints 'undefined' for a month outside 1-12", () => {
    expect(formatMonthRange({ fromMonth: 0, toMonth: 5 })).toBe("");
    expect(formatMonthRange({ fromMonth: 3, toMonth: 13 })).toBe("");
  });
});

describe("formatTimeZoneLabel", () => {
  it("names the zone with its standard-time abbreviation, whatever the date", () => {
    expect(formatTimeZoneLabel("Europe/Rome")).toBe("Europe/Rome (CET)");
  });

  it("falls back to the zone as it came when it is not a real IANA zone", () => {
    expect(formatTimeZoneLabel("Not/AZone")).toBe("Not/AZone");
  });
});

describe("formatCurrencyLabel", () => {
  it("writes the Italian currency name and its symbol", () => {
    expect(formatCurrencyLabel("EUR")).toBe("Euro (€)");
  });

  it("falls back to the code as it came when it is not a currency", () => {
    expect(formatCurrencyLabel("??")).toBe("??");
  });
});

describe("formatMaxOccupancy", () => {
  it("adds the children only when the room type hosts some, in the right number", () => {
    expect(formatMaxOccupancy({ maxAdults: 2, maxChildren: 0 })).toBe("2 adulti");
    expect(formatMaxOccupancy({ maxAdults: 2, maxChildren: 1 })).toBe("2 adulti + 1 bambino");
    expect(formatMaxOccupancy({ maxAdults: 1, maxChildren: 2 })).toBe("1 adulto + 2 bambini");
  });
});
