"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { DataSourcesResponse } from "@ninfa/contracts";

import { getDataSources } from "@/lib/api/data-sources";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; propertyId: string; data: DataSourcesResponse }
  | { kind: "error"; propertyId: string };

export interface DataSourcesHandle {
  status: "loading" | "ready" | "error";
  /** The state of the five cards for the CURRENT property - `null` while loading, on error, and when the
   * held answer belongs to another property (a switch never shows the previous property's sources). */
  data: DataSourcesResponse | null;
  /** Repeats the SAME `GET`: the one way the page learns that something changed. */
  refresh: () => Promise<void>;
}

/**
 * GET /api/v1/properties/{propertyId}/data-sources: what the five cards say. Never invented: while the
 * answer is on its way the page shows a loading state, and when it fails it says so - it never falls back
 * to "Non configurato", which would be a claim NINFA has not verified.
 */
export function useDataSources(
  propertyId: string,
  onPropertyInvalid: () => void,
): DataSourcesHandle {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  // The caller builds a new callback on every render: read it through a ref so a re-render never refetches.
  const invalidRef = useRef(onPropertyInvalid);
  useEffect(() => {
    invalidRef.current = onPropertyInvalid;
  });

  const load = useCallback(async (): Promise<LoadState> => {
    const result = await getDataSources(propertyId);
    if (result.ok) return { kind: "loaded", propertyId, data: result.data };
    if (result.code === "PROPERTY_NOT_FOUND") invalidRef.current();
    return { kind: "error", propertyId };
  }, [propertyId]);

  useEffect(() => {
    let ignore = false;
    void load().then((next) => {
      if (!ignore) setState(next);
    });
    return () => {
      ignore = true;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    const next = await load();
    // A re-read that fails keeps the last cards the backend DID give (and the dialog that is open on top
    // of them): a hiccup must not make the block, or a file being imported, vanish.
    setState((previous) =>
      next.kind === "error" && previous.kind === "loaded" && previous.propertyId === propertyId ? previous : next,
    );
  }, [load, propertyId]);

  const foreign = state.kind !== "loading" && state.propertyId !== propertyId;
  if (foreign || state.kind === "loading") return { status: "loading", data: null, refresh };
  if (state.kind === "error") return { status: "error", data: null, refresh };
  return { status: "ready", data: state.data, refresh };
}
