"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import type { DecisionDetailResponse, ObservationDetail } from "@ninfa/contracts";

import { getDecisionDetail, getDecisionHistory } from "@/lib/api/decisions";
import { copy, decisionStatusCopy, decisionTypeTitles, lifecycleEventCopy } from "@/lib/copy";
import {
  cardViewModelFromTargetAndFacts,
  type DecisionCardViewModel,
} from "@/lib/decisions/card-view-models";
import { evidenceRows } from "@/lib/decisions/evidence-rows";
import { formatMoney } from "@/lib/decisions/format";
import { whySentence } from "@/lib/decisions/why-copy";
import { formatLocalDateItalian } from "@/lib/date/local-date";
import { oggiRoute } from "@/lib/routes";

import { DecisionTimeline } from "./decision-timeline";

// Every resolved state carries WHICH (propertyId, decisionId) it belongs to, so "is this stale
// for the current props" is derived during render rather than an effect resetting to "loading"
// itself (the same pattern `components/today-screen.tsx` already uses, for the same reason).
type DetailLoadState =
  | { kind: "loading" }
  | { kind: "notFound"; propertyId: string; decisionId: string }
  | { kind: "error"; code: string; propertyId: string; decisionId: string }
  | { kind: "loaded"; detail: DecisionDetailResponse; propertyId: string; decisionId: string };

type HistoryLoadState =
  | { kind: "loading" }
  | { kind: "error"; propertyId: string; decisionId: string }
  | {
      kind: "loaded";
      items: ObservationDetail[];
      nextCursor: string | null;
      propertyId: string;
      decisionId: string;
    };

async function fetchDetailState(
  propertyId: string,
  decisionId: string,
): Promise<DetailLoadState> {
  const result = await getDecisionDetail(propertyId, decisionId);
  if (result.ok) {
    return { kind: "loaded", detail: result.data, propertyId, decisionId };
  }
  if (result.code === "DECISION_NOT_FOUND") {
    return { kind: "notFound", propertyId, decisionId };
  }
  return { kind: "error", code: result.code, propertyId, decisionId };
}

async function fetchFirstHistoryPage(propertyId: string, decisionId: string): Promise<HistoryLoadState> {
  const result = await getDecisionHistory(propertyId, decisionId);
  if (result.ok) {
    return {
      kind: "loaded",
      items: result.data.items,
      nextCursor: result.data.next_cursor,
      propertyId,
      decisionId,
    };
  }
  return { kind: "error", propertyId, decisionId };
}

export interface DecisionDetailViewProps {
  propertyId: string;
  decisionId: string;
}

