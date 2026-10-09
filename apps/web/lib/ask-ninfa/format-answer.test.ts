import { describe, expect, it } from "vitest";

import { answerBlocksOf } from "./format-answer";

describe("answerBlocksOf", () => {
  it("returns a single paragraph for an answer with no line structure", () => {
    expect(answerBlocksOf("Una sola frase.")).toEqual([
      { kind: "paragraph", text: "Una sola frase." },
    ]);
  });

  it("splits paragraphs on blank lines", () => {
    expect(answerBlocksOf("Prima parte.\n\nSeconda parte.")).toEqual([
      { kind: "paragraph", text: "Prima parte." },
      { kind: "paragraph", text: "Seconda parte." },
    ]);
  });

  it("turns '- ' lines into one list, with the intro line as its own paragraph", () => {
    const answer = [
      "Sì, oltre alla prima NINFA ha rilevato anche:",
      "- Rischio occupazione (Ricavi), data del soggiorno 22 agosto",
      "- Dipendenza OTA (Distribuzione)",
      "",
      "Non sono state analizzate le aree: Costi, Personale.",
    ].join("\n");

    expect(answerBlocksOf(answer)).toEqual([
      { kind: "paragraph", text: "Sì, oltre alla prima NINFA ha rilevato anche:" },
      {
        kind: "list",
        items: [
          "Rischio occupazione (Ricavi), data del soggiorno 22 agosto",
          "Dipendenza OTA (Distribuzione)",
        ],
      },
      { kind: "paragraph", text: "Non sono state analizzate le aree: Costi, Personale." },
    ]);
  });

  it("accepts '•' and '*' bullets too, and indentation before the marker", () => {
    expect(answerBlocksOf("• Uno\n  * Due\n   - Tre")).toEqual([
      { kind: "list", items: ["Uno", "Due", "Tre"] },
    ]);
  });

  it("does not mistake a dash or a negative number for a bullet", () => {
    expect(answerBlocksOf("-3 camere rispetto all'atteso\nNINFA - prima nell'ordine")).toEqual([
      { kind: "paragraph", text: "-3 camere rispetto all'atteso NINFA - prima nell'ordine" },
    ]);
  });

  it("joins plain consecutive lines into one paragraph", () => {
    expect(answerBlocksOf("Una riga\ne ancora la stessa frase.")).toEqual([
      { kind: "paragraph", text: "Una riga e ancora la stessa frase." },
    ]);
  });

  it("handles Windows and old-Mac line endings", () => {
    expect(answerBlocksOf("A\r\n\r\n- B\r\n- C")).toEqual([
      { kind: "paragraph", text: "A" },
      { kind: "list", items: ["B", "C"] },
    ]);
    expect(answerBlocksOf("A\r\rB")).toEqual([
      { kind: "paragraph", text: "A" },
      { kind: "paragraph", text: "B" },
    ]);
  });

  it("returns no blocks for an empty or whitespace-only answer", () => {
    expect(answerBlocksOf("")).toEqual([]);
    expect(answerBlocksOf("  \n \n")).toEqual([]);
  });

  it("interprets nothing: markup and HTML stay literal text", () => {
    const text = "**grassetto** <b>html</b> [link](http://x) # titolo";
    expect(answerBlocksOf(text)).toEqual([{ kind: "paragraph", text }]);
  });

  it("never drops a word of the answer", () => {
    const answer = "Intro.\n- Uno due\n- tre quattro\n\nChiusura finale.";
    const words = (value: string) => value.split(/\s+/u).filter((word) => word !== "" && word !== "-");
    const rendered = answerBlocksOf(answer)
      .flatMap((block) => (block.kind === "paragraph" ? [block.text] : block.items))
      .join(" ");
    expect(words(rendered)).toEqual(words(answer));
  });
});
