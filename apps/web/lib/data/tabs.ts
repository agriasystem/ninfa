import type { DataPeriod } from "@ninfa/contracts";

/** The internal sections of the Dati page. They are NOT a second application navigation: just the
 * five views of one workspace, kept in the URL (`?tab=`) so back/forward and a reload keep them. */
export type DatiTab = "overview" | "bookings" | "distribution" | "costs" | "labor";

export const DATI_TABS: readonly DatiTab[] = [
  "overview",
  "bookings",
  "distribution",
  "costs",
  "labor",
];

export const DEFAULT_DATI_TAB: DatiTab = "overview";
export const DEFAULT_DATA_PERIOD: DataPeriod = 30;

/** Anything that is not one of the five known ids (absent, mistyped, an old link) is the default
 * view: a bad `?tab=` never shows an error. */
export function parseDatiTab(value: string | null): DatiTab {
  return DATI_TABS.find((tab) => tab === value) ?? DEFAULT_DATI_TAB;
}

/** `?period=7` is the only alternative; everything else is the default 30 nights. */
export function parseDataPeriod(value: string | null): DataPeriod {
  return value === "7" ? 7 : DEFAULT_DATA_PERIOD;
}
