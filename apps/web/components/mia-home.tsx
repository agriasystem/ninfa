"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { askMiaHome } from "@/lib/api/ask-ninfa";
import { miaHomeCopy } from "@/lib/ask-ninfa/copy";
import { MAX_QUESTION_LENGTH, stateFromResponse, type AskState } from "@/lib/ask-ninfa/state";

import {
  ArrowUpIcon,
  DatabaseIcon,
  ListIcon,
  SearchIcon,
  SpinnerIcon,
  TrendIcon,
} from "./icons";
import { NinfaLogo } from "./ninfa-logo";

const SUGGESTION_ICONS = [SearchIcon, ListIcon, TrendIcon, DatabaseIcon] as const;

export interface MiaHomeProps {
  propertyId: string;
  /** The property-local business date (`YYYY-MM-DD`) of the feed on screen - sent verbatim to the
   * backend, so Mia explains the SAME analysis the user is looking at. */
  asOfLocalDate: string;
  /** Called whenever the input holds REAL (non-whitespace) text - typed, pasted or filled from a
   * suggestion - and when a question is sent. NEVER on focus alone. The caller makes it idempotent
   * (the logo transition runs once). */
  onFirstInput: () => void;
}

/**
 * "Chiedi a Mia..." on the Home: the suggested questions, the exchange and the dark input bar.
 *
 * SEND EXPERIENCE (like a modern assistant): pressing Enter or the arrow acquires the text as the
 * submitted question, EMPTIES the input immediately, shows the question above the bar as the user's
 * own message and, under it, Mia's reply (a discreet "Mia sta elaborando…" while the request runs).
 * The message never stays in the bar.
 *
 * STILL NOT A CHAT: the endpoint is stateless per question, so the Home shows exactly ONE exchange
 * (the submitted question + Mia's answer); sending a new question REPLACES it - there is no
 * history, because the model is never given one (a list of past messages would be a false
 * affordance). Nothing is persisted. Exactly one request may be in flight (guarded synchronously,
 * not just through state); a retry re-sends the SAME submitted question as a fresh, explicit call.
 *
 * Suggested questions only ever FILL the input - the user confirms with Enter / the arrow. The
 * input is a single-line `<input>`: Enter sends (there is no multi-line mode, so Shift+Enter sends
 * too). The input is NEVER disabled while Mia answers - focus must not be taken away from the user -
 * only sending is blocked until the request ends (the arrow turns into a spinner), and a draft of
 * the next question can already be typed. There is no microphone: no voice feature exists.
 *
 * ENGINE CALCULATES, MIA EXPLAINS: this component sends the question and the business date and renders
 * the answer; the context Mia answers from is built server-side, only from what the Decision Engine
 * already decided for that property and date.
 */
export function MiaHome({ propertyId, asOfLocalDate, onFirstInput }: MiaHomeProps) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [exchangeId, setExchangeId] = useState(0);
  const [state, setState] = useState<AskState>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const inFlightRef = useRef(false);
  const inputId = useId();

  const submitting = state.kind === "loading";
  const hasText = question.trim().length > 0;
  const canSubmit = !submitting && hasText;

  function changeQuestion(value: string) {
    setQuestion(value);
    if (value.trim().length > 0) onFirstInput();
  }

  /** `fromInput`: a NEW question typed in the bar (the bar is emptied and a fresh exchange begins).
   * Not for a retry, which re-sends the already-submitted question and leaves any draft untouched. */
  async function send(text: string, fromInput: boolean) {
    if (inFlightRef.current) return; // blocks a double submit synchronously (Enter + click, key repeat)
    const trimmed = text.trim();
    if (trimmed.length === 0) return;
    inFlightRef.current = true;

    onFirstInput();
    if (fromInput) {
      setQuestion("");
      setExchangeId((id) => id + 1);
    }
    setAsked(trimmed);
    setState({ kind: "loading" });
    try {
      const result = await askMiaHome(propertyId, asOfLocalDate, trimmed);
      setState(result.ok ? stateFromResponse(result.data) : { kind: "error" });
    } finally {
      inFlightRef.current = false;
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(question, true);
    // The user stays in the field they were typing in - also when the arrow (a button that is about
    // to turn into a spinner) was what they pressed - so the keyboard is never lost after sending.
    inputRef.current?.focus();
  }

  function pickSuggestedQuestion(text: string) {
    changeQuestion(text);
    inputRef.current?.focus();
  }

  return (
    <div
      className="mia"
      data-answering={state.kind !== "idle" ? "true" : "false"}
      data-has-text={hasText ? "true" : "false"}
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

        {asked !== null ? (
          <MiaExchange
            key={exchangeId}
            asked={asked}
            state={state}
            onRetry={() => {
              void send(asked, false);
              inputRef.current?.focus();
            }}
          />
        ) : null}

        <form
          className="mia__form"
          aria-label={miaHomeCopy.formLabel}
          aria-busy={submitting}
          data-busy={submitting ? "true" : "false"}
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
            onChange={(event) => changeQuestion(event.target.value)}
          />
          {hasText || submitting ? (
            <button
              type="submit"
              className="mia__send"
              aria-label={submitting ? miaHomeCopy.submitting : miaHomeCopy.submit}
              disabled={!canSubmit}
              // A mouse/touch press must not pull focus (and the on-screen keyboard) out of the input.
              onMouseDown={(event) => event.preventDefault()}
            >
              {submitting ? <SpinnerIcon className="mia__send-spinner" /> : <ArrowUpIcon />}
            </button>
          ) : null}
        </form>
      </div>
    </div>
  );
}

