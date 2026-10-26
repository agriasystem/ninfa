"use client";

import { useCallback, useRef, useState } from "react";

import type {
  DataSourceDomain,
  FileInspectionResponse,
  ImportFieldKey,
  ImportFormatHint,
  ImportMapping,
  ImportPreviewResponse,
  ImportProblem,
  ImportResultResponse,
  ImportValidationResponse,
  MappedImportResultResponse,
  MappingCheckResponse,
  SourceMethod,
  UnderstandAnswers,
  Understanding,
  UnderstandingQuestion,
} from "@ninfa/contracts";

import {
  checkMapping,
  importFile,
  importMatchedFile,
  previewImport,
  understandFile,
  validateImport,
} from "@/lib/api/data-sources";
import type { ApiResult } from "@/lib/api/client";

import {
  decisionFromSuggestions,
  mergeAnswers,
  sameDecision,
  startingDecision,
  withColumnField,
  withConstant,
  withDateOrder,
  withDecimalStyle,
} from "./mapping-decision";

/** The way a domain's file arrives: the ONLY formats NINFA reads today. */
export const METHOD_OF_DOMAIN: Record<DataSourceDomain, SourceMethod> = {
  BOOKINGS: "CSV",
  COSTS: "XML",
  LABOR: "CSV",
};

/** What the hotel can choose: a spreadsheet-like file for bookings and staff; for costs the invoices' XML or a
 * register in the same kind of file. */
const EXTENSIONS_OF_DOMAIN: Record<DataSourceDomain, string[]> = {
  BOOKINGS: [".csv", ".xlsx"],
  COSTS: [".xml", ".csv", ".xlsx"],
  LABOR: [".csv", ".xlsx"],
};

