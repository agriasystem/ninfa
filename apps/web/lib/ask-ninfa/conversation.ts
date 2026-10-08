import type { AskHomeHistoryMessage } from "@ninfa/contracts";

import type { AskState } from "./state";

/**
 * The short conversation of the Mia Home page session (Mia V2): a handful of exchanges kept ONLY in
 * the page's memory - never stored, lost on reload - and sent back with each new question so that a
 * follow-up ("Perché?", "Intendo gli OTA, sono a posto?") can be understood.
 *
 * It is referential context, not business truth: the backend rebuilds every fact fresh from NINFA for
 * each question, so an old answer on screen can never turn into a "known fact" for the next one.
 */

/** The newest exchanges kept (and shown), INCLUDING the one being asked. The history sent with a new
 * question is therefore at most `MAX_EXCHANGES - 1` complete exchanges (the backend accepts up to 4,
 * so there is headroom). */
export const MAX_EXCHANGES = 4;

export interface Exchange {
  /** Stable identity of the exchange (never reused), so a late response lands on the right one. */
  id: number;
  /** The question exactly as submitted (trimmed). */
  question: string;
  state: AskState;
}

/** Mia's answer text of a finished exchange, or `null` when it has none worth remembering (still
 * loading, refused, unavailable, a network error, or a reply without text). */
export function answerTextOf(state: AskState): string | null {
  if (state.kind === "answered" || state.kind === "insufficientContext") {
    const text = state.answer?.trim() ?? "";
    return text.length > 0 ? text : null;
  }
  return null;
}

/** The newest `MAX_EXCHANGES` of `exchanges`. */
export function retainRecent(exchanges: readonly Exchange[]): Exchange[] {
  return exchanges.slice(-MAX_EXCHANGES);
}

/** The history to send for a question that comes AFTER `prior`: only COMPLETE exchanges (a question
 * with Mia's answer text), oldest first, as alternating user/assistant messages. An exchange that
 * failed, was refused or is still loading contributes nothing - a lone question would break the
 * strict user/assistant alternation the backend requires, and a refusal must never be replayed as
 * context. */
export function historyOf(prior: readonly Exchange[]): AskHomeHistoryMessage[] {
  return prior.flatMap((exchange) => {
    const answer = answerTextOf(exchange.state);
    if (answer === null) return [];
    return [
      { role: "user" as const, content: exchange.question },
      { role: "assistant" as const, content: answer },
    ];
  });
}
