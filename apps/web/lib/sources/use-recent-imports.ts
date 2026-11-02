"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { RecentImport } from "@ninfa/contracts";

import { getRecentImports } from "@/lib/api/data-sources";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; propertyId: string; imports: RecentImport[] }
  | { kind: "error"; propertyId: string };

export interface RecentImportsHandle {
  status: "loading" | "ready" | "error";
  /** The latest attempts of the CURRENT property, `[]` while loading, on error, and when the held answer
   * belongs to another property. */
  imports: RecentImport[];
  /** Repeats the SAME `GET`: the one way the page learns that an import has ended. */
  refresh: () => Promise<void>;
}

/**
 * GET /api/v1/properties/{propertyId}/data-sources/imports: what "Importazioni recenti" says. The backend's
 * record of real attempts and nothing else: the browser keeps no history of its own.
 */
export function useRecentImports(propertyId: string, onAccessLost: () => void): RecentImportsHandle {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  // The caller builds a new callback on every render: read it through a ref so a re-render never refetches.
  const accessLostRef = useRef(onAccessLost);
  useEffect(() => {
    accessLostRef.current = onAccessLost;
  });

  const load = useCallback(async (): Promise<LoadState> => {
    const result = await getRecentImports(propertyId);
    if (result.ok) return { kind: "loaded", propertyId, imports: result.data.imports };
    if (result.status === 401 || result.code === "PROPERTY_NOT_FOUND") accessLostRef.current();
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
    // A re-read that fails keeps the last list the backend DID give: a hiccup must not make it vanish.
    setState((previous) =>
      next.kind === "error" && previous.kind === "loaded" && previous.propertyId === propertyId ? previous : next,
    );
  }, [load, propertyId]);

  const foreign = state.kind !== "loading" && state.propertyId !== propertyId;
  if (foreign || state.kind === "loading") return { status: "loading", imports: [], refresh };
  if (state.kind === "error") return { status: "error", imports: [], refresh };
  return { status: "ready", imports: state.imports, refresh };
}
