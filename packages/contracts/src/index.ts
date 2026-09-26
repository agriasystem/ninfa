/**
 * Minimal shared API types (Gate 0, extended Gate 13/14).
 *
 * The authoritative API contract is the backend's Pydantic/FastAPI models, published as OpenAPI
 * at /openapi.json. These hand-written types only mirror what the frontend already consumes
 * (health, error envelope, auth session, decision feed). The definitive strategy for keeping
 * frontend types in sync with OpenAPI is deliberately deferred to a later gate: no code
 * generation exists yet.
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

// --- Authentication & Session V1 (Gate 13, `app/api/v1/auth/schemas.py`) -------------------------

/** POST /api/v1/auth/login request body. */
export interface LoginRequest {
  email: string;
  password: string;
}

export interface SessionUser {
  id: string;
  email: string;
  display_name: string | null;
}

export interface SessionInfo {
  /** ISO 8601 datetime, timezone-aware. */
  expires_at: string;
}

export interface PropertyAccess {
  id: string;
  name: string;
  slug: string;
  /** The Property's own canonical IANA zone (Gate 14 addition) - never the browser's. */
  timezone: string;
}

export interface WorkspaceAccess {
  id: string;
  name: string;
  slug: string;
  role: string;
  properties: PropertyAccess[];
}

/** Returned by both a successful POST /api/v1/auth/login and GET /api/v1/auth/session. */
export interface SessionContextResponse {
  user: SessionUser;
  session: SessionInfo;
  workspaces: WorkspaceAccess[];
}

// --- Decision API V1 (Gate 12, `app/api/v1/decisions/schemas.py`) --------------------------------

/** Every Decimal that decided something is a canonical STRING, never a float - never parse one
 * of these back into a JS Number to recompute, re-rank or re-threshold anything; it is for
 * DISPLAY formatting only. */
export type DecimalString = string;

export interface PrioritySnapshot {
  rank: number;
  impact_score: DecimalString;
  urgency_score: DecimalString;
  confidence_score: DecimalString;
  actionability_score: DecimalString;
  priority_score: DecimalString;
  candidate_fingerprint: string;
}

export interface EconomicProxy {
  label: string;
  amount: DecimalString;
  currency: string;
}

export type DecisionType =
  | "REV_PICKUP_LOW"
  | "REV_OCCUPANCY_RISK"
  | "REV_OTA_DEPENDENCY"
  | "COST_CPOR_ANOMALY"
  | "LABOR_OVERSTAFFING";

/** `Decision.status` (Gate 11) - exactly two values in V1, no SUPPRESSED/ARCHIVED/DISMISSED. */
export type DecisionStatus = "OPEN" | "RESOLVED";

/** What ONE Observation did to its Decision's lifecycle (Gate 11's own `LifecycleTransition`). */
export type LifecycleTransition = "OPENED" | "OBSERVED" | "RESOLVED" | "REOPENED" | "NO_STATE_CHANGE";

/** A detector's own five-status vocabulary, persisted as-is, never reinterpreted. */
export type SourceStatus =
  | "TRIGGERED"
  | "CLEAR"
  | "INSUFFICIENT_DATA"
  | "NOT_APPLICABLE"
  | "SUPPRESSED_LOW_CONFIDENCE";

export interface RevenueDecisionTarget {
  type: "REV_PICKUP_LOW" | "REV_OCCUPANCY_RISK";
  booking_data_source_id: string;
  /** ISO date (YYYY-MM-DD). */
  stay_date: string;
}

export interface OtaDecisionTarget {
  type: "REV_OTA_DEPENDENCY";
  booking_data_source_id: string;
}

export interface CostDecisionTarget {
  type: "COST_CPOR_ANOMALY";
  booking_data_source_id: string;
  target_period_start: string;
  cost_category: string;
  currency: string;
}

