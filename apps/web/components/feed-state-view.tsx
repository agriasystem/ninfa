import type { AnalysisCoverage, DecisionFeedResponse, InputFreshness } from "@ninfa/contracts";

import { analysisDomainLabels, copy } from "@/lib/copy";
import { formatPropertyLocalDateTimeItalian } from "@/lib/date/property-date";

import { DecisionList } from "./decision-list";

export interface FeedStateViewProps {
  feed: DecisionFeedResponse;
  /** The Property's own IANA timezone (Gate 23B) - the freshness line below is formatted in
   * THIS timezone, never the browser's own (see `lib/date/property-date.ts`). */
  timeZone: string;
}

/** Gate 22: the one qualifying line every feed state below may add under its own headline -
 * `null` for FULL coverage (no extra noise when nothing was skipped). Coverage is a SEPARATE
 * dimension from feed_state on purpose (see docs/architecture/analysis-coverage-v1.md): this
 * never changes which of the four branches renders, only adds one subordinate line to it. */
function coverageNote(coverage: AnalysisCoverage): string | null {
  if (coverage.summary === "UNKNOWN") return copy.today.coverageUnknown;
  if (coverage.summary === "FULL") return null;
  const skipped = coverage.domains
    .filter((domain) => domain.status === "SKIPPED")
    .map((domain) => analysisDomainLabels[domain.domain]);
  return copy.today.coveragePartial(skipped.join(", "));
}

/** Gate 23B: the one qualifying FACTUAL line every processed feed state below may add under
 * its own headline (never NOT_PROCESSED - see `copy.today.freshnessKnown`'s own module
 * docstring for why this is never a judgement like CURRENT/STALE). A separate dimension from
 * both `feed_state` and coverage: this never changes which branch renders, only adds one more
 * subordinate line to it. */
function freshnessNote(freshness: InputFreshness, timeZone: string): string {
  const { bookings } = freshness;
  if (bookings.status === "UNKNOWN" || bookings.last_successful_import_finished_at === null) {
    return copy.today.freshnessUnknown;
  }
  const formatted = formatPropertyLocalDateTimeItalian(
    new Date(bookings.last_successful_import_finished_at),
    timeZone,
  );
  return copy.today.freshnessKnown(formatted);
}

/**
 * The four feed states are NON-NEGOTIABLY distinct, both visually and semantically (Gate 14
 * spec): "Tutto sotto controllo" (or its equivalent) may ONLY ever appear for
 * `NO_ACTION_REQUIRED` - every other branch below is a separate, dedicated render path so that
 * copy can never leak between them. Gate 22's coverage note is additive within each branch, never
 * a fifth branch of its own.
 */
export function FeedStateView({ feed, timeZone }: FeedStateViewProps) {
  const coverage = coverageNote(feed.analysis_coverage);
  const freshness = freshnessNote(feed.input_freshness, timeZone);

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
          {coverage !== null ? <p className="feed-state__coverage">{coverage}</p> : null}
          <p className="feed-state__freshness">{freshness}</p>
        </section>
      );

    case "NO_ACTION_REQUIRED":
      return (
        <section className="feed-state feed-state--no-action-required" data-feed-state="NO_ACTION_REQUIRED">
          <h2>{copy.today.noActionTitle}</h2>
          <p>{copy.today.noActionBody}</p>
          {coverage !== null ? <p className="feed-state__coverage">{coverage}</p> : null}
          <p className="feed-state__freshness">{freshness}</p>
        </section>
      );

    case "ACTION_REQUIRED":
      return (
        <section className="feed-state feed-state--action-required" data-feed-state="ACTION_REQUIRED">
          <DecisionList items={feed.items} propertyId={feed.property_id} />
          {coverage !== null ? <p className="feed-state__coverage">{coverage}</p> : null}
          <p className="feed-state__freshness">{freshness}</p>
        </section>
      );
  }
}
