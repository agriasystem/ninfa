"use client";

import type { AnalysisDomain, DecisionFeedResponse } from "@ninfa/contracts";

import { analysisDomainLabels, copy } from "@/lib/copy";
import { decisioniCopy } from "@/lib/decisions/list-copy";
import { countByArea, type DecisionRowData } from "@/lib/decisions/list-view-model";
import { freshnessLineOf } from "@/lib/home/freshness";

import { TargetIcon, TrendIcon } from "./icons";
import { RefreshButton } from "./refresh-button";

const AREAS: readonly AnalysisDomain[] = ["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"];

/** How many areas the run actually analysed - the denominator of "Aree coinvolte N di M". `null` when the
 * run recorded no coverage: the card then states only how many areas have a decision, never an invented M. */
function analysedAreas(coverage: DecisionFeedResponse["analysis_coverage"]): number | null {
  if (coverage.summary === "UNKNOWN") return null;
  return coverage.domains.filter((domain) => domain.status === "EVALUATED").length;
}

function StatCard({
  id,
  label,
  value,
  caption,
  Icon,
}: {
  id: string;
  label: string;
  value: string;
  caption: string;
  Icon: typeof TrendIcon;
}) {
  return (
    <article className="decisioni-stat" aria-labelledby={`${id}-label`}>
      <span className="decisioni-stat__tile" aria-hidden="true">
        <Icon className="decisioni-stat__icon" />
      </span>
      <div className="decisioni-stat__text">
        <p id={`${id}-label`} className="decisioni-stat__label">
          {label}
        </p>
        <p className="decisioni-stat__value">{value}</p>
        <p className="decisioni-stat__caption">{caption}</p>
      </div>
    </article>
  );
}

export interface DecisioniHeroProps {
  feed: DecisionFeedResponse;
  timeZone: string;
  rows: readonly DecisionRowData[];
  busy: boolean;
  onRefresh: () => void;
}

/**
 * The top of `/decisioni`: the title, how many decisions need attention, the freshness of the booking import
 * as a FACT ("Ultimo import prenotazioni: oggi alle HH:MM" - never "Dati aggiornati"), and two summary cards.
 *
 * The cards state only what the feed holds: which decision NINFA ranks first and which of the analysed areas
 * are involved. There is no aggregate "impatto stimato" total: an economic estimate exists only for cost and
 * labor decisions, carries its own currency, and the product never sums estimates or compares them across
 * kinds (revenue vs cost) - so each row shows its own impact where the engine recorded one.
 *
 * In every other feed state (no analysis, partial, nothing to act on) there is nothing to summarise: the
 * hero is just the title, and the existing state card below it says what is going on.
 */
export function DecisioniHero({ feed, timeZone, rows, busy, onRefresh }: DecisioniHeroProps) {
  const first = rows[0];
  if (feed.feed_state !== "ACTION_REQUIRED" || first === undefined) {
    return (
      <header className="decisioni-hero decisioni-hero--plain">
        <div className="decisioni-hero__title-row">
          <h1>{decisioniCopy.heading}</h1>
          <RefreshButton busy={busy} onRefresh={onRefresh} />
        </div>
      </header>
    );
  }

  const freshness = freshnessLineOf(feed.input_freshness, feed.as_of_local_date, timeZone);
  const counts = countByArea(rows);
  const involved = AREAS.filter((area) => counts[area] > 0);
  const analysed = analysedAreas(feed.analysis_coverage);

  return (
    <header className="decisioni-hero">
      <div className="decisioni-hero__heading">
        <h1>{decisioniCopy.heading}</h1>
        <p className="decisioni-hero__summary">{copy.home.decisionsRequireAttention(rows.length)}</p>
        <p className="decisioni-hero__fresh" data-kind={freshness.kind}>
          <span>{freshness.text}</span>
          <RefreshButton busy={busy} onRefresh={onRefresh} />
        </p>
      </div>

      <div className="decisioni-hero__stats">
        <StatCard
          id="decisioni-first"
          Icon={TrendIcon}
          label={decisioniCopy.firstDecision}
          value={analysisDomainLabels[first.area]}
          caption={first.title}
        />
        <StatCard
          id="decisioni-areas"
          Icon={TargetIcon}
          label={decisioniCopy.involvedAreas}
          value={analysed === null ? String(involved.length) : decisioniCopy.involvedAreasOf(involved.length, analysed)}
          caption={involved.map((area) => analysisDomainLabels[area]).join(", ")}
        />
      </div>
    </header>
  );
}
