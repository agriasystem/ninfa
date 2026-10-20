import type { DataDomainFreshness } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import {
  formatPropertyLocalDateTimeItalian,
  formatPropertyLocalTimeItalian,
  previousBusinessDate,
  propertyLocalDate,
} from "@/lib/date/property-date";
import { freshnessLineOf, type FreshnessLine } from "@/lib/home/freshness";

import { datiCopy } from "./copy";

export type { FreshnessLine };

/** The bookings line is EXACTLY the Home's own ("Ultimo import prenotazioni: oggi alle 09:31"), so the
 * same fact never reads two ways in the same product. */
export function bookingsFreshnessLine(
  freshness: DataDomainFreshness,
  businessDate: string,
  timeZone: string,
): FreshnessLine {
  return freshnessLineOf({ bookings: freshness }, businessDate, timeZone);
}

/** "oggi alle 09:31" / "ieri alle 22:15" / "31 luglio, 18:00", in the PROPERTY's timezone against the
 * business date the page is about. `null` for an unparseable instant. */
function importWhen(finishedAt: string, businessDate: string, timeZone: string): string | null {
  const instant = new Date(finishedAt);
  if (Number.isNaN(instant.getTime())) return null;
  const importDate = propertyLocalDate(instant, timeZone);
  const time = formatPropertyLocalTimeItalian(instant, timeZone);
  if (importDate === businessDate) return copy.home.freshnessToday(time);
  if (importDate === previousBusinessDate(businessDate)) return copy.home.freshnessYesterday(time);
  return formatPropertyLocalDateTimeItalian(instant, timeZone);
}

/** The costs / labor line: the same fact for THAT domain's own data source. When there is no single
 * source to speak of, it says why rather than borrowing another domain's timestamp. */
export function domainFreshnessLine(
  label: string,
  freshness: DataDomainFreshness,
  businessDate: string,
  timeZone: string,
): FreshnessLine {
  if (freshness.status === "KNOWN" && freshness.last_successful_import_finished_at !== null) {
    const when = importWhen(freshness.last_successful_import_finished_at, businessDate, timeZone);
    if (when !== null) return { kind: "known", text: `${label}: ${when}` };
  }
  const reason =
    (freshness.reason !== null ? datiCopy.freshness.unknown[freshness.reason] : undefined) ??
    datiCopy.freshness.unknownFallback;
  return { kind: "unknown", text: `${label}: ${reason}` };
}
