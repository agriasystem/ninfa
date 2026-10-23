"use client";

import { useState, type ChangeEvent } from "react";

import type { DataSourceDomain, ImportPreviewResponse, SourceMethod } from "@ninfa/contracts";

import { downloadTemplate } from "@/lib/api/data-sources";
import { formatPropertyLocalDateLongItalian } from "@/lib/date/property-date";
import { sourcesCopy } from "@/lib/sources/copy";
import { saveBlob, TEMPLATE_FILENAME } from "@/lib/sources/save-file";
import { useImportFlow, type FlowProblem } from "@/lib/sources/use-import-flow";

import { DownloadIcon, SpinnerIcon, UploadIcon } from "./icons";
import { StrutturaModal } from "./struttura-modal";
import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.importFlow;

/** The sentence for a problem, with what to do next where it helps. Never a technical word. */
function problemText(problem: FlowProblem, method: SourceMethod): string {
  if (problem === "SOURCE_GONE") return sourcesCopy.errors.sourceGone;
  if (problem === "IMPORT_IN_PROGRESS") return sourcesCopy.errors.importInProgress;
  const base = sourcesCopy.problems[problem];
  const hints: Partial<Record<FlowProblem, Record<SourceMethod, string>>> = sourcesCopy.problemHints;
  const hint = hints[problem]?.[method];
  return hint ? `${base} ${hint}` : base;
}

function Busy({ text }: { text: string }) {
  return (
    <p className="struttura-flow__busy" role="status">
      <SpinnerIcon className="struttura-flow__spinner" />
      {text}
    </p>
  );
}

