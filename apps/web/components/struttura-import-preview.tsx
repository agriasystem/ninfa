"use client";

import { formatPropertyLocalDateLongItalian } from "@/lib/date/property-date";
import { sourcesCopy } from "@/lib/sources/copy";
import { formatSampleCell } from "@/lib/sources/sample-format";
import type { ReadyStep } from "@/lib/sources/use-import-flow";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.preview;
const RECOGNIZED = sourcesCopy.recognized;
const FLOW = sourcesCopy.importFlow;

function rowProblem(code: string): string {
  return (COPY.rowProblems as Record<string, string>)[code] ?? COPY.rowProblemFallback;
}

function fieldName(field: string): string {
  return (sourcesCopy.fields as Record<string, string>)[field] ?? "";
}

export interface StrutturaImportPreviewProps {
  step: ReadyStep;
  timeZone: string;
  onSave: (save: boolean) => void;
  onImport: () => void;
  onReview: () => void;
  onChooseOther: () => void;
}

/**
 * "Anteprima importazione": what NINFA found in the whole file, row by row, before anything is imported -
 * how many rows, how many are fine, the first rows as NINFA will keep them, how dates and numbers were read.
 * The backend judged every row; this only shows its answer. A file with even one row that cannot be
 * imported imports nothing, and the screen says so instead of offering the import.
 */
export function StrutturaImportPreview({
  step,
  timeZone,
  onSave,
  onImport,
  onReview,
  onChooseOther,
}: StrutturaImportPreviewProps) {
  const { validation, inspection, decision } = step;
  const recognized = decision === null;
  const specs = new Map(inspection.fields.map((spec) => [spec.key, spec] as const));
  const lastUsed = inspection.profile.last_used_at;
  const dates = validation.format_hints.find((hint) => hint.question === "DATE_ORDER");
  const numbers = validation.format_hints.find((hint) => hint.question === "DECIMAL_STYLE");
  const provenOrder = dates?.proven === "DMY" || dates?.proven === "MDY" ? dates.proven : null;
  const provenStyle = numbers?.proven === "COMMA" || numbers?.proven === "POINT" ? numbers.proven : null;
  const dateOrder = decision?.date_order ?? provenOrder;
  const decimalStyle = decision?.decimal_style ?? provenStyle;

  return (
    <>
      <p className="struttura-flow__file">{FLOW.chosen(step.file.name)}</p>
      {recognized ? (
        <div className="struttura-flow__summary">
          <h3 className="struttura-flow__subtitle">{RECOGNIZED.title}</h3>
          <p>{RECOGNIZED.body}</p>
          {lastUsed !== null ? (
            <p className="struttura-flow__note">
              {RECOGNIZED.lastUsed(formatPropertyLocalDateLongItalian(new Date(lastUsed), timeZone))}
            </p>
          ) : null}
        </div>
      ) : null}

      <h3 className="struttura-flow__subtitle">{COPY.title}</h3>
      <p className="struttura-preview__counts">
        <strong>{COPY.rowsFound(validation.rows_total)}</strong>
        <span>{COPY.valid(validation.rows_valid)}</span>
        {validation.rows_invalid > 0 ? (
          <span className="struttura-preview__invalid">{COPY.invalid(validation.rows_invalid)}</span>
        ) : null}
      </p>
      {validation.already_imported ? (
        <p className="struttura-flow__note">{COPY.alreadyImported}</p>
      ) : null}
      {dateOrder !== null ? <p className="struttura-flow__note">{COPY.datesRead[dateOrder]}</p> : null}
      {decimalStyle !== null ? (
        <p className="struttura-flow__note">{COPY.numbersRead[decimalStyle]}</p>
      ) : null}

      {validation.rows_invalid > 0 ? (
        <div className="struttura-flow__problem" role="alert">
          <h4 className="struttura-flow__subtitle">{COPY.blockedTitle}</h4>
          <ul>
            {validation.row_problems.map((problem) => (
              <li key={`${problem.field}|${problem.code}`}>
                {COPY.problemLine(rowProblem(problem.code), fieldName(problem.field), problem.count)}
              </li>
            ))}
          </ul>
          {validation.invalid_rows.length > 0 ? (
            <>
              <p>{COPY.firstRows}</p>
              <ul>
                {validation.invalid_rows.map((row) => (
                  <li key={row.row}>
                    {COPY.rowLine(
                      row.row,
                      row.issues
                        .map((issue) => {
                          const name = fieldName(issue.field);
                          return `${name.length > 0 ? `${name}: ` : ""}${rowProblem(issue.code)}`;
                        })
                        .join("; "),
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <p>{COPY.blockedBody}</p>
        </div>
      ) : validation.sample_rows.length > 0 ? (
        <div className="struttura-flow__summary">
          <p className="struttura-flow__note">{COPY.sampleNote}</p>
          <div className="struttura-flow__sample" role="region" aria-label={COPY.sampleLabel} tabIndex={0}>
            <table>
              <thead>
                <tr>
                  {validation.sample_fields.map((field) => (
                    <th key={field} scope="col">
                      {(COPY.columns as Record<string, string>)[field] ?? sourcesCopy.fields[field]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {validation.sample_rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => {
                      const field = validation.sample_fields[cellIndex];
                      return (
                        <td key={cellIndex}>
                          {formatSampleCell(field === undefined ? undefined : specs.get(field), cell)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {!recognized && validation.can_import ? (
        <label className="struttura-match__save">
          <input type="checkbox" checked={step.save} onChange={(event) => onSave(event.target.checked)} />
          <span>
            {COPY.save}
            <small className="struttura-match__note">{COPY.saveHelp}</small>
          </span>
        </label>
      ) : null}

      <div className="struttura-flow__actions">
        <StrutturaButton variant="outline" onClick={onChooseOther}>
          {FLOW.chooseOther}
        </StrutturaButton>
        <StrutturaButton variant="outline" onClick={onReview}>
          {RECOGNIZED.review}
        </StrutturaButton>
        {validation.can_import ? (
          <StrutturaButton variant="primary" onClick={onImport}>
            {recognized ? RECOGNIZED.confirm : COPY.import}
          </StrutturaButton>
        ) : null}
      </div>
    </>
  );
}
