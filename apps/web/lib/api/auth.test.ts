import { afterEach, describe, expect, it, vi } from "vitest";

import { LOGIN_PATH, LOGOUT_PATH, SESSION_PATH, getSession, login, logout } from "./auth";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

const sessionContext = {
  user: { id: "u1", email: "a@b.c", display_name: null },
  session: { expires_at: "2026-12-31T00:00:00Z" },
  workspaces: [],
};

describe("login", () => {
  it("POSTs credentials to /api/v1/auth/login with credentials include", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sessionContext));

    const result = await login({ email: "a@b.c", password: "pw" }, fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://api.example${LOGIN_PATH}`);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.body).toBe(JSON.stringify({ email: "a@b.c", password: "pw" }));
    expect(result).toEqual({ ok: true, data: sessionContext });
  });

  it("returns the INVALID_CREDENTIALS envelope on a wrong password, never a raw exception", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "INVALID_CREDENTIALS", message: "Invalid email or password", details: null, request_id: null } },
        401,
      ),
    );

    const result = await login({ email: "a@b.c", password: "wrong" }, fetchMock);

    expect(result).toEqual({
      ok: false,
      status: 401,
      code: "INVALID_CREDENTIALS",
      message: "Invalid email or password",
    });
  });
});

describe("logout", () => {
  it("POSTs to /api/v1/auth/logout with credentials include", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    const result = await logout(fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://api.example${LOGOUT_PATH}`);
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe("POST");
    expect(result).toEqual({ ok: true, data: undefined });
  });
});

describe("getSession", () => {
  it("GETs /api/v1/auth/session with credentials include and no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sessionContext));

    const result = await getSession(fetchMock);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`https://api.example${SESSION_PATH}`);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(result).toEqual({ ok: true, data: sessionContext });
  });

  it("returns ok:false on a 401 (no session), never throwing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "AUTHENTICATION_REQUIRED", message: "Authentication is required", details: null, request_id: null } },
        401,
      ),
    );

    const result = await getSession(fetchMock);

    expect(result.ok).toBe(false);
  });
});
