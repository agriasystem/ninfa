import type {
  DecisionDetailResponse,
  DecisionFeedResponse,
  DecisionHistoryResponse,
  DecisionType,
  FeedItemResponse,
  ObservationDetail,
  RecommendationResponse,
  RecommendedActionResponse,
} from "@ninfa/contracts";

/**
 * Golden Oggi UI fixtures (Gate 14): hand-authored `DecisionFeedResponse` payloads, built the
 * same way the backend's own golden scenarios are - independently of any frontend code under
 * test, using ONLY field names and shapes audited against the real Gate 12 contract
 * (`services/api/app/api/v1/decisions/schemas.py`/`serializers.py`). Nothing here is derived
 * from `lib/decisions/card-view-models.ts` - the whole point is to catch a REAL mapping bug,
 * not to confirm the adapter agrees with itself.
 */

const PROPERTY_ID = "22222222-2222-4222-8222-222222222222";

function baseFeed(overrides: Partial<DecisionFeedResponse>): DecisionFeedResponse {
  return {
    property_id: PROPERTY_ID,
    as_of_local_date: "2026-09-26",
    feed_state: "NOT_PROCESSED",
    decision_run_id: null,
    run_sequence: null,
    triggered_count: null,
    clear_count: null,
    insufficient_count: null,
    not_applicable_count: null,
    suppressed_count: null,
    items: [],
    ...overrides,
  };
}

/** A. No DecisionRun exists yet for this property/as-of at all. */
export const GOLDEN_NOT_PROCESSED: DecisionFeedResponse = baseFeed({
  feed_state: "NOT_PROCESSED",
});

/** B. The run exists, triggered nothing, but part of it could not reach a real conclusion. */
export const GOLDEN_DATA_QUALITY_LIMITED: DecisionFeedResponse = baseFeed({
  feed_state: "DATA_QUALITY_LIMITED",
  decision_run_id: "33333333-3333-4333-8333-333333333333",
  run_sequence: 4,
  triggered_count: 0,
  clear_count: 2,
  insufficient_count: 3,
  not_applicable_count: 1,
  suppressed_count: 1,
});

/** C. The run exists, and every applicable rule cleared - the ONLY state allowed to say so. */
export const GOLDEN_NO_ACTION_REQUIRED: DecisionFeedResponse = baseFeed({
  feed_state: "NO_ACTION_REQUIRED",
  decision_run_id: "44444444-4444-4444-8444-444444444444",
  run_sequence: 5,
  triggered_count: 0,
  clear_count: 6,
  insufficient_count: 0,
  not_applicable_count: 2,
  suppressed_count: 0,
});

function priority(rank: number, fingerprint: string) {
  return {
    rank,
    impact_score: "0.62",
    urgency_score: "0.58",
    confidence_score: "81",
    actionability_score: "0.55",
    priority_score: String(0.9 - rank * 0.05),
    candidate_fingerprint: fingerprint,
  };
}

const GOLDEN_PICKUP_ITEM: FeedItemResponse = {
  decision_id: "55555555-5555-4555-8555-555555555551",
  decision_type: "REV_PICKUP_LOW",
  lifecycle_status: "OPEN",
  transition: "OPENED",
  priority: priority(1, "fp-pickup"),
  first_seen_local_date: "2026-09-24",
  last_seen_local_date: "2026-09-26",
  episode_count: 1,
  target: {
    type: "REV_PICKUP_LOW",
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    stay_date: "2026-10-05",
  },
  reason_codes: ["TRIGGER_PICKUP_SHORTFALL"],
  facts: {
    stay_date: "2026-10-05",
    lead_time_days: 9,
    current_rooms_on_books: 12,
    rooms_available: 40,
    kind: "PICKUP",
    window_days: 7,
    prior_rooms_on_books: 9,
    actual_pickup: 3,
    expected_pickup: "7.50",
    delta_rooms: "-4.50",
    missing_rooms: "4.50",
    delta_percent_exact: "-60.00",
    percent_condition: true,
    rooms_condition: true,
  },
  evidence: {
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    baseline_confidence: "0.85",
    confidence_score: "81",
    revenue_gap_proxy: "312.40",
    reference_adr: "94.30",
    reference_adr_source: "ROOM_REVENUE_ON_BOOKS",
    rules_version: "revenue-decisions-v1",
  },
  economic_proxy: null,
  source_status: "TRIGGERED",
};

