import type { DecisionFeedResponse } from "@ninfa/contracts";

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
