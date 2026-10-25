"use client";

import { useState, type ReactNode } from "react";

import type { DataSourceDomain, UnderstandAnswers, UnderstandingChoice } from "@ninfa/contracts";

import { sourcesCopy } from "@/lib/sources/copy";
import type { AskStep, ImportFlow } from "@/lib/sources/use-import-flow";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.understanding.question;
const FLOW = sourcesCopy.importFlow;
const NAMES = sourcesCopy.understanding;

type Words = Readonly<Record<string, string>>;

const DEPARTMENT_WORDS: Words = sourcesCopy.choices.labor_category;
const CATEGORY_WORDS: Words = sourcesCopy.choices.cost_category;
const STATUS_WORDS: Words = sourcesCopy.choices.status;

/** A word for a value the backend offers as a choice (a department, a category, a status). */
function choiceText(words: Words | null, value: string): string {
  return words?.[value] ?? value;
}

function fieldName(field: string): string {
  return (sourcesCopy.fields as Record<string, string>)[field] ?? field;
}

/** The words the choices of a "what does this word mean" question are written in. */
function wordsOfDocument(document: string | null): Words | null {
  if (document === "role_mapping") return DEPARTMENT_WORDS;
  if (document === "category_mapping") return CATEGORY_WORDS;
  if (document === "status_mapping") return STATUS_WORDS;
  return null;
}

function Choices({
  choices,
  words,
  onChoose,
}: {
  choices: UnderstandingChoice[];
  words: Words | null;
  onChoose: (value: string) => void;
}) {
  return (
    <div className="struttura-question__choices">
      {choices.map((choice) => (
        <StrutturaButton key={choice.value} variant="outline" onClick={() => onChoose(choice.value)}>
          {choiceText(words, choice.value)}
        </StrutturaButton>
      ))}
    </div>
  );
}

export interface StrutturaImportQuestionProps {
  step: AskStep;
  domain: DataSourceDomain;
  flow: Pick<ImportFlow, "answer" | "teach" | "chooseKind" | "matchByHand" | "reset">;
}

/**
 * ONE question, only about what is really ambiguous - never a form with a dozen selects. The backend decides
 * that a question is needed and what its choices are; this shows it in plain Italian and sends the answer back,
 * after which NINFA reads the file again with that answer and goes on. What the person has said is never asked
 * twice.
 */
