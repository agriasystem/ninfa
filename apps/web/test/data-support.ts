import type {
  DataDomainFreshness,
  DataNightRow,
  DataOverviewResponse,
  DataPeriodMetrics,
  DomainState,
  NightStatus,
} from "@ninfa/contracts";

/**
 * Hand-authored `DataOverviewResponse` fixtures for the Dati UI tests, built from the real backend
 * contract (`app/api/v1/data/schemas.py`) and independent of every component under test. No value
 * here is taken from a screenshot: the property, dates and figures are invented for the tests, and
 * the components must show whatever these say (never a hardcoded demo value).
 *
 * The analysis day is Saturday 14 March 2026; the cost month is February 2026 (the last concluded
 * month); the stay nights run 14 March - 12 April.
 */

export const AS_OF = "2026-03-14";
export const PROPERTY_ID = "p1";
export const D_PICKUP = "dec-pickup";
export const D_OCCUPANCY = "dec-occupancy";
export const D_OTA = "dec-ota";
export const D_COST = "dec-cost";
export const D_LABOR = "dec-labor";

const ALL_DOMAINS = ["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"] as const;

function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

export function metrics(overrides: Partial<DataPeriodMetrics> = {}): DataPeriodMetrics {
  return {
    start_date: AS_OF,
    end_date: AS_OF,
    nights_requested: 1,
    nights_with_data: 1,
    nights_with_capacity: 1,
    room_nights: 17,
    rooms_on_books_with_capacity: 17,
    rooms_available: 40,
    occupancy_pct: "42.50",
    room_revenue: "1700.00",
    adr: "100.00",
    room_nights_7d_ago: null,
    room_nights_delta_7d: null,
    ...overrides,
  };
}

const ROOMS_BY_WEEKDAY = [20, 19, 21, 24, 33, 37, 27]; // Mon..Sun

export function night(index: number, overrides: Partial<DataNightRow> = {}): DataNightRow {
  const day = addDays(AS_OF, index);
  const weekday = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
  const rooms = ROOMS_BY_WEEKDAY[weekday] as number;
  return {
    stay_date: day,
    has_data: true,
    bookings: Math.max(1, Math.floor(rooms / 2)),
    rooms_on_books: rooms,
    rooms_available: 40,
    occupancy_pct: ((rooms * 100) / 40).toFixed(2),
    room_revenue: `${rooms * 100}.00`,
    adr: "100.00",
    rooms_on_books_7d_ago: rooms - 2,
    rooms_delta_7d: 2,
    status: "REGULAR",
    decision_id: null,
    ...overrides,
  };
}

export function nights(count: number, overrides: Record<number, Partial<DataNightRow>> = {}): DataNightRow[] {
  return Array.from({ length: count }, (_, index) => night(index, overrides[index] ?? {}));
}

const KNOWN: DataDomainFreshness = {
  status: "KNOWN",
  last_successful_import_finished_at: "2026-03-14T08:15:00Z", // 09:15 in Rome
  reason: null,
};

function domainStates(states: Partial<Record<(typeof ALL_DOMAINS)[number], DomainState>> = {}) {
  return ALL_DOMAINS.map((domain) => ({ domain, state: states[domain] ?? ("ANALYZED" as DomainState) }));
}

function coverage(skipped: readonly (typeof ALL_DOMAINS)[number][] = []): DataOverviewResponse["analysis"]["coverage"] {
  return {
    summary: skipped.length === 0 ? "FULL" : "PARTIAL",
    domains: ALL_DOMAINS.map((domain) =>
      skipped.includes(domain)
        ? { domain, status: "SKIPPED", reason: "NOT_REQUESTED" }
        : { domain, status: "EVALUATED", reason: null },
    ),
  };
}

/** The full-data world: 30 nights (one with an unknown capacity, two with a decision), the OTA decision,
 * costs of the last concluded month, planned labor hours, and every freshness known. */
