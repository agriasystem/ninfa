/**
 * "Oggi" means "today in the Property's own timezone" - never `new Date().toISOString().slice(0,
 * 10)` (UTC), never the browser's own timezone. Both functions below take the SAME `(now,
 * timeZone)` pair through `Intl.DateTimeFormat`, the only reliable cross-runtime source of IANA
 * timezone conversion; no external date library is added for this.
 */

const partsFormatterCache = new Map<string, Intl.DateTimeFormat>();
const italianLongDateFormatterCache = new Map<string, Intl.DateTimeFormat>();
const italianLongDateTimeFormatterCache = new Map<string, Intl.DateTimeFormat>();

function partsFormatterFor(timeZone: string): Intl.DateTimeFormat {
  let formatter = partsFormatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    partsFormatterCache.set(timeZone, formatter);
  }
  return formatter;
}

function italianLongDateFormatterFor(timeZone: string): Intl.DateTimeFormat {
  let formatter = italianLongDateFormatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("it-IT", {
      timeZone,
      weekday: "long",
      day: "numeric",
      month: "long",
    });
    italianLongDateFormatterCache.set(timeZone, formatter);
  }
  return formatter;
}

/** `now`'s calendar date IN `timeZone`, as `YYYY-MM-DD`. Built from `formatToParts` (never a
 * locale-formatted string) so the result never depends on which locale produced it. */
export function propertyLocalDate(now: Date, timeZone: string): string {
  const parts = partsFormatterFor(timeZone).formatToParts(now);
  const lookup = (type: "year" | "month" | "day"): string | undefined =>
    parts.find((part) => part.type === type)?.value;
  const year = lookup("year");
  const month = lookup("month");
  const day = lookup("day");
  if (!year || !month || !day) {
    throw new Error(`Unable to compute the local date for timezone "${timeZone}"`);
  }
  return `${year}-${month}-${day}`;
}

/** `now`'s calendar date IN `timeZone`, as Italian long-form prose ("venerdì 26 settembre"),
 * capitalised. Display only - never parsed back, never compared. */
export function formatPropertyLocalDateItalian(now: Date, timeZone: string): string {
  const formatted = italianLongDateFormatterFor(timeZone).format(now);
  return formatted.length === 0 ? formatted : formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

function italianLongDateTimeFormatterFor(timeZone: string): Intl.DateTimeFormat {
  let formatter = italianLongDateTimeFormatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("it-IT", {
      timeZone,
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit",
    });
    italianLongDateTimeFormatterCache.set(timeZone, formatter);
  }
  return formatter;
}

/** An INSTANT (e.g. `ImportJob.finished_at` - Gate 23B), as Italian prose IN the property's own
 * timezone ("29 settembre, 09:15") - never the browser's own timezone. Display only - never
 * parsed back, never compared. */
export function formatPropertyLocalDateTimeItalian(instant: Date, timeZone: string): string {
  return italianLongDateTimeFormatterFor(timeZone).format(instant);
}

const ITALIAN_MONTHS = [
  "gennaio",
  "febbraio",
  "marzo",
  "aprile",
  "maggio",
  "giugno",
  "luglio",
  "agosto",
  "settembre",
  "ottobre",
  "novembre",
  "dicembre",
];

/** A bare BUSINESS date (`YYYY-MM-DD`, e.g. `DecisionRun.as_of_local_date` - Gate 24B's
 * `last_successful_analysis.as_of_local_date`), as Italian prose ("1 ottobre") - no year, no
 * weekday.
 *
 * Deliberately takes NO `timeZone` parameter and never constructs a `Date` from `isoDate` at
 * all: `new Date("2026-10-01")` parses a date-only ISO string as UTC MIDNIGHT, and reading it
 * back in a negative-UTC-offset runtime (e.g. `America/...`) prints the PREVIOUS calendar day -
 * exactly the class of bug this function exists to avoid. A bare business date already IS the
 * day in question; it has no instant and no timezone to convert, so this parses the three
 * digit groups directly out of the string and never touches `Date`/`Intl.DateTimeFormat` at
 * all. */
export function formatBusinessDateItalian(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) {
    throw new Error(`Invalid business date: "${isoDate}"`);
  }
  const [, , monthStr, dayStr] = match;
  const monthName = ITALIAN_MONTHS[Number(monthStr) - 1];
  if (monthName === undefined) {
    throw new Error(`Invalid business date: "${isoDate}"`);
  }
  return `${Number(dayStr)} ${monthName}`;
}