const GOLDEN_OCCUPANCY_ITEM: FeedItemResponse = {
  decision_id: "55555555-5555-4555-8555-555555555552",
  decision_type: "REV_OCCUPANCY_RISK",
  lifecycle_status: "OPEN",
  transition: "OPENED",
  priority: priority(2, "fp-occupancy"),
  first_seen_local_date: "2026-09-25",
  last_seen_local_date: "2026-09-26",
  episode_count: 1,
  target: {
    type: "REV_OCCUPANCY_RISK",
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    stay_date: "2026-10-12",
  },
  reason_codes: ["TRIGGER_OCCUPANCY_GAP"],
  facts: {
    stay_date: "2026-10-12",
    lead_time_days: 16,
    current_rooms_on_books: 18,
    rooms_available: 40,
    kind: "OCCUPANCY",
    forecast_rooms: "22.00",
    expected_final_rooms: "34.00",
    occupancy_gap_pp_exact: "30.00",
    room_shortfall: "12.00",
    gap_condition: true,
    shortfall_condition: true,
  },
  evidence: {
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    baseline_confidence: "0.79",
    confidence_score: "76",
    revenue_gap_proxy: "540.00",
    reference_adr: "94.30",
    reference_adr_source: "ROOM_REVENUE_ON_BOOKS",
    rules_version: "revenue-decisions-v1",
  },
  economic_proxy: null,
  source_status: "TRIGGERED",
};

const GOLDEN_OTA_ITEM: FeedItemResponse = {
  decision_id: "55555555-5555-4555-8555-555555555553",
  decision_type: "REV_OTA_DEPENDENCY",
  lifecycle_status: "OPEN",
  transition: "OPENED",
  priority: priority(3, "fp-ota"),
  first_seen_local_date: "2026-08-20",
  last_seen_local_date: "2026-09-26",
  episode_count: 1,
  target: {
    type: "REV_OTA_DEPENDENCY",
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
  },
  reason_codes: ["TRIGGER_STRUCTURAL_OTA_DEPENDENCY"],
  facts: {
    window_start: "2026-08-01",
    window_end: "2026-09-25",
    window_days: 56,
    ota_room_nights: 140,
    direct_room_nights: 84,
    ota_share_exact: "62.50",
    expected_ota_share_exact: "45.00",
    delta_pp_exact: "17.50",
    upper_fence_exact: "58.00",
    structural_condition: true,
    rising_condition: false,
  },
  evidence: {
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    classification_coverage_pct_exact: "92.00",
    observed_day_count: 52,
    reconstructed_day_count: 4,
    sample_count: 56,
    baseline_confidence: "0.88",
    confidence_score: "84",
    ota_room_revenue_exposure: "9800.00",
    rules_version: "ota-dependency-v1",
  },
  economic_proxy: null,
  source_status: "TRIGGERED",
};

