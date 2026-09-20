import { describe, expect, it, vi } from "vitest";

import { fetchHealth } from "./health";

const okBody = { status: "ok", service: "ninfa-api", version: "0.1.0" };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("fetchHealth", () => {
  it("returns the health payload when the API answers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(okBody));

    const result = await fetchHealth("https://api.example", fetchMock);

    expect(result).toEqual({ state: "ok", health: okBody });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example/api/v1/health",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("normalises trailing slashes in the base URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(okBody));

    await fetchHealth("https://api.example//", fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/api/v1/health");
  });

  it("reports a missing base URL as misconfiguration without calling the network", async () => {
    const fetchMock = vi.fn();

    const result = await fetchHealth(undefined, fetchMock);

    expect(result.state).toBe("misconfigured");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports non-2xx answers as unreachable", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ error: {} }, 503));

    const result = await fetchHealth("https://api.example", fetchMock);

    expect(result).toEqual({ state: "unreachable", reason: "API answered HTTP 503" });
  });

  it("reports network failures as unreachable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const result = await fetchHealth("https://api.example", fetchMock);

    expect(result).toEqual({ state: "unreachable", reason: "Failed to fetch" });
  });

  it("rejects payloads that do not match the health contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "degraded" }));

    const result = await fetchHealth("https://api.example", fetchMock);

    expect(result.state).toBe("unreachable");
  });
});
