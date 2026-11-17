import type { MiaAnswerResponse, MiaConversationResponse } from "@ninfa/contracts";

import type { ApiResult } from "@/lib/api/client";
import { MAX_EXCHANGES, retainRecent, type Exchange } from "@/lib/ask-ninfa/conversation";
import { stateFromResponse, type AskState } from "@/lib/ask-ninfa/state";

/** What the person sees for the result of one message. A network or HTTP failure is shown EXACTLY like
 * the backend's own `UNAVAILABLE`: one dignified, non-technical line and a manual retry - never a status
 * code, never the raw message (`ApiResult.message` is for developers, not for the screen). */
export function stateOfMiaResult(result: ApiResult<MiaAnswerResponse>): AskState {
  return result.ok ? stateFromResponse(result.data) : { kind: "unavailable" };
}

/** The exchanges of a stored conversation, as the screen shows them: every user message followed by
 * Mia's answer, newest `MAX_EXCHANGES` kept. The server only records COMPLETE exchanges, so a user
 * message with no answer after it (or an answer with no text) is skipped rather than invented. Ids are
 * handed out by `nextId` so a restored exchange can never collide with a new one. */
export function exchangesOfConversation(
  conversation: MiaConversationResponse,
  nextId: () => number,
): Exchange[] {
  const exchanges: Exchange[] = [];
  const messages = conversation.messages;
  for (let index = 0; index < messages.length - 1; index += 1) {
    const asked = messages[index];
    const answered = messages[index + 1];
    if (asked?.role !== "user" || answered?.role !== "assistant") continue;
    const text = answered.content.trim();
    if (text.length === 0) continue;
    const state: AskState =
      answered.status === "INSUFFICIENT_CONTEXT"
        ? { kind: "insufficientContext", answer: text, limitations: answered.limitations }
        : { kind: "answered", answer: text, limitations: answered.limitations };
    exchanges.push({ id: nextId(), question: asked.content, state });
    index += 1;
  }
  return retainRecent(exchanges.slice(-MAX_EXCHANGES));
}
