"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { AnalysisStatusResponse, AnalysisUpdateState } from "@ninfa/contracts";

import { getAnalysisStatus, requestAnalysisRefresh } from "@/lib/api/analysis";

/** How often a refresh under way is looked at. Only while one is: an idle page asks nothing. */
export const ANALYSIS_POLL_MS = 3000;

const UNDER_WAY: ReadonlySet<AnalysisUpdateState> = new Set(["IN_PROGRESS", "DELAYED"]);

export function isUnderWay(status: AnalysisStatusResponse | null): boolean {
  return status !== null && UNDER_WAY.has(status.state);
}

export interface UseAnalysisStatusOptions {
  propertyId: string;
  /** A refresh that was under way has ended, whichever way: the caller re-reads what it shows. */
  onSettled?: () => void;
}

export interface AnalysisStatusHandle {
  /** The backend's answer for the CURRENT property; `null` until it has given one (a page then simply says less). */
  status: AnalysisStatusResponse | null;
  /** A retry is on its way. */
  retrying: boolean;
  /** The recovery the backend offers (`can_retry`): it decides again, and never runs an analysis here. */
  retry: () => Promise<void>;
}

/**
 * GET /api/v1/properties/{propertyId}/analysis/status, again every few seconds while a refresh is under way, so
 * that a page updates by itself when the worker finishes. Nothing is decided here: the states are the backend's.
 */
export function useAnalysisStatus({ propertyId, onSettled }: UseAnalysisStatusOptions): AnalysisStatusHandle {
  const [held, setHeld] = useState<{ propertyId: string; status: AnalysisStatusResponse } | null>(null);
  const [retrying, setRetrying] = useState(false);

  // The caller builds a new callback on every render: read it through a ref so a re-render never refetches.
  const settledRef = useRef(onSettled);
  useEffect(() => {
    settledRef.current = onSettled;
  });

  const accept = useCallback((next: AnalysisStatusResponse) => {
    setHeld((previous) => {
      if (previous !== null && previous.propertyId === propertyId) {
        const moved = isUnderWay(previous.status) && !isUnderWay(next);
        if (moved || previous.status.last_analysis_at !== next.last_analysis_at) {
          // (after this update: the caller re-reads what the analysis has just written)
          queueMicrotask(() => settledRef.current?.());
        }
      }
      return { propertyId, status: next };
    });
  }, [propertyId]);

  const status = held !== null && held.propertyId === propertyId ? held.status : null;
  const underWay = isUnderWay(status);

  useEffect(() => {
    let ignore = false;
    void getAnalysisStatus(propertyId).then((result) => {
      if (!ignore && result.ok) accept(result.data);
    });
    return () => {
      ignore = true;
    };
  }, [propertyId, accept]);

  useEffect(() => {
    if (!underWay) return;
    let ignore = false;
    const timer = setInterval(() => {
      void getAnalysisStatus(propertyId).then((result) => {
        // (a request that fails is simply tried again: a hiccup says nothing about the analysis)
        if (!ignore && result.ok) accept(result.data);
      });
    }, ANALYSIS_POLL_MS);
    return () => {
      ignore = true;
      clearInterval(timer);
    };
  }, [propertyId, underWay, accept]);

  const retry = useCallback(async () => {
    setRetrying(true);
    const result = await requestAnalysisRefresh(propertyId);
    if (result.ok) accept(result.data);
    setRetrying(false);
  }, [propertyId, accept]);

  return { status, retrying, retry };
}
