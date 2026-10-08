import type { AskHomeRequest, AskRequest, AskResponse } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

export function askNinfaPath(propertyId: string, decisionId: string): string {
  return `/api/v1/properties/${propertyId}/decisions/${decisionId}/ask`;
}

/** POST .../decisions/{decisionId}/ask (Gate 18/19/19.1): one question, one grounded answer about
 * ONE Decision. No conversation is created or persisted server-side - this call never needs, and
 * never sends, a thread/message/conversation id. */
export function askNinfa(
  propertyId: string,
  decisionId: string,
  question: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<AskResponse>> {
  const payload: AskRequest = { question };
  return apiRequest<AskResponse>(
    askNinfaPath(propertyId, decisionId),
    { method: "POST", body: payload },
    fetchImpl,
  );
}

export function askHomePath(propertyId: string): string {
  return `/api/v1/properties/${propertyId}/ask`;
}

/** POST /api/v1/properties/{propertyId}/ask (Home UI V1, "Mia Home"): one question, one grounded
 * answer about TODAY'S feed of ONE property - built server-side only from what the Decision Engine
 * already decided (decisions, coverage, freshness). Like `askNinfa` above: nothing is persisted and
 * no conversation id is ever sent or received. `asOfLocalDate` is the property-local business date
 * of the feed on screen (never a server clock, never the browser's timezone). */
export function askMiaHome(
  propertyId: string,
  asOfLocalDate: string,
  question: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<AskResponse>> {
  const payload: AskHomeRequest = { question, as_of_local_date: asOfLocalDate };
  return apiRequest<AskResponse>(
    askHomePath(propertyId),
    { method: "POST", body: payload },
    fetchImpl,
  );
}