const GOLDEN_COST_ITEM: FeedItemResponse = {
  decision_id: "55555555-5555-4555-8555-555555555554",
  decision_type: "COST_CPOR_ANOMALY",
  lifecycle_status: "OPEN",
  transition: "OPENED",
  priority: priority(4, "fp-cost"),
  first_seen_local_date: "2026-09-01",
  last_seen_local_date: "2026-09-26",
  episode_count: 1,
  target: {
    type: "COST_CPOR_ANOMALY",
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    target_period_start: "2026-09-01",
    cost_category: "FOOD_AND_BEVERAGE",
    currency: "EUR",
  },
  reason_codes: ["TRIGGER_COST_ANOMALY"],
  facts: {
    target_period_start: "2026-09-01",
    target_period_end: "2026-09-30",
    cost_category: "FOOD_AND_BEVERAGE",
    currency: "EUR",
    actual_cpor_exact: "12.40",
    expected_cpor_exact: "9.00",
    delta_cpor_exact: "3.40",
    delta_percent_exact: "37.78",
    upper_fence_exact: "11.00",
    cost_gap_proxy_exact: "482.30",
  },
  evidence: {
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    classification_coverage_pct_exact: "95.00",
    occupancy_provenance_score_exact: "0.90",
    sample_count: 6,
    observed_period_count: 5,
    baseline_confidence: "0.83",
    confidence_score: "80",
    rules_version: "cost-cpor-anomaly-v1",
  },
  economic_proxy: { label: "cost_gap_proxy", amount: "482.30", currency: "EUR" },
  source_status: "TRIGGERED",
};

const GOLDEN_LABOR_ITEM: FeedItemResponse = {
  decision_id: "55555555-5555-4555-8555-555555555555",
  decision_type: "LABOR_OVERSTAFFING",
  lifecycle_status: "OPEN",
  transition: "OPENED",
  priority: priority(5, "fp-labor"),
  first_seen_local_date: "2026-09-24",
  last_seen_local_date: "2026-09-26",
  episode_count: 1,
  target: {
    type: "LABOR_OVERSTAFFING",
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    labor_data_source_id: "77777777-7777-4777-8777-777777777771",
    work_date: "2026-09-25",
    labor_category: "HOUSEKEEPING",
  },
  reason_codes: ["TRIGGER_OVERSTAFFING"],
  facts: {
    work_date: "2026-09-25",
    labor_category: "HOUSEKEEPING",
    forecast_rooms_exact: "24.00",
    scheduled_hours_exact: "40.00",
    expected_labor_hours_exact: "28.00",
    excess_hours_exact: "12.00",
    delta_percent_exact: "42.86",
    upper_fence_hours_exact: "32.00",
  },
  evidence: {
    booking_data_source_id: "66666666-6666-4666-8666-666666666661",
    labor_data_source_id: "77777777-7777-4777-8777-777777777771",
    classification_coverage_pct_exact: "97.00",
    demand_confidence: "0.82",
    target_plan_quality: "0.90",
    sample_count: 14,
    fully_observed_count: 13,
    confidence_score: "79",
    labor_cost_gap_proxy_exact: "156.00",
    cost_currency: "EUR",
    rules_version: "labor-overstaffing-v1",
  },
  economic_proxy: { label: "labor_cost_gap_proxy", amount: "156.00", currency: "EUR" },
  source_status: "TRIGGERED",
};

// --- Recommendation V1 golden fixtures (Gate 17) ---------------------------------------------
//
// Hand-built to match EXACTLY what Gate 16's real `services/api/app/modules/recommendations/
// rules.py` would compute from each item's own `facts` object above - never derived from the
// frontend's own `recommendationViewModel`, for the same reason the rest of this file is never
// derived from `card-view-models.ts`: the point is to catch a real mapping bug, not to confirm an
// adapter agrees with itself.

function titleKey(actionCode: string): string {
  return `recommendation.action.${actionCode}.title`;
}

function descriptionKey(actionCode: string): string {
  return `recommendation.action.${actionCode}.description`;
}

function recommendedAction(
  actionCode: string,
  category: string,
  scope: string,
  supportingFacts: Record<string, string>,
  riskNotes: string[] = [],
): RecommendedActionResponse {
  return {
    action_code: actionCode,
    title_key: titleKey(actionCode),
    description_key: descriptionKey(actionCode),
    category,
    scope,
    supporting_facts: supportingFacts,
    risk_notes: riskNotes,
    requires_human_review: true,
  };
}

