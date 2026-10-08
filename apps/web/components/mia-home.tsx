"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import type { AskHomeHistoryMessage } from "@ninfa/contracts";

import { askMiaHome } from "@/lib/api/ask-ninfa";
import { miaHomeCopy } from "@/lib/ask-ninfa/copy";
import { historyOf, retainRecent, type Exchange } from "@/lib/ask-ninfa/conversation";
import { answerBlocksOf } from "@/lib/ask-ninfa/format-answer";
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

/** The composer grows with the text up to this many lines, then scrolls inside itself. */
const MAX_COMPOSER_LINES = 4;
/** Used when the browser reports no usable computed line height (`normal`, or jsdom). */
const FALLBACK_LINE_HEIGHT_PX = 24;

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
 * "Chiedi a Mia..." on the Home: the suggested questions, a short conversation and the dark composer.
 *
 * SEND EXPERIENCE (like a modern assistant): Enter (or the arrow) acquires the text as the submitted
 * question, EMPTIES the composer immediately, shows the question above the bar as the user's own
 * message and, under it, Mia's reply (a discreet "Mia sta elaborando…" while the request runs).
 *
 * A SMALL CONVERSATION, not a chat page (Mia V2): the newest few exchanges of this page session stay
 * visible in a bounded area above the bar (it scrolls inside itself, so the operational Home is never
 * pushed away) and are sent back with each new question as `history`, so a follow-up such as
 * "Perché?" can be understood. The history is referential context only - the backend rebuilds every
 * fact fresh for each question. Nothing is persisted: it is lost on reload (or "Nuova conversazione").
 * Exactly one request may be in flight (guarded synchronously, not just through state); a retry
 * re-sends the SAME submitted question with the history it originally had.
 *
 * Suggested questions only ever FILL the composer - the user confirms with Enter / the arrow. The
 * composer is an auto-growing `<textarea>` (1 to 4 lines, then it scrolls): Enter sends, Shift+Enter
 * inserts a new line (and Enter during IME composition never sends). It is NEVER disabled while Mia
 * answers - focus must not be taken away from the user - only sending is blocked until the request
 * ends (the arrow turns into a spinner), and a draft of the next question can already be typed.
 * There is no microphone: no voice feature exists.
 *
 * ENGINE CALCULATES, MIA EXPLAINS: this component sends the question, the business date and the short
 * history, and renders the answer; the facts Mia answers from are built server-side, only from what
 * NINFA already decided or calculated for that property and date.
 */
