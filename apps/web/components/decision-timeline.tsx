import type { DecisionTarget, ObservationDetail } from "@ninfa/contracts";

import { copy, lifecycleEventCopy } from "@/lib/copy";
import { cardViewModelFromTargetAndFacts } from "@/lib/decisions/card-view-models";
import { formatLocalDateItalian } from "@/lib/date/local-date";
import { historyKeyFact } from "@/lib/decisions/history-key-fact";

export interface DecisionTimelineProps {
  /** Newest-first, exactly as the backend returns and as pages are appended - never re-sorted. */
  items: ObservationDetail[];
  /** The Decision's own target - shared across every observation (target does not change
   * between observations of the SAME decision). */
  target: DecisionTarget;
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: boolean;
  onLoadMore: () => void;
}

/**
 * "Evoluzione": a simple vertical list, CSS/HTML only - no chart, no sparkline. Each entry shows
 * a date, a calm lifecycle/status copy, and at most one synthetic key fact taken from THAT
 * observation's own facts (never the current detail's) - the memory has to describe what that
 * day genuinely looked like. Technical audit fields (observation id, fingerprints, memory
 * version) are never rendered here.
 */
export function DecisionTimeline({
  items,
  target,
  hasMore,
  loadingMore,
  loadMoreError,
  onLoadMore,
}: DecisionTimelineProps) {
  return (
    <section className="decision-timeline">
      <h2 className="decision-timeline__heading">{copy.detail.sectionHistory}</h2>

      {items.length === 0 ? (
        <p className="decision-timeline__empty">{copy.detail.historyEmpty}</p>
      ) : (
        <ol className="decision-timeline__items">
          {items.map((observation) => {
            const card = cardViewModelFromTargetAndFacts(target, observation.facts);
            const keyFact = historyKeyFact(card);
            const showRank = observation.source_status === "TRIGGERED" && observation.priority !== null;
            return (
              <li key={observation.observation_id} className="decision-timeline__item">
                <time className="decision-timeline__date" dateTime={observation.as_of_local_date}>
                  {formatLocalDateItalian(observation.as_of_local_date, { withYear: true })}
                </time>
                <span className="decision-timeline__event">
                  {lifecycleEventCopy(observation.lifecycle_transition, observation.source_status)}
                </span>
                {keyFact !== null ? (
                  <span className="decision-timeline__fact">{keyFact}</span>
                ) : null}
                {showRank && observation.priority !== null ? (
                  <span className="decision-timeline__rank">
                    {copy.detail.historyPriorityLine(observation.priority.rank)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      {loadMoreError ? (
        <p className="decision-timeline__error" role="alert">
          {copy.detail.historyLoadMoreError}
        </p>
      ) : null}

      {hasMore ? (
        <button type="button" onClick={onLoadMore} disabled={loadingMore}>
          {loadingMore ? copy.detail.historyLoadingMore : copy.detail.historyLoadMore}
        </button>
      ) : null}
    </section>
  );
}
