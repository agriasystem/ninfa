import type {
  MiaAnswerResponse,
  MiaConversationListResponse,
  MiaConversationResponse,
  MiaMessageRequest,
  MiaUiContext,
} from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

/** Mia's routes (Mia OpenAI Intelligence V1): everything is scoped by the property in the PATH - the
 * body never names a property, a workspace, a history or a tool. */
export function miaMessagesPath(propertyId: string): string {
  return `/api/v1/properties/${propertyId}/mia/messages`;
}

export function miaConversationsPath(propertyId: string): string {
  return `/api/v1/properties/${propertyId}/mia/conversations`;
}

export function miaConversationPath(propertyId: string, conversationId: string): string {
  return `${miaConversationsPath(propertyId)}/${encodeURIComponent(conversationId)}`;
}

export interface SendMiaMessageInput {
  message: string;
  /** The property-local business date (`YYYY-MM-DD`) the person is looking at - never a server clock,
   * never the browser's timezone. */
  asOfLocalDate: string;
  /** Absent: a NEW conversation. Present: continue that one (a stale or foreign id is a 404). */
  conversationId?: string | null;
  /** The validated, bounded hint about the screen (`lib/mia/ui-context`). Omitted when empty. */
  uiContext?: MiaUiContext;
}

/** POST .../mia/messages: one message, one answer, in the person's own conversation about this
 * property. The body carries the message, the business date and - only when there is one - the
 * conversation id and the screen hint. NEVER a history (the conversation is the server's own).
 *
 * No streaming in V1: the backend checks the whole answer (its numbers, its length) before anything
 * leaves, so there is nothing safe to show before the full answer is back. A network or HTTP failure
 * comes back as a failed `ApiResult` and is shown like any other "unavailable" (`lib/mia/state`). The
 * content of a message is never logged here. */
export function sendMiaMessage(
  propertyId: string,
  input: SendMiaMessageInput,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<MiaAnswerResponse>> {
  const payload: MiaMessageRequest = {
    message: input.message,
    as_of_local_date: input.asOfLocalDate,
  };
  if (input.conversationId) payload.conversation_id = input.conversationId;
  if (input.uiContext !== undefined && Object.keys(input.uiContext).length > 0) {
    payload.ui_context = input.uiContext;
  }
  return apiRequest<MiaAnswerResponse>(
    miaMessagesPath(propertyId),
    { method: "POST", body: payload },
    fetchImpl,
  );
}

/** GET .../mia/conversations: the person's recent conversations about this property, newest first. */
export function listMiaConversations(
  propertyId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<MiaConversationListResponse>> {
  return apiRequest<MiaConversationListResponse>(miaConversationsPath(propertyId), {}, fetchImpl);
}

/** GET .../mia/conversations/{id}: one conversation, to restore it after a refresh or a navigation. */
export function getMiaConversation(
  propertyId: string,
  conversationId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<MiaConversationResponse>> {
  return apiRequest<MiaConversationResponse>(
    miaConversationPath(propertyId, conversationId),
    {},
    fetchImpl,
  );
}
