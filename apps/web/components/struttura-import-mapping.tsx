"use client";

import type {
  ImportConstantSpec,
  ImportFieldKey,
  ImportFieldSpec,
  ImportFormatHint,
} from "@ninfa/contracts";

import { sourcesCopy } from "@/lib/sources/copy";
import { fieldOfColumn, isLockedColumn } from "@/lib/sources/mapping-decision";
import { problemText } from "@/lib/sources/problem-text";
import type { MappingStep } from "@/lib/sources/use-import-flow";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.match;
const FLOW = sourcesCopy.importFlow;

function labelOf(key: ImportFieldKey): string {
  return sourcesCopy.fields[key];
}

function choiceLabel(key: ImportFieldKey, value: string): string {
  const choices: Partial<Record<string, Record<string, string>>> = sourcesCopy.choices;
  return choices[key]?.[value] ?? value;
}

/** One fixed value: the same on every row of the file, for what the file has no column for. */
function FixedValue({
  spec,
  constant,
  value,
  required,
  disabled,
  onChange,
}: {
  spec: ImportFieldSpec;
  constant: ImportConstantSpec;
  value: string | number | undefined;
  required: boolean;
  disabled: boolean;
  onChange: (value: string | number | null) => void;
}) {
  const label = (COPY.fixedLabels as Partial<Record<ImportFieldKey, string>>)[spec.key] ?? labelOf(spec.key);
  const current = value === undefined ? "" : String(value);
  return (
    <div className="struttura-match__fixed-row">
      <label>
        <span className="struttura-match__fixed-label">
          {label}
          {required ? <span className="struttura-badge">{COPY.fixedRequired}</span> : null}
        </span>
        {constant.kind === "CHOICE" ? (
          <select value={current} disabled={disabled} onChange={(event) => onChange(event.target.value || null)}>
            <option value="">{COPY.fixedNone}</option>
            {constant.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choiceLabel(spec.key, choice)}
              </option>
            ))}
          </select>
        ) : constant.kind === "INTEGER" ? (
          <input
            type="number"
            inputMode="numeric"
            min={1}
            value={current}
            disabled={disabled}
            placeholder={COPY.fixedPlaceholder.INTEGER}
            onChange={(event) => {
              const number = Number(event.target.value);
              onChange(event.target.value === "" || !Number.isInteger(number) ? null : number);
            }}
          />
        ) : (
          <input
            type="text"
            value={current}
            maxLength={constant.kind === "CURRENCY" ? 3 : 200}
            disabled={disabled}
            placeholder={COPY.fixedPlaceholder[constant.kind === "CURRENCY" ? "CURRENCY" : "TEXT"]}
            onChange={(event) => onChange(event.target.value.trim() === "" ? null : event.target.value)}
          />
        )}
      </label>
    </div>
  );
}

function FormatQuestion({
  hint,
  chosen,
  disabled,
  onChoose,
}: {
  hint: ImportFormatHint;
  chosen: string | null | undefined;
  disabled: boolean;
  onChoose: (value: "DMY" | "MDY" | "COMMA" | "POINT") => void;
}) {
  const dates = hint.question === "DATE_ORDER";
  const options = dates
    ? (["DMY", "MDY"] as const).map((value) => [value, COPY.dateOptions[value]] as const)
    : (["COMMA", "POINT"] as const).map((value) => [value, COPY.numberOptions[value]] as const);
  return (
    <fieldset className="struttura-match__question" disabled={disabled}>
      <legend>{dates ? COPY.datesQuestion : COPY.numbersQuestion}</legend>
      <p className="struttura-flow__note">{COPY.formatColumns(hint.columns.join(", "))}</p>
      {options.map(([value, text]) => (
        <label key={value} className="struttura-match__radio">
          <input
            type="radio"
            name={`format-${hint.question}`}
            value={value}
            checked={chosen === value}
            onChange={() => onChoose(value)}
          />
          {text}
        </label>
      ))}
    </fieldset>
  );
}

export interface StrutturaImportMappingProps {
  step: MappingStep;
  onField: (header: string, field: ImportFieldKey | null) => void;
  onConstant: (field: ImportFieldKey, value: string | number | null) => void;
  onDateOrder: (order: "DMY" | "MDY") => void;
  onDecimalStyle: (style: "COMMA" | "POINT") => void;
  onContinue: () => void;
  onChooseOther: () => void;
}

/**
 * "Abbina le colonne del tuo file": each column of the hotel's own file with a few example values and what
 * NINFA thinks it means, to confirm or correct. Which pieces of information are REQUIRED is the backend's
 * answer (`check`), shown as it comes; the "Continua" button stays disabled until the backend says the
 * matching is enough. Nothing is written by anything on this screen.
 */
