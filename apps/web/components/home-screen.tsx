"use client";

import Link from "next/link";

import type { DecisionFeedResponse } from "@ninfa/contracts";

import { copy, analysisDomainLabels } from "@/lib/copy";
import { formatBusinessDateItalian } from "@/lib/date/property-date";
import { useDecisionFeed } from "@/lib/feed/use-decision-feed";
import { buildDomainSummary, decisionCountOf } from "@/lib/home/domain-summary";
import { freshnessLineOf } from "@/lib/home/freshness";
import { firstNameOf } from "@/lib/home/greeting";
import { heroFragmentsOf, type HeroFragment } from "@/lib/home/hero-copy";
import { useLogoTransition } from "@/lib/motion/use-logo-transition";
import { decisioniRoute } from "@/lib/routes";
import { useSession } from "@/lib/session/session-context";

import { DomainSummary } from "./domain-summary";
import { ArrowRightIcon } from "./icons";
import { LogoTrailCanvas } from "./logo-trail-canvas";
import { MiaHome } from "./mia-home";
import { NinfaLogo } from "./ninfa-logo";
import { RefreshButton } from "./refresh-button";
import { useShellLogo } from "./shell-logo-context";

/** What the hero says for each of the four feed states: a headline made of styled fragments, and
 * the supporting lines under it. PRESENTATION ONLY - which branch renders is `feed_state`, exactly
 * as the backend decided it; "Tutto sotto controllo" can only ever come from `NO_ACTION_REQUIRED`
 * (Gate 14), and `NOT_PROCESSED` keeps its Gate 24 wording (never analysed vs. last analysis). */
function heroOf(feed: DecisionFeedResponse): { fragments: HeroFragment[]; supporting: string[] } {
  switch (feed.feed_state) {
    case "ACTION_REQUIRED": {
      // The feed is already ordered `priority_rank ASC` by the backend - never re-sorted here.
      const top = feed.items[0];
      return {
        fragments:
          top === undefined
            ? [{ text: copy.today.actionRequiredHeading, tone: "strong" }]
            : heroFragmentsOf(top),
        supporting: [],
      };
    }
    case "NO_ACTION_REQUIRED": {
      const supporting: string[] = [copy.today.noActionBody];
      // Gate 22: "all clear" is never allowed to imply every area was checked when it was not.
      const coverage = feed.analysis_coverage;
      if (coverage.summary === "UNKNOWN") {
        supporting.push(copy.today.coverageUnknown);
      } else if (coverage.summary === "PARTIAL") {
        const skipped = coverage.domains
          .filter((domain) => domain.status === "SKIPPED")
          .map((domain) => analysisDomainLabels[domain.domain]);
        supporting.push(copy.today.coveragePartial(skipped.join(", ")));
      }
      return { fragments: [{ text: copy.today.noActionTitle, tone: "strong" }], supporting };
    }
    case "DATA_QUALITY_LIMITED": {
      const supporting: string[] = [copy.today.dataQualityBody];
      if (feed.insufficient_count !== null && feed.insufficient_count > 0) {
        supporting.push(copy.today.dataQualityInsufficientCount(feed.insufficient_count));
      }
      if (feed.suppressed_count !== null && feed.suppressed_count > 0) {
        supporting.push(copy.today.dataQualitySuppressedCount(feed.suppressed_count));
      }
      return { fragments: [{ text: copy.today.dataQualityTitle, tone: "strong" }], supporting };
    }
    case "NOT_PROCESSED": {
      // Gate 24B: "never analysed" vs "not analysed today, but a previous run exists" - without ever
      // claiming WHY today's own run is absent.
      const last = feed.last_successful_analysis;
      const supporting: string[] = [
        last === null ? copy.today.notProcessedNeverAnalyzed : copy.today.notProcessedBody,
      ];
      if (last !== null) {
        supporting.push(
          copy.today.lastSuccessfulAnalysis(formatBusinessDateItalian(last.as_of_local_date)),
        );
      }
      return { fragments: [{ text: copy.today.notProcessedTitle, tone: "strong" }], supporting };
    }
  }
}

function Fragments({ fragments }: { fragments: HeroFragment[] }) {
  return (
    <>
      {fragments.map((fragment, index) => (
        <span key={index} className={`hero-fragment hero-fragment--${fragment.tone}`}>
          {fragment.text}
        </span>
      ))}
    </>
  );
}

interface FeedContentProps {
  feed: DecisionFeedResponse;
  propertyId: string;
  timeZone: string;
  busy: boolean;
  onRefresh: () => void;
}

