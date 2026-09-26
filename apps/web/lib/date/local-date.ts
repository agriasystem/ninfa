/**
 * Displaying a plain `LocalDate` API value (`YYYY-MM-DD` - `stay_date`, `work_date`,
 * `first_seen_local_date`, ...) is a DIFFERENT problem from Gate 14's `propertyLocalDate`: there
 * is no "now" or timezone conversion involved at all, the date is already resolved. The bug this
 * guards against is `new Date("2026-10-15")` (parsed as UTC midnight) formatted with the HOST's
 * own local timezone: in any negative-offset timezone that renders as "14 October", an off-by-one
 * that has nothing to do with the actual business date. The fix is to never let the host's
 * timezone enter the computation at all: parse the three components by hand and format them
 * pinned to UTC, so the same three numbers always come back out.
 */

const italianMonths = [
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

function parseLocalDate(isoDate: string): { year: number; month: number; day: number } {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) {
    throw new Error(`Not a LocalDate (YYYY-MM-DD): "${isoDate}"`);
  }
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

export interface FormatLocalDateOptions {
  /** Defaults to false - most business copy in this product already scopes the year from
   * context; pass true for timeline/history rows that can span year boundaries. */
  withYear?: boolean;
}

/** "15 ottobre" (or "15 ottobre 2026" with `withYear: true`) - display only, never re-parsed. */
export function formatLocalDateItalian(isoDate: string, options: FormatLocalDateOptions = {}): string {
  const { year, month, day } = parseLocalDate(isoDate);
  const monthName = italianMonths[month - 1];
  if (!monthName) {
    throw new Error(`Not a valid month in LocalDate: "${isoDate}"`);
  }
  return options.withYear ? `${day} ${monthName} ${year}` : `${day} ${monthName}`;
}