export interface LaborDecisionTarget {
  type: "LABOR_OVERSTAFFING";
  booking_data_source_id: string;
  labor_data_source_id: string;
  work_date: string;
  labor_category: string;
}

export type DecisionTarget =
  | RevenueDecisionTarget
  | OtaDecisionTarget
  | CostDecisionTarget
  | LaborDecisionTarget;

/** `facts`/`evidence` are already server-side whitelisted per decision_type (never a raw
 * passthrough) - still an open record here because their exact key set differs per type; a
 * frontend adapter narrows this per `decision_type`, it never renders it as raw JSON. */
export type DecisionFacts = Record<string, unknown>;

export interface FeedItemResponse {
  decision_id: string;
  decision_type: DecisionType;
  lifecycle_status: DecisionStatus;
  transition: LifecycleTransition;
  priority: PrioritySnapshot;
  first_seen_local_date: string;
  last_seen_local_date: string;
  episode_count: number;
  target: DecisionTarget;
  reason_codes: string[];
  facts: DecisionFacts;
  evidence: DecisionFacts;
  economic_proxy: EconomicProxy | null;
  source_status: SourceStatus;
}

export type FeedState =
  | "NOT_PROCESSED"
  | "ACTION_REQUIRED"
  | "DATA_QUALITY_LIMITED"
  | "NO_ACTION_REQUIRED";

/** GET /api/v1/properties/{property_id}/decision-feed?as_of=YYYY-MM-DD.
 *
 * `items` already carries EVERY triggered candidate, ordered `priority_rank ASC` - a client only
 * ever slices this array for presentation, it never re-sorts or re-filters it. */
export interface DecisionFeedResponse {
  property_id: string;
  as_of_local_date: string;
  feed_state: FeedState;
  decision_run_id: string | null;
  run_sequence: number | null;
  triggered_count: number | null;
  clear_count: number | null;
  insufficient_count: number | null;
  not_applicable_count: number | null;
  suppressed_count: number | null;
  items: FeedItemResponse[];
}

// --- Decision Detail & History (Gate 12, Gate 15's own reading) ---------------------------------

/** The full audit shape of one Observation - shared verbatim by Decision Detail's own
 * `latest_observation` and by every Decision History item. Several fields here
 * (`source_evaluation_fingerprint`, `source_target_key`, `memory_version`) are audit/internal
 * data: the typed client carries them because the contract does, but ordinary UI never renders
 * them (see docs/architecture/decision-detail-ui-v1.md, "No detail data leak"). */
export interface ObservationDetail {
  observation_id: string;
  as_of_local_date: string;
  source_status: SourceStatus;
  lifecycle_transition: LifecycleTransition;
  source_evaluation_fingerprint: string;
  source_target_key: string;
  reason_codes: string[];
  confidence_score: DecimalString;
  priority: PrioritySnapshot | null;
  facts: DecisionFacts;
  evidence: DecisionFacts;
  economic_proxy: EconomicProxy | null;
  memory_version: string;
}

/** GET /api/v1/properties/{property_id}/decisions/{decision_id}. */
export interface DecisionDetailResponse {
  decision_id: string;
  decision_type: DecisionType;
  status: DecisionStatus;
  first_seen_local_date: string;
  last_seen_local_date: string;
  last_evaluated_local_date: string;
  resolved_local_date: string | null;
  episode_count: number;
  triggered_observation_count: number;
  target: DecisionTarget;
  latest_observation: ObservationDetail;
  decision_api_version: string;
}

/** GET /api/v1/properties/{property_id}/decisions/{decision_id}/history?limit=&cursor=.
 *
 * Newest-first, exactly as the backend orders it - a client only ever appends a further page
 * after the items already shown, never re-sorts. `next_cursor` is opaque: pass it back verbatim
 * as the next page's `cursor`, never decode or construct one. */
export interface DecisionHistoryResponse {
  items: ObservationDetail[];
  next_cursor: string | null;
}
