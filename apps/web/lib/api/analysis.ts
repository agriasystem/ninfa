import type { AnalysisStatusResponse } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

/**
 * Where a property's analysis stands against its data. The analysis itself is never started from here: a
 * successful import asks the worker on the server. The POST is only the recovery when that did not happen, and
 * the backend ignores it in any other state.
 */

function analysisPath(propertyId: string): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/analysis`;
}

export function getAnalysisStatus(
  propertyId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<AnalysisStatusResponse>> {
  return apiRequest<AnalysisStatusResponse>(`${analysisPath(propertyId)}/status`, { method: "GET" }, fetchImpl);
}

export function requestAnalysisRefresh(
  propertyId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<AnalysisStatusResponse>> {
  return apiRequest<AnalysisStatusResponse>(`${analysisPath(propertyId)}/refresh`, { method: "POST" }, fetchImpl);
}
