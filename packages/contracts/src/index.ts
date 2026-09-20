/**
 * Minimal shared API types (Gate 0).
 *
 * The authoritative API contract is the backend's Pydantic/FastAPI models, published as OpenAPI
 * at /openapi.json. These hand-written types only mirror what the frontend already consumes
 * (health + error envelope). The definitive strategy for keeping frontend types in sync with
 * OpenAPI is deliberately deferred to a later gate: no code generation exists yet.
 */

/** GET /api/v1/health */
export interface HealthResponse {
  status: "ok";
  service: string;
  /** Application version (single source: services/api/pyproject.toml). */
  version: string;
}

/** Body of every non-2xx API response. */
export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    details: unknown;
    request_id: string | null;
  };
}
