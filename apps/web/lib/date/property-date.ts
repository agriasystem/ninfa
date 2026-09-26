/**
 * "Oggi" means "today in the Property's own timezone" - never `new Date().toISOString().slice(0,
 * 10)` (UTC), never the browser's own timezone. Both functions below take the SAME `(now,
 * timeZone)` pair through `Intl.DateTimeFormat`, the only reliable cross-runtime source of IANA
 * timezone conversion; no external date library is added for this.
 */

const partsFormatterCache = new Map<string, Intl.DateTimeFormat>();
const italianLongDateFormatterCache = new Map<string, Intl.DateTimeFormat>();

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
