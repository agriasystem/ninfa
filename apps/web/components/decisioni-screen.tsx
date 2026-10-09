"use client";

import { copy } from "@/lib/copy";
import { useDecisionFeed } from "@/lib/feed/use-decision-feed";

import { FeedStateView } from "./feed-state-view";
import { PropertyScreen } from "./property-screen";
import { RefreshButton } from "./refresh-button";

interface DecisioniContentProps {
  propertyId: string;
  timeZone: string;
  onPropertyInvalid: () => void;
}

/** TODAY'S feed, every triggered decision of it (Home UI V1, D7) - exactly the list the Home's
 * "N decisioni richiedono attenzione" counted, so the number a user clicks and the page they land
 * on can never disagree. It is NOT the Decision memory (`GET /decisions`, lifecycle history): that
 * stays deferred. Same fetch/stale/refresh behaviour as the Home (`useDecisionFeed`), same four
 * feed states (`FeedStateView`), ordered exactly as the backend returned them. */
function DecisioniContent({ propertyId, timeZone, onPropertyInvalid }: DecisioniContentProps) {
  const { busy, feed, failed, refresh } = useDecisionFeed({
    propertyId,
    timeZone,
    onPropertyInvalid,
  });

  return (
    <div className="decisioni-screen">
      <header className="decisioni-screen__header">
        <h1>{copy.decisioni.heading}</h1>
        <RefreshButton busy={busy} onRefresh={() => void refresh()} />
      </header>

      {feed !== null ? (
        <FeedStateView feed={feed} timeZone={timeZone} showAllDecisions />
      ) : failed ? (
        <div className="decisioni-screen__error" role="alert">
          <p>{copy.today.loadErrorGeneric}</p>
          <button type="button" onClick={() => void refresh()}>
            {copy.today.retry}
          </button>
        </div>
      ) : (
        <div className="today-screen__skeleton" aria-live="polite" aria-busy="true">
          <div className="today-screen__skeleton-line" />
          <div className="today-screen__skeleton-line" />
          <div className="today-screen__skeleton-line" />
        </div>
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
    <PropertyScreen {...props} activeSection="decisioni">
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
