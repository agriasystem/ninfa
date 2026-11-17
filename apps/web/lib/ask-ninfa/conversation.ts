import type { AskState } from "./state";

/**
 * The exchanges Mia shows on screen: the newest few of the person's conversation. The conversation
 * itself is the SERVER's (Mia OpenAI Intelligence V1): it is restored after a refresh or a navigation,
 * and the browser never sends it back - a follow-up such as "Perché?" is understood from what the
 * server holds, and every fact is read again through the backend's tools for each question. What is
 * kept here is only what is drawn.
 */

/** The newest exchanges shown, INCLUDING the one being asked: the area above the bar stays small, so
 * the operational Home is never pushed away (older ones stay in the server's conversation). */
export const MAX_EXCHANGES = 4;

export interface Exchange {
  /** Stable identity of the exchange (never reused), so a late response lands on the right one. */
  id: number;
  /** The question exactly as submitted (trimmed). */
  question: string;
  state: AskState;
}

/** The newest `MAX_EXCHANGES` of `exchanges`. */
export function retainRecent(exchanges: readonly Exchange[]): Exchange[] {
  return exchanges.slice(-MAX_EXCHANGES);
}
