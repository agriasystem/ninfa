import type { DecisionDetailResponse, DecisionFeedResponse, DecisionHistoryResponse } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

export function decisionFeedPath(propertyId: string, asOfLocalDate: string): string {
  return `/api/v1/properties/${propertyId}/decision-feed?as_of=${asOfLocalDate}`;
}

/** GET /api/v1/properties/{propertyId}/decision-feed?as_of=YYYY-MM-DD. `asOfLocalDate` MUST be
 * the property's own local date (see `lib/date/property-date.ts`) - never a server clock, never
 * the browser's own timezone. */
export function getDecisionFeed(
  propertyId: string,
  asOfLocalDate: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<DecisionFeedResponse>> {
  return apiRequest<DecisionFeedResponse>(
    decisionFeedPath(propertyId, asOfLocalDate),
    { method: "GET" },
    fetchImpl,
  );
}

export function decisionDetailPath(propertyId: string, decisionId: string): string {
  return `/api/v1/properties/${propertyId}/decisions/${decisionId}`;
}

/** GET /api/v1/properties/{propertyId}/decisions/{decisionId} (Gate 12, read by Gate 15's
 * Decision Detail page). Never calls a detector, `PriorityService` or `DecisionService.sync()` -
 * this is the SAME read-only endpoint the feed already reads from, by decision id instead of
 * by as-of date. */
export function getDecisionDetail(
  propertyId: string,
  decisionId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<DecisionDetailResponse>> {
  return apiRequest<DecisionDetailResponse>(
    decisionDetailPath(propertyId, decisionId),
    { method: "GET" },
    fetchImpl,
  );
}

export interface DecisionHistoryOptions {
  /** An opaque cursor from a previous `DecisionHistoryResponse.next_cursor` - passed back
   * verbatim, never decoded or constructed client-side. */
  cursor?: string;
  limit?: number;
}

export function decisionHistoryPath(
  propertyId: string,
  decisionId: string,
  options: DecisionHistoryOptions = {},
): string {
  const params = new URLSearchParams();
  if (options.cursor !== undefined) params.set("cursor", options.cursor);
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  const base = `/api/v1/properties/${propertyId}/decisions/${decisionId}/history`;
  return query ? `${base}?${query}` : base;
}

/** GET /api/v1/properties/{propertyId}/decisions/{decisionId}/history?limit=&cursor=. Newest-
 * first, cursor-paginated (Gate 12); a client only ever appends a further page, never re-sorts. */
export function getDecisionHistory(
  propertyId: string,
  decisionId: string,
  options: DecisionHistoryOptions = {},
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<DecisionHistoryResponse>> {
  return apiRequest<DecisionHistoryResponse>(
    decisionHistoryPath(propertyId, decisionId, options),
    { method: "GET" },
    fetchImpl,
  );
}
