"use client";

import { useEffect, useRef } from "react";

import type { DataSourceDomain, ImportLimitsResponse, UnderstandingBlocker } from "@ninfa/contracts";

import { useAnalysisStatus } from "@/lib/analysis/use-analysis-status";
import { formatPropertyLocalDateLongItalian, propertyLocalDate } from "@/lib/date/property-date";
import { oggiRoute } from "@/lib/routes";
import { sourcesCopy } from "@/lib/sources/copy";
import { problemText } from "@/lib/sources/problem-text";
import { periodText } from "@/lib/sources/understanding-format";
import { useImportFlow, type ImportFlowState, type RejectedFile } from "@/lib/sources/use-import-flow";
import { fileSizeText, useImportLimits } from "@/lib/sources/use-import-limits";

import { AnalysisNotice } from "./analysis-notice";
import { CheckCircleIcon, SpinnerIcon } from "./icons";
import { ImportaFileDropzone } from "./importa-file-dropzone";
import { StrutturaImportMapping } from "./struttura-import-mapping";
import { StrutturaImportPreview } from "./struttura-import-preview";
import { StrutturaImportQuestion } from "./struttura-import-question";
import { StrutturaImportUnderstood } from "./struttura-import-understood";
import { StrutturaButton, StrutturaLinkButton } from "./struttura-parts";

const PAGE = sourcesCopy.importPage;
const FLOW = sourcesCopy.importFlow;
const UNDERSTANDING = sourcesCopy.understanding;

function Busy({ text }: { text: string }) {
  return (
    <p className="struttura-flow__busy" role="status">
      <SpinnerIcon className="struttura-flow__spinner" />
      {text}
    </p>
  );
}

/** Why a file cannot be imported as it is, in the hotelier's words (the backend names the reason). */
function BlockerLine({ blocker }: { blocker: UnderstandingBlocker }) {
  const copy = UNDERSTANDING.blocked;
  if (blocker.code !== "MISSING_REQUIRED") return <p>{copy[blocker.code]}</p>;
  const label = (field: string) => (sourcesCopy.fields as Record<string, string>)[field] ?? field;
  return (
    <>
      <p>{copy.MISSING_REQUIRED}</p>
      <ul>
        {blocker.groups.map((group) => (
          <li key={group.join("|")}>{copy.missingGroup(group.map(label))}</li>
        ))}
      </ul>
    </>
  );
}

/**
 * What the page really knows while NINFA works: a request is out and has not answered, or it has. No percentage
 * and no timer: the two lines are the two requests, and the first is marked done only once it has come back.
 */
function Reading({ phase }: { phase: "reading" | "verifying" }) {
  const copy = PAGE.checking;
  return (
    <>
      <Busy text={copy[phase]} />
      <ol className="importa-steps">
        <li data-state={phase === "reading" ? "current" : "done"}>{copy.stepReading}</li>
        <li data-state={phase === "verifying" ? "current" : "pending"}>{copy.stepVerifying}</li>
      </ol>
    </>
  );
}

/** Once the file is in, the analysis follows by itself on the server: this says where it stands, live. */
function ImportedAnalysis({ propertyId }: { propertyId: string }) {
  const analysis = useAnalysisStatus({ propertyId });
  return <AnalysisNotice analysis={analysis} showUpToDate />;
}

/** Why a file never left the browser, with the backend's own limit when that is the reason. */
function rejectedText(rejected: RejectedFile, limits: ImportLimitsResponse | null): string {
  if (rejected === "TOO_LARGE" && limits !== null) return PAGE.tooLarge(fileSizeText(limits.max_file_bytes));
  return PAGE.rejected[rejected];
}

export interface ImportaFileFlowProps {
  propertyId: string;
  timeZone: string;
  /** "Modifica associazioni": the columns of this kind of source are looked at again. */
  review?: DataSourceDomain | null;
  /** An import SUCCEEDED: the list of imports is re-read from the backend. */
  onImported: () => void;
  /** The session is over, or the property is no longer the person's. */
  onAccessLost: () => void;
}

/**
 * The flow of the "Importa file" page: the person hands over a file, NINFA reads it, and only what the backend
 * asks for reaches the screen - a summary and one button, a question, a plain "no". The steps themselves are
 * `useImportFlow`'s, and the screens of a question, of the summary and of the columns are the ones Smart Import
 * already has. Nothing is parsed, decided or counted here. Matching columns by hand is always the person's own
 * choice, never a step of the way.
 */
