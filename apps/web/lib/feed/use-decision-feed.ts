"use client";

import { useEffect, useState } from "react";

import type { DecisionFeedResponse } from "@ninfa/contracts";

import { getDecisionFeed } from "@/lib/api/decisions";
import { propertyLocalDate } from "@/lib/date/property-date";

// Every resolved state (not just "loading") carries WHICH property/date it was fetched for, so
// "is this stale for the CURRENT props" can be derived during render (React's own recommended
// pattern) instead of an effect resetting to "loading" itself.
export type FeedLoadState =
  | { kind: "loading" }
  | { kind: "resolvingProperty"; propertyId: string; asOfLocalDate: string }
  | { kind: "error"; code: string; propertyId: string; asOfLocalDate: string }
  | { kind: "loaded"; feed: DecisionFeedResponse; propertyId: string; asOfLocalDate: string };

/** Pure: GET the feed and translate it into a `FeedLoadState`. No React tie at all - deliberately a
 * plain module-level function, not a hook-memoized callback, so it can be awaited from EITHER
 * the mount/prop-change effect below or a button click without either caller synchronously
 * calling setState from inside a shared, effect-tracked callback (see `react-hooks/
 * set-state-in-effect`; that rule specifically flags a `useCallback`-produced function that
 * itself sets state being invoked from an effect). */
async function fetchFeedState(propertyId: string, asOfLocalDate: string): Promise<FeedLoadState> {
  const result = await getDecisionFeed(propertyId, asOfLocalDate);
  if (result.ok) {
    return { kind: "loaded", feed: result.data, propertyId, asOfLocalDate };
  }
  if (result.code === "PROPERTY_NOT_FOUND") {
    return { kind: "resolvingProperty", propertyId, asOfLocalDate };
  }
  return { kind: "error", code: result.code, propertyId, asOfLocalDate };
}

export interface UseDecisionFeedOptions {
  propertyId: string;
  timeZone: string;
  /** Called when the feed request itself answers 404 PROPERTY_NOT_FOUND (the property became
   * invalid mid-session) - the caller re-resolves property selection; this hook never shows the
   * raw backend error for that case, only a neutral "resolving" state meanwhile. */
  onPropertyInvalid: () => void;
}

export interface DecisionFeedHandle {
  /** The property-local "today" the feed is (being) requested for - `YYYY-MM-DD`. */
  asOfLocalDate: string;
  /** `true` while loading, refreshing, resolving the property, or holding a result that belongs
   * to a DIFFERENT property/date than the current props. */
  busy: boolean;
  /** The loaded feed for the CURRENT property/date - `null` before the first answer, on error, and
   * whenever the held result is stale. NOT cleared by a refresh in flight (see `busy`). */
  feed: DecisionFeedResponse | null;
  /** `true` only for a settled, non-busy error (a retry is offered). */
  failed: boolean;
  /** Repeats the SAME `GET` - never a detector run, a Decision sync or any other write. */
  refresh: () => Promise<void>;
}

/**
 * GET /api/v1/properties/{propertyId}/decision-feed?as_of=<property-local-today> (Gate 14), shared
 * by every screen that renders today's feed (the Home and `/decisioni`) - one fetch/stale/
 * refresh behaviour, never two diverging copies of it.
 */
export function useDecisionFeed({
  propertyId,
  timeZone,
  onPropertyInvalid,
}: UseDecisionFeedOptions): DecisionFeedHandle {
  const [state, setState] = useState<FeedLoadState>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const asOfLocalDate = propertyLocalDate(new Date(), timeZone);

  useEffect(() => {
    let ignore = false;
    async function run() {
      const next = await fetchFeedState(propertyId, asOfLocalDate);
      if (ignore) return;
      setState(next);
      if (next.kind === "resolvingProperty") {
        onPropertyInvalid();
      }
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [propertyId, asOfLocalDate, onPropertyInvalid]);

  async function refresh() {
    setRefreshing(true);
    const next = await fetchFeedState(propertyId, asOfLocalDate);
    setState(next);
    if (next.kind === "resolvingProperty") {
      onPropertyInvalid();
    }
    setRefreshing(false);
  }

  // The last resolved state belongs to a DIFFERENT property/date than what is asked for right
  // now (e.g. the property was just switched) - treat it exactly like "still loading".
  const stale =
    state.kind !== "loading" &&
    (state.propertyId !== propertyId || state.asOfLocalDate !== asOfLocalDate);
  const busy = refreshing || state.kind === "loading" || state.kind === "resolvingProperty" || stale;

  return {
    asOfLocalDate,
    busy,
    // Kept on screen WHILE a refresh is in flight (only `busy` flips): a refresh never swaps the
    // whole page for a skeleton, so the control that triggered it is never unmounted under the
    // user's focus. A feed that belongs to another property/date (`stale`) is never shown.
    feed: !stale && state.kind === "loaded" ? state.feed : null,
    failed: !busy && state.kind === "error",
    refresh,
  };
}
