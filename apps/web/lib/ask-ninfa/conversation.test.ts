import { describe, expect, it } from "vitest";

import { MAX_EXCHANGES, answerTextOf, historyOf, retainRecent, type Exchange } from "./conversation";

function exchange(id: number, question: string, state: Exchange["state"]): Exchange {
  return { id, question, state };
}

const answered = (id: number, question: string, answer: string) =>
  exchange(id, question, { kind: "answered", answer, limitations: [] });

describe("answerTextOf", () => {
  it("is Mia's text for an answer and for an explanation of what she cannot say", () => {
    expect(answerTextOf({ kind: "answered", answer: " Sì. ", limitations: [] })).toBe("Sì.");
    expect(answerTextOf({ kind: "insufficientContext", answer: "Non posso.", limitations: [] })).toBe(
      "Non posso.",
    );
  });

  it("is null when there is nothing worth remembering", () => {
    expect(answerTextOf({ kind: "idle" })).toBeNull();
    expect(answerTextOf({ kind: "loading" })).toBeNull();
    expect(answerTextOf({ kind: "unavailable" })).toBeNull();
    expect(answerTextOf({ kind: "refused" })).toBeNull();
    expect(answerTextOf({ kind: "error" })).toBeNull();
    expect(answerTextOf({ kind: "answered", answer: "   ", limitations: [] })).toBeNull();
    expect(answerTextOf({ kind: "insufficientContext", answer: null, limitations: [] })).toBeNull();
  });
});

describe("historyOf", () => {
  it("is empty before any exchange", () => {
    expect(historyOf([])).toEqual([]);
  });

  it("turns complete exchanges into alternating user/assistant messages, oldest first", () => {
    const history = historyOf([
      answered(1, "Gli OTA sono a posto?", "Per quanto analizzato oggi..."),
      answered(2, "Perché?", "Perché la quota è sotto il riferimento."),
    ]);

    expect(history).toEqual([
      { role: "user", content: "Gli OTA sono a posto?" },
      { role: "assistant", content: "Per quanto analizzato oggi..." },
      { role: "user", content: "Perché?" },
      { role: "assistant", content: "Perché la quota è sotto il riferimento." },
    ]);
  });

  it("drops a refused, failed, unavailable or still-loading exchange - never a lone question", () => {
    const history = historyOf([
      exchange(1, "Abbassa il prezzo", { kind: "refused" }),
      exchange(2, "Una domanda andata male", { kind: "error" }),
      exchange(3, "Una domanda non disponibile", { kind: "unavailable" }),
      answered(4, "Una buona domanda", "Una buona risposta."),
      exchange(5, "In corso", { kind: "loading" }),
    ]);

    expect(history).toEqual([
      { role: "user", content: "Una buona domanda" },
      { role: "assistant", content: "Una buona risposta." },
    ]);
    expect(history.length % 2).toBe(0); // always whole exchanges: the backend requires it
  });

  it("an explanation of what Mia cannot say is still a complete exchange", () => {
    expect(
      historyOf([
        exchange(1, "Qual è il revpar?", {
          kind: "insufficientContext",
          answer: "NINFA non calcola il RevPAR.",
          limitations: [],
        }),
      ]),
    ).toEqual([
      { role: "user", content: "Qual è il revpar?" },
      { role: "assistant", content: "NINFA non calcola il RevPAR." },
    ]);
  });
});

describe("retainRecent", () => {
  it("keeps the newest four", () => {
    const all = Array.from({ length: 6 }, (_, index) => answered(index, `D${index}`, `R${index}`));

    expect(MAX_EXCHANGES).toBe(4);
    expect(retainRecent(all).map((item) => item.id)).toEqual([2, 3, 4, 5]);
    expect(retainRecent(all.slice(0, 2))).toHaveLength(2);
  });
});
