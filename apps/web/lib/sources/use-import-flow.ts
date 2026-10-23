"use client";

import { useCallback, useState } from "react";

import type {
  DataSourceDomain,
  ImportPreviewResponse,
  ImportProblem,
  ImportResultResponse,
  SourceMethod,
} from "@ninfa/contracts";

import { importFile, previewImport } from "@/lib/api/data-sources";
import type { ApiResult } from "@/lib/api/client";

/** The way a domain's file arrives: the ONLY formats NINFA reads today. */
export const METHOD_OF_DOMAIN: Record<DataSourceDomain, SourceMethod> = {
  BOOKINGS: "CSV",
  COSTS: "XML",
  LABOR: "CSV",
};

const EXTENSION_OF_METHOD: Record<SourceMethod, string> = { CSV: ".csv", XML: ".xml" };

/** A problem that is not about the file itself. */
export type FlowProblem = ImportProblem | "SOURCE_GONE";

export type ImportFlowState =
  | { step: "choose"; wrongType: boolean }
  | { step: "checking"; file: File }
  | { step: "preview"; file: File; preview: ImportPreviewResponse }
  | { step: "importing"; file: File; preview: ImportPreviewResponse }
  | { step: "done"; file: File; result: ImportResultResponse }
  | { step: "failed"; file: File; problem: FlowProblem };

export interface ImportFlowOptions {
  propertyId: string;
  domain: DataSourceDomain;
  /** The property-local day the file is dated as of; labor only. */
  snapshotLocalDate: string;
  /** Called once an import SUCCEEDED, so the cards can be re-read from the backend. */
  onImported: () => void;
}

export interface ImportFlow {
  state: ImportFlowState;
  method: SourceMethod;
  /** Looks at the file (writes nothing). A file of the wrong type never leaves the browser. */
  chooseFile: (file: File) => Promise<void>;
  /** Imports the file that was just looked at. */
  confirm: () => Promise<void>;
  /** Back to choosing a file. */
  reset: () => void;
}

/** The reason an API call failed, in the page's own terms. Technical text never leaves this function. */
function problemOfFailure(result: Extract<ApiResult<unknown>, { ok: false }>): FlowProblem {
  if (result.code === "FILE_TOO_LARGE") return "FILE_TOO_LARGE";
  if (result.code === "DATA_SOURCE_NOT_FOUND" || result.code === "PROPERTY_NOT_FOUND") {
    return "SOURCE_GONE";
  }
  return "GENERIC";
}

/**
 * The steps of putting a file into NINFA: choose -> look at it -> confirm -> done. The backend does every
 * check (readable, columns, rows, already imported) and the import itself; this hook only walks the steps
 * and keeps the user informed. Nothing is parsed, validated or counted here.
 *
 * Nothing before `confirm` writes anything: opening the dialog, choosing a file and looking at it leave
 * the property exactly as it was. The source behind the card is created by the backend only when the
 * confirmed import succeeds, so a flow that is abandoned or fails never leaves a "configured" source.
 */
export function useImportFlow({
  propertyId,
  domain,
  snapshotLocalDate,
  onImported,
}: ImportFlowOptions): ImportFlow {
  const method = METHOD_OF_DOMAIN[domain];
  const [state, setState] = useState<ImportFlowState>({ step: "choose", wrongType: false });

  const chooseFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(EXTENSION_OF_METHOD[method])) {
        setState({ step: "choose", wrongType: true });
        return;
      }
      setState({ step: "checking", file });
      const result = await previewImport(propertyId, domain, file);
      if (!result.ok) {
        setState({ step: "failed", file, problem: problemOfFailure(result) });
        return;
      }
      setState({ step: "preview", file, preview: result.data });
    },
    [propertyId, domain, method],
  );

  const confirm = useCallback(async () => {
    if (state.step !== "preview" || !state.preview.can_import) return;
    const { file, preview } = state;
    setState({ step: "importing", file, preview });
    const result = await importFile({
      propertyId,
      domain,
      file,
      snapshotLocalDate: domain === "LABOR" ? snapshotLocalDate : undefined,
    });
    if (!result.ok) {
      setState({ step: "failed", file, problem: problemOfFailure(result) });
      return;
    }
    if (!result.data.succeeded) {
      setState({ step: "failed", file, problem: result.data.problem ?? "GENERIC" });
      return;
    }
    setState({ step: "done", file, result: result.data });
    onImported();
  }, [state, propertyId, domain, snapshotLocalDate, onImported]);

  const reset = useCallback(() => setState({ step: "choose", wrongType: false }), []);

  return { state, method, chooseFile, confirm, reset };
}
