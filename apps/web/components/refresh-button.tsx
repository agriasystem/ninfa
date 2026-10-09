"use client";

import { copy } from "@/lib/copy";

import { RefreshIcon } from "./icons";

export interface RefreshButtonProps {
  busy: boolean;
  onRefresh: () => void;
}

/** Gate 14's refresh, kept (Home UI V1): the large "Aggiorna" button did not fit the approved
 * concept, so it became this discreet icon button next to the freshness line. It repeats the SAME
 * `GET` of the feed - never a detector run, never a write. The accessible name is constant
 * ("Aggiorna analisi"); progress is `aria-busy` + disabled. */
export function RefreshButton({ busy, onRefresh }: RefreshButtonProps) {
  return (
    <button
      type="button"
      className="refresh-button"
      aria-label={copy.home.refresh}
      title={copy.home.refresh}
      aria-busy={busy}
      disabled={busy}
      onClick={onRefresh}
    >
      <RefreshIcon className="refresh-button__icon" />
    </button>
  );
}
