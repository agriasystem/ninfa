/**
 * Business-date formatting for Dati. A stay night is a bare calendar date (`YYYY-MM-DD`): it has no
 * instant and no timezone, so none of these ever builds a `Date` from the string in the browser's
 * zone (`new Date("2026-10-01")` is UTC midnight and prints the previous day west of UTC). The three
 * digit groups are parsed directly; the weekday uses UTC calendar arithmetic only, on purpose.
 */

const MONTHS = [
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
] as const;

const MONTHS_SHORT = [
  "gen",
  "feb",
  "mar",
  "apr",
  "mag",
  "giu",
  "lug",
  "ago",
  "set",
  "ott",
  "nov",
  "dic",
] as const;

const WEEKDAYS = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"] as const;
const WEEKDAYS_SHORT = ["dom", "lun", "mar", "mer", "gio", "ven", "sab"] as const;

interface Parts {
  year: number;
  month: number; // 1-12
  day: number;
}

function partsOf(isoDate: string): Parts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

function weekdayIndex({ year, month, day }: Parts): number {
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay();
}

/** "sab 1 ago" - the compact label of a table row / chart tick. */
export function formatNightShort(isoDate: string): string {
  const parts = partsOf(isoDate);
  if (!parts) return isoDate;
  return `${WEEKDAYS_SHORT[weekdayIndex(parts)]} ${parts.day} ${MONTHS_SHORT[parts.month - 1]}`;
}

/** "sabato 1 agosto" - for assistive technology and tooltips. */
export function formatNightLong(isoDate: string): string {
  const parts = partsOf(isoDate);
  if (!parts) return isoDate;
  return `${WEEKDAYS[weekdayIndex(parts)]} ${parts.day} ${MONTHS[parts.month - 1]}`;
}

/** "sab 1" - the axis tick of a 7-night chart. */
export function formatNightTick(isoDate: string): string {
  const parts = partsOf(isoDate);
  if (!parts) return isoDate;
  return `${WEEKDAYS_SHORT[weekdayIndex(parts)]} ${parts.day}`;
}

/** "1 ago" - an axis tick. */
export function formatDayMonthShort(isoDate: string): string {
  const parts = partsOf(isoDate);
  if (!parts) return isoDate;
  return `${parts.day} ${MONTHS_SHORT[parts.month - 1]}`;
}

/** "luglio" - the month a monthly figure belongs to. */
export function formatMonthName(isoDate: string): string {
  const parts = partsOf(isoDate);
  if (!parts) return isoDate;
  return MONTHS[parts.month - 1] ?? isoDate;
}

/** "dal 1 al 30 agosto", or "dal 25 luglio al 23 agosto" across a month boundary. */
export function formatDateRange(startIso: string, endIso: string): string {
  const start = partsOf(startIso);
  const end = partsOf(endIso);
  if (!start || !end) return `${startIso} - ${endIso}`;
  const endMonth = MONTHS[end.month - 1];
  if (start.month === end.month && start.year === end.year) {
    return `dal ${start.day} al ${end.day} ${endMonth}`;
  }
  return `dal ${start.day} ${MONTHS[start.month - 1]} al ${end.day} ${endMonth}`;
}

/** The searchable text of a night: every way a person might type it ("sab", "1 ago", "agosto",
 * "2026-08-01"), lower-cased. */
export function nightSearchText(isoDate: string): string {
  return `${formatNightShort(isoDate)} ${formatNightLong(isoDate)} ${isoDate}`.toLocaleLowerCase("it-IT");
}
