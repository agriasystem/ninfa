import { describe, expect, it, vi } from "vitest";

import type { AnalysisDomain, DataDomainFreshness, DomainState, NightStatus } from "@ninfa/contracts";

import { dataOverviewPath, getDataOverview } from "@/lib/api/data-overview";
import { datiRoute } from "@/lib/routes";

import {
  channelGroupLabel,
  costCategoryLabel,
  cporStatusText,
  datiCopy,
  domainStateText,
  laborCategoryLabel,
  nightStatusText,
  otaInsufficientReasonsText,
  otaOutcomeText,
  unavailableReasonText,
} from "./copy";
import {
  formatDateRange,
  formatDayMonthShort,
  formatMonthName,
  formatNightLong,
  formatNightShort,
  formatNightTick,
  nightSearchText,
} from "./dates";
import {
  MISSING,
  formatMoneyCents,
  formatMoneyWhole,
  formatSignedCount,
  formatSignedPercent,
} from "./format";
import { bookingsFreshnessLine, domainFreshnessLine } from "./freshness";
import { DATI_TABS, parseDataPeriod, parseDatiTab } from "./tabs";

/** Intl puts a non-breaking space before "€"; tests compare with an ordinary one. */
const plain = (value: string) => value.replace(/ /gu, " ");

describe("signed changes", () => {
  it("shows an explicit sign, a typographic minus, and a plain zero", () => {
    expect(formatSignedCount(12)).toBe("+12");
    expect(formatSignedCount(-5)).toBe("−5");
    expect(formatSignedCount(0)).toBe("0");
    // thousands are grouped from four digits, like `formatCount` - one convention across the page
    expect(formatSignedCount(1234)).toBe("+1.234");
    expect(formatSignedCount(12345)).toBe("+12.345");
  });

  it("a missing change is a dash, never 0", () => {
    expect(formatSignedCount(null)).toBe(MISSING);
    expect(formatSignedPercent(null)).toBe(MISSING);
  });

  it("formats a percentage change on the 0-100 scale without multiplying it again", () => {
    expect(formatSignedPercent("18.43")).toBe("+18,4%");
    expect(formatSignedPercent("-4.20")).toBe("−4,2%");
    expect(formatSignedPercent("0.00")).toBe("0,0%");
  });
});

describe("money", () => {
  it("shows a headline amount in whole units and an ADR with cents, in the given currency", () => {
    expect(plain(formatMoneyWhole("38250.40", "EUR"))).toBe("38.250 €");
    expect(plain(formatMoneyCents("116.67", "EUR"))).toBe("116,67 €");
    expect(plain(formatMoneyWhole("1700.00", "EUR"))).toBe("1.700 €");
    expect(plain(formatMoneyCents("1680.00", "EUR"))).toBe("1.680,00 €");
  });

  it("a missing amount is a dash, never 0 euro", () => {
    expect(formatMoneyWhole(null, "EUR")).toBe(MISSING);
    expect(formatMoneyCents(null, "EUR")).toBe(MISSING);
  });

  it("never throws for an unknown currency code", () => {
    expect(() => formatMoneyWhole("10.00", "??")).not.toThrow();
  });
});

describe("business dates never drift with the browser's timezone", () => {
  it("labels a night with its weekday, day and month", () => {
    expect(formatNightShort("2026-03-14")).toBe("sab 14 mar");
    expect(formatNightLong("2026-03-14")).toBe("sabato 14 marzo");
    expect(formatNightTick("2026-03-14")).toBe("sab 14");
    expect(formatDayMonthShort("2026-03-14")).toBe("14 mar");
  });

  it("names the month of a monthly figure", () => {
    expect(formatMonthName("2026-02-01")).toBe("febbraio");
    expect(formatMonthName("2026-12-01")).toBe("dicembre");
  });

  it("writes a range inside a month and across a boundary", () => {
    expect(formatDateRange("2026-03-14", "2026-03-28")).toBe("dal 14 al 28 marzo");
    expect(formatDateRange("2026-03-25", "2026-04-23")).toBe("dal 25 marzo al 23 aprile");
  });

  it("returns an unparseable value unchanged instead of throwing", () => {
    expect(formatNightShort("not-a-date")).toBe("not-a-date");
    expect(formatMonthName("2026-13-01")).toBe("2026-13-01");
  });

  it("is searchable by weekday, day, month name and ISO date", () => {
    const text = nightSearchText("2026-03-14");
    for (const needle of ["sab", "14 mar", "marzo", "2026-03-14", "sabato"]) {
      expect(text).toContain(needle);
    }
  });
});