export function StrutturaImportMapping({
  step,
  onField,
  onConstant,
  onDateOrder,
  onDecimalStyle,
  onContinue,
  onChooseOther,
}: StrutturaImportMappingProps) {
  const { inspection, decision, check, checking, busy, hints, notice } = step;
  const fixedFields = inspection.fields.filter(
    (spec) => spec.constant !== null && !decision.columns.some((column) => column.field === spec.key),
  );
  const missingKeys = new Set<ImportFieldKey>((check?.missing ?? []).flat());
  const questions = hints.filter((hint) => hint.proven === null);
  const unanswered = questions.some((hint) =>
    hint.question === "DATE_ORDER" ? !decision.date_order : !decision.decimal_style,
  );
  // A saved configuration that was NOT applied says why, so the person is not left wondering.
  const savedNote =
    inspection.profile.status === "NEEDS_REVIEW" && inspection.profile.reason !== null
      ? COPY.savedNotApplied[inspection.profile.reason]
      : null;
  const canContinue = check?.valid === true && !busy && !checking && !unanswered;

  return (
    <>
      <p className="struttura-flow__file">{FLOW.chosen(step.file.name)}</p>
      <h3 className="struttura-flow__subtitle">{COPY.title}</h3>
      <p>{COPY.intro}</p>
      {savedNote !== null ? <p className="struttura-flow__note">{savedNote}</p> : null}

      <div className="struttura-flow__sample struttura-match" role="region" aria-label={COPY.tableLabel} tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th scope="col">{COPY.columns.file}</th>
              <th scope="col">{COPY.columns.example}</th>
              <th scope="col">{COPY.columns.meaning}</th>
            </tr>
          </thead>
          <tbody>
            {inspection.columns.map((column) => {
              const field = fieldOfColumn(decision, column.header);
              const locked = isLockedColumn(column);
              const proposed = !locked && field !== null && field === column.field ? column.level : null;
              return (
                <tr key={column.header}>
                  <th scope="row">{column.header}</th>
                  <td>{column.examples.join(" · ")}</td>
                  <td>
                    <select
                      aria-label={COPY.meaningLabel(column.header)}
                      value={locked ? "" : (field ?? "")}
                      disabled={locked || busy}
                      onChange={(event) =>
                        onField(column.header, (event.target.value || null) as ImportFieldKey | null)
                      }
                    >
                      <option value="">{COPY.ignore}</option>
                      {inspection.fields.map((spec) => (
                        <option key={spec.key} value={spec.key}>
                          {labelOf(spec.key)}
                        </option>
                      ))}
                    </select>
                    {proposed !== null ? (
                      <span className="struttura-badge" data-level={proposed}>
                        {proposed === "RECOGNIZED" ? COPY.recognized : COPY.toCheck}
                      </span>
                    ) : null}
                    {column.not_used_reason !== null ? (
                      <small className="struttura-match__note">{COPY.notUsed[column.not_used_reason]}</small>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {fixedFields.length > 0 ? (
        // Open on its own when something required is still missing, or a fixed value is already set; otherwise
        // it stays folded so a file that is already matched is not cluttered with options it does not need.
        <details
          className="struttura-match__fixed"
          open={missingKeys.size > 0 || Object.keys(decision.constants).length > 0}
        >
          <summary>{COPY.fixedTitle}</summary>
          <p className="struttura-flow__note">{COPY.fixedIntro}</p>
          {fixedFields.map((spec) =>
            spec.constant === null ? null : (
              <FixedValue
                key={spec.key}
                spec={spec}
                constant={spec.constant}
                value={decision.constants[spec.key]}
                required={missingKeys.has(spec.key)}
                disabled={busy}
                onChange={(value) => onConstant(spec.key, value)}
              />
            ),
          )}
        </details>
      ) : null}

      <div className="struttura-match__status" role="status" aria-live="polite">
        {check === null ? (
          <p className="struttura-flow__note">{COPY.checking}</p>
        ) : check.valid ? (
          <p className="struttura-flow__note">{COPY.complete}</p>
        ) : (
          <>
            {check.missing.length > 0 ? (
              <>
                <p>{COPY.missingTitle(check.missing.length)}</p>
                <ul>
                  {check.missing.map((group) => (
                    <li key={group.join("|")}>{COPY.missingGroup(group.map(labelOf))}</li>
                  ))}
                </ul>
              </>
            ) : null}
            {check.problems.map((problem) => (
              <p key={`${problem.code}|${problem.fields.join("|")}`} className="struttura-flow__error">
                {(COPY.problems as Record<string, string>)[problem.code] ?? COPY.problemFallback}
              </p>
            ))}
          </>
        )}
      </div>

      {questions.map((hint) => (
        <FormatQuestion
          key={hint.question}
          hint={hint}
          chosen={hint.question === "DATE_ORDER" ? decision.date_order : decision.decimal_style}
          disabled={busy}
          onChoose={(value) =>
            value === "DMY" || value === "MDY" ? onDateOrder(value) : onDecimalStyle(value)
          }
        />
      ))}

      {notice !== null ? (
        <div className="struttura-flow__problem" role="alert">
          <p>{problemText(notice, "CSV")}</p>
        </div>
      ) : null}

      <div className="struttura-flow__actions">
        <StrutturaButton variant="outline" onClick={onChooseOther}>
          {FLOW.chooseOther}
        </StrutturaButton>
        <StrutturaButton variant="primary" disabled={!canContinue} onClick={onContinue}>
          {COPY.continue}
        </StrutturaButton>
      </div>
    </>
  );
}