function availableRecommendation(
  primary: RecommendedActionResponse,
  supporting: RecommendedActionResponse[],
): RecommendationResponse {
  return {
    status: "AVAILABLE",
    version: "recommendation-engine-v1",
    fingerprint: "a".repeat(64),
    primary_action: primary,
    supporting_checks: supporting,
    confidence: "81",
    requires_human_review: true,
  };
}

export const GOLDEN_NOT_AVAILABLE_RECOMMENDATION: RecommendationResponse = {
  status: "NOT_AVAILABLE",
  version: "recommendation-engine-v1",
  fingerprint: "a".repeat(64),
  primary_action: null,
  supporting_checks: [],
  confidence: null,
  requires_human_review: true,
};

export const GOLDEN_INSUFFICIENT_CONTEXT_RECOMMENDATION: RecommendationResponse = {
  status: "INSUFFICIENT_CONTEXT",
  version: "recommendation-engine-v1",
  fingerprint: "a".repeat(64),
  primary_action: null,
  supporting_checks: [],
  confidence: "81",
  requires_human_review: true,
};

// Mirrors `pickup_rule(GOLDEN_PICKUP_ITEM.facts)`: actual_pickup/expected_pickup -> primary;
// rooms_condition then missing_rooms -> the two supporting checks, in that exact order.
const GOLDEN_PICKUP_RECOMMENDATION = availableRecommendation(
  recommendedAction("REVIEW_PRICING_AND_AVAILABILITY", "REVIEW_PRICING", "STAY_DATE", {
    actual_pickup: "3",
    expected_pickup: "7.50",
  }, ["PRICING_CHANGE_MAY_AFFECT_REVENUE"]),
  [
    recommendedAction("CHECK_CHANNEL_VISIBILITY", "VERIFY_DATA", "STAY_DATE", { rooms_condition: "True" }),
    recommendedAction("CHECK_BOOKING_RESTRICTIONS", "VERIFY_DATA", "STAY_DATE", { missing_rooms: "4.50" }),
  ],
);

// Mirrors `occupancy_rule(GOLDEN_OCCUPANCY_ITEM.facts)`.
const GOLDEN_OCCUPANCY_RECOMMENDATION = availableRecommendation(
  recommendedAction("REVIEW_DEMAND_POSITIONING", "REVIEW_AVAILABILITY", "STAY_DATE", {
    forecast_rooms: "22.00",
    expected_final_rooms: "34.00",
  }, ["PRICING_CHANGE_MAY_AFFECT_REVENUE"]),
  [
    recommendedAction("CHECK_PRICING", "VERIFY_DATA", "STAY_DATE", { occupancy_gap_pp_exact: "30.00" }),
    recommendedAction("CHECK_AVAILABILITY_AND_RESTRICTIONS", "VERIFY_DATA", "STAY_DATE", {
      room_shortfall: "12.00",
    }),
  ],
);

// Mirrors `ota_rule(GOLDEN_OTA_ITEM.facts)`.
const GOLDEN_OTA_RECOMMENDATION = availableRecommendation(
  recommendedAction("REVIEW_DISTRIBUTION_MIX", "REVIEW_DISTRIBUTION", "DISTRIBUTION_WINDOW", {
    ota_share_exact: "62.50",
    expected_ota_share_exact: "45.00",
  }, ["DISTRIBUTION_CHANGE_MAY_AFFECT_VISIBILITY"]),
  [
    recommendedAction("CHECK_DIRECT_CHANNEL_AVAILABILITY", "VERIFY_DATA", "DISTRIBUTION_WINDOW", {
      structural_condition: "True",
    }),
    recommendedAction("CHECK_DISTRIBUTION_CONFIGURATION", "VERIFY_DATA", "DISTRIBUTION_WINDOW", {
      rising_condition: "False",
    }),
  ],
);