function FeedContent({ feed, propertyId, timeZone, busy, onRefresh }: FeedContentProps) {
  const hero = heroOf(feed);
  const count = decisionCountOf(feed);
  const tiles = buildDomainSummary(feed);
  // Gate 23B: never under NOT_PROCESSED (no run, so nothing to describe) - and always a FACT.
  const freshness =
    feed.feed_state === "NOT_PROCESSED"
      ? null
      : freshnessLineOf(feed.input_freshness, feed.as_of_local_date, timeZone);

  return (
    <div className="home__feed" data-feed-state={feed.feed_state} aria-busy={busy}>
      <h1 className="home__message">
        <Fragments fragments={hero.fragments} />
      </h1>
      {hero.supporting.map((line) => (
        <p key={line} className="home__supporting">
          {line}
        </p>
      ))}

      <div className="home__status">
        {count > 0 ? (
          <Link className="home__decisions-link" href={decisioniRoute(propertyId)}>
            <span>{copy.home.decisionsRequireAttention(count)}</span>
            <ArrowRightIcon className="home__decisions-link-arrow" />
          </Link>
        ) : null}
        {count > 0 && freshness !== null ? (
          <span className="home__status-divider" aria-hidden="true" />
        ) : null}
        <div className="home__freshness-group">
          {freshness !== null ? (
            <p className="home__freshness" data-freshness={freshness.kind}>
              <span className="home__freshness-dot" aria-hidden="true" />
              <span>{freshness.text}</span>
            </p>
          ) : null}
          <RefreshButton busy={busy} onRefresh={onRefresh} />
        </div>
      </div>

      {tiles !== null ? <DomainSummary tiles={tiles} /> : null}
    </div>
  );
}

export interface HomeScreenProps {
  propertyId: string;
  timeZone: string;
  /** Called when the feed request itself answers 404 PROPERTY_NOT_FOUND (the property became
   * invalid mid-session) - the caller re-resolves property selection; this screen never shows the
   * raw backend error for that case, only a neutral loading state meanwhile. */
  onPropertyInvalid: () => void;
}

/**
 * The decision-first Home, "Oggi" (Home UI V1): NINFA tells the user what deserves attention, so the
 * user never has to read the data. Presents ONLY what the Decision Engine already decided - the feed
 * of `GET /properties/{id}/decision-feed?as_of=<property-local-today>` - and adds no detection,
 * ranking or interpretation of its own. The hero is the top-priority Decision (or the truthful
 * state headline), then "N decisioni richiedono attenzione" (-> /decisioni), the factual last
 * booking import, the four-area strip and Mia.
 *
 * Gate 14/24 semantics are preserved: the four feed states stay mutually exclusive, a refresh stays
 * available (the discreet icon next to the freshness line), 404 PROPERTY_NOT_FOUND re-resolves the
 * property instead of showing a raw error.
 */
export function HomeScreen({ propertyId, timeZone, onPropertyInvalid }: HomeScreenProps) {
  const { session } = useSession();
  const shellLogo = useShellLogo();
  const logo = useLogoTransition({ revealSidebarLogo: () => shellLogo.setHidden(false) });
  const { asOfLocalDate, busy, feed, failed, refresh } = useDecisionFeed({
    propertyId,
    timeZone,
    onPropertyInvalid,
  });

  const greeting = copy.home.greeting(firstNameOf(session?.user.display_name));
  const fading = logo.phase === "morphing" && logo.mode === "fade";

  return (
    <div className="home" data-logo-phase={logo.phase}>
      <div className="home__aurora" aria-hidden="true" />
      <div className="home__layout">
        <section className="home__hero">
          <div className="home__logo-wrap">
            {logo.phase === "settled" ? null : (
              <NinfaLogo
                imgRef={logo.heroRef}
                className={fading ? "home__logo home__logo--leaving" : "home__logo"}
              />
            )}
          </div>
          <p className="home__greeting">{greeting}</p>

          {feed !== null ? (
            <FeedContent
              feed={feed}
              propertyId={propertyId}
              timeZone={timeZone}
              busy={busy}
              onRefresh={() => void refresh()}
            />
          ) : failed ? (
            <div className="home__feed">
              <h1 className="visually-hidden">{copy.today.heading}</h1>
              <div className="home__error" role="alert">
                <p>{copy.today.loadErrorGeneric}</p>
                <button type="button" onClick={() => void refresh()}>
                  {copy.today.retry}
                </button>
              </div>
            </div>
          ) : (
            <div className="home__feed" aria-busy="true">
              <h1 className="visually-hidden">{copy.today.heading}</h1>
              <div className="home__skeleton" aria-live="polite">
                <span className="home__skeleton-line home__skeleton-line--wide" />
                <span className="home__skeleton-line" />
                <span className="home__skeleton-line home__skeleton-line--short" />
              </div>
            </div>
          )}
        </section>

        <MiaHome
          key={propertyId}
          propertyId={propertyId}
          asOfLocalDate={asOfLocalDate}
          onFirstInput={logo.trigger}
        />
      </div>

      {logo.phase === "morphing" && logo.mode === "trail" ? (
        <LogoTrailCanvas
          heroRef={logo.heroRef}
          slotRef={shellLogo.slotRef}
          onProgress={logo.trail.onProgress}
          onArrive={logo.trail.onArrive}
          onDone={logo.trail.onDone}
          onUnavailable={logo.trail.onUnavailable}
        />
      ) : null}
    </div>
  );
}
