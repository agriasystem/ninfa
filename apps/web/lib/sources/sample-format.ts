import type { ImportFieldSpec } from "@ninfa/contracts";

import { sourcesCopy } from "./copy";

/**
 * How one cell of the preview is written for the hotelier. Presentation only: the values come from the
 * backend already in NINFA's own form (ISO dates, plain decimals, standard names) and are never computed on.
 */

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})/u;

/** `2026-10-21` -> `21/10/2026`. Anything that is not a date is returned as it is. */
export function formatDay(value: string): string {
  const match = ISO_DAY.exec(value);
  return match === null ? value : `${match[3]}/${match[2]}/${match[1]}`;
}

/** `1234.5` -> `1.234,5`: Italian separators, the decimals the value already has. */
export function formatDecimal(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const decimals = value.includes(".") ? value.length - value.indexOf(".") - 1 : 0;
  return new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(number);
}

function choiceLabel(key: string, value: string): string {
  const choices: Partial<Record<string, Record<string, string>>> = sourcesCopy.choices;
  return choices[key]?.[value] ?? value;
}

export function formatSampleCell(spec: ImportFieldSpec | undefined, value: string | null): string {
  if (value === null || value === "") return "–";
  if (spec === undefined) return value;
  switch (spec.kind) {
    case "DATE":
    case "DATETIME":
      return formatDay(value);
    case "DECIMAL":
      return formatDecimal(value);
    case "CHOICE":
      return choiceLabel(spec.key, value);
    default:
      return value;
  }
}
