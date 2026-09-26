import type { LoginRequest, SessionContextResponse } from "@ninfa/contracts";

import { apiRequest, type ApiResult } from "@/lib/api/client";

export const LOGIN_PATH = "/api/v1/auth/login";
export const LOGOUT_PATH = "/api/v1/auth/logout";
export const SESSION_PATH = "/api/v1/auth/session";

/** POST /api/v1/auth/login. On success, the response IS the session context - callers should
 * use it directly rather than immediately re-fetching `getSession()`. */
export function login(
  payload: LoginRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<SessionContextResponse>> {
  return apiRequest<SessionContextResponse>(LOGIN_PATH, { method: "POST", body: payload }, fetchImpl);
}

/** POST /api/v1/auth/logout. Revokes the current session server-side; the cookie is cleared by
 * the response itself (never deleted client-side by JS - it is `HttpOnly`, JS cannot read it). */
export function logout(fetchImpl: typeof fetch = fetch): Promise<ApiResult<undefined>> {
  return apiRequest<undefined>(LOGOUT_PATH, { method: "POST" }, fetchImpl);
}

/** GET /api/v1/auth/session. `ok: false` (any status, typically 401) means "not authenticated" -
 * callers never distinguish "no session" from a network error for the purpose of the auth
 * bootstrap decision (loading -> authenticated | unauthenticated). */
export function getSession(
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<SessionContextResponse>> {
  return apiRequest<SessionContextResponse>(SESSION_PATH, { method: "GET" }, fetchImpl);
}
