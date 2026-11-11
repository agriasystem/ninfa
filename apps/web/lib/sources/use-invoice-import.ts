"use client";

import { useCallback, useState } from "react";

import type { ImportPreviewResponse, ImportResultResponse } from "@ninfa/contracts";

import { importFile, previewImport } from "@/lib/api/data-sources";

import { problemOfFailure, type FlowProblem } from "./use-import-flow";

/** What an electronic invoice is: the one kind of file "Importa file" does not read (see `use-import-flow`). */
export const INVOICE_ACCEPT = ".xml,text/xml,application/xml";

export type InvoiceImportState =
  | { step: "choose"; wrongType: boolean }
  | { step: "checking"; file: File }
  | { step: "preview"; file: File; preview: ImportPreviewResponse }
  | { step: "importing"; file: File }
  | { step: "done"; file: File; result: ImportResultResponse }
  | { step: "failed"; file: File; problem: FlowProblem };

export interface InvoiceImport {
  state: InvoiceImportState;
  /** Looks at the invoice (writes nothing). Any other kind of file never leaves the browser. */
  chooseFile: (file: File) => Promise<void>;
  /** Imports the invoice that was just looked at. */
  confirm: () => Promise<void>;
  /** Back to choosing a file. */
  reset: () => void;
}

/**
 * An electronic invoice (XML) into NINFA: choose -> NINFA looks at it -> confirm -> import. The backend does
 * every check and the import itself. Nothing before `confirm` writes anything: the source behind the card
 * comes to exist only when the confirmed import succeeds.
 */
export function useInvoiceImport(propertyId: string, onImported: () => void): InvoiceImport {
  const [state, setState] = useState<InvoiceImportState>({ step: "choose", wrongType: false });

  const chooseFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".xml")) {
        setState({ step: "choose", wrongType: true });
        return;
      }
      setState({ step: "checking", file });
      const result = await previewImport(propertyId, "COSTS", file);
      if (!result.ok) {
        setState({ step: "failed", file, problem: problemOfFailure(result) });
        return;
      }
      setState({ step: "preview", file, preview: result.data });
    },
    [propertyId],
  );

  const confirm = useCallback(async () => {
    if (state.step !== "preview" || !state.preview.can_import) return;
    const { file } = state;
    setState({ step: "importing", file });
    const result = await importFile({ propertyId, domain: "COSTS", file });
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
  }, [state, propertyId, onImported]);

  const reset = useCallback(() => setState({ step: "choose", wrongType: false }), []);

  return { state, chooseFile, confirm, reset };
}
