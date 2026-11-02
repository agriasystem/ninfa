"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  DataSourceDomain,
  FileInspectionResponse,
  ImportFieldKey,
  ImportFormatHint,
  ImportMapping,
  ImportProblem,
  ImportValidationResponse,
  MappedImportResultResponse,
  MappingCheckResponse,
  UnderstandAnswers,
  Understanding,
  UnderstandingQuestion,
} from "@ninfa/contracts";

import { checkMapping, importMatchedFile, understandFile, validateImport } from "@/lib/api/data-sources";
import type { ApiResult } from "@/lib/api/client";

import {
  decisionFromSuggestions,
  mergeAnswers,
  personAnswered,
  sameDecision,
  startingDecision,
  withColumnField,
  withConstant,
  withDateOrder,
  withDecimalStyle,
} from "./mapping-decision";

/** The files Smart Import reads. An electronic invoice (XML) has its own path: see `use-invoice-import.ts`. */
const FILE_EXTENSIONS = [".csv", ".xlsx"];

export const FILE_ACCEPT = ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** The backend's own limit (`MAX_FILE_BYTES`), and it stays the one that decides: this only spares the browser
 * from reading into memory a file that would be refused anyway. */
const MAX_FILE_BYTES = 10 * 1024 * 1024;

/**
 * The first reading of a file nobody has said anything about. The API reads a file "as" a kind of data, but the
 * verdict on what the document IS (`understanding.detection`) is the same whichever kind is named: this stands
 * for no choice of the person's, and what the backend answers about THIS kind is used only if the verdict agrees.
 */
const FIRST_READING: DataSourceDomain = "BOOKINGS";

/** A problem that is not about the file itself. */
export type FlowProblem =
  | ImportProblem
  | "SOURCE_GONE"
  | "IMPORT_IN_PROGRESS"
  | "SEVERAL_SOURCES"
  | "SESSION_EXPIRED";

/** Why a file never left the browser. */
export type RejectedFile = "WRONG_TYPE" | "EMPTY" | "TOO_LARGE" | "SEVERAL";

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

/** NINFA read the file but is not sure enough to go on alone: it says so, and the person decides. */
export interface ManualStep {
  step: "manual";
  file: File;
  inspection: FileInspectionResponse;
  understanding: Understanding;
  /** Questions about how the file writes dates / numbers, for when the person takes over. */
  hints: ImportFormatHint[];
  /** Why trying the whole file did not work, in one stable word. */
  notice: FlowProblem | null;
}