export function fullOverview(overrides: Partial<DataOverviewResponse> = {}): DataOverviewResponse {
  const nightRows = nights(30, {
    4: { status: "ATTENTION", decision_id: D_PICKUP },
    9: { rooms_available: null, occupancy_pct: null, rooms_delta_7d: null, rooms_on_books_7d_ago: null },
    16: { status: "ATTENTION", decision_id: D_OCCUPANCY },
  });
  const week = metrics({
    start_date: AS_OF,
    end_date: addDays(AS_OF, 6),
    nights_requested: 7,
    nights_with_data: 7,
    nights_with_capacity: 7,
    room_nights: 179,
    rooms_on_books_with_capacity: 179,
    rooms_available: 280,
    occupancy_pct: "63.93",
    room_revenue: "17900.00",
    adr: "100.00",
    room_nights_7d_ago: 159,
    room_nights_delta_7d: 20,
  });
  const month = metrics({
    start_date: AS_OF,
    end_date: addDays(AS_OF, 29),
    nights_requested: 30,
    nights_with_data: 30,
    nights_with_capacity: 29,
    room_nights: 764,
    rooms_on_books_with_capacity: 727,
    rooms_available: 1160,
    occupancy_pct: "62.67",
    room_revenue: "76400.00",
    adr: "100.00",
  });
  return {
    property_id: PROPERTY_ID,
    as_of_local_date: AS_OF,
    period_days: 30,
    currency: "EUR",
    analysis: {
      feed_state: "ACTION_REQUIRED",
      coverage: coverage(),
      domain_states: domainStates(),
      last_successful_analysis: null,
    },
    freshness: {
      bookings: KNOWN,
      costs: { ...KNOWN, last_successful_import_finished_at: "2026-03-13T17:05:00Z" },
      labor: { ...KNOWN, last_successful_import_finished_at: "2026-03-11T08:30:00Z" },
    },
    occupancy: {
      state: "AVAILABLE",
      reason: null,
      today: metrics(),
      days_7: week,
      days_30: month,
      selected: month,
      nights: nightRows,
    },
    distribution: {
      state: "AVAILABLE",
      reason: null,
      window_start: AS_OF,
      window_end: addDays(AS_OF, 29),
      outcome: "DECISION",
      ota_share_pct: "72.20",
      direct_share_pct: "27.80",
      reference_ota_share_pct: "50.00",
      classification_coverage_pct: "100.00",
      insufficient_reasons: [],
      decision_id: D_OTA,
      channel_mix: {
        total_room_nights: 870,
        channels: [
          { name: "Booking.com", group: "OTA", room_nights: 390, share_pct: "44.83" },
          { name: "Diretto", group: "DIRECT", room_nights: 240, share_pct: "27.59" },
          { name: "Expedia", group: "OTA", room_nights: 180, share_pct: "20.69" },
          { name: "Agency", group: "OTHER", room_nights: 60, share_pct: "6.90" },
        ],
      },
    },
    costs: {
      state: "AVAILABLE",
      reason: null,
      month_start: "2026-02-01",
      month_end: "2026-02-28",
      previous_month_start: "2026-01-01",
      currency: "EUR",
      total_net_cost: "17445.00",
      previous_total_net_cost: "14730.00",
      delta_pct: "18.43",
      other_currencies_present: false,
      classification_coverage_pct: "98.10",
      categories: [
        { category: "FOOD", net_cost: "6840.00", cpor: "7.68", cpor_status: "READY", decision_id: D_COST },
        { category: "UTILITIES", net_cost: "4125.00", cpor: "4.63", cpor_status: "READY", decision_id: null },
        { category: "LAUNDRY", net_cost: "3000.00", cpor: null, cpor_status: "INCOMPLETE", decision_id: null },
        { category: "OTHER", net_cost: "340.00", cpor: null, cpor_status: "NOT_APPLICABLE", decision_id: null },
      ],
      decision: {
        decision_id: D_COST,
        period_start: "2026-02-01",
        category: "FOOD",
        currency: "EUR",
        actual_cpor: "7.68",
        expected_cpor: "6.10",
      },
    },
    labor: {
      state: "AVAILABLE",
      reason: null,
      window_start: AS_OF,
      window_end: addDays(AS_OF, 6),
      currency: "EUR",
      days_with_data: 7,
      categories: [
        { category: "HOUSEKEEPING", planned_hours: "112.00", days_complete: 7, days_incomplete: 0, planned_cost: "1680.00" },
        { category: "KITCHEN", planned_hours: "77.00", days_complete: 6, days_incomplete: 1, planned_cost: null },
      ],
      decision: {
        decision_id: D_LABOR,
        work_date: AS_OF,
        category: "HOUSEKEEPING",
        scheduled_hours: "32.00",
        expected_hours: "24.00",
        excess_hours: "8.00",
      },
    },
    decisions: [
      { decision_id: D_PICKUP, decision_type: "REV_PICKUP_LOW", domain: "REVENUE", target_date: addDays(AS_OF, 4), category: null },
      { decision_id: D_OCCUPANCY, decision_type: "REV_OCCUPANCY_RISK", domain: "REVENUE", target_date: addDays(AS_OF, 16), category: null },
      { decision_id: D_OTA, decision_type: "REV_OTA_DEPENDENCY", domain: "DISTRIBUTION", target_date: null, category: null },
      { decision_id: D_COST, decision_type: "COST_CPOR_ANOMALY", domain: "COSTS", target_date: "2026-02-01", category: "FOOD" },
      { decision_id: D_LABOR, decision_type: "LABOR_OVERSTAFFING", domain: "LABOR", target_date: AS_OF, category: "HOUSEKEEPING" },
    ],
    overview_version: "data-overview-v1",
    ...overrides,
  };
}