describe("tabs and URL state", () => {
  it("has the five sections in the specified order", () => {
    expect(DATI_TABS).toEqual(["overview", "bookings", "distribution", "costs", "labor"]);
    expect(DATI_TABS.map((tab) => datiCopy.tabs[tab])).toEqual([
      "Panoramica",
      "Prenotazioni",
      "Distribuzione",
      "Costi",
      "Personale",
    ]);
  });

  it("falls back to Panoramica for anything that is not a known tab", () => {
    expect(parseDatiTab(null)).toBe("overview");
    expect(parseDatiTab("")).toBe("overview");
    expect(parseDatiTab("hack")).toBe("overview");
    expect(parseDatiTab("costs")).toBe("costs");
  });

  it("30 days is the default period and 7 the only alternative", () => {
    expect(parseDataPeriod(null)).toBe(30);
    expect(parseDataPeriod("14")).toBe(30);
    expect(parseDataPeriod("7")).toBe(7);
  });

  it("builds the Dati URL with the property, the tab, and the period only when it is not the default", () => {
    expect(datiRoute()).toBe("/dati");
    expect(datiRoute("p1")).toBe("/dati?property=p1");
    expect(datiRoute("p1", { tab: "bookings" })).toBe("/dati?property=p1&tab=bookings");
    expect(datiRoute("p1", { tab: "overview", period: 30 })).toBe("/dati?property=p1&tab=overview");
    expect(datiRoute("p1", { tab: "costs", period: 7 })).toBe("/dati?property=p1&tab=costs&period=7");
  });
});

describe("API client", () => {
  it("requests the overview with the property-local date and the period", () => {
    expect(dataOverviewPath("p1", "2026-03-14", 7)).toBe(
      "/api/v1/properties/p1/data/overview?as_of=2026-03-14&period=7",
    );
  });

  it("is a credentialed, uncached GET and never sends a body", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    const result = await getDataOverview("p1", "2026-03-14", 30, fetchImpl as unknown as typeof fetch);

    expect(result.ok).toBe(true);
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.test/api/v1/properties/p1/data/overview?as_of=2026-03-14&period=30");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(init.body).toBeUndefined();
    vi.unstubAllEnvs();
  });
});

describe("copy: no technical identifier ever reaches the screen", () => {
  const RAW = /[A-Z]{2,}_[A-Z_]+/u; // an UPPER_SNAKE enum

  it("translates every cost category and falls back safely on an unknown one", () => {
    for (const code of [
      "PERSONNEL", "LAUNDRY", "CLEANING", "AMENITIES", "FOOD", "BEVERAGE", "UTILITIES",
      "MAINTENANCE", "SOFTWARE", "MARKETING", "OTA_COMMISSIONS", "PROFESSIONAL_SERVICES", "TRANSPORT", "OTHER",
    ]) {
      expect(costCategoryLabel(code)).not.toMatch(RAW);
      expect(costCategoryLabel(code)).not.toBe(code);
    }
    expect(costCategoryLabel("OTHER")).toBe("Non classificato");
    expect(costCategoryLabel("SOMETHING_NEW")).toBe("Altra voce");
  });

  it("translates every labor category and falls back safely", () => {
    for (const code of ["HOUSEKEEPING", "FRONT_OFFICE", "FOOD_BEVERAGE", "KITCHEN", "MAINTENANCE", "MANAGEMENT", "SPA_WELLNESS", "OTHER"]) {
      expect(laborCategoryLabel(code)).not.toMatch(RAW);
    }
    expect(laborCategoryLabel("FRONT_OFFICE")).toBe("Ricevimento");
    expect(laborCategoryLabel("NEW_ROLE")).toBe("Altro personale");
  });

  it("every unavailable reason the backend can send reads as a sentence", () => {
    for (const reason of [
      "NO_ANALYSIS", "NO_BOOKING_SOURCE", "NO_BOOKING_DATA", "COVERAGE_UNKNOWN", "NOT_ANALYZED",
      "EVALUATION_FAILED", "NO_DATA", "NO_OCCUPANCY", "NO_SOURCE", "SEVERAL_SOURCES",
    ]) {
      const text = unavailableReasonText(reason);
      expect(text).not.toMatch(RAW);
      expect(text.endsWith(".")).toBe(true);
    }
    expect(unavailableReasonText("BRAND_NEW_REASON")).toBe("Dato non disponibile.");
    expect(unavailableReasonText(null)).toBe("Dato non disponibile.");
  });

  it("maps the four night statuses to the specified words, exhaustively", () => {
    const expected: Record<NightStatus, string> = {
      ATTENTION: "Attenzione",
      PARTIAL: "Analisi parziale",
      REGULAR: "Regolare",
      NOT_EVALUATED: "Non valutato",
    };
    for (const [status, text] of Object.entries(expected)) {
      expect(nightStatusText(status as NightStatus)).toBe(text);
    }
  });

  it("each area agrees with its own gender and number, in every state", () => {
    const states: DomainState[] = ["ANALYZED", "PARTIAL", "NOT_ANALYZED", "UNKNOWN"];
    const domains: AnalysisDomain[] = ["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"];
    expect(domainStateText("DISTRIBUTION", "NOT_ANALYZED")).toBe("Non analizzata");
    expect(domainStateText("LABOR", "ANALYZED")).toBe("Analizzato");
    expect(domainStateText("REVENUE", "ANALYZED")).toBe("Analizzati");
    for (const domain of domains) {
      for (const state of states) expect(domainStateText(domain, state)).not.toMatch(RAW);
    }
  });

  it("explains an OTA outcome and its insufficiency reasons in plain Italian, never 'va tutto bene'", () => {
    expect(otaOutcomeText("CLEAR")).toMatch(/non rileva criticità/u);
    expect(otaOutcomeText("CLEAR")).not.toMatch(/tutto bene|perfett/iu);
    expect(otaOutcomeText("DECISION")).toBeNull();
    expect(otaOutcomeText(null)).toBeNull();
    expect(otaInsufficientReasonsText(["OTA_BOOKING_VOLUME_LOW", "OTA_BOOKING_VOLUME_LOW"])).toBe(
      "le prenotazioni classificate come OTA o dirette sono troppo poche",
    );
    expect(otaInsufficientReasonsText(["UNKNOWN_CODE"])).toBe("dati insufficienti");
  });

  it("describes a cost-per-room status without a code", () => {
    for (const status of ["NO_OCCUPANCY_SOURCE", "INCOMPLETE", "ZERO_OCCUPANCY", "LOW_CLASSIFICATION_COVERAGE", "NO_COST_DATA", "NOT_APPLICABLE", "XYZ"]) {
      expect(cporStatusText(status)).not.toMatch(RAW);
    }
  });

  it("labels the channel groups", () => {
    expect(channelGroupLabel("OTA")).toBe("OTA");
    expect(channelGroupLabel("DIRECT")).toBe("Diretto");
    expect(channelGroupLabel("OTHER")).toBe("Altro canale");
    expect(channelGroupLabel("???")).toBe("Non classificato");
  });

  it("states what each money/rate figure is without accounting vocabulary", () => {
    const wording = JSON.stringify([datiCopy.kpi, datiCopy.occupancy, datiCopy.costs]);
    expect(wording).toMatch(/prenotazioni già a sistema/u);
    expect(wording).not.toMatch(/fatturat|incass|margine|utile/iu);
  });
});

