import type { HealthResponse } from "@ninfa/contracts";

export const HEALTH_PATH = "/api/v1/health";

export type HealthResult =
  | { state: "ok"; health: HealthResponse }
  | { state: "unreachable"; reason: string }
  | { state: "misconfigured"; reason: string };

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "ok" &&
    typeof candidate.service === "string" &&
    typeof candidate.version === "string"
  );
}

/** Calls GET {baseUrl}/api/v1/health. Never throws: failures are returned as a result. */
export async function fetchHealth(
  baseUrl: string | undefined,
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<HealthResult> {
  if (!baseUrl) {
    return { state: "misconfigured", reason: "NEXT_PUBLIC_API_BASE_URL is not set" };
  }

  const url = baseUrl.replace(/\/+$/, "") + HEALTH_PATH;
  try {
    const response = await fetchImpl(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
    if (!response.ok) {
      return { state: "unreachable", reason: `API answered HTTP ${response.status}` };
    }
    const body: unknown = await response.json();
    if (!isHealthResponse(body)) {
      return { state: "unreachable", reason: "Unexpected health response" };
    }
    return { state: "ok", health: body };
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Unknown error";
    return { state: "unreachable", reason };
  }
}
