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

/** The four user-facing analysis domains (Gate 22) - group the five detector types the way an
 * operator/hotel thinks about them, never the raw `DecisionType` enum (that never reaches the
 * frontend here). */
export type AnalysisDomain = "REVENUE" | "DISTRIBUTION" | "COSTS" | "LABOR";

/** Coverage != outcome: a domain is EVALUATED whichever status its detectors returned, CLEAR
 * through TRIGGERED - this only says whether NINFA looked, never what it found. */
export type DomainCoverageStatus = "EVALUATED" | "SKIPPED";

/** One value in V1: every skip here is a caller-side choice (an optional domain not requested
 * this run), never a runtime failure - a crashed run never persists at all (Gate 21's fail-loud
 * guarantee). */
export type DomainSkipReason = "NOT_REQUESTED";

export interface DomainCoverage {
  domain: AnalysisDomain;
  status: DomainCoverageStatus;
  reason: DomainSkipReason | null;
}

/** `"UNKNOWN"` (with an empty `domains` list) means this run predates Gate 22 or no run exists
 * yet - NEVER inferred as `"FULL"` or `"PARTIAL"` by the backend, and a client must not either. */
export type CoverageSummary = "FULL" | "PARTIAL" | "UNKNOWN";

export interface AnalysisCoverage {
  summary: CoverageSummary;
  domains: DomainCoverage[];
}

/** Gate 23B: a FACT, never a judgement - `"KNOWN"` only states that a SUCCEEDED booking import
 * was known at analysis time, and WHEN it finished; it never claims that import was "the" source
 * of this run's numbers (canonical booking state is cumulative/upserted) and never implies
 * CURRENT/STALE (no freshness threshold exists in V1). Deliberately omits the internal
 * `ImportJob`/`DataSource` UUIDs - no frontend need for them exists yet. */
export type BookingFreshnessStatus = "KNOWN" | "UNKNOWN";

export interface BookingFreshness {
  status: BookingFreshnessStatus;
  /** ISO 8601 datetime, timezone-aware. Present only when `status === "KNOWN"`. */
  last_successful_import_finished_at: string | null;
}

/** `bookings` is the only key in V1 (Gate 23B's own P0 scope) - no cost/labor freshness exists
 * yet. Always present and never null, exactly like `AnalysisCoverage` above. */
export interface InputFreshness {
  bookings: BookingFreshness;
}

/** Gate 24B: populated ONLY when `feed_state === "NOT_PROCESSED"` AND a prior run exists for
 * this property on some OTHER as-of date - `null` for every processed feed state and `null`
 * when the property has never been analysed at all (never inferred, never fabricated - a client
 * must not treat `null` as "never analysed" by itself, since a processed feed is also `null`).
 * `as_of_local_date` is the BUSINESS date that run represents (use this for "L'ultima analisi
 * completata risale al ..." copy - never `completed_at` for that sentence);  `completed_at` is
 * when NINFA actually finished/persisted it - two distinct facts, kept separate on purpose. No
 * run id, no `run_sequence` - no frontend need for them exists. */
export interface LastSuccessfulAnalysis {
  /** ISO date (YYYY-MM-DD). */
  as_of_local_date: string;
  /** ISO 8601 datetime, timezone-aware. */
  completed_at: string;
}

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
  analysis_coverage: AnalysisCoverage;
  input_freshness: InputFreshness;
  last_successful_analysis: LastSuccessfulAnalysis | null;
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

// --- Recommendation Engine V1 (Gate 16, `app/modules/recommendations/`) ------------------------

/** One structured action (Gate 16): a REVIEW or a CHECK, never an executed change.
 * `action_code`/`category`/`scope`/`risk_notes` are plain strings on the wire - the backend's own
 * `RecommendedActionResponse` types them as `str`, not a closed enum (unlike `target.type`, a real
 * `Literal` discriminated union) - so a frontend copy mapping
 * (`lib/recommendations/copy.ts`) narrows them defensively and fails safe on anything it does not
 * recognise, rather than assuming closure the wire type itself does not promise.
 * `title_key`/`description_key` are deterministic template keys, not prose - the frontend maps
 * `action_code` directly to Italian copy and never reads these two fields. */
export interface RecommendedActionResponse {
  action_code: string;
  title_key: string;
  description_key: string;
  category: string;
  scope: string;
  supporting_facts: Record<string, string>;
  risk_notes: string[];
  requires_human_review: boolean;
}

/** GET .../decisions/{decision_id}'s additive `recommendation` field (Gate 16) - NEVER null:
 * `status` itself ("AVAILABLE" | "NOT_AVAILABLE" | "INSUFFICIENT_CONTEXT") says whether a real
 * recommendation exists right now. Deliberately omits the engine's own internal bookkeeping
 * (`generated_from_observation_id`, `generated_from_evaluation_fingerprint`, `reason_codes`) - see
 * docs/architecture/recommendation-engine-v1.md. No field here can ever mean "apply automatically":
 * `requires_human_review` is always `true`, and there is no `auto_apply`/`execute`/`approved_by_default`
 * anywhere in this shape. */
export interface RecommendationResponse {
  status: string;
  version: string;
  fingerprint: string;
  primary_action: RecommendedActionResponse | null;
  supporting_checks: RecommendedActionResponse[];
  confidence: DecimalString | null;
  requires_human_review: boolean;
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
  recommendation: RecommendationResponse;
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

/** Ask NINFA (Gate 18/19/19.1) - the SERVICE's own final result status, a small, closed, stable
 * protocol-level vocabulary (unlike `RecommendationResponse.status`'s deliberately-open `string`,
 * which maps a growing set of business codes through a lookup table). A closed union here gets
 * TypeScript's own exhaustiveness checking on the one `switch` that renders it (Gate 20). */
export type AskStatus = "ANSWERED" | "INSUFFICIENT_CONTEXT" | "UNAVAILABLE" | "REFUSED";

/** POST /api/v1/properties/{property_id}/decisions/{decision_id}/ask request body. */
export interface AskRequest {
  question: string;
}

/** POST .../ask response (Gate 18). `answer`/`limitations` carry real content only for
 * `ANSWERED`/`INSUFFICIENT_CONTEXT` - `UNAVAILABLE`/`REFUSED` carry `answer: null`. No chat id, no
 * thread id, no conversation id anywhere - one question, one answer, nothing persisted. */
export interface AskResponse {
  status: AskStatus;
  answer: string | null;
  grounding_refs: string[];
  limitations: string[];
}
