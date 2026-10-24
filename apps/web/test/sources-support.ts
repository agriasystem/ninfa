import type {
  DataSourceCard,
  DataSourcesResponse,
  ImportPreviewResponse,
  ImportResultResponse,
  SourceCardKey,
} from "@ninfa/contracts";

/**
 * Hand-authored `DataSourcesResponse` fixtures for the "Fonti dati" tests, built from the backend contract
 * (`app/api/v1/sources/schemas.py`). They live ONLY in tests: no value here reaches the production path,
 * and the vendor name in `channelManagerConnected` exists to prove the page renders a CONNECTED card from
 * what the backend says (the backend itself never says it today).
 */

export const PROPERTY_ID = "p1";

const NOW_ISO = "2026-10-23T09:31:00Z"; // 11:31 in Europe/Rome (CEST)

function card(key: SourceCardKey, overrides: Partial<DataSourceCard> = {}): DataSourceCard {
  return {
    card: key,
    state: "NOT_CONFIGURED",
    domain: null,
    data_source_id: null,
    method: null,
    last_update_at: null,
    several_sources: false,
    derived_from: null,
    provider: null,
    channels: [],
    ...overrides,
  };
}

const CAPABILITIES: DataSourcesResponse["capabilities"] = [
  { domain: "BOOKINGS", methods: ["CSV"] },
  { domain: "COSTS", methods: ["XML"] },
  { domain: "LABOR", methods: ["CSV"] },
];

export function sources(
  cards: Partial<Record<SourceCardKey, Partial<DataSourceCard>>> = {},
  extra: Partial<DataSourcesResponse> = {},
): DataSourcesResponse {
  const domains = { PMS: "BOOKINGS", ACCOUNTING: "COSTS", STAFF: "LABOR" } as const;
  const order: SourceCardKey[] = ["PMS", "CHANNEL_MANAGER", "OTA", "ACCOUNTING", "STAFF"];
  return {
    property_id: PROPERTY_ID,
    cards: order.map((key) =>
      card(key, {
        domain: key in domains ? domains[key as keyof typeof domains] : null,
        ...cards[key],
      }),
    ),
    capabilities: CAPABILITIES,
    automatic_integrations: [],
    ...extra,
  };
}

/** Scenario 1: nothing configured (what a real property reads today). */
export const nothingConfigured = (): DataSourcesResponse => sources();

/** Scenario 2: the labor file is configured and was imported. */
export const laborViaCsv = (lastUpdateAt: string | null = NOW_ISO): DataSourcesResponse =>
  sources({
    STAFF: {
      state: "CONFIGURED_FILE",
      data_source_id: "src-labor",
      method: "CSV",
      last_update_at: lastUpdateAt,
    },
  });

/** Scenario 3: costs through invoices (XML). */
export const costsViaXml = (): DataSourcesResponse =>
  sources({
    ACCOUNTING: {
      state: "CONFIGURED_FILE",
      data_source_id: "src-costs",
      method: "XML",
      last_update_at: "2026-10-22T16:04:00Z",
    },
  });

/** Scenario 4 (what V1 really produces): bookings imported from a file; Channel Manager and OTA derived. */
export const bookingsViaFile = (): DataSourcesResponse =>
  sources({
    PMS: {
      state: "CONFIGURED_FILE",
      data_source_id: "src-bookings",
      method: "CSV",
      last_update_at: NOW_ISO,
    },
    CHANNEL_MANAGER: { state: "DERIVED", derived_from: "BOOKINGS_FILE" },
    OTA: { state: "DERIVED", derived_from: "BOOKINGS_FILE", channels: ["Booking.com", "Expedia"] },
  });

/** Scenario 4 (preview fixture only): a Channel Manager that is REALLY connected, with the OTA read
 * through it. The backend never produces this today; the page must still render it truthfully. */
export const channelManagerConnected = (): DataSourcesResponse =>
  sources({
    CHANNEL_MANAGER: {
      state: "CONNECTED",
      provider: "Fixture Channel Manager",
      last_update_at: NOW_ISO,
    },
    OTA: { state: "DERIVED", derived_from: "CHANNEL_MANAGER", channels: ["Booking.com", "Expedia"] },
  });

export function previewOf(overrides: Partial<ImportPreviewResponse> = {}): ImportPreviewResponse {
  return {
    method: "CSV",
    can_import: true,
    problem: null,
    rows_total: 2,
    recognized_columns: ["work_date", "labor_category", "planned_hours"],
    missing_columns: [],
    unrecognized_columns: [],
    sample_columns: ["work_date", "labor_category", "planned_hours"],
    sample_rows: [
      ["2026-11-02", "HOUSEKEEPING", "8"],
      ["2026-11-03", "HOUSEKEEPING", "6"],
    ],
    documents_with_issues: 0,
    already_imported: false,
    ...overrides,
  };
}

export function resultOf(overrides: Partial<ImportResultResponse> = {}): ImportResultResponse {
  return {
    succeeded: true,
    problem: null,
    rows_total: 2,
    rows_invalid: 0,
    created: 2,
    updated: 0,
    unchanged: 0,
    already_imported: false,
    ...overrides,
  };
}

export const ok = <T>(data: T) => ({ ok: true as const, data });
export const failure = (code: string, status = 400) => ({
  ok: false as const,
  status,
  code,
  message: "technical message that must never reach the page",
});

export function csvFile(name = "personale.csv"): File {
  return new File(["work_date,labor_category,planned_hours\n2026-11-02,HOUSEKEEPING,8\n"], name, {
    type: "text/csv",
  });
}

export function xmlFile(name = "fattura.xml"): File {
  return new File(["<FatturaElettronica/>"], name, { type: "text/xml" });
}