// Mirrors `cost_rule(GOLDEN_COST_ITEM.facts)` - no risk note fits "review cost drivers" (Gate 16's
// own honest empty tuple, never a forced fit - see ADR 0022, point 8).
const GOLDEN_COST_RECOMMENDATION = availableRecommendation(
  recommendedAction("REVIEW_COST_DRIVERS", "REVIEW_COST_DRIVERS", "COST_PERIOD", {
    actual_cpor_exact: "12.40",
    expected_cpor_exact: "9.00",
  }),
  [
    recommendedAction("CHECK_RECENT_COST_ENTRIES", "VERIFY_DATA", "COST_PERIOD", { delta_cpor_exact: "3.40" }),
    recommendedAction("CHECK_VOLUME_VS_COST", "VERIFY_DATA", "COST_PERIOD", { delta_percent_exact: "37.78" }),
  ],
);

// Mirrors `labor_rule(GOLDEN_LABOR_ITEM.facts)`: CHECK_SHIFT_COVERAGE (excess_hours_exact) then the
// unconditional CHECK_SCHEDULED_HOURS, in that exact order.
const GOLDEN_LABOR_RECOMMENDATION = availableRecommendation(
  recommendedAction("REVIEW_STAFFING_PLAN", "REVIEW_STAFFING", "WORK_DATE", {
    scheduled_hours_exact: "40.00",
    expected_labor_hours_exact: "28.00",
  }, ["STAFFING_CHANGE_MAY_AFFECT_SERVICE"]),
  [
    recommendedAction("CHECK_SHIFT_COVERAGE", "VERIFY_DATA", "WORK_DATE", { excess_hours_exact: "12.00" }),
    recommendedAction("CHECK_SCHEDULED_HOURS", "VERIFY_DATA", "WORK_DATE", { scheduled_hours_exact: "40.00" }),
  ],
);

const GOLDEN_RECOMMENDATION_BY_TYPE: Record<DecisionType, RecommendationResponse> = {
  REV_PICKUP_LOW: GOLDEN_PICKUP_RECOMMENDATION,
  REV_OCCUPANCY_RISK: GOLDEN_OCCUPANCY_RECOMMENDATION,
  REV_OTA_DEPENDENCY: GOLDEN_OTA_RECOMMENDATION,
  COST_CPOR_ANOMALY: GOLDEN_COST_RECOMMENDATION,
  LABOR_OVERSTAFFING: GOLDEN_LABOR_RECOMMENDATION,
};

/** The recommendation a real Gate 16 engine run would compute for this golden item's OWN
 * `decision_type`+`facts` - keyed by decision_type here ONLY because this is hand-authored test
 * data simulating five independent real backend outputs, never a rule the frontend's own
 * production code is allowed to apply (see `lib/recommendations/view-model.ts`, which keys
 * exclusively off `action_code`, never `decision_type`). */
export function recommendationFor(item: FeedItemResponse): RecommendationResponse {
  return GOLDEN_RECOMMENDATION_BY_TYPE[item.decision_type];
}

export const GOLDEN_FIVE_DECISION_TYPES: FeedItemResponse[] = [
  GOLDEN_PICKUP_ITEM,
  GOLDEN_OCCUPANCY_ITEM,
  GOLDEN_OTA_ITEM,
  GOLDEN_COST_ITEM,
  GOLDEN_LABOR_ITEM,
];

/** D. ACTION_REQUIRED with exactly the five MVP decision types, `priority_rank ASC`. */
export const GOLDEN_ACTION_REQUIRED_FIVE_TYPES: DecisionFeedResponse = baseFeed({
  feed_state: "ACTION_REQUIRED",
  decision_run_id: "88888888-8888-4888-8888-888888888888",
  run_sequence: 6,
  triggered_count: 5,
  clear_count: 1,
  insufficient_count: 0,
  not_applicable_count: 0,
  suppressed_count: 0,
  items: GOLDEN_FIVE_DECISION_TYPES,
});

function extraTriggeredItem(rank: number, decisionId: string): FeedItemResponse {
  return {
    ...GOLDEN_PICKUP_ITEM,
    decision_id: decisionId,
    priority: priority(rank, `fp-extra-${rank}`),
    target: {
      type: "REV_PICKUP_LOW",
      booking_data_source_id: GOLDEN_PICKUP_ITEM.target.booking_data_source_id,
      stay_date: `2026-10-${String(5 + rank).padStart(2, "0")}`,
    },
  };
}

