"use client";

import { useEffect, useState } from "react";

import type { ImportLimitsResponse } from "@ninfa/contracts";

import { getImportLimits } from "@/lib/api/data-sources";

/** The size in the words a page uses: "10 MB". */
export function fileSizeText(bytes: number): string {
  const megabytes = bytes / (1024 * 1024);
  return `${megabytes.toLocaleString("it-IT", { maximumFractionDigits: 1 })} MB`;
}

/** What the file input offers: the kinds the backend reads. */
export function fileAcceptOf(limits: ImportLimitsResponse | null): string | undefined {
  return limits === null ? undefined : limits.file_extensions.join(",");
}

/**
 * GET .../data-sources/import-limits: what a file may be, from the one place that enforces it. `null` until the
 * backend has answered, or if it does not: the page then checks nothing by itself and the backend still decides.
 */
export function useImportLimits(propertyId: string): ImportLimitsResponse | null {
  const [held, setHeld] = useState<{ propertyId: string; limits: ImportLimitsResponse } | null>(null);

  useEffect(() => {
    let ignore = false;
    void getImportLimits(propertyId).then((result) => {
      if (!ignore && result.ok) setHeld({ propertyId, limits: result.data });
    });
    return () => {
      ignore = true;
    };
  }, [propertyId]);

  return held !== null && held.propertyId === propertyId ? held.limits : null;
}
