import type {
  DataSourceDomain,
  ImportSummary,
  ImportValidationResponse,
  Understanding,
  UnderstandingRecognized,
} from "@ninfa/contracts";

import { sourcesCopy } from "./copy";

/**
 * How what NINFA understood is SAID: numbers, money and dates in Italian, and the origin of each thing in a
 * sentence. Nothing here computes anything about the data - every figure is the backend's, from the rows
 * that passed validation - it only writes it down.
 */

const COPY = sourcesCopy.understanding;

function numberOf(text: string): number | null {
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** "410" / "420,5": hours as the hotel writes them. */
export function hoursText(value: string): string {
  const number = numberOf(value);
  if (number === null) return value;
  return new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2, useGrouping: "always" }).format(number);
}

/** "€6.304,60": an amount with its currency. */
export function moneyText(value: string, currency: string | null): string {
  const number = numberOf(value);
  if (number === null) return value;
  const plain = new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: "always", // 6.304,60 - Italian leaves a four-digit number ungrouped by default
  }).format(number);
  if (currency === null || currency === "EUR") return `€${plain}`;
  return `${plain} ${currency}`;
}

/** "26 ottobre 2026" from "2026-10-26" (a calendar day, no time zone involved). */
export function isoDateText(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** The facts of a file, as short phrases ("13 persone", "410 ore previste"): only those the backend derived. */
export function factsOf(
  domain: DataSourceDomain,
  understanding: Understanding,
  validation: ImportValidationResponse,
): string[] {
  const summary: ImportSummary | null = validation.summary ?? null;
  const facts: string[] = [];
  const money = (value: string | null) =>
    value === null ? null : moneyText(value, summary?.currency ?? null);
  if (domain === "LABOR") {
    if (understanding.people !== null) facts.push(COPY.facts.people(understanding.people));
    if (summary !== null && summary.departments.length > 0) {
      facts.push(COPY.facts.departments(summary.departments.length));
    }
    if (summary?.planned_hours) facts.push(COPY.facts.plannedHours(hoursText(summary.planned_hours)));
    if (summary?.actual_hours) facts.push(COPY.facts.actualHours(hoursText(summary.actual_hours)));
    const planned = money(summary?.planned_cost ?? null);
    if (planned !== null) facts.push(COPY.facts.plannedCost(planned));
    const actual = money(summary?.actual_cost ?? null);
    if (actual !== null) facts.push(COPY.facts.actualCost(actual));
  } else if (domain === "BOOKINGS") {
    facts.push(COPY.facts.bookings(validation.rows_total));
    if (summary?.channels) facts.push(COPY.facts.channels(summary.channels));
    if (summary?.revenue) facts.push(COPY.facts.revenue(moneyText(summary.revenue, null)));
  } else {
    if (summary?.documents) facts.push(COPY.facts.documents(summary.documents));
    if (summary?.suppliers) facts.push(COPY.facts.suppliers(summary.suppliers));
    const net = money(summary?.net_total ?? null);
    if (net !== null) facts.push(COPY.facts.netTotal(net));
  }
  if (facts.length === 0) facts.push(COPY.facts.rows(validation.rows_total));
  return facts;
}

/** "dal 26 ottobre 2026 al 1 novembre 2026", or nothing when the file does not say. */
export function periodText(validation: ImportValidationResponse): string | null {
  const summary = validation.summary ?? null;
  if (summary === null || summary.date_from === null || summary.date_to === null) return null;
  return COPY.facts.period(isoDateText(summary.date_from), isoDateText(summary.date_to));
}

/** Where a recognised thing comes from, in a sentence. */
export function originText(item: UnderstandingRecognized): string {
  const { kind, detail } = item.origin;
  const column = detail ?? "";
  switch (kind) {
    case "COLUMN":
      return COPY.origins.COLUMN(column);
    case "PROFILE":
      return COPY.origins.PROFILE(column);
    case "ASSISTANT":
      return COPY.origins.ASSISTANT(column);
    case "SECTION":
      return COPY.origins.SECTION;
    case "SHEET":
      return COPY.origins.SHEET;
    case "TITLE":
      return COPY.origins.TITLE;
    case "USER":
      return COPY.origins.USER;
    case "LEARNED":
      return COPY.origins.LEARNED;
    case "GRID":
      return COPY.origins.GRID;
    case "PROPERTY":
      return COPY.origins.PROPERTY;
  }
}