/** E. ACTION_REQUIRED with more than 5 triggered candidates - the UI presents only the top 5. */
export const GOLDEN_ACTION_REQUIRED_EIGHT_ITEMS: DecisionFeedResponse = baseFeed({
  feed_state: "ACTION_REQUIRED",
  decision_run_id: "99999999-9999-4999-8999-999999999999",
  run_sequence: 7,
  triggered_count: 8,
  clear_count: 0,
  insufficient_count: 0,
  not_applicable_count: 0,
  suppressed_count: 0,
  items: [
    ...GOLDEN_FIVE_DECISION_TYPES,
    extraTriggeredItem(6, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6"),
    extraTriggeredItem(7, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7"),
    extraTriggeredItem(8, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa8"),
  ],
});

// --- Decision Detail V1 golden scenarios (Gate 15) ------------------------------------------
//
// Built from the SAME feed-item fixtures above (target/facts are decision-level, not feed-
// specific), reshaped into the real Decision Detail/History contract
// (`app/api/v1/decisions/schemas.py::DecisionDetailResponse`/`ObservationDetail`) - never
// derived from the frontend adapters under test.

function observationFromFeedItem(
  item: FeedItemResponse,
  overrides: Partial<ObservationDetail> = {},
): ObservationDetail {
  return {
    observation_id: `obs-${item.decision_id}`,
    as_of_local_date: item.last_seen_local_date,
    source_status: item.source_status,
    lifecycle_transition: item.transition,
    source_evaluation_fingerprint: `fp-${item.decision_id}`,
    source_target_key: `key-${item.decision_id}`,
    reason_codes: item.reason_codes,
    confidence_score: item.priority?.confidence_score ?? "80",
    priority: item.priority,
    facts: item.facts,
    evidence: item.evidence,
    economic_proxy: item.economic_proxy,
    memory_version: "decision-memory-v1",
    ...overrides,
  };
}

function detailFromFeedItem(
  item: FeedItemResponse,
  overrides: Partial<DecisionDetailResponse> = {},
): DecisionDetailResponse {
  return {
    decision_id: item.decision_id,
    decision_type: item.decision_type,
    status: item.lifecycle_status,
    first_seen_local_date: item.first_seen_local_date,
    last_seen_local_date: item.last_seen_local_date,
    last_evaluated_local_date: item.last_seen_local_date,
    resolved_local_date: null,
    episode_count: item.episode_count,
    triggered_observation_count: 1,
    target: item.target,
    latest_observation: observationFromFeedItem(item),
    // Gate 17: the recommendation a real engine run would compute for this item's OWN
    // decision_type+facts - a scenario whose OWN latest_observation is overridden to a
    // non-TRIGGERED source_status below also overrides this to GOLDEN_NOT_AVAILABLE_RECOMMENDATION,
    // since Gate 16's NOT_AVAILABLE is driven by source_status, never by Decision.status.
    recommendation: recommendationFor(item),
    decision_api_version: "decision-api-v1",
    ...overrides,
  };
}

/** A. OPEN, latest observation TRIGGERED with a real priority rank - history newest-first,
 * OBSERVED (the repeat trigger) before the original OPENED. */
export const GOLDEN_DETAIL_OPEN_TRIGGERED: DecisionDetailResponse = detailFromFeedItem(
  GOLDEN_PICKUP_ITEM,
  { first_seen_local_date: "2026-09-18", episode_count: 1 },
);

export const GOLDEN_HISTORY_OPEN_TRIGGERED: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_PICKUP_ITEM, {
      observation_id: "obs-pickup-observed",
      as_of_local_date: "2026-09-26",
      lifecycle_transition: "OBSERVED",
    }),
    observationFromFeedItem(GOLDEN_PICKUP_ITEM, {
      observation_id: "obs-pickup-opened",
      as_of_local_date: "2026-09-18",
      lifecycle_transition: "OPENED",
    }),
  ],
  next_cursor: null,
};

