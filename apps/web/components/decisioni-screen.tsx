"use client";

import { useMemo } from "react";

import { copy } from "@/lib/copy";
import { decisioniCopy } from "@/lib/decisions/list-copy";
import { buildDecisionRows } from "@/lib/decisions/list-view-model";
import { useDecisionFeed } from "@/lib/feed/use-decision-feed";

import { DecisioniBoard } from "./decisioni-board";
import { DecisioniHero } from "./decisioni-hero";
import { coverageNote, FeedStateView } from "./feed-state-view";
import { PropertyScreen } from "./property-screen";
import { RefreshButton } from "./refresh-button";

interface DecisioniContentProps {
  propertyId: string;
  timeZone: string;
  onPropertyInvalid: () => void;
}

/** The title alone, with its refresh: what the page shows before there is a feed to summarise. */
function PlainHeader({ busy, onRefresh }: { busy: boolean; onRefresh: () => void }) {
  return (
    <header className="decisioni-hero decisioni-hero--plain">
      <div className="decisioni-hero__title-row">
        <h1>{decisioniCopy.heading}</h1>
        <RefreshButton busy={busy} onRefresh={onRefresh} />
      </div>
    </header>
  );
}

/** Skeleton rows in the shape of the final list, so nothing jumps when the feed arrives. */
function DecisioniSkeleton() {
  return (
    <div className="decisioni-skeleton" aria-busy="true" aria-live="polite">
      <p className="visually-hidden" role="status">
        {copy.today.refreshing}
      </p>
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="decisioni-skeleton__row" aria-hidden="true" />
      ))}
    </div>
  );
}

/** TODAY'S feed, every decision of it (Home UI V1, D7) - exactly the list the Home's "N decisioni richiedono
 * attenzione" counted, so the number a user clicks and the page they land on can never disagree. It is NOT
 * the Decision memory (`GET /decisions`, lifecycle history): that stays deferred.
 *
 * Same fetch / stale / refresh behaviour as the Home (`useDecisionFeed`) and the same four feed states: with
 * decisions to act on, the hero and the board present them (ordered exactly as the backend returned them
 * unless the reader chooses another sort); every other state keeps its dedicated card (`FeedStateView`), so
 * "Tutto sotto controllo" can still only ever appear for `NO_ACTION_REQUIRED`. */
function DecisioniContent({ propertyId, timeZone, onPropertyInvalid }: DecisioniContentProps) {
  const { busy, feed, failed, refresh } = useDecisionFeed({ propertyId, timeZone, onPropertyInvalid });
  const rows = useMemo(() => (feed === null ? [] : buildDecisionRows(feed)), [feed]);
  const onRefresh = () => void refresh();

  if (feed === null) {
    return (
      <div className="decisioni-page">
        <PlainHeader busy={busy} onRefresh={onRefresh} />
        {failed ? (
          <div className="decisioni-screen__error" role="alert">
            <p>{copy.today.loadErrorGeneric}</p>
            <button type="button" onClick={onRefresh}>
              {copy.today.retry}
            </button>
          </div>
        ) : (
          <DecisioniSkeleton />
        )}
      </div>
    );
  }

  const showBoard = feed.feed_state === "ACTION_REQUIRED" && rows.length > 0;
  const coverage = showBoard ? coverageNote(feed.analysis_coverage) : null;

  return (
    <div className="decisioni-page">
      <DecisioniHero feed={feed} timeZone={timeZone} rows={rows} busy={busy} onRefresh={onRefresh} />
      {showBoard ? (
        <>
          <DecisioniBoard feed={feed} rows={rows} />
          {coverage !== null ? <p className="decisioni-coverage">{coverage}</p> : null}
        </>
      ) : (
        <FeedStateView feed={feed} timeZone={timeZone} showAllDecisions />
      )}
    </div>
  );
}

export interface DecisioniScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
}

/** The full "/decisioni" screen: auth bootstrap gate, property resolution, the sidebar shell (with
 * "Decisioni" active) and today's decisions. Framework-free - `app/decisioni/page.tsx` wires it to
 * the real router. */
export function DecisioniScreen(props: DecisioniScreenProps) {
  return (
    <PropertyScreen {...props} activeSection="decisioni" variant="wide">
      {(selected, onPropertyInvalid) => (
        <DecisioniContent
          propertyId={selected.id}
          timeZone={selected.timezone}
          onPropertyInvalid={onPropertyInvalid}
        />
      )}
    </PropertyScreen>
  );
}
