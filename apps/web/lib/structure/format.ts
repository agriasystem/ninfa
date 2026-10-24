import { strutturaCopy } from "./copy";
import type { MonthRange, RoomType } from "./types";

/** "Marzo – Novembre"; one month on its own when the range is a single month. Never throws: a month
 * outside 1-12 (a malformed backend value) is shown as nothing rather than as "undefined". */
export function formatMonthRange(range: MonthRange): string {
  const from = strutturaCopy.months[range.fromMonth - 1];
  const to = strutturaCopy.months[range.toMonth - 1];
  if (from === undefined || to === undefined) return "";
  return range.fromMonth === range.toMonth ? from : `${from} – ${to}`;
}

/** A mid-winter instant: the zone's STANDARD-time abbreviation ("CET"), which is how the page names a zone
 * all year round, rather than "CEST" in summer. Zones without a local abbreviation read "GMT+3". */
const STANDARD_TIME_INSTANT = new Date("2026-01-15T12:00:00Z");

/** "Europe/Rome (CET)". An unknown zone is shown as it came. */
export function formatTimeZoneLabel(timeZone: string): string {
  try {
    const abbreviation = new Intl.DateTimeFormat("it-IT", { timeZone, timeZoneName: "short" })
      .formatToParts(STANDARD_TIME_INSTANT)
      .find((part) => part.type === "timeZoneName")?.value;
    return abbreviation ? `${timeZone} (${abbreviation})` : timeZone;
  } catch {
    return timeZone;
  }
}

/** "Euro (€)" from "EUR". An unknown code is shown as it came. */
export function formatCurrencyLabel(code: string): string {
  try {
    const name = new Intl.DisplayNames(["it-IT"], { type: "currency" }).of(code);
    const symbol = new Intl.NumberFormat("it-IT", {
      style: "currency",
      currency: code,
      currencyDisplay: "narrowSymbol",
    })
      .formatToParts(0)
      .find((part) => part.type === "currency")?.value;
    if (!name || !symbol) return code;
    return `${name.charAt(0).toUpperCase()}${name.slice(1)} (${symbol})`;
  } catch {
    return code;
  }
}

/** "2 adulti + 1 bambino": the children part is left out when the type hosts none. */
export function formatMaxOccupancy(room: Pick<RoomType, "maxAdults" | "maxChildren">): string {
  const adults = strutturaCopy.rooms.adults(room.maxAdults);
  return room.maxChildren > 0 ? `${adults} + ${strutturaCopy.rooms.children(room.maxChildren)}` : adults;
}
