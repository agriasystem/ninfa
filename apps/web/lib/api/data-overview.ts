import type { DataOverviewResponse, DataPeriod } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

export function dataOverviewPath(propertyId: string, asOfLocalDate: string, period: DataPeriod): string {
  return `/api/v1/properties/${propertyId}/data/overview?as_of=${asOfLocalDate}&period=${period}`;
}

/** GET /api/v1/properties/{propertyId}/data/overview?as_of=YYYY-MM-DD&period=7|30 (Dati UI V1).
 * `asOfLocalDate` MUST be the property's own local date (`lib/date/property-date.ts`) - never a
 * server clock, never the browser's timezone. The response is a deterministic, read-only projection:
 * this call never runs a detector, a Decision sync or a language model. */
export function getDataOverview(
  propertyId: string,
  asOfLocalDate: string,
  period: DataPeriod,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<DataOverviewResponse>> {
  return apiRequest<DataOverviewResponse>(
    dataOverviewPath(propertyId, asOfLocalDate, period),
    { method: "GET" },
    fetchImpl,
  );
}
