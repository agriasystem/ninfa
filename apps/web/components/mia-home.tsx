"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { askMiaHome } from "@/lib/api/ask-ninfa";
import { miaHomeCopy } from "@/lib/ask-ninfa/copy";
import { MAX_QUESTION_LENGTH, stateFromResponse, type AskState } from "@/lib/ask-ninfa/state";

import { ArrowUpIcon, DatabaseIcon, ListIcon, SearchIcon, TrendIcon } from "./icons";

const SUGGESTION_ICONS = [SearchIcon, ListIcon, TrendIcon, DatabaseIcon] as const;

export interface MiaHomeProps {
  propertyId: string;
  /** The property-local business date (`YYYY-MM-DD`) of the feed on screen - sent verbatim to the
   * backend, so Mia explains the SAME analysis the user is looking at. */
  asOfLocalDate: string;
  /** Called whenever the input holds REAL (non-whitespace) text - typed, pasted or filled from a
   * suggestion. NEVER on focus alone. The caller makes it idempotent (the logo transition runs once). */
  onFirstInput: () => void;
}

/**
 * "Chiedi a Mia..." on the Home (Home UI V1): the suggested questions, the answer surface and the
 * dark input bar. Deliberately NOT a chat: ONE question in, ONE answer surface out (a new question
 * REPLACES the previous answer - there is no message list, no bubbles, no history, nothing
 * persisted); exactly one request in flight at a time; a retry after `unavailable`/`error` is
 * always a fresh, explicit, user-triggered call.
 *
 * Suggested questions only ever FILL the input (the user confirms with Enter / the send button,
 * exactly like the Decision Detail's own chips) - they never submit. There is no microphone: no
 * voice feature exists, and a control that does nothing is never drawn.
 *
 * ENGINE CALCULATES, MIA EXPLAINS: this component sends the question and the business date, and
 * renders the answer; the context Mia answers from is built server-side, only from what the
 * Decision Engine already decided for that property and date.
 */
export function MiaHome({ propertyId, asOfLocalDate, onFirstInput }: MiaHomeProps) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [state, setState] = useState<AskState>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  const submitting = state.kind === "loading";
  const canSubmit = !submitting && question.trim().length > 0;

  function changeQuestion(value: string) {
    setQuestion(value);
    if (value.trim().length > 0) onFirstInput();
  }

  async function submit(text: string) {
    if (submitting) return; // blocks a double submit (e.g. Enter + click mid-flight)
    const trimmed = text.trim();
    if (trimmed.length === 0) return;

    onFirstInput();
    setAsked(trimmed);
    setState({ kind: "loading" });
    const result = await askMiaHome(propertyId, asOfLocalDate, trimmed);
    setState(result.ok ? stateFromResponse(result.data) : { kind: "error" });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(question);
  }

  function pickSuggestedQuestion(text: string) {
    changeQuestion(text);
    inputRef.current?.focus();
  }

  return (
    <div
      className="mia"
      data-answering={state.kind !== "idle" ? "true" : "false"}
      data-has-text={question.trim().length > 0 ? "true" : "false"}
    >
      <div className="mia__dock">
        <div className="mia__suggest">
          <p className="mia__caption">{miaHomeCopy.captionSuggestions}</p>
          <ul className="mia__suggestions" aria-label={miaHomeCopy.suggestedQuestionsLabel}>
            {miaHomeCopy.suggestedQuestions.map((suggested, index) => {
              const SuggestionIcon = SUGGESTION_ICONS[index] ?? SearchIcon;
              return (
                <li key={suggested}>
                  <button
                    type="button"
                    className="mia__chip"
                    disabled={submitting}
                    onClick={() => pickSuggestedQuestion(suggested)}
                  >
                    <SuggestionIcon className="mia__chip-icon" />
                    <span>{suggested}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <MiaAnswer state={state} asked={asked} onRetry={() => void submit(asked ?? "")} />

        <form
          className="mia__form"
          aria-label={miaHomeCopy.formLabel}
          onSubmit={handleSubmit}
          noValidate
        >
          <label className="visually-hidden" htmlFor={inputId}>
            {miaHomeCopy.inputLabel}
          </label>
          <SearchIcon className="mia__form-icon" />
          <input
            id={inputId}
            ref={inputRef}
            type="text"
            className="mia__input"
            placeholder={miaHomeCopy.placeholder}
            value={question}
            maxLength={MAX_QUESTION_LENGTH}
            autoComplete="off"
            enterKeyHint="send"
            disabled={submitting}
            onChange={(event) => changeQuestion(event.target.value)}
          />
          {question.trim().length > 0 ? (
            <button
              type="submit"
              className="mia__send"
              aria-label={miaHomeCopy.submit}
              disabled={!canSubmit}
            >
              <ArrowUpIcon />
            </button>
          ) : null}
        </form>
      </div>
    </div>
  );
}

function MiaAnswer({
  state,
  asked,
  onRetry,
}: {
  state: AskState;
  asked: string | null;
  onRetry: () => void;
}) {
  if (state.kind === "idle") return null;

  return (
    <div className="mia__answer" aria-live="polite" aria-atomic="false">
      {asked !== null ? (
        <p className="mia__asked">
          <span className="mia__asked-label">{miaHomeCopy.yourQuestion}</span>
          <span className="mia__asked-text">{asked}</span>
        </p>
      ) : null}

      {state.kind === "loading" ? (
        <p className="mia__loading" role="status">
          {miaHomeCopy.submitting}
        </p>
      ) : null}

      {state.kind === "answered" ? (
        <div className="mia__result">
          <h2 className="mia__answer-heading">{miaHomeCopy.answerHeading}</h2>
          <p className="mia__answer-text">{state.answer}</p>
          <Limitations items={state.limitations} />
        </div>
      ) : null}

      {state.kind === "insufficientContext" ? (
        <div className="mia__result">
          <p className="mia__answer-heading">{miaHomeCopy.insufficientContextHeading}</p>
          {state.answer !== null && state.answer.length > 0 ? (
            <p className="mia__answer-text">{state.answer}</p>
          ) : null}
          <p className="mia__note">{miaHomeCopy.insufficientContextSupporting}</p>
          <Limitations items={state.limitations} />
        </div>
      ) : null}

      {state.kind === "refused" ? (
        <p className="mia__note" role="status">
          {miaHomeCopy.refused}
        </p>
      ) : null}

      {state.kind === "unavailable" ? (
        <div className="mia__result" role="alert">
          <p className="mia__answer-heading">{miaHomeCopy.unavailableHeading}</p>
          <p className="mia__note">{miaHomeCopy.unavailableSupporting}</p>
          <button type="button" className="mia__retry" onClick={onRetry}>
            {miaHomeCopy.retry}
          </button>
        </div>
      ) : null}

      {state.kind === "error" ? (
        <div className="mia__result" role="alert">
          <p className="mia__answer-heading">{miaHomeCopy.networkError}</p>
          <button type="button" className="mia__retry" onClick={onRetry}>
            {miaHomeCopy.retry}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function Limitations({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mia__limitations">
      <h3>{miaHomeCopy.limitationsHeading}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
