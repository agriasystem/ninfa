import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("apiRequest", () => {
  it("reads the base URL from NEXT_PUBLIC_API_BASE_URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/api/v1/health", {}, fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://api.example/api/v1/health");
  });

  it("reports a missing base URL as a client misconfiguration, without calling the network", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", undefined);
    const fetchMock = vi.fn();

    const result = await apiRequest("/api/v1/health", {}, fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 0,
      code: "CLIENT_MISCONFIGURED",
      message: "NEXT_PUBLIC_API_BASE_URL is not set",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("always sends credentials: include - the only way the session cookie is ever attached", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/api/v1/auth/session", {}, fetchMock);

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "include" });
  });

  it("always sends cache: no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/api/v1/auth/session", {}, fetchMock);

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
  });

  it("serialises a JSON body and sets Content-Type only when a body is present", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));

    await apiRequest("/api/v1/auth/login", { method: "POST", body: { email: "a@b.c" } }, fetchMock);

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ email: "a@b.c" }));
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("returns the parsed body on a 2xx response", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "ok" }));

    const result = await apiRequest<{ status: string }>("/api/v1/health", {}, fetchMock);

    expect(result).toEqual({ ok: true, data: { status: "ok" } });
  });

  it("treats 204 No Content as success with no body", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    const result = await apiRequest("/api/v1/auth/logout", { method: "POST" }, fetchMock);

    expect(result).toEqual({ ok: true, data: undefined });
  });

  it("parses the Gate 12/13 error envelope into a stable {code, message} shape", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "INVALID_CREDENTIALS", message: "Invalid email or password", details: null, request_id: "abc" } },
        401,
      ),
    );

    const result = await apiRequest("/api/v1/auth/login", { method: "POST", body: {} }, fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 401,
      code: "INVALID_CREDENTIALS",
      message: "Invalid email or password",
    });
  });

  it("never exposes details/request_id/raw body to the caller", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "bad",
            details: [{ loc: ["body", "password"], msg: "leaked?", type: "value_error" }],
            request_id: "should-not-leak",
          },
        },
        422,
      ),
    );

    const result = await apiRequest("/api/v1/auth/login", { method: "POST", body: {} }, fetchMock);

    expect(Object.keys(result)).toEqual(["ok", "status", "code", "message"]);
  });

  it("falls back to a stable unknown-error shape for a non-envelope error body", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ surprising: true }, 500));

    const result = await apiRequest("/api/v1/health", {}, fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 500,
      code: "UNKNOWN_ERROR",
      message: "Request failed with status 500",
    });
  });

  it("reports a network failure as a generic NETWORK_ERROR, never a thrown exception", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const result = await apiRequest("/api/v1/health", {}, fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 0,
      code: "NETWORK_ERROR",
      message: "Failed to fetch",
    });
  });
});