/**
 * The single, current exchange: the user's own message (right-aligned, softly tinted - clearly "mine",
 * never a boxed form summary) and, under it, Mia's reply (open text under her name, no card). The
 * reply region is the polite live region: loading and the answer are announced, the question and the
 * rest of the Home are not read again. It is keyed by the exchange so a NEW question enters afresh.
 */
function MiaExchange({
  asked,
  state,
  onRetry,
}: {
  asked: string;
  state: AskState;
  onRetry: () => void;
}) {
  return (
    <div className="mia__exchange">
      <p className="mia__user-message">
        <span className="visually-hidden">{miaHomeCopy.askedPrefix} </span>
        {asked}
      </p>

      <section
        className="mia__reply"
        aria-live="polite"
        aria-atomic="false"
        aria-busy={state.kind === "loading"}
      >
        <div className="mia__reply-header">
          <NinfaLogo className="mia__reply-logo" />
          <h2 className="mia__reply-name">{miaHomeCopy.assistantName}</h2>
        </div>
        <div className="mia__reply-body" key={state.kind}>
          <MiaReplyBody state={state} onRetry={onRetry} />
        </div>
      </section>
    </div>
  );
}

function MiaReplyBody({ state, onRetry }: { state: AskState; onRetry: () => void }) {
  switch (state.kind) {
    case "idle":
      return null;

    case "loading":
      return (
        <p className="mia__thinking" role="status">
          <span>{miaHomeCopy.submitting}</span>
          <span className="mia__thinking-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </p>
      );

    case "answered":
      return (
        <>
          <p className="mia__reply-text">{state.answer}</p>
          <Limitations items={state.limitations} />
        </>
      );

    case "insufficientContext":
      return (
        <>
          <p className="mia__reply-lead">{miaHomeCopy.insufficientContextHeading}</p>
          {state.answer !== null && state.answer.length > 0 ? (
            <p className="mia__reply-text">{state.answer}</p>
          ) : null}
          <p className="mia__note">{miaHomeCopy.insufficientContextSupporting}</p>
          <Limitations items={state.limitations} />
        </>
      );

    case "refused":
      return (
        <p className="mia__reply-text" role="status">
          {miaHomeCopy.refused}
        </p>
      );

    case "unavailable":
      return (
        <div role="alert">
          <p className="mia__reply-lead">{miaHomeCopy.unavailableHeading}</p>
          <p className="mia__note">{miaHomeCopy.unavailableSupporting}</p>
          <button type="button" className="mia__retry" onClick={onRetry}>
            {miaHomeCopy.retry}
          </button>
        </div>
      );

    case "error":
      return (
        <div role="alert">
          <p className="mia__reply-lead">{miaHomeCopy.networkError}</p>
          <button type="button" className="mia__retry" onClick={onRetry}>
            {miaHomeCopy.retry}
          </button>
        </div>
      );
  }
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
