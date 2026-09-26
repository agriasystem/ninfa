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
