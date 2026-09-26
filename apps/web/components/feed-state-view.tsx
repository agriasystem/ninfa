import type { DecisionFeedResponse } from "@ninfa/contracts";

import { copy } from "@/lib/copy";

import { DecisionList } from "./decision-list";

export interface FeedStateViewProps {
  feed: DecisionFeedResponse;
}

/**
 * The four feed states are NON-NEGOTIABLY distinct, both visually and semantically (Gate 14
 * spec): "Tutto sotto controllo" (or its equivalent) may ONLY ever appear for
 * `NO_ACTION_REQUIRED` - every other branch below is a separate, dedicated render path so that
 * copy can never leak between them.
 */
export function FeedStateView({ feed }: FeedStateViewProps) {
  switch (feed.feed_state) {
    case "NOT_PROCESSED":
      return (
        <section className="feed-state feed-state--not-processed" data-feed-state="NOT_PROCESSED">
          <h2>{copy.today.notProcessedTitle}</h2>
          <p>{copy.today.notProcessedBody}</p>
        </section>
      );

    case "DATA_QUALITY_LIMITED":
      return (
        <section
          className="feed-state feed-state--data-quality-limited"
          data-feed-state="DATA_QUALITY_LIMITED"
        >
          <h2>{copy.today.dataQualityTitle}</h2>
          <p>{copy.today.dataQualityBody}</p>
          {feed.insufficient_count !== null && feed.insufficient_count > 0 ? (
            <p className="feed-state__detail">
              {copy.today.dataQualityInsufficientCount(feed.insufficient_count)}
            </p>
          ) : null}
          {feed.suppressed_count !== null && feed.suppressed_count > 0 ? (
            <p className="feed-state__detail">
              {copy.today.dataQualitySuppressedCount(feed.suppressed_count)}
            </p>
          ) : null}
        </section>
      );

    case "NO_ACTION_REQUIRED":
      return (
        <section className="feed-state feed-state--no-action-required" data-feed-state="NO_ACTION_REQUIRED">
          <h2>{copy.today.noActionTitle}</h2>
          <p>{copy.today.noActionBody}</p>
        </section>
      );

    case "ACTION_REQUIRED":
      return (
        <section className="feed-state feed-state--action-required" data-feed-state="ACTION_REQUIRED">
          <DecisionList items={feed.items} />
        </section>
      );
  }
}