export function DecisionDetailView({ propertyId, decisionId }: DecisionDetailViewProps) {
  const [detailState, setDetailState] = useState<DetailLoadState>({ kind: "loading" });
  const [historyState, setHistoryState] = useState<HistoryLoadState>({ kind: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState(false);

  useEffect(() => {
    let ignore = false;
    async function run() {
      // Parallel, never a waterfall: detail and the first history page are independent reads.
      const [nextDetail, nextHistory] = await Promise.all([
        fetchDetailState(propertyId, decisionId),
        fetchFirstHistoryPage(propertyId, decisionId),
      ]);
      if (ignore) return;
      setDetailState(nextDetail);
      setHistoryState(nextHistory);
      setLoadMoreError(false);
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [propertyId, decisionId]);

  async function retryDetail() {
    setDetailState(await fetchDetailState(propertyId, decisionId));
  }

  async function retryHistory() {
    setHistoryState(await fetchFirstHistoryPage(propertyId, decisionId));
  }

  async function loadMoreHistory() {
    if (historyState.kind !== "loaded" || historyState.nextCursor === null) return;
    setLoadingMore(true);
    setLoadMoreError(false);
    const result = await getDecisionHistory(propertyId, decisionId, { cursor: historyState.nextCursor });
    if (result.ok) {
      setHistoryState((previous) =>
        previous.kind === "loaded"
          ? {
              kind: "loaded",
              items: [...previous.items, ...result.data.items],
              nextCursor: result.data.next_cursor,
              propertyId,
              decisionId,
            }
          : previous,
      );
    } else {
      setLoadMoreError(true);
    }
    setLoadingMore(false);
  }

  const detailStale =
    detailState.kind !== "loading" &&
    (detailState.propertyId !== propertyId || detailState.decisionId !== decisionId);
  const detailBusy = detailState.kind === "loading" || detailStale;

  const historyStale =
    historyState.kind !== "loading" &&
    (historyState.propertyId !== propertyId || historyState.decisionId !== decisionId);
  const historyBusy = historyState.kind === "loading" || historyStale;

  return (
    <div className="decision-detail">
      <p className="decision-detail__back">
        <Link href={oggiRoute(propertyId)}>{copy.detail.back}</Link>
      </p>

      {detailBusy ? (
        <div className="decision-detail__skeleton" aria-live="polite" aria-busy="true">
          <div className="decision-detail__skeleton-line" />
          <div className="decision-detail__skeleton-line" />
          <div className="decision-detail__skeleton-line" />
        </div>
      ) : detailState.kind === "notFound" ? (
        <div className="decision-detail__not-found">
          <h1>{copy.detail.notFoundTitle}</h1>
          <p>{copy.detail.notFoundBody}</p>
          <Link href={oggiRoute(propertyId)}>{copy.detail.backToOggi}</Link>
        </div>
      ) : detailState.kind === "error" ? (
        <div className="decision-detail__error" role="alert">
          <p>{copy.detail.loadErrorGeneric}</p>
          <button type="button" onClick={() => void retryDetail()}>
            {copy.detail.retry}
          </button>
        </div>
      ) : (
        <DecisionDetailContent detail={detailState.detail} />
      )}

      {!detailBusy && detailState.kind === "loaded" ? (
        historyBusy ? (
          <div className="decision-timeline__skeleton" aria-live="polite" aria-busy="true">
            <div className="decision-detail__skeleton-line" />
          </div>
        ) : historyState.kind === "error" ? (
          <div className="decision-timeline__error" role="alert">
            <p>{copy.detail.loadErrorGeneric}</p>
            <button type="button" onClick={() => void retryHistory()}>
              {copy.detail.retry}
            </button>
          </div>
        ) : (
          <DecisionTimeline
            items={historyState.items}
            target={detailState.detail.target}
            hasMore={historyState.nextCursor !== null}
            loadingMore={loadingMore}
            loadMoreError={loadMoreError}
            onLoadMore={() => void loadMoreHistory()}
          />
        )
      ) : null}
    </div>
  );
}

/** Exported so golden fixtures (Gate 15) can render the current-state/evidence content directly
 * from a hand-authored `DecisionDetailResponse`, without needing to mock the fetch layer - the
 * same pattern Gate 14's own `FeedStateView` golden tests already use. */
export function DecisionDetailContent({ detail }: { detail: DecisionDetailResponse }) {
  const observation = detail.latest_observation;
  const card = cardViewModelFromTargetAndFacts(detail.target, observation.facts);
  const title = decisionTypeTitles[detail.decision_type];
  const why = whySentence(card);
  const rows = evidenceRows(card, observation.confidence_score, observation.evidence);
  const showRank = observation.source_status === "TRIGGERED" && observation.priority !== null;
  const currentEvent = lifecycleEventCopy(observation.lifecycle_transition, observation.source_status);

  return (
    <article className="decision-detail__content">
      {/* 1. Header / identity */}
      <header className="decision-detail__header">
        <h1 className="decision-detail__title">{title}</h1>
        <p className="decision-detail__target">{targetSubtitle(card)}</p>
        <p className="decision-detail__status">
          {copy.detail.sectionCurrentState}: {decisionStatusCopy(detail.status)}
        </p>
      </header>

      {/* 2. Stato attuale - the DECISION's own lifecycle facts, never a call to action */}
      <section className="decision-detail__current-state">
        <p className="decision-detail__detected">
          {copy.detail.detectedOn(formatLocalDateItalian(detail.first_seen_local_date, { withYear: true }))}
        </p>
        {detail.status === "RESOLVED" && detail.resolved_local_date !== null ? (
          <p className="decision-detail__resolved">
            {copy.detail.resolvedOn(formatLocalDateItalian(detail.resolved_local_date, { withYear: true }))}
          </p>
        ) : null}
        {detail.episode_count > 1 ? (
          <p className="decision-detail__episodes">{copy.detail.episodeCount(detail.episode_count)}</p>
        ) : null}
      </section>

      {/* 3. Cosa sta succedendo - the latest OBSERVATION's own meaning, in calm, static copy */}
      <section className="decision-detail__current-observation">
        <p className="decision-detail__event">{currentEvent}</p>
        {showRank && observation.priority !== null ? (
          <p className="decision-detail__priority">
            {copy.detail.currentPriorityLine(observation.priority.rank)}
          </p>
        ) : null}
        {why !== null ? (
          <div className="decision-detail__why">
            <h2>{copy.detail.sectionWhy}</h2>
            <p>{why}</p>
          </div>
        ) : null}
      </section>

      {/* 4. Evidenze */}
      <section className="decision-detail__evidence">
        <h2>{copy.detail.sectionEvidence}</h2>
        <dl className="decision-detail__evidence-list">
          {rows.map((row, index) => (
            <div key={`${row.label}-${index}`}>
              {row.label !== "" ? <dt>{row.label}</dt> : null}
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        {observation.economic_proxy !== null ? (
          <p className="decision-detail__proxy">
            {copy.detail.economicImpactLabel}:{" "}
            {formatMoney(observation.economic_proxy.amount, observation.economic_proxy.currency)}
          </p>
        ) : null}
      </section>
    </article>
  );
}

function targetSubtitle(card: DecisionCardViewModel): string {
  switch (card.kind) {
    case "PICKUP":
    case "OCCUPANCY":
      return formatLocalDateItalian(card.stayDate);
    case "OTA":
      return `${formatLocalDateItalian(card.windowStart)} – ${formatLocalDateItalian(card.windowEnd)}`;
    case "COST":
      return `${card.costCategory} · ${formatLocalDateItalian(card.periodStart)} · ${card.currency}`;
    case "LABOR":
      return `${card.laborCategory} · ${formatLocalDateItalian(card.workDate)}`;
  }
}