/** The 7-night response of the same property (what `period=7` returns). */
export function fullOverviewSevenDays(): DataOverviewResponse {
  const full = fullOverview();
  return {
    ...full,
    period_days: 7,
    occupancy: {
      ...full.occupancy,
      selected: full.occupancy.days_7,
      nights: full.occupancy.nights.slice(0, 7),
    },
  };
}

/** No decision run exists for the day: nothing about bookings can be said. */
export function notProcessedOverview(lastAnalysisDate: string | null = "2026-03-12"): DataOverviewResponse {
  const full = fullOverview();
  const unknown: DataDomainFreshness = { status: "UNKNOWN", last_successful_import_finished_at: null, reason: "NO_SOURCE" };
  return {
    ...full,
    analysis: {
      feed_state: "NOT_PROCESSED",
      coverage: { summary: "UNKNOWN", domains: [] },
      domain_states: domainStates({ REVENUE: "UNKNOWN", DISTRIBUTION: "UNKNOWN", COSTS: "UNKNOWN", LABOR: "UNKNOWN" }),
      last_successful_analysis:
        lastAnalysisDate === null ? null : { as_of_local_date: lastAnalysisDate, completed_at: "2026-03-12T07:00:00Z" },
    },
    freshness: { bookings: { ...unknown, reason: "NO_SOURCE" }, costs: unknown, labor: unknown },
    occupancy: { state: "NOT_AVAILABLE", reason: "NO_ANALYSIS", today: null, days_7: null, days_30: null, selected: null, nights: [] },
    distribution: {
      ...full.distribution,
      state: "NOT_AVAILABLE",
      reason: "NO_ANALYSIS",
      outcome: null,
      ota_share_pct: null,
      direct_share_pct: null,
      reference_ota_share_pct: null,
      classification_coverage_pct: null,
      decision_id: null,
      channel_mix: null,
    },
    costs: {
      ...full.costs,
      state: "NOT_AVAILABLE",
      reason: "NO_DATA",
      total_net_cost: null,
      previous_total_net_cost: null,
      delta_pct: null,
      classification_coverage_pct: null,
      categories: [],
      decision: null,
    },
    labor: { ...full.labor, state: "NOT_AVAILABLE", reason: "NO_SOURCE", days_with_data: 0, categories: [], decision: null },
    decisions: [],
  };
}