/** B. RESOLVED: the latest observation is CLEAR (no priority at all), a real resolved date, and
 * the timeline includes the RESOLVED transition. */
export const GOLDEN_DETAIL_RESOLVED: DecisionDetailResponse = detailFromFeedItem(GOLDEN_OCCUPANCY_ITEM, {
  status: "RESOLVED",
  first_seen_local_date: "2026-09-10",
  resolved_local_date: "2026-09-24",
  episode_count: 1,
  latest_observation: observationFromFeedItem(GOLDEN_OCCUPANCY_ITEM, {
    observation_id: "obs-occupancy-resolved",
    as_of_local_date: "2026-09-24",
    source_status: "CLEAR",
    lifecycle_transition: "RESOLVED",
    priority: null,
    economic_proxy: null,
  }),
  // F. RESOLVED/CLEAR -> NOT_AVAILABLE: no stale recommendation from before the problem cleared.
  recommendation: GOLDEN_NOT_AVAILABLE_RECOMMENDATION,
});

export const GOLDEN_HISTORY_RESOLVED: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_OCCUPANCY_ITEM, {
      observation_id: "obs-occupancy-resolved",
      as_of_local_date: "2026-09-24",
      source_status: "CLEAR",
      lifecycle_transition: "RESOLVED",
      priority: null,
      economic_proxy: null,
    }),
    observationFromFeedItem(GOLDEN_OCCUPANCY_ITEM, {
      observation_id: "obs-occupancy-opened",
      as_of_local_date: "2026-09-10",
      lifecycle_transition: "OPENED",
    }),
  ],
  next_cursor: null,
};

/** C. REOPENED: the SAME logical decision, episode_count > 1, a full OPENED -> OBSERVED ->
 * RESOLVED -> REOPENED history. H. Also the Recommendation golden scenario for REOPENED/TRIGGERED:
 * `latest_observation` stays TRIGGERED (only its transition changes to REOPENED), so
 * `detailFromFeedItem`'s default `recommendation` is the real OTA AVAILABLE recommendation, built
 * from THIS observation's own facts only - never a prior episode's. */
export const GOLDEN_DETAIL_REOPENED: DecisionDetailResponse = detailFromFeedItem(GOLDEN_OTA_ITEM, {
  status: "OPEN",
  first_seen_local_date: "2026-08-01",
  resolved_local_date: null,
  episode_count: 2,
  latest_observation: observationFromFeedItem(GOLDEN_OTA_ITEM, {
    observation_id: "obs-ota-reopened",
    as_of_local_date: "2026-09-26",
    lifecycle_transition: "REOPENED",
  }),
});

export const GOLDEN_HISTORY_REOPENED: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_OTA_ITEM, {
      observation_id: "obs-ota-reopened",
      as_of_local_date: "2026-09-26",
      lifecycle_transition: "REOPENED",
    }),
    observationFromFeedItem(GOLDEN_OTA_ITEM, {
      observation_id: "obs-ota-resolved",
      as_of_local_date: "2026-09-10",
      source_status: "CLEAR",
      lifecycle_transition: "RESOLVED",
      priority: null,
      economic_proxy: null,
    }),
    observationFromFeedItem(GOLDEN_OTA_ITEM, {
      observation_id: "obs-ota-observed",
      as_of_local_date: "2026-08-15",
      lifecycle_transition: "OBSERVED",
    }),
    observationFromFeedItem(GOLDEN_OTA_ITEM, {
      observation_id: "obs-ota-opened",
      as_of_local_date: "2026-08-01",
      lifecycle_transition: "OPENED",
    }),
  ],
  next_cursor: null,
};

/** D. The latest observation is INSUFFICIENT_DATA: the Decision stays OPEN, has no priority,
 * and the copy must never imply the problem was resolved. */
