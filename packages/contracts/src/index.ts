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

/** POST /api/v1/properties/{property_id}/ask request body (Home UI V1, "Mia Home"): one question
 * about TODAY'S analysis of the whole property, never about one Decision. `as_of_local_date` is the
 * SAME property-local business date (`YYYY-MM-DD`) the Decision Feed was requested for - explicit,
 * never a server clock. Answered with the same `AskResponse` shape as the Decision Ask below. */
export interface AskHomeRequest {
  question: string;
  /** ISO date (YYYY-MM-DD). */
  as_of_local_date: string;
  /** The short conversation of the CURRENT page session (Mia V2), oldest first: complete
   * user/assistant exchanges only, at most 4, sent explicitly with every question (nothing is
   * stored server-side). Referential context for follow-ups such as "Perché?" - never business
   * truth: every fact is rebuilt fresh by the backend. Omitted for a first question. */
  history?: AskHomeHistoryMessage[];
}

/** One earlier message of the page session, as sent back with the next question. */
export interface AskHomeHistoryMessage {
  role: "user" | "assistant";
  content: string;
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

// --- Dati overview API V1 (Dati UI V1, `app/api/v1/data/schemas.py`) ---------------------------------
//
// ONE read-only GET: GET /api/v1/properties/{property_id}/data/overview?as_of=YYYY-MM-DD&period=7|30.
// Every figure is calculated by the backend (a deterministic projection of what NINFA already stores
// or calculates) - the frontend only formats. A Decimal is a two-decimal STRING and a figure that
// cannot be calculated safely is `null` with a stated `reason`: never `0`. Open vocabularies (reason
// codes, cost/labor categories, outcome) are plain strings on the wire and are mapped to Italian
// defensively by `lib/data/*`, failing safe on anything unknown.

export type DataPeriod = 7 | 30;

/** A night's status, read from the run's own decisions and coverage - never a frontend threshold. */
export type NightStatus = "ATTENTION" | "PARTIAL" | "REGULAR" | "NOT_EVALUATED";

/** The analysis state of one area, in the Home's own vocabulary. */
export type DomainState = "ANALYZED" | "PARTIAL" | "NOT_ANALYZED" | "UNKNOWN";

export type DataAvailability = "AVAILABLE" | "NOT_AVAILABLE";

export interface DataDecisionRef {
  decision_id: string;
  decision_type: string;
  domain: string;
  /** ISO date: the stay date (revenue), the work date (labor) or the month start (cost). */
  target_date: string | null;
  category: string | null;
}

export interface DataPeriodMetrics {
  start_date: string;
  end_date: string;
  nights_requested: number;
  nights_with_data: number;
  nights_with_capacity: number;
  /** Room-nights booked over every stored night - NOT a booking count. */
  room_nights: number | null;
  rooms_on_books_with_capacity: number | null;
  rooms_available: number | null;
  occupancy_pct: DecimalString | null;
  room_revenue: DecimalString | null;
  adr: DecimalString | null;
  /** Present only when EVERY night has a row both today and in the snapshot of 7 days ago. */
  room_nights_7d_ago: number | null;
  room_nights_delta_7d: number | null;
}

export interface DataNightRow {
  stay_date: string;
  has_data: boolean;
  bookings: number | null;
  rooms_on_books: number | null;
  rooms_available: number | null;
  occupancy_pct: DecimalString | null;
  room_revenue: DecimalString | null;
  adr: DecimalString | null;
  rooms_on_books_7d_ago: number | null;
  /** Rooms now minus rooms 7 days ago for this night, calculated by the backend. */
  rooms_delta_7d: number | null;
  status: NightStatus;
  decision_id: string | null;
}

export interface DataOccupancy {
  state: DataAvailability;
  reason: string | null;
  today: DataPeriodMetrics | null;
  days_7: DataPeriodMetrics | null;
  days_30: DataPeriodMetrics | null;
  selected: DataPeriodMetrics | null;
  nights: DataNightRow[];
}

export interface DataChannelWeight {
  name: string;
  /** "OTA" | "DIRECT" | "OTHER" | "UNKNOWN". */
  group: string;
  room_nights: number;
  share_pct: DecimalString;
}

export interface DataChannelMix {
  total_room_nights: number;
  channels: DataChannelWeight[];
}

export interface DataDistribution {
  state: DataAvailability;
  reason: string | null;
  window_start: string | null;
  window_end: string | null;
  /** "DECISION" | "CLEAR" | "INSUFFICIENT_DATA" | "SUPPRESSED" | "NOT_APPLICABLE" |
   * "CHANGED_AFTER_ANALYSIS". */
  outcome: string | null;
  ota_share_pct: DecimalString | null;
  direct_share_pct: DecimalString | null;
  reference_ota_share_pct: DecimalString | null;
  classification_coverage_pct: DecimalString | null;
  insufficient_reasons: string[];
  decision_id: string | null;
  channel_mix: DataChannelMix | null;
}

export interface DataCostCategory {
  category: string;
  net_cost: DecimalString;
  cpor: DecimalString | null;
  /** "READY" | "NO_OCCUPANCY_SOURCE" | "INCOMPLETE" | "ZERO_OCCUPANCY" |
   * "LOW_CLASSIFICATION_COVERAGE" | "NO_COST_DATA" | "NOT_APPLICABLE". */
  cpor_status: string;
  decision_id: string | null;
}

export interface DataCostDecision {
  decision_id: string;
  period_start: string;
  category: string;
  currency: string | null;
  actual_cpor: DecimalString | null;
  expected_cpor: DecimalString | null;
}

export interface DataCosts {
  state: DataAvailability;
  reason: string | null;
  month_start: string;
  month_end: string;
  previous_month_start: string;
  currency: string;
  total_net_cost: DecimalString | null;
  previous_total_net_cost: DecimalString | null;
  delta_pct: DecimalString | null;
  other_currencies_present: boolean;
  classification_coverage_pct: DecimalString | null;
  categories: DataCostCategory[];
  decision: DataCostDecision | null;
}

export interface DataLaborCategory {
  category: string;
  planned_hours: DecimalString;
  days_complete: number;
  days_incomplete: number;
  planned_cost: DecimalString | null;
}

export interface DataLaborDecision {
  decision_id: string;
  work_date: string;
  category: string;
  scheduled_hours: DecimalString | null;
  expected_hours: DecimalString | null;
  excess_hours: DecimalString | null;
}

export interface DataLabor {
  state: DataAvailability;
  reason: string | null;
  window_start: string;
  window_end: string;
  currency: string;
  days_with_data: number;
  categories: DataLaborCategory[];
  decision: DataLaborDecision | null;
}

/** A FACT about one domain's data: when the latest successful import of its source finished. */
export interface DataDomainFreshness {
  status: "KNOWN" | "UNKNOWN";
  last_successful_import_finished_at: string | null;
  /** "NO_SOURCE" | "SEVERAL_SOURCES" | "NO_IMPORT" when UNKNOWN. */
  reason: string | null;
}

export interface DataFreshness {
  bookings: DataDomainFreshness;
  costs: DataDomainFreshness;
  labor: DataDomainFreshness;
}

export interface DataDomainState {
  domain: AnalysisDomain;
  state: DomainState;
}

export interface DataAnalysis {
  feed_state: FeedState;
  coverage: AnalysisCoverage;
  domain_states: DataDomainState[];
  last_successful_analysis: LastSuccessfulAnalysis | null;
}

export interface DataOverviewResponse {
  property_id: string;
  as_of_local_date: string;
  period_days: number;
  currency: string;
  analysis: DataAnalysis;
  freshness: DataFreshness;
  occupancy: DataOccupancy;
  distribution: DataDistribution;
  costs: DataCosts;
  labor: DataLabor;
  decisions: DataDecisionRef[];
  overview_version: string;
}

// --- Data-source API V1 (Struttura > Fonti dati, `app/api/v1/sources`) ---------------------------------

/** The five cards of "Fonti dati". A card is a PRESENTATION of a kind of data, not a connection of its own:
 * Channel Manager and OTA are never linked separately (they are read from the bookings). */
export type SourceCardKey = "PMS" | "CHANNEL_MANAGER" | "OTA" | "ACCOUNTING" | "STAFF";

/** The kind of data a file source carries. */
export type DataSourceDomain = "BOOKINGS" | "COSTS" | "LABOR";

export type SourceCardState =
  | "NOT_CONFIGURED"
  /** A file source exists: data arrive when someone uploads a file. */
  | "CONFIGURED_FILE"
  /** A real automatic integration. The backend never produces it today: no integration exists. */
  | "CONNECTED"
  /** Received through another configured source (the OTA channels come with the bookings). */
  | "DERIVED";

export type SourceMethod = "CSV" | "XML";

export interface DataSourceCard {
  card: SourceCardKey;
  state: SourceCardState;
  domain: DataSourceDomain | null;
  /** Only when exactly one active source of the domain exists. */
  data_source_id: string | null;
  method: SourceMethod | null;
  /** When the latest SUCCEEDED import of this exact source finished (UTC). `null` = never imported. */
  last_update_at: string | null;
  /** More than one active source of the domain: NINFA does not pick one. */
  several_sources: boolean;
  /** `PMS` and `CHANNEL_MANAGER` appear only once an automatic integration exists. */
  derived_from: "BOOKINGS_FILE" | "PMS" | "CHANNEL_MANAGER" | null;
  /** The automatic integration's own name; always `null` while none exists. */
  provider: string | null;
  /** Real channel names read from the imported bookings (OTA card only). */
  channels: string[];
}

export interface DataSourceCapability {
  domain: DataSourceDomain;
  methods: SourceMethod[];
}

export interface DataSourcesResponse {
  property_id: string;
  cards: DataSourceCard[];
  /** How each kind of data can REALLY be provided today; nothing else is ever offered. */
  capabilities: DataSourceCapability[];
  /** Real automatic integrations. Empty today, by design. */
  automatic_integrations: string[];
}

/** WHY a file cannot be (or was not) imported - one stable word the page turns into a sentence. */
export type ImportProblem =
  | "UNSUPPORTED_FILE"
  | "UNREADABLE_FILE"
  | "EMPTY_FILE"
  | "NO_ROWS"
  | "FILE_TOO_LARGE"
  | "MISSING_COLUMNS"
  | "DUPLICATE_COLUMNS"
  | "INVALID_ROWS"
  | "UNSUPPORTED_FORMAT"
  | "SAME_DAY_CONFLICT"
  /** Smart Import: matching the columns of a file the person already has. */
  | "MAPPING_INCOMPLETE"
  | "FORMAT_UNCLEAR"
  | "PROFILE_NOT_USABLE"
  | "SHEET_REQUIRED"
  | "GENERIC";

export interface ImportPreviewResponse {
  method: SourceMethod;
  can_import: boolean;
  problem: ImportProblem | null;
  /** Data rows of a CSV, invoices of an XML. */
  rows_total: number;
  recognized_columns: string[];
  /** Each entry is a group of alternatives, one of which the file must carry. */
  missing_columns: string[][];
  unrecognized_columns: string[];
  sample_columns: string[];
  sample_rows: string[][];
  documents_with_issues: number;
  already_imported: boolean;
}

export interface ImportResultResponse {
  succeeded: boolean;
  problem: ImportProblem | null;
  rows_total: number;
  rows_invalid: number;
  created: number;
  updated: number;
  unchanged: number;
  already_imported: boolean;
}

// --- Smart Import: the hotel's own CSV / Excel file, its columns matched by the person -------------------

/** What a column of a spreadsheet-like file can mean. The backend owns the list (`fields` of an inspection). */
export type ImportFieldKey =
  // bookings
  | "source_record_id"
  | "booked_at"
  | "check_in"
  | "check_out"
  | "status"
  | "rooms"
  | "room_revenue"
  | "channel"
  | "guests"
  | "total_revenue"
  | "commission_amount"
  | "commission_rate"
  | "cancelled_at"
  | "room_type"
  | "rate_plan"
  // labor
  | "work_date"
  | "role"
  | "labor_category"
  | "planned_hours"
  | "actual_hours"
  | "planned_cost"
  | "actual_cost"
  | "currency";

/** What the person decided about ONE column. `field: null` is "ignore this column". */
export interface ImportColumnChoice {
  header: string;
  field: ImportFieldKey | null;
}

/** The whole decision: what each column means, fixed values for what the file lacks, how it is written. */
export interface ImportMapping {
  sheet_name?: string | null;
  columns: ImportColumnChoice[];
  /** "The same value on every row", only for the fields the backend allows it for. */
  constants: Partial<Record<ImportFieldKey, string | number>>;
  /** Only needed when the file writes dates as 12/10/2026 and its values do not say which is the day. */
  date_order?: "DMY" | "MDY" | null;
  /** Only needed when the file writes amounts with a comma or a point as the decimal mark. */
  decimal_style?: "COMMA" | "POINT" | null;
}

export type ImportSuggestionLevel = "RECOGNIZED" | "TO_CHECK";

export interface ImportColumnInfo {
  position: number;
  header: string;
  examples: string[];
  /** The meaning NINFA proposes; `null` = nothing proposed. */
  field: ImportFieldKey | null;
  level: ImportSuggestionLevel | null;
  /** Why a column is deliberately not offered as a field: a person's name, an hourly rate. */
  not_used_reason: "PERSON" | "HOURLY_RATE" | null;
  /** What the values prove about how dates / numbers are written. */
  date_order: "ISO" | "DMY" | "MDY" | "AMBIGUOUS" | "CONFLICT" | null;
  number_style: "COMMA" | "POINT" | "AMBIGUOUS" | "MIXED" | null;
}

export interface ImportConstantSpec {
  kind: "INTEGER" | "TEXT" | "CHOICE" | "CURRENCY";
  choices: string[];
  default: string | number | null;
}

export interface ImportFieldSpec {
  key: ImportFieldKey;
  kind: "DATE" | "DATETIME" | "DECIMAL" | "INTEGER" | "TEXT" | "CHOICE" | "CURRENCY";
  /** `null`: this field can only come from a column of the file. */
  constant: ImportConstantSpec | null;
}

export type ImportProfileStatus = "NONE" | "RECOGNIZED" | "NEEDS_REVIEW";

export interface ImportProfileInfo {
  status: ImportProfileStatus;
  reason: "COLUMNS_CHANGED" | "VERSION_CHANGED" | "INVALID" | null;
  /** The saved configuration written as a decision, to start "Controlla colonne" from it. */
  mapping: ImportMapping | null;
  last_used_at: string | null;
  missing_columns: string[];
}

export interface FileInspectionResponse {
  domain: DataSourceDomain;
  file_type: "CSV" | "XLSX" | null;
  problem: ImportProblem | null;
  sheet_name: string | null;
  sheet_names: string[];
  requires_sheet_selection: boolean;
  columns: ImportColumnInfo[];
  fields: ImportFieldSpec[];
  /** Each group is "at least one of"; a one-field group is a field that is required. */
  requirement_groups: ImportFieldKey[][];
  /** The proposal as it stands already meets every requirement. */
  suggestion_complete: boolean;
  /** The file already is in NINFA's own format. */
  already_canonical: boolean;
  profile: ImportProfileInfo;
  already_imported: boolean;
}

export interface MappingCheckResponse {
  valid: boolean;
  /** What is still needed: each entry is a group "at least one of these". */
  missing: ImportFieldKey[][];
  problems: { code: string; fields: string[] }[];
}

export interface ImportFormatHint {
  question: "DATE_ORDER" | "DECIMAL_STYLE";
  /** What the values already prove, or `null` when only the person knows. */
  proven: "DMY" | "MDY" | "COMMA" | "POINT" | null;
  columns: string[];
}

export interface ImportRowProblem {
  /** `""` when more than one field has this problem. */
  field: string;
  code: string;
  count: number;
}

export interface ImportInvalidRow {
  row: number;
  issues: { field: string; code: string }[];
}

export interface ImportValidationResponse {
  status: "READY" | "NEEDS_CHOICE" | "BLOCKED";
  problem: ImportProblem | null;
  can_import: boolean;
  check: MappingCheckResponse | null;
  format_hints: ImportFormatHint[];
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  sample_fields: ImportFieldKey[];
  sample_rows: (string | null)[][];
  row_problems: ImportRowProblem[];
  invalid_rows: ImportInvalidRow[];
  already_imported: boolean;
  /**
   * Staff files: valid rows whose department NINFA could not work out. They are kept as "Altro", which no
   * staffing decision uses. Counted over the whole file. Always 0 for the other kinds of data.
   */
  rows_unclassified: number;
}

export interface MappedImportResultResponse extends ImportResultResponse {
  /** The way the columns were matched has been remembered for the next file of the same layout. */
  configuration_saved: boolean;
}

/** How a source's files are read, as it was saved. */
export interface SavedImportConfiguration {
  data_source_id: string;
  domain: DataSourceDomain;
  columns: { field: ImportFieldKey; column: string }[];
  constants: { field: ImportFieldKey; value: string }[];
  last_used_at: string | null;
  /** `false`: made for another version of NINFA's rules, so it must be looked at again. */
  schema_current: boolean;
}
