import { describe, expect, it } from "vitest";

import { formatPropertyLocalDateTimeItalian } from "@/lib/date/property-date";
import { UNKNOWN_FRESHNESS, knownFreshness } from "@/test/home-support";

import { freshnessLineOf } from "./freshness";

const ROME = "Europe/Rome";

describe("freshnessLineOf - a plain fact, never a judgement", () => {
  it("reads 'oggi alle HH:MM' for an import on the analysis' own business day", () => {
    // 07:31 UTC on 8 October is 09:31 in Rome (UTC+2, summer time).
    const line = freshnessLineOf(knownFreshness("2026-10-08T07:31:00Z"), "2026-10-08", ROME);

    expect(line).toEqual({ kind: "known", text: "Ultimo import prenotazioni: oggi alle 09:31" });
  });

  it("reads 'ieri alle HH:MM' for an import on the previous business day", () => {
    // 20:15 UTC on 7 October is 22:15 in Rome.
    const line = freshnessLineOf(knownFreshness("2026-10-07T20:15:00Z"), "2026-10-08", ROME);

    expect(line.text).toBe("Ultimo import prenotazioni: ieri alle 22:15");
  });

  it("falls back to the existing date+time formatter for anything older", () => {
    const iso = "2026-09-29T07:15:00Z";
    const line = freshnessLineOf(knownFreshness(iso), "2026-10-08", ROME);

    const formatted = formatPropertyLocalDateTimeItalian(new Date(iso), ROME);
    expect(line).toEqual({ kind: "known", text: `Ultimo import prenotazioni: ${formatted}` });
    expect(line.text).toContain("29 settembre");
    expect(line.text).toContain("09:15");
    expect(line.text).not.toMatch(/oggi|ieri/u);
  });

  it("decides today/yesterday in the PROPERTY's timezone, not UTC and not the browser's", () => {
    // 22:30 UTC on 7 Oct: still 7 Oct in UTC/London, but already 00:30 on 8 Oct in Rome.
    const instant = "2026-10-07T22:30:00Z";

    expect(freshnessLineOf(knownFreshness(instant), "2026-10-08", ROME).text).toBe(
      "Ultimo import prenotazioni: oggi alle 00:30",
    );
    // The same instant, for a property in Honolulu (UTC-10): 12:30 on 7 Oct -> "oggi" for ITS day.
    expect(freshnessLineOf(knownFreshness(instant), "2026-10-07", "Pacific/Honolulu").text).toBe(
      "Ultimo import prenotazioni: oggi alle 12:30",
    );
  });

  it("uses the real IANA offset of that specific day (DST): same wall clock, different UTC", () => {
    // 09:31 in Rome in January is 08:31Z (UTC+1); in July it is 07:31Z (UTC+2).
    expect(
      freshnessLineOf(knownFreshness("2026-01-15T08:31:00Z"), "2026-01-15", ROME).text,
    ).toBe("Ultimo import prenotazioni: oggi alle 09:31");
    expect(
      freshnessLineOf(knownFreshness("2026-07-15T07:31:00Z"), "2026-07-15", ROME).text,
    ).toBe("Ultimo import prenotazioni: oggi alle 09:31");
  });

  it("rolls 'ieri' correctly over a month and a year boundary", () => {
    // 1 January 2027: yesterday is 31 December 2026.
    expect(
      freshnessLineOf(knownFreshness("2026-12-31T20:00:00Z"), "2027-01-01", ROME).text,
    ).toBe("Ultimo import prenotazioni: ieri alle 21:00");
    // 1 March 2028 (leap year): yesterday is 29 February.
    expect(
      freshnessLineOf(knownFreshness("2028-02-29T10:00:00Z"), "2028-03-01", ROME).text,
    ).toBe("Ultimo import prenotazioni: ieri alle 11:00");
  });

  it("writes midnight as 00:xx, never 24:xx", () => {
    expect(
      freshnessLineOf(knownFreshness("2026-10-07T22:05:00Z"), "2026-10-08", ROME).text,
    ).toBe("Ultimo import prenotazioni: oggi alle 00:05");
  });
});

describe("freshnessLineOf - unknown never invents a time", () => {
  it("is neutral and short for UNKNOWN", () => {
    expect(freshnessLineOf(UNKNOWN_FRESHNESS, "2026-10-08", ROME)).toEqual({
      kind: "unknown",
      text: "Ultimo import prenotazioni non disponibile",
    });
  });

  it("is UNKNOWN when KNOWN carries no timestamp", () => {
    const line = freshnessLineOf(
      { bookings: { status: "KNOWN", last_successful_import_finished_at: null } },
      "2026-10-08",
      ROME,
    );
    expect(line.kind).toBe("unknown");
    expect(line.text).not.toMatch(/\d{2}:\d{2}/u);
  });

  it("is UNKNOWN when the timestamp is not a date (never a crash, never a guess)", () => {
    const line = freshnessLineOf(knownFreshness("not-a-date"), "2026-10-08", ROME);
    expect(line.kind).toBe("unknown");
  });

  it("is UNKNOWN when UNKNOWN still carries a stray timestamp (status wins)", () => {
    const line = freshnessLineOf(
      { bookings: { status: "UNKNOWN", last_successful_import_finished_at: "2026-10-08T07:31:00Z" } },
      "2026-10-08",
      ROME,
    );
    expect(line.kind).toBe("unknown");
  });
});

describe("freshness copy (Gate 23B)", () => {
  it("never claims the data is current, recent or 'aggiornati' - a fact only", () => {
    const lines = [
      freshnessLineOf(knownFreshness("2026-10-08T07:31:00Z"), "2026-10-08", ROME),
      freshnessLineOf(knownFreshness("2026-10-07T20:15:00Z"), "2026-10-08", ROME),
      freshnessLineOf(knownFreshness("2026-09-01T07:31:00Z"), "2026-10-08", ROME),
      freshnessLineOf(UNKNOWN_FRESHNESS, "2026-10-08", ROME),
    ];
    for (const line of lines) {
      expect(line.text).toMatch(/^Ultimo import prenotazioni/u);
      expect(line.text).not.toMatch(/aggiornat|attual|recent|obsolet|vecchi|stale|current/iu);
    }
  });
});
