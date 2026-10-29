import type {
  FileInspectionResponse,
  ImportColumnChoice,
  ImportColumnInfo,
  ImportFieldKey,
  ImportMapping,
  UnderstandAnswers,
} from "@ninfa/contracts";

/**
 * The person's decision about the columns of their file, as plain data and pure functions. Nothing here
 * knows what a field means or which ones are required: the backend says that (`requirement_groups`, `fields`)
 * and checks the decision itself. These functions only keep a decision consistent while it is being edited:
 * a meaning belongs to ONE column, and a fixed value and a column never stand for the same field.
 */

/** A column NINFA deliberately never reads (a person's name, an hourly rate): it can only be ignored. */
export function isLockedColumn(column: ImportColumnInfo): boolean {
  return column.not_used_reason !== null;
}

/** The proposal, written as a decision: each column with the meaning NINFA suggests for it (or none). */
export function decisionFromSuggestions(inspection: FileInspectionResponse): ImportMapping {
  return {
    sheet_name: inspection.sheet_name,
    columns: inspection.columns.map((column) => ({
      header: column.header,
      field: isLockedColumn(column) ? null : column.field,
    })),
    constants: {},
  };
}

/**
 * Where "Controlla colonne" starts: the saved configuration where it still applies, and NINFA's proposal for
 * the columns it says nothing about (a new column of the same file) - never a meaning that is already taken.
 */
export function startingDecision(inspection: FileInspectionResponse): ImportMapping {
  const proposal = decisionFromSuggestions(inspection);
  const saved = inspection.profile.mapping;
  if (saved === null) return proposal;
  const taken = new Set<ImportFieldKey>(
    saved.columns.flatMap((column) => (column.field === null ? [] : [column.field])),
  );
  for (const key of Object.keys(saved.constants) as ImportFieldKey[]) taken.add(key);
  const savedOf = new Map(saved.columns.map((column) => [column.header, column.field] as const));
  const columns: ImportColumnChoice[] = proposal.columns.map((column) => {
    const field = savedOf.get(column.header) ?? null;
    if (field !== null) return { header: column.header, field };
    if (column.field !== null && !taken.has(column.field)) {
      taken.add(column.field);
      return column;
    }
    return { header: column.header, field: null };
  });
  return {
    sheet_name: proposal.sheet_name,
    columns,
    constants: { ...saved.constants },
    date_order: saved.date_order ?? null,
    decimal_style: saved.decimal_style ?? null,
  };
}

export function fieldOfColumn(decision: ImportMapping, header: string): ImportFieldKey | null {
  return decision.columns.find((column) => column.header === header)?.field ?? null;
}

/** The fields that already have a column or a fixed value. */
export function fieldsInUse(decision: ImportMapping): Set<ImportFieldKey> {
  const used = new Set<ImportFieldKey>(Object.keys(decision.constants) as ImportFieldKey[]);
  for (const column of decision.columns) if (column.field !== null) used.add(column.field);
  return used;
}

/** A column now means `field` (or nothing). The meaning leaves the column that had it, and a fixed value
 * for the same field goes away: a field has exactly one source. */
export function withColumnField(
  decision: ImportMapping,
  header: string,
  field: ImportFieldKey | null,
): ImportMapping {
  const constants = { ...decision.constants };
  if (field !== null) delete constants[field];
  return {
    ...decision,
    columns: decision.columns.map((column) => {
      if (column.header === header) return { header, field };
      return field !== null && column.field === field ? { header: column.header, field: null } : column;
    }),
    constants,
  };
}

/** A field gets one value for every row (or loses it, with `null`). A column that stood for the field is
 * ignored: the file does not have to be told twice. */
export function withConstant(
  decision: ImportMapping,
  field: ImportFieldKey,
  value: string | number | null,
): ImportMapping {
  const constants = { ...decision.constants };
  if (value === null || value === "") delete constants[field];
  else constants[field] = value;
  return {
    ...decision,
    columns: decision.columns.map((column) =>
      value !== null && value !== "" && column.field === field
        ? { header: column.header, field: null }
        : column,
    ),
    constants,
  };
}

export function withDateOrder(decision: ImportMapping, order: "DMY" | "MDY"): ImportMapping {
  return { ...decision, date_order: order };
}

export function withDecimalStyle(decision: ImportMapping, style: "COMMA" | "POINT"): ImportMapping {
  return { ...decision, decimal_style: style };
}

/** Same decision, same text: used to tell whether an answer still belongs to what is on screen. */
/**
 * Did the person decide something while NINFA was asking (a column, a department, a week's hours basis, VAT,
 * how dates are written...)? Then the source is remembered by default, even if it was known before: it is
 * their confirmation that makes the next file ask less. (The server decides what is actually learned.)
 */
export function personAnswered(answers: UnderstandAnswers): boolean {
  return (
    Object.keys(answers.column_fields ?? {}).length > 0 ||
    [
      answers.grid_hours,
      answers.amount_basis,
      answers.date_order,
      answers.decimal_style,
      answers.department_from,
      answers.department_value,
      answers.table_key,
      answers.sheet_name,
    ].some((value) => value !== undefined && value !== null && value !== "")
  );
}

export function sameDecision(a: ImportMapping, b: ImportMapping): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** What the person has said so far plus the answer just given: a column or a word answered earlier stays
 * answered, and anything else is replaced by the newer answer. */
export function mergeAnswers(
  base: UnderstandAnswers,
  patch: Partial<UnderstandAnswers>,
): UnderstandAnswers {
  const labels: Record<string, Record<string, string>> = { ...(base.labels ?? {}) };
  for (const [document, words] of Object.entries(patch.labels ?? {})) {
    labels[document] = { ...(labels[document] ?? {}), ...words };
  }
  return {
    ...base,
    ...patch,
    column_fields: { ...(base.column_fields ?? {}), ...(patch.column_fields ?? {}) },
    labels,
  };
}
