import type { ApiErrorResponse } from "@ninfa/contracts";

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; code: string; message: string };

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== "object" || value === null) return false;
  const error = (value as Record<string, unknown>).error;
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

export function apiBaseUrl(): string | undefined {
  return process.env.NEXT_PUBLIC_API_BASE_URL;
}

/**
 * Calls `{baseUrl}{path}`. Every call sends `credentials: "include"` - the ONLY way the Gate 13
 * session cookie is ever attached, never a stored token - and `cache: "no-store"`, since an
 * authenticated read must never be served from the browser's HTTP cache. Never throws: a network
 * failure, a non-JSON body, or a backend error envelope all come back as a typed `ApiResult`, and
 * the caller never sees a raw `Response`, a stack trace, or backend internals (no `details`, no
 * `request_id`, no SQL - see docs/architecture/oggi-ui-v1.md, "Error handling").
 */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<T>> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    return {
      ok: false,
      status: 0,
      code: "CLIENT_MISCONFIGURED",
      message: "NEXT_PUBLIC_API_BASE_URL is not set",
    };
  }

  const url = baseUrl.replace(/\/+$/, "") + path;
  const hasBody = options.body !== undefined;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: options.method ?? "GET",
      headers: hasBody
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: hasBody ? JSON.stringify(options.body) : undefined,
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    return {
      ok: false,
      status: 0,
      code: "NETWORK_ERROR",
      message: error instanceof Error ? error.message : "Network error",
    };
  }

  if (response.status === 204) {
    return { ok: true, data: undefined as T };
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (response.ok) {
    return { ok: true, data: payload as T };
  }
  if (isApiErrorResponse(payload)) {
    return {
      ok: false,
      status: response.status,
      code: payload.error.code,
      message: payload.error.message,
    };
  }
  return {
    ok: false,
    status: response.status,
    code: "UNKNOWN_ERROR",
    message: `Request failed with status ${response.status}`,
  };
}
