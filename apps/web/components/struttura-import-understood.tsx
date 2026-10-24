"use client";

import { useState } from "react";

import type { UnderstandingRecognized } from "@ninfa/contracts";

import { sourcesCopy } from "@/lib/sources/copy";
import { factsOf, originText, periodText } from "@/lib/sources/understanding-format";
import type { ReadyStep } from "@/lib/sources/use-import-flow";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.understanding;
const FLOW = sourcesCopy.importFlow;

function fieldName(field: string): string {
  return (sourcesCopy.fields as Record<string, string>)[field] ?? field;
}

/** What is shown as the "value" of a recognised thing: a value seen in the file, or - for a department that
 * is not a column - where it comes from. Never a personal datum: the backend sends none. */
function valueText(item: UnderstandingRecognized): string {
  if (item.example !== null) {
    const choices: Record<string, Record<string, string>> = sourcesCopy.choices;
    return choices[item.field]?.[item.example] ?? item.example;
  }
  return "";
}

export interface StrutturaImportUnderstoodProps {
  step: ReadyStep;
  onSave: (save: boolean) => void;
  onImport: () => void;
  onReview: () => void;
  onChooseOther: () => void;
}

/**
 * "File riconosciuto": NINFA read the whole document by itself and says what it found - a few facts the
 * backend derived from the rows that passed validation - with one button. Nothing is asked. "Controlla cosa
 * ho riconosciuto" opens the same findings field by field with where each one comes from (a column, the name
 * of the sheet, the title...), so the person can see - not just trust - what the import will do.
 */
export function StrutturaImportUnderstood({
  step,
  onSave,
  onImport,
  onReview,
  onChooseOther,
}: StrutturaImportUnderstoodProps) {
  const [explaining, setExplaining] = useState(false);
  const { understanding, validation, inspection } = step;
  if (understanding === null) return null;
  const domain = inspection.domain;
  const facts = factsOf(domain, understanding, validation);
  const period = periodText(validation);
  const document = understanding.document;
  const known = inspection.profile.status === "RECOGNIZED";
  const suggested = understanding.recognized.some((item) => item.origin.kind === "ASSISTANT");

  return (
    <>
      <p className="struttura-flow__file">{FLOW.chosen(step.file.name)}</p>
      <div className="struttura-understood">
        <h3 className="struttura-flow__subtitle">{COPY.recognizedTitle}</h3>
        <p className="struttura-understood__kind">{COPY.kinds[domain]}</p>
        <ul className="struttura-understood__facts" aria-label={COPY.recognizedTitle}>
          {facts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
        {period !== null ? <p className="struttura-flow__note">{period}</p> : null}
        {known ? <p className="struttura-flow__note">{COPY.sameAsLastTime}</p> : null}
      </div>

      {understanding.people !== null ? (
        <p className="struttura-flow__note">{COPY.peopleNote}</p>
      ) : null}
      {document.skipped.totals > 0 ? (
        <p className="struttura-flow__note">{COPY.skipped.totals(document.skipped.totals)}</p>
      ) : null}
      {document.skipped.notes > 0 ? (
        <p className="struttura-flow__note">{COPY.skipped.notes(document.skipped.notes)}</p>
      ) : null}
      {document.skipped.sections > 0 ? (
        <p className="struttura-flow__note">{COPY.skipped.sections(document.skipped.sections)}</p>
      ) : null}
      {document.totals !== null && document.totals !== "UNVERIFIED" ? (
        <p
          className={
            document.totals === "MISMATCH" ? "struttura-flow__error" : "struttura-flow__note"
          }
        >
          {COPY.totalsCheck[document.totals]}
        </p>
      ) : null}
      {document.amounts !== null ? (
        <p
          className={
            document.amounts === "MISMATCH" ? "struttura-flow__error" : "struttura-flow__note"
          }
        >
          {COPY.amountsCheck[document.amounts]}
        </p>
      ) : null}
      {validation.rows_unclassified > 0 && validation.rows_invalid === 0 ? (
        <div className="struttura-preview__attention" role="note">
          <p>{COPY.unclassified(validation.rows_unclassified)}</p>
        </div>
      ) : null}
      {suggested ? <p className="struttura-flow__note">{COPY.assistantNote}</p> : null}
      {validation.already_imported ? (
        <p className="struttura-flow__note">{sourcesCopy.preview.alreadyImported}</p>
      ) : null}

      {explaining ? (
        <div className="struttura-flow__summary">
          <h4 className="struttura-flow__subtitle">{COPY.explainTitle}</h4>
          <div
            className="struttura-flow__sample struttura-understood__table"
            role="region"
            aria-label={COPY.tableLabel}
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">{COPY.columns.field}</th>
                  <th scope="col">{COPY.columns.value}</th>
                  <th scope="col">{COPY.columns.origin}</th>
                </tr>
              </thead>
              <tbody>
                {understanding.recognized.map((item) => (
                  <tr key={`${item.field}|${item.origin.kind}|${item.origin.detail ?? ""}`}>
                    <th scope="row">{fieldName(item.field)}</th>
                    <td>{valueText(item)}</td>
                    <td>
                      {originText(item)}
                      {item.level !== "HIGH" ? (
                        <span className="struttura-badge">{COPY.toCheck}</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!known && validation.can_import ? (
            <label className="struttura-match__save">
              <input
                type="checkbox"
                checked={step.save}
                onChange={(event) => onSave(event.target.checked)}
              />
              <span>
                {sourcesCopy.preview.save}
                <small className="struttura-match__note">{sourcesCopy.preview.saveHelp}</small>
              </span>
            </label>
          ) : null}
          <div className="struttura-flow__actions">
            <StrutturaButton variant="outline" onClick={onReview}>
              {COPY.reviewColumns}
            </StrutturaButton>
          </div>
        </div>
      ) : null}

      <div className="struttura-flow__actions">
        <StrutturaButton variant="outline" onClick={onChooseOther}>
          {FLOW.chooseOther}
        </StrutturaButton>
        <StrutturaButton
          variant="outline"
          expanded={explaining}
          onClick={() => setExplaining((value) => !value)}
        >
          {explaining ? COPY.hideExplain : COPY.explain}
        </StrutturaButton>
        {validation.can_import ? (
          <StrutturaButton variant="primary" onClick={onImport}>
            {COPY.primary}
          </StrutturaButton>
        ) : null}
      </div>
    </>
  );
}
