"use client";

import { useCallback } from "react";

import type { MiaUiContext } from "@ninfa/contracts";

import {
  PAGE_ROUTES,
  usePageStateReader,
  type PageState,
} from "@/lib/page-context/page-context";

/**
 * What Mia is told about the SCREEN the person is looking at (Mia OpenAI Intelligence V1, "page-aware"):
 * the screens' published state (`lib/page-context`) turned into the request's `ui_context`, at the
 * moment a message is sent. A small, bounded HINT - only identifiers, never DOM, HTML or text typed or
 * shown on the page. The backend checks every id against the person's own property and drops anything
 * that does not check out; the truth of a figure still comes from the backend's tools, never from this
 * hint.
 */

const ROUTES: ReadonlySet<string> = new Set(Object.values(PAGE_ROUTES));
const ENTITY_KINDS: ReadonlySet<string> = new Set([
  "night",
  "data_source",
  "cost_category",
  "labor_category",
  "channel",
]);
const PERIODS: ReadonlySet<number> = new Set([7, 30]);

// The shapes the backend accepts (`ui_context.py`): a value that does not match is left out HERE, so a
// wrong value from a screen can never turn a question into a validation error.
const SECTION = /^[a-z0-9_-]{1,40}$/u;
const METRIC = /^[A-Za-z0-9_.:-]{1,60}$/u;
const ENTITY_ID = /^[A-Za-z0-9_.:-]{1,64}$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;

/** The request's `ui_context` from the published state: only the allowed keys, only well-formed
 * values, nothing undefined. Pure. */
export function buildMiaUiContext(state: PageState): MiaUiContext {
  const context: MiaUiContext = {};
  if (state.route !== undefined && ROUTES.has(state.route)) context.route = state.route;
  if (state.section !== undefined && SECTION.test(state.section)) context.section = state.section;
  if (state.periodDays !== undefined && PERIODS.has(state.periodDays)) {
    context.period_days = state.periodDays;
  }
  if (state.dateFrom !== undefined && ISO_DATE.test(state.dateFrom)) {
    context.date_from = state.dateFrom;
  }
  if (state.dateTo !== undefined && ISO_DATE.test(state.dateTo)) context.date_to = state.dateTo;
  if (state.metricId !== undefined && METRIC.test(state.metricId)) {
    context.selected_metric = state.metricId;
  }
  if (state.decisionId !== undefined && UUID.test(state.decisionId)) {
    context.decision_id = state.decisionId;
  }
  if (state.importId !== undefined && UUID.test(state.importId)) context.import_id = state.importId;
  if (state.entityKind !== undefined && ENTITY_KINDS.has(state.entityKind)) {
    context.entity_kind = state.entityKind;
    if (state.entityId !== undefined && ENTITY_ID.test(state.entityId)) {
      context.entity_id = state.entityId;
    }
  }
  return context;
}

/** The reader a conversation calls when a message is sent: the `ui_context` of the screen as it is at
 * that moment. `{}` outside a provider. Stable between renders. */
export function useMiaUiContextReader(): () => MiaUiContext {
  const readPage = usePageStateReader();
  return useCallback(() => buildMiaUiContext(readPage()), [readPage]);
}
