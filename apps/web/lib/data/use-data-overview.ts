"use client";

import { useEffect, useRef, useState } from "react";

import type { DataOverviewResponse, DataPeriod } from "@ninfa/contracts";

import { getDataOverview } from "@/lib/api/data-overview";
import { propertyLocalDate } from "@/lib/date/property-date";

// Every resolved state carries WHICH property / date / period it was fetched for, so "is this stale
// for the CURRENT props" is derived during render (React's own recommended pattern) instead of an
// effect resetting to "loading" itself.
type LoadState =
  | { kind: "loading" }
  | { kind: "resolvingProperty"; propertyId: string; asOfLocalDate: string; period: DataPeriod }
  | { kind: "error"; code: string; propertyId: string; asOfLocalDate: string; period: DataPeriod }
  | {
      kind: "loaded";
      data: DataOverviewResponse;
      propertyId: string;
      asOfLocalDate: string;
      period: DataPeriod;
    };

/** Pure: GET the overview and translate it into a `LoadState`. A plain module-level function (not a
 * hook-memoized callback) so an effect and a click can both await it without either synchronously
 * setting state from a shared, effect-tracked callback (`react-hooks/set-state-in-effect`). */
async function fetchOverviewState(
  propertyId: string,
  asOfLocalDate: string,
  period: DataPeriod,
): Promise<LoadState> {
  const result = await getDataOverview(propertyId, asOfLocalDate, period);
  if (result.ok) {
    return { kind: "loaded", data: result.data, propertyId, asOfLocalDate, period };
  }
  if (result.code === "PROPERTY_NOT_FOUND") {
    return { kind: "resolvingProperty", propertyId, asOfLocalDate, period };
  }
  return { kind: "error", code: result.code, propertyId, asOfLocalDate, period };
}

export interface UseDataOverviewOptions {
  propertyId: string;
  timeZone: string;
  period: DataPeriod;
  /** Called when the request itself answers 404 PROPERTY_NOT_FOUND (the property became invalid
   * mid-session): the caller re-resolves the selection; the raw error is never shown. */
  onPropertyInvalid: () => void;
}

export interface DataOverviewHandle {
  /** The property-local "today" the overview is (being) requested for - `YYYY-MM-DD`. */
  asOfLocalDate: string;
  /** `true` while loading, refreshing, resolving the property, or while a different period / property
   * / date than the one shown is being fetched. */
  busy: boolean;
  /** The loaded overview for the CURRENT property and date - `null` before the first answer, on
   * error, and when the held result belongs to another property or date. A result of ANOTHER PERIOD
   * stays on screen while the new one loads (`busy`), so toggling 7/30 days never blanks the page. */
  data: DataOverviewResponse | null;
  /** `true` only for a settled, non-busy error (a retry is offered). */
  failed: boolean;
  /** Repeats the SAME `GET` - never a detector run, a Decision sync or any other write. */
  refresh: () => Promise<void>;
}

/**
 * GET /api/v1/properties/{propertyId}/data/overview?as_of=<property-local-today>&period=7|30: one
 * fetch/stale/refresh behaviour for the whole Dati page, whatever tab is open (the five tabs are five
 * views of the same response). Deterministic: the page never asks a model anything.
 */
export function useDataOverview({
  propertyId,
  timeZone,
  period,
  onPropertyInvalid,
}: UseDataOverviewOptions): DataOverviewHandle {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const asOfLocalDate = propertyLocalDate(new Date(), timeZone);

  // The caller builds a new `onPropertyInvalid` on every render. Listing it as an effect dependency
  // would refetch the overview whenever ANYTHING re-renders - switching a tab included - although a tab
  // is only a view of the same response. The effect therefore reads the latest callback through a ref
  // and depends only on what really changes the request: the property, the date and the period.
  const onPropertyInvalidRef = useRef(onPropertyInvalid);
  useEffect(() => {
    onPropertyInvalidRef.current = onPropertyInvalid;
  });

  useEffect(() => {
    let ignore = false;
    async function run() {
      const next = await fetchOverviewState(propertyId, asOfLocalDate, period);
      if (ignore) return;
      setState(next);
      if (next.kind === "resolvingProperty") onPropertyInvalidRef.current();
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [propertyId, asOfLocalDate, period]);

  async function refresh() {
    setRefreshing(true);
    const next = await fetchOverviewState(propertyId, asOfLocalDate, period);
    setState(next);
    if (next.kind === "resolvingProperty") onPropertyInvalid();
    setRefreshing(false);
  }

  // The held result belongs to ANOTHER property or date: never shown (a switch must update every
  // figure). Another PERIOD of the same property and date is merely not the latest yet.
  const foreign =
    state.kind !== "loading" &&
    (state.propertyId !== propertyId || state.asOfLocalDate !== asOfLocalDate);
  const periodChanged = state.kind !== "loading" && !foreign && state.period !== period;
  const busy =
    refreshing ||
    state.kind === "loading" ||
    state.kind === "resolvingProperty" ||
    foreign ||
    periodChanged;

  return {
    asOfLocalDate,
    busy,
    data: !foreign && state.kind === "loaded" ? state.data : null,
    failed: !busy && state.kind === "error",
    refresh,
  };
}