export const ACCEPT_OF_DOMAIN: Record<DataSourceDomain, string> = {
  BOOKINGS: ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  COSTS:
    ".xml,.csv,.xlsx,text/xml,application/xml,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  LABOR: ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

/** An invoice XML keeps its own short path; every other file NINFA reads is a spreadsheet-like one. */
function isInvoiceXml(file: File): boolean {
  return file.name.toLowerCase().endsWith(".xml");
}

/** The way THIS file arrives (a costs register is a spreadsheet-like file, an invoice is XML). */
export function methodOfFile(domain: DataSourceDomain, file: File | null): SourceMethod {
  if (file === null) return METHOD_OF_DOMAIN[domain];
  return isInvoiceXml(file) ? "XML" : "CSV";
}

/** A problem that is not about the file itself. */
export type FlowProblem = ImportProblem | "SOURCE_GONE" | "IMPORT_IN_PROGRESS";

export interface MappingStep {
  step: "mapping";
  file: File;
  inspection: FileInspectionResponse;
  decision: ImportMapping;
  /** The backend's answer about THIS decision: what is still missing. `null` until it arrives. */
  check: MappingCheckResponse | null;
  checking: boolean;
  /** The whole file is being tried with this decision. */
  busy: boolean;
  /** Questions about how the file writes dates / numbers that only the person can answer. */
  hints: ImportFormatHint[];
  /** Why the last attempt to go on did not work, in one stable word. */
  notice: FlowProblem | null;
  /** NINFA read the document but is not sure of everything: what it did understand. */
  understanding: Understanding | null;
}

export interface ReadyStep {
  step: "ready";
  file: File;
  inspection: FileInspectionResponse;
  /** The matching the import will use; `null` = the configuration saved for this kind of data. */
  decision: ImportMapping | null;
  validation: ImportValidationResponse;
  /** Remember the matching once the import has succeeded. */
  save: boolean;
  /** NINFA understood the document by itself ("File riconosciuto"); `null` = the matching was done by hand. */
  understanding: Understanding | null;
}

/** NINFA understood almost everything and needs ONE more piece of information. */
export interface AskStep {
  step: "ask";
  file: File;
  inspection: FileInspectionResponse;
  understanding: Understanding;
  answers: UnderstandAnswers;
  confirmedDomain: boolean;
  question: UnderstandingQuestion;
  /** The words of a VALUE_LABELS question answered so far (word -> meaning). */
  taught: Record<string, string>;
}

/** The file cannot be imported as it is, and says why. */
export interface BlockedStep {
  step: "blocked";
  file: File;
  inspection: FileInspectionResponse;
  understanding: Understanding;
}

export type ImportFlowState =
  | { step: "choose"; wrongType: boolean }
  | { step: "checking"; file: File }
  | { step: "sheet"; file: File; sheets: string[] }
  | MappingStep
  | ReadyStep
  | AskStep
  | BlockedStep
  | { step: "other-kind"; file: File; kind: DataSourceDomain }
  | { step: "preview"; file: File; preview: ImportPreviewResponse }
  | { step: "importing"; file: File }
  | { step: "done"; file: File; result: ImportResultResponse | MappedImportResultResponse }
  | { step: "failed"; file: File; problem: FlowProblem };

export interface ImportFlowOptions {
  propertyId: string;
  domain: DataSourceDomain;
  /** The property-local day the file is dated as of; labor only. */
  snapshotLocalDate: string;
  /** "edit": the person wants to look at the columns again, so the saved configuration is not applied
   * on its own. */
  mode?: "import" | "edit";
  /** Called once an import SUCCEEDED, so the cards can be re-read from the backend. */
  onImported: () => void;
}

export interface ImportFlow {
  state: ImportFlowState;
  method: SourceMethod;
  /** Reads the file (writes nothing). A file of the wrong type never leaves the browser. */
  chooseFile: (file: File) => Promise<void>;
  /** An Excel file with several sheets: the one to read. */
  chooseSheet: (name: string) => Promise<void>;
  /** The answer to the question on screen (what the person has said is never asked again). */
  answer: (patch: Partial<UnderstandAnswers>, confirmedDomain?: boolean) => Promise<void>;
  /** A VALUE_LABELS question: what the current word means (the last answer sends them all). */
  teach: (meaning: string) => Promise<void>;
  /** The file is another kind of data than the one being imported: say where it belongs. */
  chooseKind: (kind: DataSourceDomain) => Promise<void>;
  /** Leave the questions and match the columns by hand. */
  matchByHand: () => void;
  /** A column of the file now means `field` (`null`: ignore it). */
  setColumnField: (header: string, field: ImportFieldKey | null) => void;
  /** A field gets the same value on every row (`null`: no fixed value). */
  setConstant: (field: ImportFieldKey, value: string | number | null) => void;
  setDateOrder: (order: "DMY" | "MDY") => void;
  setDecimalStyle: (style: "COMMA" | "POINT") => void;
  /** From the matching of the columns to the preview. */
  continueToPreview: () => Promise<void>;
  /** From the preview back to the columns. */
  reviewColumns: () => void;
  setSave: (save: boolean) => void;
  /** Imports the file that was just looked at. */
  confirm: () => Promise<void>;
  /** Back to choosing a file. */
  reset: () => void;
}

/** The reason an API call failed, in the page's own terms. Technical text never leaves this function. */
function problemOfFailure(result: Extract<ApiResult<unknown>, { ok: false }>): FlowProblem {
  if (result.code === "FILE_TOO_LARGE") return "FILE_TOO_LARGE";
  // Another import of the same data is still running: nothing was changed, the user can try again.
  if (result.code === "IMPORT_IN_PROGRESS") return "IMPORT_IN_PROGRESS";
  if (result.code === "DATA_SOURCE_NOT_FOUND" || result.code === "PROPERTY_NOT_FOUND") {
    return "SOURCE_GONE";
  }
  return "GENERIC";
}

/**
 * The steps of putting a file into NINFA.
 *
 * Bookings and staff, a file the hotel already has (CSV or Excel):
 *   choose -> NINFA reads it -> [recognised format | file already in NINFA's own form] -> preview -> import
 *                            \-> match the columns -> preview -> import
 *
 * Smart Import V3 reads the whole DOCUMENT first (every sheet, titles, totals, department lines, a grid of
 * days). Almost always the result is READY - a summary ("File riconosciuto") and one button; otherwise ONE
 * question at a time ("ask"), or the file says plainly why it cannot be imported ("blocked"), or the person
 * matches the columns by hand as before ("mapping").
 * Costs, an invoice XML:  choose -> NINFA looks at it -> confirm -> import.
 *
 * The backend does every check - what a column probably means, what is still missing, how dates and numbers
 * are written, every row of the file - and the import itself; this hook only walks the steps and keeps the
 * person informed. Nothing is parsed, validated or counted here, and no rule about what is required lives
 * here: the backend answers it for each change the person makes.
 *
 * Nothing before `confirm` writes anything: opening the dialog, choosing a file, matching its columns and
 * looking at the preview leave the property exactly as it was. The source behind the card, and the
 * remembered configuration, come to exist only when the confirmed import succeeds.
 */
export function useImportFlow({
  propertyId,
  domain,
  snapshotLocalDate,
  mode = "import",
  onImported,
}: ImportFlowOptions): ImportFlow {
  const [state, setState] = useState<ImportFlowState>({ step: "choose", wrongType: false });
  const method = methodOfFile(domain, "file" in state ? state.file : null);
  // An answer about a decision that is no longer on screen is dropped.
  const checkToken = useRef(0);

  const runCheck = useCallback(
    async (decision: ImportMapping) => {
      checkToken.current += 1;
      const token = checkToken.current;
      setState((current) => (current.step === "mapping" ? { ...current, checking: true } : current));
      const result = await checkMapping(propertyId, domain, decision);
      if (token !== checkToken.current) return;
      setState((current) =>
        current.step === "mapping" && sameDecision(current.decision, decision)
          ? { ...current, checking: false, check: result.ok ? result.data : null }
          : current,
      );
    },
    [propertyId, domain],
  );

  const openMapping = useCallback(
    (
      file: File,
      inspection: FileInspectionResponse,
      proposed: ImportMapping,
      extra: Partial<Pick<MappingStep, "hints" | "notice" | "understanding">> = {},
    ) => {
      // The person takes over: a matching built by hand is theirs and carries no reference to the
      // server's understanding. (A decision that carries it is only imported if the server, reading
      // the file again with those answers, finds it READY and unaltered.)
      const decision: ImportMapping = { ...proposed, smart_import: null };
      setState({
        step: "mapping",
        file,
        inspection,
        decision,
        check: null,
        checking: true,
        busy: false,
        hints: extra.hints ?? [],
        notice: extra.notice ?? null,
        understanding: extra.understanding ?? null,
      });
      void runCheck(decision);
    },
    [runCheck],
  );

  /** NINFA understood the document: where does the person go next? Nothing here decides anything about the
   * data - the level, the questions and the proposal are the backend's. */
  const routeUnderstood = useCallback(
    async (
      file: File,
      inspection: FileInspectionResponse,
      understanding: Understanding,
      proposal: ImportMapping,
      answers: UnderstandAnswers,
      confirmedDomain: boolean,
    ) => {
      if (mode === "edit") {
        // "Modifica associazioni": the person wants the columns in front of them.
        openMapping(file, inspection, proposal, { understanding });
        return;
      }
      if (understanding.level === "BLOCKED") {
        setState({ step: "blocked", file, inspection, understanding });
        return;
      }
      const question = understanding.questions[0];
      if (understanding.level === "ASK" && question !== undefined) {
        setState({
          step: "ask",
          file,
          inspection,
          understanding,
          answers,
          confirmedDomain,
          question,
          taught: {},
        });
        return;
      }
      if (understanding.level === "MANUAL") {
        openMapping(file, inspection, proposal, { understanding });
        return;
      }
      // READY: the whole file is tried with the proposal and, if every row is fine, the person sees a
      // summary and one button.
      const tried = await validateImport({ propertyId, domain, file, mapping: proposal });
      if (tried.ok && tried.data.status === "READY") {
        const known = inspection.profile.status === "RECOGNIZED";
        const taught = Object.keys(answers.labels ?? {}).length > 0;
        setState({
          step: "ready",
          file,
          inspection,
          decision: proposal,
          validation: tried.data,
          save: !known || taught,
          understanding,
        });
        return;
      }
      openMapping(file, inspection, proposal, {
        hints: tried.ok && tried.data.status === "NEEDS_CHOICE" ? tried.data.format_hints : [],
        notice: tried.ok && tried.data.status === "BLOCKED" ? (tried.data.problem ?? "GENERIC") : null,
        understanding,
      });
    },
    [propertyId, domain, mode, openMapping],
  );

  const readFile = useCallback(
    async (
      file: File,
      answers: UnderstandAnswers = {},
      confirmedDomain = false,
    ) => {
      setState({ step: "checking", file });
      const result = await understandFile({ propertyId, domain, file, answers, confirmedDomain });
      if (!result.ok) {
        setState({ step: "failed", file, problem: problemOfFailure(result) });
        return;
      }
      const inspection = result.data;
      if (inspection.problem === "SHEET_REQUIRED") {
        setState({ step: "sheet", file, sheets: inspection.sheet_names });
        return;
      }
      if (inspection.problem !== null) {
        setState({ step: "failed", file, problem: inspection.problem });
        return;
      }
      if (inspection.understanding && inspection.proposal) {
        await routeUnderstood(
          file,
          inspection,
          inspection.understanding,
          inspection.proposal,
          answers,
          confirmedDomain,
        );
        return;
      }

      if (mode === "import" && inspection.profile.status === "RECOGNIZED") {
        // A layout NINFA already knows: the whole file is tried with the saved configuration and, if every
        // row is fine, the person goes straight to the preview.
        const tried = await validateImport({ propertyId, domain, file, mapping: null });
        if (tried.ok && tried.data.status === "READY") {
          setState({
            step: "ready",
            file,
            inspection,
            decision: null,
            validation: tried.data,
            save: false,
            understanding: null,
          });
          return;
        }
      } else if (mode === "import" && inspection.already_canonical) {
        // A file already written in NINFA's own columns needs no matching either.
        const proposal = decisionFromSuggestions(inspection);
        const tried = await validateImport({ propertyId, domain, file, mapping: proposal });
        if (tried.ok && tried.data.status === "READY") {
          setState({
            step: "ready",
            file,
            inspection,
            decision: proposal,
            validation: tried.data,
            save: true,
            understanding: null,
          });
          return;
        }
        openMapping(file, inspection, proposal, {
          hints: tried.ok && tried.data.status === "NEEDS_CHOICE" ? tried.data.format_hints : [],
        });
        return;
      }
      openMapping(file, inspection, startingDecision(inspection));
    },
    [propertyId, domain, mode, openMapping, routeUnderstood],
  );

  const chooseFile = useCallback(
    async (file: File) => {
      const name = file.name.toLowerCase();
      if (!EXTENSIONS_OF_DOMAIN[domain].some((extension) => name.endsWith(extension))) {
        setState({ step: "choose", wrongType: true });
        return;
      }
      if (!isInvoiceXml(file)) {
        await readFile(file);
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
    [propertyId, domain, readFile],
  );

  const chooseSheet = useCallback(
    async (name: string) => {
      if (state.step !== "sheet") return;
      await readFile(state.file, { sheet_name: name });
    },
    [state, readFile],
  );

  const answer = useCallback(
    async (patch: Partial<UnderstandAnswers>, confirmedDomain?: boolean) => {
      if (state.step !== "ask") return;
      await readFile(
        state.file,
        mergeAnswers(state.answers, patch),
        confirmedDomain ?? state.confirmedDomain,
      );
    },
    [state, readFile],
  );

  const teach = useCallback(
    async (meaning: string) => {
      if (state.step !== "ask" || state.question.kind !== "VALUE_LABELS") return;
      const pending = state.question.labels.filter((item) => !(item.label in state.taught));
      const current = pending[0];
      if (current === undefined) return;
      const taught = { ...state.taught, [current.label]: meaning };
      if (pending.length > 1) {
        setState({ ...state, taught });
        return;
      }
      const document = state.question.document;
      if (document === null) return;
      await readFile(
        state.file,
        mergeAnswers(state.answers, { labels: { [document]: taught } }),
        state.confirmedDomain,
      );
    },
    [state, readFile],
  );

  const chooseKind = useCallback(
    async (kind: DataSourceDomain) => {
      if (state.step !== "ask") return;
      if (kind === domain) {
        await readFile(state.file, state.answers, true);
        return;
      }
      setState({ step: "other-kind", file: state.file, kind });
    },
    [state, domain, readFile],
  );

  const matchByHand = useCallback(() => {
    if (state.step !== "ask" && state.step !== "blocked") return;
    const proposal = state.inspection.proposal ?? startingDecision(state.inspection);
    openMapping(state.file, state.inspection, proposal, { understanding: state.understanding });
  }, [state, openMapping]);

  const edit = useCallback(
    (change: (decision: ImportMapping) => ImportMapping, recheck: boolean) => {
      if (state.step !== "mapping") return;
      const decision = change(state.decision);
      // Answering a question keeps the other questions; changing the matching asks them all again.
      setState({
        ...state,
        decision,
        check: recheck ? null : state.check,
        hints: recheck ? [] : state.hints,
        notice: null,
      });
      if (recheck) void runCheck(decision);
    },
    [state, runCheck],
  );

  const setColumnField = useCallback(
    (header: string, field: ImportFieldKey | null) =>
      edit((decision) => withColumnField(decision, header, field), true),
    [edit],
  );
  const setConstant = useCallback(
    (field: ImportFieldKey, value: string | number | null) =>
      edit((decision) => withConstant(decision, field, value), true),
    [edit],
  );
  const setDateOrder = useCallback(
    (order: "DMY" | "MDY") => edit((decision) => withDateOrder(decision, order), false),
    [edit],
  );
  const setDecimalStyle = useCallback(
    (style: "COMMA" | "POINT") => edit((decision) => withDecimalStyle(decision, style), false),
    [edit],
  );

  const continueToPreview = useCallback(async () => {
    if (state.step !== "mapping" || state.busy || state.check?.valid !== true) return;
    const { file, inspection, decision } = state;
    setState({ ...state, busy: true, notice: null });
    const result = await validateImport({ propertyId, domain, file, mapping: decision });
    const stay = (extra: Partial<MappingStep>) =>
      setState((current) =>
        current.step === "mapping" && sameDecision(current.decision, decision)
          ? { ...current, busy: false, ...extra }
          : current,
      );
    if (!result.ok) {
      stay({ notice: problemOfFailure(result) });
      return;
    }
    const tried = result.data;
    if (tried.status === "READY") {
      setState({
        step: "ready",
        file,
        inspection,
        decision,
        validation: tried,
        save: true,
        understanding: null, // matched by hand: the classic preview, not "File riconosciuto"
      });
      return;
    }
    if (tried.status === "NEEDS_CHOICE") {
      stay({ hints: tried.format_hints });
      return;
    }
    stay({
      notice: tried.problem ?? "GENERIC",
      hints: tried.format_hints,
      check: tried.check ?? state.check,
    });
  }, [state, propertyId, domain]);

  const reviewColumns = useCallback(() => {
    if (state.step !== "ready") return;
    openMapping(state.file, state.inspection, state.decision ?? startingDecision(state.inspection));
  }, [state, openMapping]);

  const setSave = useCallback(
    (save: boolean) => setState((current) => (current.step === "ready" ? { ...current, save } : current)),
    [],
  );

  const confirm = useCallback(async () => {
    if (state.step === "preview") {
      if (!state.preview.can_import) return;
      const { file } = state;
      setState({ step: "importing", file });
      const result = await importFile({ propertyId, domain, file });
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
      return;
    }
    if (state.step !== "ready" || !state.validation.can_import) return;
    const { file, decision, save } = state;
    setState({ step: "importing", file });
    const result = await importMatchedFile({
      propertyId,
      domain,
      file,
      mapping: decision,
      saveConfiguration: decision !== null && save,
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

  const reset = useCallback(() => {
    checkToken.current += 1;
    setState({ step: "choose", wrongType: false });
  }, []);

  return {
    state,
    method,
    chooseFile,
    chooseSheet,
    answer,
    teach,
    chooseKind,
    matchByHand,
    setColumnField,
    setConstant,
    setDateOrder,
    setDecimalStyle,
    continueToPreview,
    reviewColumns,
    setSave,
    confirm,
    reset,
  };
}
