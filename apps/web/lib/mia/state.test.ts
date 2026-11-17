import { describe, expect, it } from "vitest";

import type { MiaAnswerResponse, MiaConversationResponse } from "@ninfa/contracts";

import { exchangesOfConversation, stateOfMiaResult } from "./state";

const ok = (data: Partial<MiaAnswerResponse>) => ({
  ok: true as const,
  data: {
    status: "ANSWERED" as const,
    answer: "x",
    limitations: [],
    grounding_refs: [],
    conversation_id: "c1",
    ...data,
  },
});

describe("stateOfMiaResult", () => {
  it("maps each of the backend's own statuses", () => {
    expect(stateOfMiaResult(ok({ answer: "Sì.", limitations: ["Solo oggi."] }))).toEqual({
      kind: "answered",
      answer: "Sì.",
      limitations: ["Solo oggi."],
    });
    expect(stateOfMiaResult(ok({ status: "INSUFFICIENT_CONTEXT", answer: "Non so." }))).toEqual({
      kind: "insufficientContext",
      answer: "Non so.",
      limitations: [],
    });
    expect(stateOfMiaResult(ok({ status: "REFUSED", answer: null }))).toEqual({ kind: "refused" });
    expect(stateOfMiaResult(ok({ status: "UNAVAILABLE", answer: null }))).toEqual({
      kind: "unavailable",
    });
  });

  it("shows a network or HTTP failure exactly as UNAVAILABLE - never a status code, never the message", () => {
    const failed = { ok: false as const, status: 500, code: "UNKNOWN_ERROR", message: "boom" };
    const network = { ok: false as const, status: 0, code: "NETWORK_ERROR", message: "offline" };

    expect(stateOfMiaResult(failed)).toEqual({ kind: "unavailable" });
    expect(stateOfMiaResult(network)).toEqual({ kind: "unavailable" });
  });
});

describe("exchangesOfConversation", () => {
  const message = (
    role: "user" | "assistant",
    content: string,
    extra: Partial<MiaConversationResponse["messages"][number]> = {},
  ) => ({ role, content, created_at: "2026-10-08T09:00:00Z", limitations: [], ...extra });
  const conversation = (messages: MiaConversationResponse["messages"]): MiaConversationResponse => ({
    id: "c1",
    title: "t",
    updated_at: "2026-10-08T09:00:00Z",
    messages,
  });
  const ids = () => {
    let next = 10;
    return () => next++;
  };

  it("pairs every user message with Mia's answer, oldest first, with fresh ids", () => {
    const result = exchangesOfConversation(
      conversation([
        message("user", "Prima?"),
        message("assistant", "Prima risposta.", { status: "ANSWERED", limitations: ["Nota."] }),
        message("user", "Seconda?"),
        message("assistant", "Non posso dirlo.", { status: "INSUFFICIENT_CONTEXT" }),
      ]),
      ids(),
    );

    expect(result).toEqual([
      {
        id: 10,
        question: "Prima?",
        state: { kind: "answered", answer: "Prima risposta.", limitations: ["Nota."] },
      },
      {
        id: 11,
        question: "Seconda?",
        state: { kind: "insufficientContext", answer: "Non posso dirlo.", limitations: [] },
      },
    ]);
  });

  it("skips what is not a complete exchange rather than inventing it", () => {
    const result = exchangesOfConversation(
      conversation([
        message("assistant", "Una risposta senza domanda."),
        message("user", "Una domanda con risposta vuota?"),
        message("assistant", "   "),
        message("user", "Una domanda senza risposta?"),
      ]),
      ids(),
    );

    expect(result).toEqual([]);
  });

  it("keeps only the newest four exchanges", () => {
    const messages = [1, 2, 3, 4, 5, 6].flatMap((n) => [
      message("user", `D${n}?`),
      message("assistant", `R${n}.`, { status: "ANSWERED" }),
    ]);

    const result = exchangesOfConversation(conversation(messages), ids());

    expect(result.map((exchange) => exchange.question)).toEqual(["D3?", "D4?", "D5?", "D6?"]);
  });

  it("treats an unknown assistant status as an ordinary answer (an open string on the wire)", () => {
    const result = exchangesOfConversation(
      conversation([message("user", "Q?"), message("assistant", "A.", { status: "SOMETHING_NEW" })]),
      ids(),
    );

    expect(result[0]?.state).toEqual({ kind: "answered", answer: "A.", limitations: [] });
  });
});