/** What NINFA found in the file, before anything is imported. */
function PreviewSummary({ preview }: { preview: ImportPreviewResponse }) {
  return (
    <div className="struttura-flow__summary">
      <p className="struttura-flow__found">{COPY.rowsFound(preview.rows_total, preview.method)}</p>
      {preview.already_imported ? <p className="struttura-flow__note">{COPY.alreadyImported}</p> : null}
      {preview.unrecognized_columns.length > 0 ? (
        <p className="struttura-flow__note">{COPY.unusedColumns(preview.unrecognized_columns.join(", "))}</p>
      ) : null}
      {preview.sample_rows.length > 0 ? (
        <div
          className="struttura-flow__sample"
          role="region"
          aria-label={COPY.sampleLabel}
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                {preview.sample_columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.sample_rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {preview.can_import ? <p className="struttura-flow__note">{COPY.rowChecks}</p> : null}
    </div>
  );
}

export interface StrutturaImportDialogProps {
  propertyId: string;
  timeZone: string;
  domain: DataSourceDomain;
  /** The property-local day (YYYY-MM-DD) a labor file is dated as of. */
  snapshotLocalDate: string;
  /** An import SUCCEEDED: the cards are re-read from the backend. */
  onImported: () => void;
  onClose: () => void;
}

/**
 * Putting a file into NINFA, one step at a time: choose the file -> NINFA looks at it -> confirm -> the
 * result. The backend does every check and the import itself (the same services the pilot's tooling uses);
 * this dialog shows what the backend found and what it did, in plain Italian.
 *
 * Opening it, choosing a file and looking at it write nothing: the data source behind the card comes to
 * exist only when the confirmed import succeeds. Closing the dialog at any earlier step (or an import
 * that fails) therefore leaves the card exactly as it was.
 */
export function StrutturaImportDialog({
  propertyId,
  timeZone,
  domain,
  snapshotLocalDate,
  onImported,
  onClose,
}: StrutturaImportDialogProps) {
  const flow = useImportFlow({ propertyId, domain, snapshotLocalDate, onImported });
  const { state, method } = flow;
  const [templateFailed, setTemplateFailed] = useState(false);
  const hasTemplate = domain !== "COSTS";
  const busy = state.step === "checking" || state.step === "importing";

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // the same file can be chosen again after a correction
    if (file) void flow.chooseFile(file);
  }

  async function handleTemplate() {
    if (domain === "COSTS") return;
    const blob = await downloadTemplate(propertyId, domain);
    if (blob === null) {
      setTemplateFailed(true);
      return;
    }
    setTemplateFailed(false);
    saveBlob(blob, TEMPLATE_FILENAME[domain]);
  }

  const templateButton = hasTemplate ? (
    <StrutturaButton variant="outline" Icon={DownloadIcon} onClick={() => void handleTemplate()}>
      {COPY.template}
    </StrutturaButton>
  ) : null;

  return (
    <StrutturaModal title={COPY.titles[domain]} dismissible={!busy} onClose={onClose}>
      <div className="struttura-flow" aria-busy={busy}>
        {state.step === "choose" ? (
          <>
            <p className="struttura-flow__hint">{COPY.hints[method]}</p>
            {domain === "LABOR" ? (
              <p className="struttura-flow__hint">
                {COPY.laborDate(formatPropertyLocalDateLongItalian(new Date(), timeZone))}
              </p>
            ) : null}
            {state.wrongType ? (
              <p className="struttura-flow__error" role="alert">
                {COPY.wrongType[method]}
              </p>
            ) : null}
            {templateFailed ? (
              <p className="struttura-flow__error" role="alert">
                {COPY.templateFailed}
              </p>
            ) : null}
            <div className="struttura-flow__actions">
              <label className="struttura-button struttura-button--primary struttura-flow__pick">
                <UploadIcon className="struttura-button__icon" />
                {COPY.chooseFile}
                <input
                  type="file"
                  className="visually-hidden"
                  accept={method === "CSV" ? ".csv,text/csv" : ".xml,text/xml,application/xml"}
                  onChange={handlePick}
                />
              </label>
              {templateButton}
            </div>
          </>
        ) : null}

        {state.step === "checking" ? <Busy text={COPY.checking} /> : null}

        {state.step === "preview" ? (
          <>
            <p className="struttura-flow__file">{COPY.chosen(state.file.name)}</p>
            {state.preview.can_import ? (
              <>
                <h3 className="struttura-flow__subtitle">{COPY.previewTitle}</h3>
                <PreviewSummary preview={state.preview} />
              </>
            ) : (
              <div className="struttura-flow__problem" role="alert">
                <p>
                  {problemText(state.preview.problem ?? "GENERIC", method)}
                </p>
                {state.preview.missing_columns.length > 0 ? (
                  <>
                    <p>{COPY.missingTitle}</p>
                    <ul>
                      {state.preview.missing_columns.map((group) => (
                        <li key={group.join("|")}>
                          <code>{COPY.missingGroup(group)}</code>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
                <p>{COPY.nothingImported}</p>
              </div>
            )}
            <div className="struttura-flow__actions">
              <StrutturaButton variant="outline" onClick={flow.reset}>
                {COPY.chooseOther}
              </StrutturaButton>
              {state.preview.can_import ? (
                <StrutturaButton variant="primary" onClick={() => void flow.confirm()}>
                  {COPY.confirm}
                </StrutturaButton>
              ) : (
                templateButton
              )}
            </div>
          </>
        ) : null}

        {state.step === "importing" ? <Busy text={COPY.importing} /> : null}

        {state.step === "done" ? (
          <>
            <h3 className="struttura-flow__subtitle">{COPY.doneTitle}</h3>
            <p className="struttura-flow__found">
              {COPY.rowsFound(state.result.rows_total, method)}
            </p>
            <p>{COPY.doneCounts(state.result.created, state.result.updated, state.result.unchanged)}</p>
            <p className="struttura-flow__note">{COPY.doneNote}</p>
            <div className="struttura-flow__actions">
              <StrutturaButton variant="primary" onClick={onClose}>
                {sourcesCopy.dialog.close}
              </StrutturaButton>
            </div>
          </>
        ) : null}

        {state.step === "failed" ? (
          <>
            <div className="struttura-flow__problem" role="alert">
              <h3 className="struttura-flow__subtitle">{COPY.failedTitle}</h3>
              <p>{problemText(state.problem, method)}</p>
              <p>{COPY.nothingImported}</p>
            </div>
            <div className="struttura-flow__actions">
              <StrutturaButton variant="outline" onClick={flow.reset}>
                {COPY.chooseOther}
              </StrutturaButton>
              <StrutturaButton variant="soft" onClick={onClose}>
                {sourcesCopy.dialog.close}
              </StrutturaButton>
            </div>
          </>
        ) : null}
      </div>
    </StrutturaModal>
  );
}
