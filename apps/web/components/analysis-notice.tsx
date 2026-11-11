"use client";

import type { AnalysisStatusResponse } from "@ninfa/contracts";

import { isUnderWay, type AnalysisStatusHandle } from "@/lib/analysis/use-analysis-status";
import { analysisUpdateLine, copy } from "@/lib/copy";

import { SpinnerIcon } from "./icons";

export interface AnalysisNoticeProps {
  analysis: AnalysisStatusHandle;
  /** Also say that the analysis is up to date (right after an import). A page at rest says nothing. */
  showUpToDate?: boolean;
}

function lineOf(status: AnalysisStatusResponse, showUpToDate: boolean): string | null {
  if (status.state === "UP_TO_DATE" && !showUpToDate) return null;
  return analysisUpdateLine(status.state);
}

/**
 * One line saying where the analysis stands against the data, in the backend's own states: nothing is worked out
 * here. It says nothing while the answer is not there, and nothing at all when there is nothing to say. The only
 * action is the recovery the backend offers: the analysis normally starts by itself.
 */
export function AnalysisNotice({ analysis, showUpToDate = false }: AnalysisNoticeProps) {
  const { status, retrying, retry } = analysis;
  if (status === null) return null;
  const line = lineOf(status, showUpToDate);
  if (line === null) return null;

  return (
    <div className="analysis-notice" data-state={status.state} role="status">
      {isUnderWay(status) ? <SpinnerIcon className="analysis-notice__spinner" /> : null}
      <span>{line}</span>
      {status.can_retry ? (
        <button
          type="button"
          className="analysis-notice__retry"
          disabled={retrying}
          onClick={() => void retry()}
        >
          {status.state === "FAILED" ? copy.analysisUpdate.retry : copy.analysisUpdate.start}
        </button>
      ) : null}
    </div>
  );
}