export function StrutturaImportQuestion({ step, domain, flow }: StrutturaImportQuestionProps) {
  const { question } = step;
  const [week, setWeek] = useState("");
  const words = wordsOfDocument(question.document);
  const heading = (text: string) => (
    <h3 className="struttura-flow__subtitle" id="struttura-question-title">
      {text}
    </h3>
  );
  const candidate = question.candidate;

  let body: ReactNode;
  switch (question.kind) {
    case "DOMAIN": {
      const detected = candidate as DataSourceDomain | null;
      body = (
        <>
          {heading(
            detected !== null ? COPY.DOMAIN.withCandidate(NAMES.kindPhrase[detected]) : COPY.DOMAIN.nothing,
          )}
          {question.origin === "ASSISTANT" ? (
            <p className="struttura-flow__note">{COPY.DOMAIN.suggested}</p>
          ) : null}
          {detected !== null ? (
            <div className="struttura-question__choices">
              <StrutturaButton variant="primary" onClick={() => void flow.chooseKind(detected)}>
                {COPY.DOMAIN.asIs(NAMES.kindPhrase[detected])}
              </StrutturaButton>
              <StrutturaButton variant="outline" onClick={() => void flow.chooseKind(domain)}>
                {COPY.DOMAIN.notIt(NAMES.kindPhrase[domain])}
              </StrutturaButton>
            </div>
          ) : (
            <div className="struttura-question__choices">
              {question.choices.map((choice) => (
                <StrutturaButton
                  key={choice.value}
                  variant="outline"
                  onClick={() => void flow.chooseKind(choice.value as DataSourceDomain)}
                >
                  {NAMES.kindName[choice.value as DataSourceDomain]}
                </StrutturaButton>
              ))}
            </div>
          )}
        </>
      );
      break;
    }
    case "TABLE":
      body = (
        <>
          {heading(COPY.TABLE.title)}
          <div className="struttura-question__choices struttura-question__choices--stacked">
            {question.choices.map((choice) => (
              <StrutturaButton
                key={choice.value}
                variant="outline"
                onClick={() => void flow.answer({ table_key: choice.value })}
              >
                {COPY.TABLE.choice(
                  choice.title ?? "",
                  choice.sheets[0] ?? choice.value,
                  choice.first_row ?? 0,
                  choice.count ?? 0,
                  choice.columns.join(", "),
                )}
              </StrutturaButton>
            ))}
          </div>
        </>
      );
      break;
    case "DEPARTMENT_ROWS":
      body = (
        <>
          {heading(COPY.DEPARTMENT_ROWS)}
          <Choices
            choices={question.choices}
            words={DEPARTMENT_WORDS}
            onChoose={(value) => void flow.answer({ department_value: value })}
          />
        </>
      );
      break;
    case "DEPARTMENT_CONFIRM": {
      const proposed = candidate ?? "";
      const name = choiceText(DEPARTMENT_WORDS, proposed);
      body = (
        <>
          {heading(COPY.DEPARTMENT_CONFIRM.title(name))}
          <div className="struttura-question__choices">
            <StrutturaButton
              variant="primary"
              onClick={() => void flow.answer({ department_from: "TITLE" })}
            >
              {COPY.DEPARTMENT_CONFIRM.yes(name)}
            </StrutturaButton>
          </div>
          <p className="struttura-flow__note">{COPY.DEPARTMENT_CONFIRM.other}</p>
          <Choices
            choices={question.choices.filter((choice) => choice.value !== proposed)}
            words={DEPARTMENT_WORDS}
            onChoose={(value) => void flow.answer({ department_value: value })}
          />
        </>
      );
      break;
    }
    case "VALUE_LABELS": {
      const pending = question.labels.filter((item) => !(item.label in step.taught));
      const current = pending[0];
      const text =
        words === CATEGORY_WORDS
          ? COPY.VALUE_LABELS.category
          : words === STATUS_WORDS
            ? COPY.VALUE_LABELS.status
            : COPY.VALUE_LABELS.department;
      body =
        current === undefined ? null : (
          <>
            {heading(text(current.label, current.count))}
            <Choices
              choices={question.choices}
              words={words}
              onChoose={(value) => void flow.teach(value)}
            />
            <p className="struttura-flow__note">{COPY.VALUE_LABELS.remembered}</p>
            {pending.length > 1 ? (
              <p className="struttura-flow__note">{COPY.VALUE_LABELS.left(pending.length - 1)}</p>
            ) : null}
          </>
        );
      break;
    }
    case "COLUMN_MEANING": {
      const column = question.column ?? "";
      if (candidate !== null) {
        body = (
          <>
            {heading(COPY.COLUMN_MEANING.confirm(column, fieldName(candidate)))}
            {question.origin === "ASSISTANT" ? (
              <p className="struttura-flow__note">{COPY.DOMAIN.suggested}</p>
            ) : null}
            <div className="struttura-question__choices">
              <StrutturaButton
                variant="primary"
                onClick={() => void flow.answer({ column_fields: { [column]: candidate } })}
              >
                {COPY.yes}
              </StrutturaButton>
              <StrutturaButton variant="outline" onClick={flow.matchByHand}>
                {COPY.COLUMN_MEANING.notThis}
              </StrutturaButton>
            </div>
          </>
        );
      } else {
        body = (
          <>
            {heading(COPY.COLUMN_MEANING.choose(column))}
            <div className="struttura-question__choices">
              {question.choices.map((choice) => (
                <StrutturaButton
                  key={choice.value}
                  variant="outline"
                  onClick={() => void flow.answer({ column_fields: { [column]: choice.value } })}
                >
                  {fieldName(choice.value)}
                </StrutturaButton>
              ))}
            </div>
          </>
        );
      }
      break;
    }
    case "GRID_HOURS":
      body = (
        <>
          {heading(COPY.GRID_HOURS.title)}
          <div className="struttura-question__choices">
            {question.choices.map((choice) => (
              <StrutturaButton
                key={choice.value}
                variant="outline"
                onClick={() =>
                  void flow.answer({ grid_hours: choice.value as UnderstandAnswers["grid_hours"] })
                }
              >
                {fieldName(choice.value)}
              </StrutturaButton>
            ))}
          </div>
        </>
      );
      break;
    case "PERIOD":
      body = (
        <>
          {heading(COPY.PERIOD.title)}
          <label className="struttura-question__date">
            <span>{COPY.PERIOD.label}</span>
            <input
              type="date"
              value={week}
              onChange={(event) => setWeek(event.target.value)}
              aria-describedby="struttura-question-help"
            />
          </label>
          <p className="struttura-flow__note" id="struttura-question-help">
            {COPY.PERIOD.help}
          </p>
          <div className="struttura-question__choices">
            <StrutturaButton
              variant="primary"
              disabled={week === ""}
              onClick={() => void flow.answer({ period_start: week })}
            >
              {COPY.PERIOD.confirm}
            </StrutturaButton>
          </div>
        </>
      );
      break;
    case "AMOUNT_BASIS":
      body = (
        <>
          {heading(COPY.AMOUNT_BASIS.title(question.column ?? ""))}
          <p className="struttura-flow__note">{COPY.AMOUNT_BASIS.why}</p>
          <div className="struttura-question__choices">
            <StrutturaButton variant="primary" onClick={() => void flow.answer({ amount_basis: "NET" })}>
              {COPY.AMOUNT_BASIS.net}
            </StrutturaButton>
            <StrutturaButton variant="outline" onClick={() => void flow.answer({ amount_basis: "GROSS" })}>
              {COPY.AMOUNT_BASIS.gross}
            </StrutturaButton>
          </div>
        </>
      );
      break;
    case "DATE_ORDER":
      body = (
        <>
          {heading(COPY.DATE_ORDER.title)}
          {question.column !== null ? (
            <p className="struttura-flow__note">{sourcesCopy.match.formatColumns(question.column)}</p>
          ) : null}
          <div className="struttura-question__choices struttura-question__choices--stacked">
            {(["DMY", "MDY"] as const).map((order) => (
              <StrutturaButton
                key={order}
                variant="outline"
                onClick={() => void flow.answer({ date_order: order })}
              >
                {sourcesCopy.match.dateOptions[order]}
              </StrutturaButton>
            ))}
          </div>
        </>
      );
      break;
    case "DATES_REVERSED":
      body = (
        <>
          {heading(COPY.DATES_REVERSED.title(question.column ?? "", question.choices[0]?.value ?? ""))}
          <p className="struttura-flow__note">{COPY.DATES_REVERSED.why}</p>
          <div className="struttura-question__choices">
            <StrutturaButton variant="primary" onClick={flow.matchByHand}>
              {COPY.DATES_REVERSED.check}
            </StrutturaButton>
          </div>
        </>
      );
      break;
    case "DECIMAL_STYLE":
      body = (
        <>
          {heading(COPY.DECIMAL_STYLE.title)}
          {question.column !== null ? (
            <p className="struttura-flow__note">{sourcesCopy.match.formatColumns(question.column)}</p>
          ) : null}
          <div className="struttura-question__choices struttura-question__choices--stacked">
            {(["COMMA", "POINT"] as const).map((style) => (
              <StrutturaButton
                key={style}
                variant="outline"
                onClick={() => void flow.answer({ decimal_style: style })}
              >
                {sourcesCopy.match.numberOptions[style]}
              </StrutturaButton>
            ))}
          </div>
        </>
      );
      break;
  }

  return (
    <>
      <p className="struttura-flow__file">{FLOW.chosen(step.file.name)}</p>
      <section className="struttura-question" aria-labelledby="struttura-question-title">
        <p className="struttura-question__progress">{COPY.progress}</p>
        {body}
      </section>
      <div className="struttura-flow__actions">
        <StrutturaButton variant="soft" onClick={flow.reset}>
          {COPY.back}
        </StrutturaButton>
      </div>
    </>
  );
}
