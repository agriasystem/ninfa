import type { AskResponse } from "@ninfa/contracts";

/** The one-question/one-answer surface's states - shared by the Decision Detail's own panel
 * (`AskNinfaPanel`) and the Home's property-level Mia (`MiaHome`): the SAME closed `AskStatus`
 * protocol answers both, so the SAME mapping renders both. */
export type AskState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "answered"; answer: string; limitations: string[] }
  | { kind: "insufficientContext"; answer: string | null; limitations: string[] }
  | { kind: "unavailable" }
  | { kind: "refused" }
  | { kind: "error" };

/** Maps the backend's own closed `AskStatus` (Gate 18) onto this UI state - an exhaustive
 * `switch`, so a future fifth status value fails to compile here rather than silently falling
 * through to nothing. */
export function stateFromResponse(data: AskResponse): AskState {
  switch (data.status) {
    case "ANSWERED":
      return { kind: "answered", answer: data.answer ?? "", limitations: data.limitations };
    case "INSUFFICIENT_CONTEXT":
      return { kind: "insufficientContext", answer: data.answer, limitations: data.limitations };
    case "UNAVAILABLE":
      return { kind: "unavailable" };
    case "REFUSED":
      return { kind: "refused" };
  }
}

/** The backend's own question bound (`MAX_QUESTION_LENGTH`, `app/modules/ai/ask_ninfa/types.py`). */
export const MAX_QUESTION_LENGTH = 1000;