export function MiaHome({ propertyId, asOfLocalDate, onFirstInput }: MiaHomeProps) {
  const [question, setQuestion] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inFlightRef = useRef(false);
  const tokenRef = useRef(0);
  const exchangesRef = useRef<Exchange[]>([]);
  const nextIdRef = useRef(0);
  const inputId = useId();

  const latest = exchanges[exchanges.length - 1];
  const submitting = latest?.state.kind === "loading";
  const hasText = question.trim().length > 0;
  const canSubmit = !submitting && hasText;

  function commit(next: Exchange[]) {
    exchangesRef.current = next;
    setExchanges(next);
  }

  // A different property or business date is a different analysis: the conversation does not carry
  // over (and a late answer of the old one is ignored - see `settle`).
  const scopeRef = useRef(`${propertyId}|${asOfLocalDate}`);
  useEffect(() => {
    const scope = `${propertyId}|${asOfLocalDate}`;
    if (scopeRef.current === scope) return;
    scopeRef.current = scope;
    // The old analysis' request (if any) can no longer block, nor land on, the new conversation.
    tokenRef.current += 1;
    inFlightRef.current = false;
    commit([]);
  }, [propertyId, asOfLocalDate]);

  // The composer grows with its content (1-4 lines), and shrinks back when it is emptied.
  useLayoutEffect(() => {
    const element = inputRef.current;
    if (element !== null) autosize(element);
  }, [question]);

  // The newest exchange starts at the top of the bounded area: its question is visible, and a long
  // answer is read from its beginning rather than from its end.
  const latestKey = latest === undefined ? "" : `${latest.id}:${latest.state.kind}`;
  useEffect(() => {
    const area = scrollRef.current;
    const last = area?.lastElementChild;
    if (area && last instanceof HTMLElement) area.scrollTop = last.offsetTop;
  }, [latestKey]);

  function changeQuestion(value: string) {
    setQuestion(value);
    if (value.trim().length > 0) onFirstInput();
  }

  /** Sets the state of exchange `id`, unless it is gone (reset, or pushed out of the newest few). */
  function settle(id: number, state: AskState, scope: string) {
    if (scope !== scopeRef.current) return;
    commit(
      exchangesRef.current.map((exchange) => (exchange.id === id ? { ...exchange, state } : exchange)),
    );
  }

  /** `retryOf`: the id of an exchange whose question is re-sent as it was (same history, any draft in
   * the composer untouched). Otherwise `text` is a NEW question typed in the composer: it is emptied
   * and a fresh exchange begins. */
  async function send(text: string, retryOf?: number) {
    if (inFlightRef.current) return; // blocks a double submit synchronously (Enter + click, key repeat)
    const trimmed = text.trim();
    if (trimmed.length === 0) return;
    inFlightRef.current = true;
    const token = ++tokenRef.current;
    onFirstInput();

    const scope = scopeRef.current;
    let id: number;
    let history: AskHomeHistoryMessage[];
    if (retryOf === undefined) {
      id = nextIdRef.current++;
      const fresh: Exchange = { id, question: trimmed, state: { kind: "loading" } };
      const retained = retainRecent([...exchangesRef.current, fresh]);
      // What the model is told is exactly what is on screen BEFORE this question.
      history = historyOf(retained.slice(0, -1));
      commit(retained);
      setQuestion("");
    } else {
      id = retryOf;
      const position = exchangesRef.current.findIndex((exchange) => exchange.id === id);
      history = historyOf(exchangesRef.current.slice(0, Math.max(position, 0)));
      settle(id, { kind: "loading" }, scope);
    }

    try {
      const result = await askMiaHome(propertyId, asOfLocalDate, trimmed, history);
      settle(id, result.ok ? stateFromResponse(result.data) : { kind: "error" }, scope);
    } finally {
      if (tokenRef.current === token) inFlightRef.current = false;
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(question);
    // The user stays in the field they were typing in - also when the arrow (a button that is about
    // to turn into a spinner) was what they pressed - so the keyboard is never lost after sending.
    inputRef.current?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a new line. Enter while composing (IME) belongs to the composition.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void send(question);
  }

  function pickSuggestedQuestion(text: string) {
    changeQuestion(text);
    inputRef.current?.focus();
  }

  function startOver() {
    if (inFlightRef.current) return;
    commit([]);
    inputRef.current?.focus();
  }

  return (
    <div
      className="mia"
      data-answering={exchanges.length > 0 ? "true" : "false"}
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

        {exchanges.length > 0 ? (
          <section className="mia__conversation" aria-label={miaHomeCopy.conversationLabel}>
            <div className="mia__conversation-tools">
              <button
                type="button"
                className="mia__reset"
                disabled={submitting}
                onClick={startOver}
              >
                {miaHomeCopy.newConversation}
              </button>
            </div>
            <div className="mia__conversation-scroll" ref={scrollRef}>
              {exchanges.map((exchange, index) => (
                <MiaExchange
                  key={exchange.id}
                  asked={exchange.question}
                  state={exchange.state}
                  isLatest={index === exchanges.length - 1}
                  onRetry={() => {
                    void send(exchange.question, exchange.id);
                    inputRef.current?.focus();
                  }}
                />
              ))}
            </div>
          </section>
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
          <textarea
            id={inputId}
            ref={inputRef}
            rows={1}
            className="mia__input"
            placeholder={miaHomeCopy.placeholder}
            value={question}
            maxLength={MAX_QUESTION_LENGTH}
            autoComplete="off"
            enterKeyHint="send"
            onChange={(event) => changeQuestion(event.target.value)}
            onKeyDown={handleKeyDown}
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

/** Grows the composer to its content, capped at `MAX_COMPOSER_LINES` lines (then it scrolls). */
function autosize(element: HTMLTextAreaElement) {
  const style = window.getComputedStyle(element);
  const lineHeight = Number.parseFloat(style.lineHeight) || FALLBACK_LINE_HEIGHT_PX;
  const padding =
    (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0);
  const maxHeight = lineHeight * MAX_COMPOSER_LINES + padding;
  element.style.height = "auto";
  const contentHeight = element.scrollHeight;
  element.style.height = `${Math.min(contentHeight, maxHeight)}px`;
  element.style.overflowY = contentHeight > maxHeight ? "auto" : "hidden";
}

/**
 * One exchange: the user's own message (right-aligned, softly tinted - clearly "mine", never a boxed
 * form summary) and, under it, Mia's reply (open text under her name, no card). Only the NEWEST
 * exchange's reply is the polite live region: loading and the answer are announced, older replies
 * and the rest of the Home are not read again.
 */
function MiaExchange({
  asked,
  state,
  isLatest,
  onRetry,
}: {
  asked: string;
  state: AskState;
  isLatest: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="mia__exchange" data-latest={isLatest ? "true" : "false"}>
      <p className="mia__user-message">
        <span className="visually-hidden">{miaHomeCopy.askedPrefix} </span>
        {asked}
      </p>

      <section
        className="mia__reply"
        aria-live={isLatest ? "polite" : undefined}
        aria-atomic={isLatest ? "false" : undefined}
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
          <AnswerText text={state.answer} />
          <Limitations items={state.limitations} />
        </>
      );

    case "insufficientContext": {
      // Mia's own explanation of what she cannot say IS the answer: it stands alone, with her
      // specific limits underneath. The generic "non ha abbastanza informazioni" lead and its
      // "riformula la domanda" hint are only the fallback for a reply that carries no text - they
      // are never put around a concrete explanation (that would be a generic disclaimer wrapped
      // around the real answer).
      if (state.answer !== null && state.answer.trim().length > 0) {
        return (
          <>
            <AnswerText text={state.answer} />
            <Limitations items={state.limitations} />
          </>
        );
      }
      return (
        <>
          <p className="mia__reply-lead">{miaHomeCopy.insufficientContextHeading}</p>
          <p className="mia__note">{miaHomeCopy.insufficientContextSupporting}</p>
          <Limitations items={state.limitations} />
        </>
      );
    }

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

/** Mia's answer as short paragraphs and, when she lists several decisions, a real list. Plain text
 * with line structure only - see `answerBlocksOf` (nothing is interpreted as Markdown or HTML). */
function AnswerText({ text }: { text: string }) {
  return (
    <>
      {answerBlocksOf(text).map((block, index) =>
        block.kind === "paragraph" ? (
          <p className="mia__reply-text" key={index}>
            {block.text}
          </p>
        ) : (
          <ul className="mia__reply-list" key={index}>
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>{item}</li>
            ))}
          </ul>
        ),
      )}
    </>
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
