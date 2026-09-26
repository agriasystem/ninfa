import { afterEach, describe, expect, it, vi } from "vitest";

import { decisionFeedPath, getDecisionFeed } from "./decisions";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("decisionFeedPath", () => {
  it("builds the exact Gate 12 path with an explicit as_of query parameter", () => {
    expect(decisionFeedPath("prop-1", "2026-09-26")).toBe(
      "/api/v1/properties/prop-1/decision-feed?as_of=2026-09-26",
    );
  });
});

describe("getDecisionFeed", () => {
  it("GETs the feed with credentials include and the explicit as_of date", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const feed = {
      property_id: "prop-1",
      as_of_local_date: "2026-09-26",
      feed_state: "NO_ACTION_REQUIRED",
      decision_run_id: "run-1",
      run_sequence: 1,
      triggered_count: 0,
      clear_count: 3,
      insufficient_count: 0,
      not_applicable_count: 0,
      suppressed_count: 0,
      items: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(feed));

    const result = await getDecisionFeed("prop-1", "2026-09-26", fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example/api/v1/properties/prop-1/decision-feed?as_of=2026-09-26",
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(result).toEqual({ ok: true, data: feed });
  });

  it("surfaces a 404 PROPERTY_NOT_FOUND as a stable error, never a raw exception", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "PROPERTY_NOT_FOUND", message: "Property not found", details: null, request_id: null } },
        404,
      ),
    );

    const result = await getDecisionFeed("unknown-prop", "2026-09-26", fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 404,
      code: "PROPERTY_NOT_FOUND",
      message: "Property not found",
    });
  });
});
