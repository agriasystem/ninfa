import { afterEach, describe, expect, it, vi } from "vitest";

import { askHomePath, askMiaHome, askNinfa, askNinfaPath } from "./ask-ninfa";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("askHomePath", () => {
  it("is the property-level route, distinct from the Decision Ask route", () => {
    expect(askHomePath("prop-1")).toBe("/api/v1/properties/prop-1/ask");
    expect(askNinfaPath("prop-1", "dec-1")).toBe("/api/v1/properties/prop-1/decisions/dec-1/ask");
  });
});

describe("askMiaHome", () => {
  it("POSTs the question AND the explicit business date, with credentials and no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const body = { status: "ANSWERED", answer: "Una decisione.", grounding_refs: [], limitations: [] };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body));

    const result = await askMiaHome("prop-1", "2026-10-08", "Qual è la priorità più urgente oggi?", fetchImpl);

    expect(result).toEqual({ ok: true, data: body });
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/v1/properties/prop-1/ask");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(JSON.parse(init.body as string)).toEqual({
      question: "Qual è la priorità più urgente oggi?",
      as_of_local_date: "2026-10-08",
    });
  });

  it("never sends a thread, conversation or message id (one question, one answer)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "ANSWERED", answer: "x", grounding_refs: [], limitations: [] }));

    await askMiaHome("prop-1", "2026-10-08", "Ciao?", fetchImpl);

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(Object.keys(JSON.parse(init.body as string)).sort()).toEqual(["as_of_local_date", "question"]);
  });

  it("turns an API error into a typed failure, never a throw", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ error: { code: "INVALID_AS_OF_DATE", message: "bad", details: null, request_id: null } }, 400),
    );

    const result = await askMiaHome("prop-1", "nope", "Ciao?", fetchImpl);

    expect(result).toEqual({ ok: false, status: 400, code: "INVALID_AS_OF_DATE", message: "bad" });
  });

  it("does not touch the Decision Ask: it keeps its own path and body", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "ANSWERED", answer: "x", grounding_refs: [], limitations: [] }));

    await askNinfa("prop-1", "dec-1", "Perché?", fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/v1/properties/prop-1/decisions/dec-1/ask");
    expect(JSON.parse(init.body as string)).toEqual({ question: "Perché?" });
  });
});
