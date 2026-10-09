import type { InputFreshness } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import {
  formatPropertyLocalDateTimeItalian,
  formatPropertyLocalTimeItalian,
  previousBusinessDate,
  propertyLocalDate,
} from "@/lib/date/property-date";

export interface FreshnessLine {
  /** `known`: a factual import timestamp exists; `unknown`: it does not (never invented). */
  kind: "known" | "unknown";
  text: string;
}

/**
 * The Home's one freshness line (Home UI V1, D2 - Gate 23B): a plain FACT about when NINFA finished
 * importing bookings, never a CURRENT/STALE judgement and never "Dati aggiornati alle ...".
 *
 * - imported on the analysis' own business day -> "Ultimo import prenotazioni: oggi alle 09:31"
 * - the day before                              -> "Ultimo import prenotazioni: ieri alle 22:15"
 * - anything older                              -> the existing date+time formatter
 * - UNKNOWN / no timestamp / unparseable one    -> "Ultimo import prenotazioni non disponibile"
 *
 * "Today"/"yesterday" are decided in the PROPERTY's timezone against the feed's own business date
 * (`feed.as_of_local_date`, the property-local "today" the feed was requested for) - never the
 * browser's timezone and never a clock the test would have to freeze.
 */
export function freshnessLineOf(
  freshness: InputFreshness,
  businessDate: string,
  timeZone: string,
): FreshnessLine {
  const { bookings } = freshness;
  const unknown: FreshnessLine = { kind: "unknown", text: copy.home.freshnessUnknown };
  if (bookings.status !== "KNOWN" || bookings.last_successful_import_finished_at === null) {
    return unknown;
  }
  const instant = new Date(bookings.last_successful_import_finished_at);
  if (Number.isNaN(instant.getTime())) return unknown;

  const importDate = propertyLocalDate(instant, timeZone);
  let when: string;
  if (importDate === businessDate) {
    when = copy.home.freshnessToday(formatPropertyLocalTimeItalian(instant, timeZone));
  } else if (importDate === previousBusinessDate(businessDate)) {
    when = copy.home.freshnessYesterday(formatPropertyLocalTimeItalian(instant, timeZone));
  } else {
    when = formatPropertyLocalDateTimeItalian(instant, timeZone);
  }
  return { kind: "known", text: copy.home.freshnessKnown(when) };
}
