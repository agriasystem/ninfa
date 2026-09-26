import { afterEach, describe, expect, it, vi } from "vitest";

import type { DecisionDetailResponse, DecisionHistoryResponse } from "@ninfa/contracts";

import {
  decisionDetailPath,
  decisionFeedPath,
  decisionHistoryPath,
  getDecisionDetail,
  getDecisionFeed,
  getDecisionHistory,
} from "./decisions";

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

describe("decisionDetailPath", () => {
  it("builds the exact Gate 12 detail path", () => {
    expect(decisionDetailPath("prop-1", "dec-1")).toBe("/api/v1/properties/prop-1/decisions/dec-1");
  });
});

describe("getDecisionDetail", () => {
  it("GETs the detail with credentials include and no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const detail: DecisionDetailResponse = {
      decision_id: "dec-1",
      decision_type: "REV_PICKUP_LOW",
      status: "OPEN",
      first_seen_local_date: "2026-09-20",
      last_seen_local_date: "2026-09-26",
      last_evaluated_local_date: "2026-09-26",
      resolved_local_date: null,
      episode_count: 1,
      triggered_observation_count: 1,
      target: { type: "REV_PICKUP_LOW", booking_data_source_id: "src-1", stay_date: "2026-10-01" },
      latest_observation: {
        observation_id: "obs-1",
        as_of_local_date: "2026-09-26",
        source_status: "TRIGGERED",
        lifecycle_transition: "OPENED",
        source_evaluation_fingerprint: "fp",
        source_target_key: "key",
        reason_codes: [],
        confidence_score: "0.8",
        priority: null,
        facts: {},
        evidence: {},
        economic_proxy: null,
        memory_version: "v1",
      },
      decision_api_version: "decision-api-v1",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(detail));

    const result = await getDecisionDetail("prop-1", "dec-1", fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/api/v1/properties/prop-1/decisions/dec-1");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(result).toEqual({ ok: true, data: detail });
  });

  it("surfaces a 404 DECISION_NOT_FOUND as a stable error", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "DECISION_NOT_FOUND", message: "Decision not found", details: null, request_id: null } },
        404,
      ),
    );

    const result = await getDecisionDetail("prop-1", "unknown-decision", fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 404,
      code: "DECISION_NOT_FOUND",
      message: "Decision not found",
    });
  });
});

describe("decisionHistoryPath", () => {
  it("builds the path with no query when no options are given", () => {
    expect(decisionHistoryPath("prop-1", "dec-1")).toBe(
      "/api/v1/properties/prop-1/decisions/dec-1/history",
    );
  });

  it("includes cursor and limit when given, passing the cursor back verbatim", () => {
    expect(decisionHistoryPath("prop-1", "dec-1", { cursor: "opaque-cursor==", limit: 10 })).toBe(
      "/api/v1/properties/prop-1/decisions/dec-1/history?cursor=opaque-cursor%3D%3D&limit=10",
    );
  });
});

describe("getDecisionHistory", () => {
  it("GETs the first page with credentials include and no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const history: DecisionHistoryResponse = { items: [], next_cursor: null };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(history));

    const result = await getDecisionHistory("prop-1", "dec-1", {}, fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example/api/v1/properties/prop-1/decisions/dec-1/history",
    );
    expect(result).toEqual({ ok: true, data: history });
  });

  it("passes an opaque cursor through to the next page request unchanged", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));

    await getDecisionHistory("prop-1", "dec-1", { cursor: "opaque-cursor-value" }, fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toContain("cursor=opaque-cursor-value");
  });
});
