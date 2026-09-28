import type { AskRequest, AskResponse } from "@ninfa/contracts";

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
