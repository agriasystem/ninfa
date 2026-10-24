"use client";

import { useId, useMemo, useState } from "react";

import type { AnalysisDomain, DecisionFeedResponse } from "@ninfa/contracts";

import { analysisDomainLabels } from "@/lib/copy";
import { decisioniCopy } from "@/lib/decisions/list-copy";
import { countByArea, sortRows, type DecisionRowData, type DecisionSort } from "@/lib/decisions/list-view-model";
import { buildDomainSummary } from "@/lib/home/domain-summary";
import { decisionDetailRoute } from "@/lib/routes";

import { ChevronDownIcon } from "./icons";
import { DecisionRow } from "./decision-row";

const AREAS: readonly AnalysisDomain[] = ["REVENUE", "DISTRIBUTION", "COSTS", "LABOR"];
const SORTS: readonly DecisionSort[] = ["priority", "recent", "oldest"];

type AreaFilter = "ALL" | AnalysisDomain;

/** What an area with no decision says - from the run's own coverage, so an area that was not analysed (or
 * only partly) is never read as "all fine". */
function emptyAreaText(feed: DecisionFeedResponse, area: AnalysisDomain): string {
  const tile = buildDomainSummary(feed)?.find((item) => item.domain === area);
  switch (tile?.tone) {
    case "clear":
      return decisioniCopy.emptyArea.clear;
    case "partial":
      return decisioniCopy.emptyArea.partial;
    default:
      return decisioniCopy.emptyArea.unavailable;
  }
}

export interface DecisioniBoardProps {
  feed: DecisionFeedResponse;
  rows: readonly DecisionRowData[];
}

/**
 * The filter pills (every area with its count), the sort control, and the list of rows.
 *
 * Filtering narrows the rows the backend sent and sorting reorders them for the reader; the default - "Priorità" -
 * is the backend's own order, untouched. Nothing here re-ranks, re-thresholds or recomputes a decision.
 */
export function DecisioniBoard({ feed, rows }: DecisioniBoardProps) {
  const [area, setArea] = useState<AreaFilter>("ALL");
  const [sort, setSort] = useState<DecisionSort>("priority");
  const sortId = useId();

  const counts = useMemo(() => countByArea(rows), [rows]);
  const visible = useMemo(() => {
    const ordered = sortRows(rows, sort);
    return area === "ALL" ? ordered : ordered.filter((row) => row.area === area);
  }, [rows, area, sort]);

  return (
    <section className="decisioni-board" aria-label={decisioniCopy.listLabel}>
      <div className="decisioni-filters">
        <div className="decisioni-filters__pills" role="group" aria-label={decisioniCopy.filtersLabel}>
          <button
            type="button"
            className="decisioni-pill decisioni-pill--all"
            aria-pressed={area === "ALL"}
            aria-label={decisioniCopy.countAll(rows.length)}
            onClick={() => setArea("ALL")}
          >
            <span>{decisioniCopy.all}</span>
            <span className="decisioni-pill__count" aria-hidden="true">
              {rows.length}
            </span>
          </button>
          {AREAS.map((item) => (
            <button
              key={item}
              type="button"
              className="decisioni-pill"
              data-area={item}
              aria-pressed={area === item}
              aria-label={decisioniCopy.countInArea(analysisDomainLabels[item], counts[item])}
              onClick={() => setArea(item)}
            >
              <span className="decisioni-pill__dot" aria-hidden="true" />
              <span>{analysisDomainLabels[item]}</span>
              <span className="decisioni-pill__count" aria-hidden="true">
                {counts[item]}
              </span>
            </button>
          ))}
        </div>

        <div className="decisioni-sort">
          <label htmlFor={sortId} className="decisioni-sort__label">
            {decisioniCopy.sortLabel}:
          </label>
          <span className="decisioni-sort__control">
            <select id={sortId} value={sort} onChange={(event) => setSort(event.target.value as DecisionSort)}>
              {SORTS.map((value) => (
                <option key={value} value={value}>
                  {decisioniCopy.sort[value]}
                </option>
              ))}
            </select>
            <ChevronDownIcon className="decisioni-sort__chevron" />
          </span>
        </div>
      </div>

      {visible.length > 0 ? (
        <ol className="decisioni-list">
          {visible.map((row) => (
            <li key={row.decisionId}>
              <DecisionRow row={row} href={decisionDetailRoute(feed.property_id, row.decisionId)} />
            </li>
          ))}
        </ol>
      ) : (
        <p className="decisioni-empty" role="status">
          {area === "ALL" ? decisioniCopy.emptyArea.unavailable : emptyAreaText(feed, area)}
        </p>
      )}
    </section>
  );
}
