import type {
  DataSourceCard,
  DataSourcesResponse,
  FileInspectionResponse,
  ImportColumnInfo,
  ImportFieldSpec,
  ImportMapping,
  ImportProfileInfo,
  ImportPreviewResponse,
  ImportResultResponse,
  ImportValidationResponse,
  MappedImportResultResponse,
  MappingCheckResponse,
  SavedImportConfiguration,
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

// --- Smart Import: the hotel's own CSV / Excel file ------------------------------------------------------------

const LABOR_FIELDS: ImportFieldSpec[] = [
  { key: "work_date", kind: "DATE", constant: null },
  { key: "role", kind: "TEXT", constant: null },
  {
    key: "labor_category",
    kind: "CHOICE",
    constant: {
      kind: "CHOICE",
      choices: ["HOUSEKEEPING", "FRONT_OFFICE", "FOOD_BEVERAGE", "KITCHEN", "OTHER"],
      default: null,
    },
  },
  { key: "planned_hours", kind: "DECIMAL", constant: null },
  { key: "actual_hours", kind: "DECIMAL", constant: null },
  { key: "planned_cost", kind: "DECIMAL", constant: null },
  { key: "actual_cost", kind: "DECIMAL", constant: null },
  { key: "currency", kind: "CURRENCY", constant: { kind: "CURRENCY", choices: [], default: "EUR" } },
];

const BOOKINGS_FIELDS: ImportFieldSpec[] = [
  { key: "source_record_id", kind: "TEXT", constant: null },
  { key: "booked_at", kind: "DATETIME", constant: null },
  { key: "check_in", kind: "DATE", constant: null },
  { key: "check_out", kind: "DATE", constant: null },
  {
    key: "status",
    kind: "CHOICE",
    constant: { kind: "CHOICE", choices: ["CONFIRMED", "CANCELLED"], default: "CONFIRMED" },
  },
  { key: "rooms", kind: "INTEGER", constant: { kind: "INTEGER", choices: [], default: 1 } },
  { key: "room_revenue", kind: "DECIMAL", constant: null },
  { key: "channel", kind: "TEXT", constant: { kind: "TEXT", choices: [], default: null } },
];

function column(
  position: number,
  header: string,
  examples: string[],
  overrides: Partial<ImportColumnInfo> = {},
): ImportColumnInfo {
  return {
    position,
    header,
    examples,
    field: null,
    level: null,
    not_used_reason: null,
    date_order: null,
    number_style: null,
    ...overrides,
  };
}

function nothingSaved(): ImportProfileInfo {
  return { status: "NONE", reason: null, mapping: null, last_used_at: null, missing_columns: [] };
}

/** The staff-shifts file of the brief: a day, a person, the hours of the shift, an hourly rate, a team. */
export function laborInspection(overrides: Partial<FileInspectionResponse> = {}): FileInspectionResponse {
  return {
    domain: "LABOR",
    file_type: "CSV",
    problem: null,
    sheet_name: null,
    sheet_names: [],
    requires_sheet_selection: false,
    columns: [
      column(0, "Giorno", ["26/10/2026", "27/10/2026"], { field: "work_date", level: "RECOGNIZED", date_order: "DMY" }),
      column(1, "Nome dipendente", ["Persona 1", "Persona 2"], { not_used_reason: "PERSON" }),
      column(2, "Ore turno", ["8", "8"], { field: "planned_hours", level: "RECOGNIZED" }),
      column(3, "Costo orario", ["14,50", "14,50"], { not_used_reason: "HOURLY_RATE", number_style: "COMMA" }),
      column(4, "Reparto", ["Reception", "Cucina"], { field: "role", level: "TO_CHECK" }),
    ],
    fields: LABOR_FIELDS,
    requirement_groups: [["work_date"], ["actual_hours", "planned_hours"], ["labor_category", "role"]],
    suggestion_complete: true,
    already_canonical: false,
    profile: nothingSaved(),
    already_imported: false,
    ...overrides,
  };
}

/** The same staff file without its team column: the proposal is not complete. */
export function laborInspectionWithoutTeam(): FileInspectionResponse {
  const base = laborInspection();
  return laborInspection({
    columns: base.columns.filter((item) => item.header !== "Reparto"),
    suggestion_complete: false,
  });
}

/** A hotel's bookings export. */
export function bookingsInspection(overrides: Partial<FileInspectionResponse> = {}): FileInspectionResponse {
  return {
    domain: "BOOKINGS",
    file_type: "CSV",
    problem: null,
    sheet_name: null,
    sheet_names: [],
    requires_sheet_selection: false,
    columns: [
      column(0, "N. prenotazione", ["IT-0001"], { field: "source_record_id", level: "RECOGNIZED" }),
      column(1, "Data prenotazione", ["01/10/2026"], { field: "booked_at", level: "RECOGNIZED", date_order: "AMBIGUOUS" }),
      column(2, "Data arrivo", ["12/11/2026"], { field: "check_in", level: "RECOGNIZED", date_order: "DMY" }),
      column(3, "Data partenza", ["14/11/2026"], { field: "check_out", level: "RECOGNIZED", date_order: "DMY" }),
      column(4, "Stato", ["Confermata"], { field: "status", level: "RECOGNIZED" }),
      column(5, "Camere", ["1"], { field: "rooms", level: "RECOGNIZED" }),
      column(6, "Importo camera", ["150,00"], { field: "room_revenue", level: "RECOGNIZED", number_style: "COMMA" }),
      column(7, "Canale", ["Booking.com"], { field: "channel", level: "RECOGNIZED" }),
    ],
    fields: BOOKINGS_FIELDS,
    requirement_groups: [
      ["source_record_id"],
      ["booked_at"],
      ["check_in"],
      ["check_out"],
      ["status"],
      ["rooms"],
      ["room_revenue"],
      ["channel"],
    ],
    suggestion_complete: true,
    already_canonical: false,
    profile: nothingSaved(),
    already_imported: false,
    ...overrides,
  };
}

/** A file whose headers say nothing NINFA knows. */
export function unknownInspection(): FileInspectionResponse {
  return laborInspection({
    columns: [
      column(0, "Colonna A", ["26/10/2026"]),
      column(1, "Colonna B", ["8"]),
      column(2, "Colonna C", ["Cucina"]),
    ],
    suggestion_complete: false,
  });
}

/** A file already written in NINFA's own column names. */
export function canonicalInspection(): FileInspectionResponse {
  return laborInspection({
    columns: [
      column(0, "work_date", ["2026-10-26"], { field: "work_date", level: "RECOGNIZED", date_order: "ISO" }),
      column(1, "labor_category", ["KITCHEN"], { field: "labor_category", level: "RECOGNIZED" }),
      column(2, "planned_hours", ["8"], { field: "planned_hours", level: "RECOGNIZED" }),
    ],
    already_canonical: true,
  });
}

/** The saved matching of the staff file, written as a decision. */
export function savedLaborMapping(): ImportMapping {
  return {
    sheet_name: null,
    columns: [
      { header: "Giorno", field: "work_date" },
      { header: "Nome dipendente", field: null },
      { header: "Ore turno", field: "planned_hours" },
      { header: "Costo orario", field: null },
      { header: "Reparto", field: "role" },
    ],
    constants: {},
    date_order: "DMY",
    decimal_style: null,
  };
}

/** A staff file whose layout NINFA already knows. */
export function recognizedInspection(): FileInspectionResponse {
  return laborInspection({
    profile: {
      status: "RECOGNIZED",
      reason: null,
      mapping: savedLaborMapping(),
      last_used_at: "2026-10-22T08:15:00Z",
      missing_columns: [],
    },
  });
}

export function checkOf(overrides: Partial<MappingCheckResponse> = {}): MappingCheckResponse {
  return { valid: true, missing: [], problems: [], ...overrides };
}

export function validationOf(overrides: Partial<ImportValidationResponse> = {}): ImportValidationResponse {
  return {
    status: "READY",
    problem: null,
    can_import: true,
    check: null,
    format_hints: [{ question: "DATE_ORDER", proven: "DMY", columns: ["Giorno"] }],
    rows_total: 3,
    rows_valid: 3,
    rows_invalid: 0,
    sample_fields: ["work_date", "labor_category", "planned_hours"],
    sample_rows: [
      ["2026-10-26", "FRONT_OFFICE", "8"],
      ["2026-10-27", "HOUSEKEEPING", "7.5"],
      ["2026-10-28", "KITCHEN", "8"],
    ],
    row_problems: [],
    invalid_rows: [],
    already_imported: false,
    rows_unclassified: 0,
    ...overrides,
  };
}

export function matchedResultOf(overrides: Partial<MappedImportResultResponse> = {}): MappedImportResultResponse {
  return { ...resultOf({ rows_total: 3, created: 3 }), configuration_saved: true, ...overrides };
}

export function savedConfigurationOf(overrides: Partial<SavedImportConfiguration> = {}): SavedImportConfiguration {
  return {
    data_source_id: "src-labor",
    domain: "LABOR",
    columns: [
      { field: "work_date", column: "Giorno" },
      { field: "planned_hours", column: "Ore turno" },
      { field: "role", column: "Reparto" },
    ],
    constants: [],
    last_used_at: "2026-10-22T08:15:00Z",
    schema_current: true,
    ...overrides,
  };
}

export function xlsxFile(name = "turni.xlsx"): File {
  return new File(["PK"], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}
