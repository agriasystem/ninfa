"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import type { AskResponse } from "@ninfa/contracts";

import { askNinfa } from "@/lib/api/ask-ninfa";
import { askNinfaCopy } from "@/lib/ask-ninfa/copy";

type AskState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "answered"; answer: string; limitations: string[] }
  | { kind: "insufficientContext"; answer: string | null; limitations: string[] }
  | { kind: "unavailable" }
  | { kind: "refused" }
  | { kind: "error" };

/** Maps the backend's own closed `AskStatus` (Gate 18) onto this panel's UI state - an exhaustive
 * `switch`, so a future fifth status value fails to compile here rather than silently falling
 * through to nothing. */
function stateFromResponse(data: AskResponse): AskState {
  switch (data.status) {
    case "ANSWERED":
      return { kind: "answered", answer: data.answer ?? "", limitations: data.limitations };
    case "INSUFFICIENT_CONTEXT":
      return { kind: "insufficientContext", answer: data.answer, limitations: data.limitations };
    case "UNAVAILABLE":
      return { kind: "unavailable" };
    case "REFUSED":
      return { kind: "refused" };
  }
}

export interface AskNinfaPanelProps {
  propertyId: string;
  decisionId: string;
}

/**
 * "Chiedi a NINFA" (Gate 20): a single, additive Decision Detail section, always rendered AFTER
 * the recommendation and BEFORE Evoluzione. Deliberately NOT a chat: one question in, one answer
 * surface out, no message list, no thread, no history, no persistence anywhere (refreshing the
 * page returns this to `idle` - that is correct, not a bug, for V1). Exactly one request may be
 * in flight at a time; a retry after `unavailable`/`error` is always a fresh, explicit,
 * user-triggered call, never automatic.
 */
export function AskNinfaPanel({ propertyId, decisionId }: AskNinfaPanelProps) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ kind: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);
  const questionInputId = useId();

  const submitting = state.kind === "loading";
  const canSubmit = !submitting && question.trim().length > 0;

  async function submit() {
    if (submitting) return; // blocks a double submit (e.g. Enter + click mid-flight)
    const trimmed = question.trim();
    if (trimmed.length === 0) return;

    setState({ kind: "loading" });
    const result = await askNinfa(propertyId, decisionId, trimmed);

    if (result.ok) {
      setState(stateFromResponse(result.data));
    } else {
      setState({ kind: "error" });
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  function pickSuggestedQuestion(text: string) {
    setQuestion(text);
    inputRef.current?.focus();
  }

  return (
    <section className="ask-ninfa-panel">
      <h2 className="ask-ninfa-panel__heading">{askNinfaCopy.heading}</h2>
      <p className="ask-ninfa-panel__supporting">{askNinfaCopy.supportingText}</p>

      <div className="ask-ninfa-panel__suggested" aria-label={askNinfaCopy.suggestedQuestionsLabel}>
        {askNinfaCopy.suggestedQuestions.map((suggested) => (
          <button
            key={suggested}
            type="button"
            className="ask-ninfa-panel__chip"
            disabled={submitting}
            onClick={() => pickSuggestedQuestion(suggested)}
          >
            {suggested}
          </button>
        ))}
      </div>

      <form className="ask-ninfa-panel__form" onSubmit={handleSubmit} noValidate>
        <label className="ask-ninfa-panel__label" htmlFor={questionInputId}>
          {askNinfaCopy.questionLabel}
        </label>
        <div className="ask-ninfa-panel__row">
          <input
            id={questionInputId}
            ref={inputRef}
            type="text"
            placeholder={askNinfaCopy.placeholder}
            value={question}
            disabled={submitting}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" disabled={!canSubmit}>
            {submitting ? askNinfaCopy.submitting : askNinfaCopy.submit}
          </button>
        </div>
      </form>

      {submitting ? (
        <p className="ask-ninfa-panel__loading" role="status" aria-live="polite">
          {askNinfaCopy.submitting}
        </p>
      ) : null}

      {state.kind === "answered" ? (
        <div className="ask-ninfa-panel__answer" role="status" aria-live="polite">
          <h3>{askNinfaCopy.answerHeading}</h3>
          <p>{state.answer}</p>
          {state.limitations.length > 0 ? (
            <div className="ask-ninfa-panel__limitations">
              <h4>{askNinfaCopy.limitationsHeading}</h4>
              <ul>
                {state.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {state.kind === "insufficientContext" ? (
        <div className="ask-ninfa-panel__insufficient" role="status" aria-live="polite">
          <p>{askNinfaCopy.insufficientContextHeading}</p>
          {state.answer !== null && state.answer.length > 0 ? <p>{state.answer}</p> : null}
          <p className="ask-ninfa-panel__supporting">{askNinfaCopy.insufficientContextSupporting}</p>
          {state.limitations.length > 0 ? (
            <div className="ask-ninfa-panel__limitations">
              <h4>{askNinfaCopy.limitationsHeading}</h4>
              <ul>
                {state.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {state.kind === "refused" ? (
        <p className="ask-ninfa-panel__refused" role="status">
          {askNinfaCopy.refused}
        </p>
      ) : null}

      {state.kind === "unavailable" ? (
        <div className="ask-ninfa-panel__unavailable" role="alert">
          <p>{askNinfaCopy.unavailableHeading}</p>
          <p className="ask-ninfa-panel__supporting">{askNinfaCopy.unavailableSupporting}</p>
          <button type="button" onClick={() => void submit()}>
            {askNinfaCopy.retry}
          </button>
        </div>
      ) : null}

      {state.kind === "error" ? (
        <div className="ask-ninfa-panel__error" role="alert">
          <p>{askNinfaCopy.networkError}</p>
          <button type="button" onClick={() => void submit()}>
            {askNinfaCopy.retry}
          </button>
        </div>
      ) : null}
    </section>
  );
}