export const GOLDEN_DETAIL_INSUFFICIENT_LATEST: DecisionDetailResponse = detailFromFeedItem(
  GOLDEN_COST_ITEM,
  {
    status: "OPEN",
    first_seen_local_date: "2026-09-01",
    resolved_local_date: null,
    episode_count: 1,
    latest_observation: observationFromFeedItem(GOLDEN_COST_ITEM, {
      observation_id: "obs-cost-insufficient",
      as_of_local_date: "2026-09-26",
      source_status: "INSUFFICIENT_DATA",
      lifecycle_transition: "NO_STATE_CHANGE",
      priority: null,
      economic_proxy: null,
    }),
    // source_status != TRIGGERED -> NOT_AVAILABLE regardless of Decision.status staying OPEN.
    recommendation: GOLDEN_NOT_AVAILABLE_RECOMMENDATION,
  },
);

export const GOLDEN_HISTORY_INSUFFICIENT_LATEST: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_COST_ITEM, {
      observation_id: "obs-cost-insufficient",
      as_of_local_date: "2026-09-26",
      source_status: "INSUFFICIENT_DATA",
      lifecycle_transition: "NO_STATE_CHANGE",
      priority: null,
      economic_proxy: null,
    }),
    observationFromFeedItem(GOLDEN_COST_ITEM, {
      observation_id: "obs-cost-opened",
      as_of_local_date: "2026-09-01",
      lifecycle_transition: "OPENED",
    }),
  ],
  next_cursor: null,
};

/** E. History pagination: more observations exist than the first page returns - the second page
 * appends strictly older entries, never replacing the first. */
export const GOLDEN_DETAIL_FOR_PAGINATION: DecisionDetailResponse = detailFromFeedItem(GOLDEN_LABOR_ITEM, {
  first_seen_local_date: "2026-07-01",
  episode_count: 1,
});

export const GOLDEN_HISTORY_PAGE_1: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_LABOR_ITEM, {
      observation_id: "obs-labor-p1-a",
      as_of_local_date: "2026-09-26",
    }),
    observationFromFeedItem(GOLDEN_LABOR_ITEM, {
      observation_id: "obs-labor-p1-b",
      as_of_local_date: "2026-09-19",
      lifecycle_transition: "OBSERVED",
    }),
  ],
  next_cursor: "opaque-cursor-page-2",
};

export const GOLDEN_HISTORY_PAGE_2: DecisionHistoryResponse = {
  items: [
    observationFromFeedItem(GOLDEN_LABOR_ITEM, {
      observation_id: "obs-labor-p2-a",
      as_of_local_date: "2026-07-01",
      lifecycle_transition: "OPENED",
    }),
  ],
  next_cursor: null,
};

// --- Recommendation UI V1 golden scenarios (Gate 17) -------------------------------------------

/** G. INSUFFICIENT_CONTEXT: the latest observation IS TRIGGERED (unlike NOT_AVAILABLE above), but
 * the facts `pickup_rule` needs (`actual_pickup`/`expected_pickup`) are genuinely missing - the
 * real shape Gate 11's own minimal `revenue_evaluation()` test fixture produces end to end (see
 * `recommendation-engine-v1.md`, "Missing or malformed context"). Confidence can still be a real,
 * non-null value: only the RULE's own facts are insufficient, not the confidence score itself. */
export const GOLDEN_DETAIL_RECOMMENDATION_INSUFFICIENT_CONTEXT: DecisionDetailResponse = detailFromFeedItem(
  GOLDEN_PICKUP_ITEM,
  {
    decision_id: "55555555-5555-4555-8555-555555555556",
    latest_observation: observationFromFeedItem(GOLDEN_PICKUP_ITEM, {
      observation_id: "obs-pickup-insufficient-context",
      facts: { stay_date: "2026-10-05", kind: "PICKUP" },
    }),
    recommendation: GOLDEN_INSUFFICIENT_CONTEXT_RECOMMENDATION,
  },
);