/** A data-quality-limited run: some capacity unknown, every night "Analisi parziale", the OTA check
 * inconclusive, costs and labor skipped. */
export function partialOverview(): DataOverviewResponse {
  const full = fullOverview();
  const partialNights: DataNightRow[] = nights(30, {
    2: { rooms_available: null, occupancy_pct: null },
    3: { rooms_available: null, occupancy_pct: null },
  }).map((row) => ({ ...row, status: "PARTIAL" as NightStatus, decision_id: null }));
  const month = metrics({
    start_date: AS_OF,
    end_date: addDays(AS_OF, 29),
    nights_requested: 30,
    nights_with_data: 30,
    nights_with_capacity: 28,
    room_nights: 764,
    occupancy_pct: "60.71",
    rooms_available: 1120,
  });
  return {
    ...full,
    analysis: {
      feed_state: "DATA_QUALITY_LIMITED",
      coverage: coverage(["COSTS", "LABOR"]),
      domain_states: domainStates({ REVENUE: "PARTIAL", DISTRIBUTION: "PARTIAL", COSTS: "NOT_ANALYZED", LABOR: "NOT_ANALYZED" }),
      last_successful_analysis: null,
    },
    freshness: {
      bookings: { ...KNOWN, last_successful_import_finished_at: "2026-03-13T21:40:00Z" },
      costs: { status: "UNKNOWN", last_successful_import_finished_at: null, reason: "NO_SOURCE" },
      labor: { status: "UNKNOWN", last_successful_import_finished_at: null, reason: "NO_SOURCE" },
    },
    occupancy: { ...full.occupancy, days_30: month, selected: month, nights: partialNights },
    distribution: {
      ...full.distribution,
      outcome: "INSUFFICIENT_DATA",
      ota_share_pct: null,
      direct_share_pct: null,
      reference_ota_share_pct: null,
      classification_coverage_pct: null,
      decision_id: null,
      insufficient_reasons: ["OTA_BOOKING_VOLUME_LOW", "SOME_FUTURE_CODE"],
      channel_mix: null,
    },
    costs: { ...full.costs, state: "NOT_AVAILABLE", reason: "NO_DATA", total_net_cost: null, previous_total_net_cost: null, delta_pct: null, categories: [], decision: null },
    labor: { ...full.labor, state: "NOT_AVAILABLE", reason: "NO_SOURCE", days_with_data: 0, categories: [], decision: null },
    decisions: [],
  };
}

/** The run recorded no coverage at all (it predates the coverage feature): nothing is "evaluated". */
export function unknownCoverageOverview(): DataOverviewResponse {
  const full = fullOverview();
  return {
    ...full,
    analysis: {
      feed_state: "NO_ACTION_REQUIRED",
      coverage: { summary: "UNKNOWN", domains: [] },
      domain_states: domainStates({ REVENUE: "UNKNOWN", DISTRIBUTION: "UNKNOWN", COSTS: "UNKNOWN", LABOR: "UNKNOWN" }),
      last_successful_analysis: null,
    },
    occupancy: {
      ...full.occupancy,
      nights: nights(30).map((row) => ({ ...row, status: "NOT_EVALUATED" as NightStatus })),
    },
    distribution: { ...full.distribution, state: "NOT_AVAILABLE", reason: "COVERAGE_UNKNOWN", outcome: null, ota_share_pct: null, direct_share_pct: null, reference_ota_share_pct: null, classification_coverage_pct: null, decision_id: null, channel_mix: null },
    decisions: [],
  };
}