export function ImportaFileFlow({
  propertyId,
  timeZone,
  review = null,
  onImported,
  onAccessLost,
}: ImportaFileFlowProps) {
  const limits = useImportLimits(propertyId);
  const flow = useImportFlow({
    propertyId,
    snapshotLocalDate: propertyLocalDate(new Date(), timeZone),
    review,
    limits,
    onImported,
    onAccessLost,
  });
  const { state } = flow;
  const busy = state.step === "checking" || state.step === "importing";
  const dateNote =
    state.step === "ready" && state.inspection.domain === "LABOR"
      ? FLOW.laborDate(formatPropertyLocalDateLongItalian(new Date(), timeZone))
      : null;

  // A file dropped beside the zone must not make the browser leave the page and open it - and the pointer says so.
  useEffect(() => {
    const keepThePage = (event: globalThis.DragEvent) => {
      if (event.defaultPrevented) return; // the zone took it
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
    };
    window.addEventListener("dragover", keepThePage);
    window.addEventListener("drop", keepThePage);
    return () => {
      window.removeEventListener("dragover", keepThePage);
      window.removeEventListener("drop", keepThePage);
    };
  }, []);

  // The control that had the focus has just gone away: the keyboard goes on from what took its place.
  const sectionRef = useRef<HTMLElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const shownStep = useRef<ImportFlowState["step"]>(state.step);
  useEffect(() => {
    if (shownStep.current === state.step) return;
    shownStep.current = state.step;
    if (state.step === "choose") sectionRef.current?.querySelector("input")?.focus();
    else panelRef.current?.focus({ preventScroll: true });
  }, [state.step]);

  return (
    <section ref={sectionRef} className="importa-flow" aria-labelledby="importa-flow-title" aria-busy={busy}>
      <h2 id="importa-flow-title" className="visually-hidden">
        {PAGE.panelLabel}
      </h2>

      {state.step === "choose" ? (
        <ImportaFileDropzone
          problem={state.rejected === null ? null : rejectedText(state.rejected, limits)}
          limits={limits}
          onFiles={(files) => void flow.chooseFiles(files)}
        />
      ) : (
        <div ref={panelRef} className="importa-panel struttura-flow" tabIndex={-1}>
          {state.step === "checking" ? <Reading phase={state.phase} /> : null}

          {state.step === "sheet" ? (
            <>
              <p className="struttura-flow__file">{FLOW.chosen(state.file.name)}</p>
              <h3 className="struttura-flow__subtitle">{sourcesCopy.match.sheetTitle}</h3>
              <p>{sourcesCopy.match.sheetIntro}</p>
              <div className="struttura-flow__actions">
                {state.sheets.map((sheet) => (
                  <StrutturaButton key={sheet} variant="outline" onClick={() => void flow.chooseSheet(sheet)}>
                    {sheet}
                  </StrutturaButton>
                ))}
              </div>
              <div className="struttura-flow__actions">
                <StrutturaButton variant="outline" onClick={flow.reset}>
                  {FLOW.chooseOther}
                </StrutturaButton>
              </div>
            </>
          ) : null}

          {state.step === "kind" ? (
            <>
              <p className="struttura-flow__file">{FLOW.chosen(state.file.name)}</p>
              <section className="struttura-question" aria-labelledby="importa-kind-title">
                <h3 className="struttura-flow__subtitle" id="importa-kind-title">
                  {PAGE.kind.title}
                </h3>
                <p>{PAGE.kind.body}</p>
                <div className="struttura-question__choices">
                  {state.kinds.map((kind) => (
                    <StrutturaButton key={kind} variant="outline" onClick={() => void flow.chooseKind(kind)}>
                      {UNDERSTANDING.kindName[kind]}
                    </StrutturaButton>
                  ))}
                </div>
              </section>
              <div className="struttura-flow__actions">
                <StrutturaButton variant="soft" onClick={flow.reset}>
                  {FLOW.chooseOther}
                </StrutturaButton>
              </div>
            </>
          ) : null}

          {state.step === "mapping" ? (
            <StrutturaImportMapping
              step={state}
              onField={flow.setColumnField}
              onConstant={flow.setConstant}
              onDateOrder={flow.setDateOrder}
              onDecimalStyle={flow.setDecimalStyle}
              onContinue={() => void flow.continueToPreview()}
              onChooseOther={flow.reset}
            />
          ) : null}

          {state.step === "manual" ? (
            <>
              <p className="struttura-flow__file">{FLOW.chosen(state.file.name)}</p>
              <div className="struttura-flow__problem" role="alert">
                <h3 className="struttura-flow__subtitle">{PAGE.manual.title}</h3>
                <p>{PAGE.manual.body}</p>
                {state.understanding.blockers.map((blocker) => (
                  <BlockerLine key={blocker.code} blocker={blocker} />
                ))}
                {state.notice !== null ? <p>{problemText(state.notice, "CSV")}</p> : null}
                <p>{UNDERSTANDING.blocked.nothingImported}</p>
              </div>
              <p className="struttura-flow__note">{PAGE.manual.offer}</p>
              <div className="struttura-flow__actions">
                <StrutturaButton variant="outline" onClick={flow.reset}>
                  {FLOW.chooseOther}
                </StrutturaButton>
                <StrutturaButton variant="primary" onClick={flow.matchByHand}>
                  {PAGE.manual.action}
                </StrutturaButton>
              </div>
            </>
          ) : null}

          {state.step === "ready" && state.understanding !== null ? (
            <StrutturaImportUnderstood
              step={state}
              dateNote={dateNote}
              onSave={flow.setSave}
              onImport={() => void flow.confirm()}
              onReview={flow.reviewColumns}
              onChooseOther={flow.reset}
            />
          ) : null}

          {state.step === "ready" && state.understanding === null ? (
            <StrutturaImportPreview
              step={state}
              timeZone={timeZone}
              dateNote={dateNote}
              onSave={flow.setSave}
              onImport={() => void flow.confirm()}
              onReview={flow.reviewColumns}
              onChooseOther={flow.reset}
            />
          ) : null}

          {state.step === "ask" ? <StrutturaImportQuestion step={state} flow={flow} /> : null}

          {state.step === "blocked" ? (
            <>
              <p className="struttura-flow__file">{FLOW.chosen(state.file.name)}</p>
              <div className="struttura-flow__problem" role="alert">
                <h3 className="struttura-flow__subtitle">{UNDERSTANDING.blocked.title}</h3>
                {state.understanding.blockers.map((blocker) => (
                  <BlockerLine key={blocker.code} blocker={blocker} />
                ))}
                <p>{UNDERSTANDING.blocked.nothingImported}</p>
              </div>
              <div className="struttura-flow__actions">
                <StrutturaButton variant="outline" onClick={flow.reset}>
                  {FLOW.chooseOther}
                </StrutturaButton>
              </div>
            </>
          ) : null}

          {state.step === "importing" ? <Busy text={FLOW.importing} /> : null}

          {state.step === "done" ? (
            <div className="importa-done">
              <span className="importa-done__icon" aria-hidden="true">
                <CheckCircleIcon />
              </span>
              <div role="status">
                <h3 className="importa-done__title">{FLOW.doneTitle}</h3>
              </div>
              <dl className="importa-done__facts">
                <div>
                  <dt>{PAGE.done.file}</dt>
                  <dd>{state.file.name}</dd>
                </div>
                <div>
                  <dt>{PAGE.done.kind}</dt>
                  <dd>{UNDERSTANDING.kindName[state.domain]}</dd>
                </div>
                <div>
                  <dt>{PAGE.done.rows}</dt>
                  <dd>
                    {UNDERSTANDING.facts.rows(state.result.rows_total)}.{" "}
                    {FLOW.doneCounts(
                      state.result.created,
                      state.result.updated,
                      state.result.unchanged,
                      state.result.removed,
                    )}
                  </dd>
                </div>
                {periodText(state.validation) !== null ? (
                  <div>
                    <dt>{PAGE.done.period}</dt>
                    <dd>{periodText(state.validation)}</dd>
                  </div>
                ) : null}
              </dl>
              {state.result.configuration_saved ? (
                <p className="struttura-flow__note">{FLOW.configurationSaved}</p>
              ) : null}
              {state.result.changed_data ? (
                <ImportedAnalysis propertyId={propertyId} />
              ) : (
                <p className="struttura-flow__note">{PAGE.done.nothingNew}</p>
              )}
              <div className="struttura-flow__actions">
                <StrutturaLinkButton variant="primary" href={oggiRoute(propertyId)}>
                  {PAGE.done.goToday}
                </StrutturaLinkButton>
                <StrutturaButton variant="outline" onClick={flow.reset}>
                  {PAGE.done.another}
                </StrutturaButton>
              </div>
            </div>
          ) : null}

          {state.step === "failed" ? (
            <>
              <div className="struttura-flow__problem" role="alert">
                <h3 className="struttura-flow__subtitle">{FLOW.failedTitle}</h3>
                <p>{problemText(state.problem, "CSV")}</p>
                <p>{FLOW.nothingImported}</p>
              </div>
              <div className="struttura-flow__actions">
                <StrutturaButton variant="outline" onClick={flow.reset}>
                  {FLOW.chooseOther}
                </StrutturaButton>
              </div>
            </>
          ) : null}
        </div>
      )}
    </section>
  );
}