/** Nothing in the document says what kind of data it holds, and nobody has said it yet. */
export interface KindStep {
  step: "kind";
  file: File;
  /** The kinds of data NINFA can read, as the backend lists them. */
  kinds: DataSourceDomain[];
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
  | { step: "choose"; rejected: RejectedFile | null }
  /** Only what the page really knows: the file is being read, or the whole of it is being tried. */
  | { step: "checking"; file: File; phase: "reading" | "verifying" }
  | { step: "sheet"; file: File; sheets: string[]; domain: DataSourceDomain }
  | KindStep
  | MappingStep
  | ManualStep
  | ReadyStep
  | AskStep
  | BlockedStep
  | { step: "importing"; file: File }
  | {
      step: "done";
      file: File;
      domain: DataSourceDomain;
      result: MappedImportResultResponse;
      /** What the whole file was found to hold, just before it was imported. */
      validation: ImportValidationResponse;
    }
  | { step: "failed"; file: File; problem: FlowProblem };

export interface ImportFlowOptions {
  propertyId: string;
  /** The property-local day the file is dated as of; labor only. */
  snapshotLocalDate: string;
  /** The person asked to look at the columns again for this kind of source: nothing is left to the document,
   * and the saved configuration is not applied on its own. */
  review?: DataSourceDomain | null;
  /** Called once an import SUCCEEDED, so the page can re-read the list of imports from the backend. */
  onImported: () => void;
  /** The session is over, or the property is no longer the person's: the caller re-resolves them. */
  onAccessLost: () => void;
}

export interface ImportFlow {
  state: ImportFlowState;
  /** What the person handed over. Reads a file (writes nothing); one that cannot be read never leaves the
   * browser. */
  chooseFiles: (files: readonly File[]) => Promise<void>;
  /** An Excel file with several sheets: the one to read. */
  chooseSheet: (name: string) => Promise<void>;
  /** The answer to the question on screen (what the person has said is never asked again). */
  answer: (patch: Partial<UnderstandAnswers>, confirmedDomain?: boolean) => Promise<void>;
  /** A VALUE_LABELS question: what the current word means (the last answer sends them all). */
  teach: (meaning: string) => Promise<void>;
  /** What kind of data the file holds, when the document does not say. */
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
export function problemOfFailure(result: Extract<ApiResult<unknown>, { ok: false }>): FlowProblem {
  if (result.status === 401) return "SESSION_EXPIRED";
  if (result.code === "FILE_TOO_LARGE") return "FILE_TOO_LARGE";
  if (result.code === "FILE_NOT_READABLE") return "UNREADABLE_FILE";
  // More than one source of this kind, created outside this page: NINFA does not pick one.
  if (result.code === "SEVERAL_SOURCES") return "SEVERAL_SOURCES";
  // Another import of the same data is still running: nothing was changed, the user can try again.
  if (result.code === "IMPORT_IN_PROGRESS") return "IMPORT_IN_PROGRESS";
  if (result.code === "DATA_SOURCE_NOT_FOUND" || result.code === "PROPERTY_NOT_FOUND") {
    return "SOURCE_GONE";
  }
  return "GENERIC";
}

/** Why a file is not even sent: its name says NINFA cannot read it, or it plainly holds nothing. */
function rejectionOf(files: readonly File[]): RejectedFile | null {
  if (files.length > 1) return "SEVERAL";
  const [file] = files;
  if (file === undefined) return null;
  const name = file.name.toLowerCase();
  if (!FILE_EXTENSIONS.some((extension) => name.endsWith(extension))) return "WRONG_TYPE";
  if (file.size === 0) return "EMPTY";
  if (file.size > MAX_FILE_BYTES) return "TOO_LARGE";
  return null;
}

/**
 * The steps of putting a file into NINFA. The person hands over the file; what it is, is read from the document:
 *
 *   choose -> NINFA reads the whole DOCUMENT -> tries every row -> a summary and one button -> import
 *                                            \-> ONE question at a time ("ask")
 *                                            \-> "I cannot go on alone": the person may match the columns ("manual")
 *                                            \-> why it cannot be imported ("blocked")
 *                                            \-> nothing says what kind of data it is: the person says ("kind")
 *
 * The kind of data is the engine's own verdict (`understanding.detection`). A verdict that points at a kind is
 * followed - HIGH and MEDIUM alike, because the engine then answers about THAT kind, nothing is imported before
 * the person presses the button, and the summary above that button names the kind. A verdict that points nowhere
 * is never followed: only a person can say what the file is (`confirmedDomain`).
 *
 * The backend does every check - what a column probably means, what is still missing, how dates and numbers
 * are written, every row of the file - and the import itself; this hook only walks the steps and keeps the
 * person informed. Nothing is parsed, validated or counted here, and no rule about what is required lives
 * here: the backend answers it for each change the person makes.
 *
 * Nothing before `confirm` writes anything: choosing a file, matching its columns and looking at the summary
 * leave the property exactly as it was. The source behind a card of Fonti dati, and the remembered configuration,
 * come to exist only when the confirmed import succeeds (the backend reuses the source of that kind of data).
 */
export function useImportFlow({
  propertyId,
  snapshotLocalDate,
  review = null,
  onImported,
  onAccessLost,
}: ImportFlowOptions): ImportFlow {
  const [state, setState] = useState<ImportFlowState>({ step: "choose", rejected: null });
  // An answer about a decision that is no longer on screen is dropped.
  const checkToken = useRef(0);

  // The caller builds a new callback on every render: read it through a ref.
  const accessLostRef = useRef(onAccessLost);
  useEffect(() => {
    accessLostRef.current = onAccessLost;
  });

  /** A request that failed ends the flow, with its reason in the page's own terms. */
  const fail = useCallback((file: File, result: Extract<ApiResult<unknown>, { ok: false }>) => {
    if (result.status === 401 || result.code === "PROPERTY_NOT_FOUND") accessLostRef.current();
    setState({ step: "failed", file, problem: problemOfFailure(result) });
  }, []);

  const runCheck = useCallback(
    async (domain: DataSourceDomain, decision: ImportMapping) => {
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
    [propertyId],
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
      void runCheck(inspection.domain, decision);
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
      if (review !== null) {
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
        setState({ step: "manual", file, inspection, understanding, hints: [], notice: null });
        return;
      }
      // READY: the whole file is tried with the proposal and, if every row is fine, the person sees a
      // summary and one button.
      setState({ step: "checking", file, phase: "verifying" });
      const tried = await validateImport({ propertyId, domain: inspection.domain, file, mapping: proposal });
      if (!tried.ok) {
        fail(file, tried);
        return;
      }
      if (tried.data.status === "READY") {
        const known = inspection.profile.status === "RECOGNIZED";
        const taught = Object.keys(answers.labels ?? {}).length > 0;
        setState({
          step: "ready",
          file,
          inspection,
          decision: proposal,
          validation: tried.data,
          // what the person answered is worth remembering even for a source NINFA already knows
          save: !known || taught || personAnswered(answers),
          understanding,
        });
        return;
      }
      setState({
        step: "manual",
        file,
        inspection,
        understanding,
        hints: tried.data.status === "NEEDS_CHOICE" ? tried.data.format_hints : [],
        notice: tried.data.status === "BLOCKED" ? (tried.data.problem ?? "GENERIC") : null,
      });
    },
    [propertyId, review, openMapping, fail],
  );

  /** What the backend answered about a file, as a step of the flow. */
  const settle = useCallback(
    async (
      file: File,
      inspection: FileInspectionResponse,
      answers: UnderstandAnswers,
      confirmedDomain: boolean,
    ) => {
      const { domain } = inspection;
      if (inspection.problem === "SHEET_REQUIRED") {
        setState({ step: "sheet", file, sheets: inspection.sheet_names, domain });
        return;
      }
      if (inspection.problem !== null) {
        // (a document with no table at all says so as a blocker, in better words than the problem's)
        if (inspection.understanding && inspection.understanding.blockers.length > 0) {
          setState({ step: "blocked", file, inspection, understanding: inspection.understanding });
          return;
        }
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

      if (review === null && inspection.profile.status === "RECOGNIZED") {
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
      } else if (review === null && inspection.already_canonical) {
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
    [propertyId, review, openMapping, routeUnderstood],
  );

  /** Reads the file as a kind of data that is already known: what the person said, or the document's verdict. */
  const readFile = useCallback(
    async (
      file: File,
      domain: DataSourceDomain,
      answers: UnderstandAnswers = {},
      confirmedDomain = false,
    ) => {
      setState({ step: "checking", file, phase: "reading" });
      const result = await understandFile({ propertyId, domain, file, answers, confirmedDomain });
      if (!result.ok) {
        fail(file, result);
        return;
      }
      await settle(file, result.data, answers, confirmedDomain);
    },
    [propertyId, settle, fail],
  );

  /** Reads a file nobody has said anything about, and follows what the document says it is. */
  const readUnknownFile = useCallback(
    async (file: File) => {
      setState({ step: "checking", file, phase: "reading" });
      const result = await understandFile({
        propertyId,
        domain: FIRST_READING,
        file,
        answers: {},
        confirmedDomain: false,
      });
      if (!result.ok) {
        fail(file, result);
        return;
      }
      const inspection = result.data;
      const understanding = inspection.understanding;
      if (understanding && inspection.problem === null) {
        const { domain, scores } = understanding.detection;
        if (domain !== null && domain !== inspection.domain) {
          await readFile(file, domain);
          return;
        }
        // (the optional assistant may have a suggestion: that is a question of the backend's, not this)
        const suggested = understanding.questions.some((question) => question.kind === "DOMAIN");
        if (domain === null && !suggested) {
          setState({ step: "kind", file, kinds: scores.map((score) => score.domain) });
          return;
        }
      }
      await settle(file, inspection, {}, false);
    },
    [propertyId, readFile, settle, fail],
  );

  const chooseFiles = useCallback(
    async (files: readonly File[]) => {
      const rejected = rejectionOf(files);
      if (rejected !== null) {
        setState({ step: "choose", rejected });
        return;
      }
      const [file] = files;
      if (file === undefined) return;
      await (review !== null ? readFile(file, review) : readUnknownFile(file));
    },
    [review, readFile, readUnknownFile],
  );

  const chooseSheet = useCallback(
    async (name: string) => {
      if (state.step !== "sheet") return;
      await readFile(state.file, state.domain, { sheet_name: name });
    },
    [state, readFile],
  );

  const answer = useCallback(
    async (patch: Partial<UnderstandAnswers>, confirmedDomain?: boolean) => {
      if (state.step !== "ask") return;
      await readFile(
        state.file,
        state.inspection.domain,
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
        state.inspection.domain,
        mergeAnswers(state.answers, { labels: { [document]: taught } }),
        state.confirmedDomain,
      );
    },
    [state, readFile],
  );

  const chooseKind = useCallback(
    async (kind: DataSourceDomain) => {
      if (state.step !== "ask" && state.step !== "kind") return;
      await readFile(state.file, kind, state.step === "ask" ? state.answers : {}, true);
    },
    [state, readFile],
  );

  const matchByHand = useCallback(() => {
    if (state.step !== "ask" && state.step !== "blocked" && state.step !== "manual") return;
    const proposal = state.inspection.proposal ?? startingDecision(state.inspection);
    openMapping(state.file, state.inspection, proposal, {
      understanding: state.understanding,
      ...(state.step === "manual" ? { hints: state.hints, notice: state.notice } : {}),
    });
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
      if (recheck) void runCheck(state.inspection.domain, decision);
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
    const result = await validateImport({ propertyId, domain: inspection.domain, file, mapping: decision });
    const stay = (extra: Partial<MappingStep>) =>
      setState((current) =>
        current.step === "mapping" && sameDecision(current.decision, decision)
          ? { ...current, busy: false, ...extra }
          : current,
      );
    if (!result.ok) {
      if (result.status === 401 || result.code === "PROPERTY_NOT_FOUND") accessLostRef.current();
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
  }, [state, propertyId]);

  const reviewColumns = useCallback(() => {
    if (state.step !== "ready") return;
    openMapping(state.file, state.inspection, state.decision ?? startingDecision(state.inspection));
  }, [state, openMapping]);

  const setSave = useCallback(
    (save: boolean) => setState((current) => (current.step === "ready" ? { ...current, save } : current)),
    [],
  );

  const confirm = useCallback(async () => {
    if (state.step !== "ready" || !state.validation.can_import) return;
    const { file, decision, save, validation } = state;
    const { domain } = state.inspection;
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
      fail(file, result);
      return;
    }
    if (!result.data.succeeded) {
      setState({ step: "failed", file, problem: result.data.problem ?? "GENERIC" });
      return;
    }
    setState({ step: "done", file, domain, result: result.data, validation });
    onImported();
  }, [state, propertyId, snapshotLocalDate, onImported, fail]);

  const reset = useCallback(() => {
    checkToken.current += 1;
    setState({ step: "choose", rejected: null });
  }, []);

  return {
    state,
    chooseFiles,
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
