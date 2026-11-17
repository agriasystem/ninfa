import { describe, expect, it } from "vitest";

import { MAX_EXCHANGES, retainRecent, type Exchange } from "./conversation";

describe("retainRecent", () => {
  it("keeps the newest exchanges, in order, and never more than the bounded area shows", () => {
    const all: Exchange[] = Array.from({ length: 6 }, (_, id) => ({
      id,
      question: `q${id}`,
      state: { kind: "answered", answer: `a${id}`, limitations: [] },
    }));

    expect(MAX_EXCHANGES).toBe(4);
    expect(retainRecent(all).map((item) => item.id)).toEqual([2, 3, 4, 5]);
    expect(retainRecent(all.slice(0, 2))).toHaveLength(2);
  });
});
