import type { DataPeriod } from "@ninfa/contracts";

import { DEFAULT_DATA_PERIOD, type DatiTab } from "@/lib/data/tabs";

/**
 * Frontend route paths, centralised so the query-param name/shape is defined once. These build
 * URLs WITHIN this app (never a backend API path - see `lib/api/decisions.ts` for those).
 */

export const PROPERTY_QUERY_PARAM = "property";

/** "/oggi", optionally scoped to a property via the same `?property=` convention Gate 14
 * established - never a path segment, for consistency with the rest of this app. */
export function oggiRoute(propertyId?: string): string {
  return propertyId ? `/oggi?${PROPERTY_QUERY_PARAM}=${propertyId}` : "/oggi";
}

/** "/oggi/decisioni/{decisionId}?property={propertyId}" - the canonical Decision Detail route
 * (Gate 15). `propertyId` is carried so the page can call the backend's own
 * `GET /properties/{property_id}/decisions/{decision_id}` without depending on any other client
 * state; it is validated against the SessionContext before ever being trusted (see
 * `components/decision-detail-screen.tsx`). */
export function decisionDetailRoute(propertyId: string, decisionId: string): string {
  return `/oggi/decisioni/${decisionId}?${PROPERTY_QUERY_PARAM}=${propertyId}`;
}

/** "/decisioni", optionally scoped to a property - the list of TODAY'S actionable Decisions (Home
 * UI V1): exactly the feed the Home's "N decisioni richiedono attenzione" count is taken from, so
 * the number a user clicks and the list they land on can never disagree. */
export function decisioniRoute(propertyId?: string): string {
  return propertyId ? `/decisioni?${PROPERTY_QUERY_PARAM}=${propertyId}` : "/decisioni";
}

export const DATI_TAB_PARAM = "tab";
export const DATI_PERIOD_PARAM = "period";

export interface DatiRouteOptions {
  /** The internal section; `?tab=` is written whenever it is given. */
  tab?: DatiTab;
  /** `?period=` is written only for the non-default 7 days (30 is the default). */
  period?: DataPeriod;
}

/** "/dati?property={propertyId}&tab={tab}&period={period}" - the Dati workspace (Dati UI V1). The
 * property stays in the query like every other screen; the section and the period are query state
 * too, so back/forward and a reload keep them. */
export function datiRoute(propertyId?: string, options: DatiRouteOptions = {}): string {
  const params = new URLSearchParams();
  if (propertyId) params.set(PROPERTY_QUERY_PARAM, propertyId);
  if (options.tab !== undefined) params.set(DATI_TAB_PARAM, options.tab);
  if (options.period !== undefined && options.period !== DEFAULT_DATA_PERIOD) {
    params.set(DATI_PERIOD_PARAM, String(options.period));
  }
  const query = params.toString();
  return query ? `/dati?${query}` : "/dati";
}