describe("freshness is a fact, per domain, in the property's timezone", () => {
  const known = (finishedAt: string): DataDomainFreshness => ({
    status: "KNOWN",
    last_successful_import_finished_at: finishedAt,
    reason: null,
  });

  it("uses the Home's own wording for bookings", () => {
    const line = bookingsFreshnessLine(known("2026-03-14T08:15:00Z"), "2026-03-14", "Europe/Rome");
    expect(line).toEqual({ kind: "known", text: "Ultimo import prenotazioni: oggi alle 09:15" });
  });

  it("decides today / yesterday in the PROPERTY's timezone, not UTC", () => {
    // 23:30 UTC on the 13th is already the 14th in Rome (00:30)
    const line = domainFreshnessLine("Ultimo import costi", known("2026-03-13T23:30:00Z"), "2026-03-14", "Europe/Rome");
    expect(line.text).toBe("Ultimo import costi: oggi alle 00:30");
    const yesterday = domainFreshnessLine("Ultimo import costi", known("2026-03-13T17:05:00Z"), "2026-03-14", "Europe/Rome");
    expect(yesterday.text).toBe("Ultimo import costi: ieri alle 18:05");
  });

  it("never says 'Dati aggiornati', whatever the freshness", () => {
    const lines = [
      bookingsFreshnessLine(known("2026-03-14T08:15:00Z"), "2026-03-14", "Europe/Rome").text,
      bookingsFreshnessLine({ status: "UNKNOWN", last_successful_import_finished_at: null, reason: "NO_SOURCE" }, "2026-03-14", "Europe/Rome").text,
    ];
    for (const text of lines) expect(text).not.toMatch(/aggiornat/iu);
  });

  it("says why a domain has no import fact instead of borrowing another domain's timestamp", () => {
    const base = { status: "UNKNOWN", last_successful_import_finished_at: null } as const;
    expect(domainFreshnessLine("Ultimo import costi", { ...base, reason: "NO_SOURCE" }, "2026-03-14", "Europe/Rome").text).toBe(
      "Ultimo import costi: nessuna origine dati configurata",
    );
    expect(domainFreshnessLine("Ultimo import personale", { ...base, reason: "SEVERAL_SOURCES" }, "2026-03-14", "Europe/Rome").text).toBe(
      "Ultimo import personale: più origini dati: non confrontabili",
    );
    expect(domainFreshnessLine("Ultimo import costi", { ...base, reason: "NO_IMPORT" }, "2026-03-14", "Europe/Rome").kind).toBe("unknown");
    expect(domainFreshnessLine("Ultimo import costi", { ...base, reason: null }, "2026-03-14", "Europe/Rome").text).toBe(
      "Ultimo import costi: non disponibile",
    );
  });

  it("treats an unparseable instant as unknown rather than printing 'Invalid Date'", () => {
    const line = domainFreshnessLine("Ultimo import costi", known("not-an-instant"), "2026-03-14", "Europe/Rome");
    expect(line.kind).toBe("unknown");
    expect(line.text).not.toMatch(/invalid/iu);
  });
});
