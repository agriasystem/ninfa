"use client";

import { useEffect, useState } from "react";

import type { DecisionFeedResponse } from "@ninfa/contracts";

import { getDecisionFeed } from "@/lib/api/decisions";
import { copy } from "@/lib/copy";
import { formatPropertyLocalDateItalian, propertyLocalDate } from "@/lib/date/property-date";

import { FeedStateView } from "./feed-state-view";

// Every resolved state (not just "loading") carries WHICH property/date it was fetched for, so
// "is this stale for the CURRENT props" can be derived during render (React's own recommended
// pattern) instead of an effect resetting to "loading" itself.
type LoadState =
  | { kind: "loading" }
  | { kind: "resolvingProperty"; propertyId: string; asOfLocalDate: string }
  | { kind: "error"; code: string; propertyId: string; asOfLocalDate: string }
  | { kind: "loaded"; feed: DecisionFeedResponse; propertyId: string; asOfLocalDate: string };

/** Pure: GET the feed and translate it into a `LoadState`. No React tie at all - deliberately a
 * plain module-level function, not a hook-memoized callback, so it can be awaited from EITHER
 * the mount/prop-change effect below or a button click without either caller synchronously
 * calling setState from inside a shared, effect-tracked callback (see `react-hooks/
 * set-state-in-effect`; that rule specifically flags a `useCallback`-produced function that
 * itself sets state being invoked from an effect). */
async function fetchFeedState(propertyId: string, asOfLocalDate: string): Promise<LoadState> {
  const result = await getDecisionFeed(propertyId, asOfLocalDate);
  if (result.ok) {
    return { kind: "loaded", feed: result.data, propertyId, asOfLocalDate };
  }
  if (result.code === "PROPERTY_NOT_FOUND") {
    return { kind: "resolvingProperty", propertyId, asOfLocalDate };
  }
  return { kind: "error", code: result.code, propertyId, asOfLocalDate };
}

export interface TodayScreenProps {
  propertyId: string;
  timeZone: string;
  /** Called when the feed request itself answers 404 PROPERTY_NOT_FOUND (the property became
   * invalid mid-session) - the caller re-resolves property selection; this component never
   * shows the raw backend error for that case, only a neutral "resolving" state meanwhile. */
  onPropertyInvalid: () => void;
}

/** GET /api/v1/properties/{propertyId}/decision-feed?as_of=<property-local-today>, rendered as
 * one of the four feed states - see docs/architecture/oggi-ui-v1.md, "Oggi feed". */
export function TodayScreen({ propertyId, timeZone, onPropertyInvalid }: TodayScreenProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
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

  async function handleRefresh() {
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
    state.kind !== "loading" && (state.propertyId !== propertyId || state.asOfLocalDate !== asOfLocalDate);
  const busy = refreshing || state.kind === "loading" || state.kind === "resolvingProperty" || stale;

  return (
    <div className="today-screen">
      <header className="today-screen__header">
        <h1>{copy.today.heading}</h1>
        <p className="today-screen__date">{formatPropertyLocalDateItalian(new Date(), timeZone)}</p>
        <button type="button" onClick={() => void handleRefresh()} disabled={busy}>
          {busy ? copy.today.refreshing : copy.today.refresh}
        </button>
      </header>

      {busy ? (
        <div className="today-screen__skeleton" aria-live="polite" aria-busy="true">
          <div className="today-screen__skeleton-line" />
          <div className="today-screen__skeleton-line" />
          <div className="today-screen__skeleton-line" />
        </div>
      ) : state.kind === "error" ? (
        <div className="today-screen__error" role="alert">
          <p>{copy.today.loadErrorGeneric}</p>
          <button type="button" onClick={() => void handleRefresh()}>
            {copy.today.retry}
          </button>
        </div>
      ) : state.kind === "loaded" ? (
        <FeedStateView feed={state.feed} />
      ) : null}
    </div>
  );
}
