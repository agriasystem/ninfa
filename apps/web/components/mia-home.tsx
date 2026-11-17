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

import { miaHomeCopy } from "@/lib/ask-ninfa/copy";
import { MAX_QUESTION_LENGTH } from "@/lib/ask-ninfa/state";
import { useMiaUiContextReader } from "@/lib/mia/ui-context";
import { useMiaConversation } from "@/lib/mia/use-mia-conversation";

import {
  ArrowUpIcon,
  DatabaseIcon,
  ListIcon,
  SearchIcon,
  SpinnerIcon,
  TrendIcon,
} from "./icons";
import { MiaExchangeView } from "./mia-exchange";

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
 * "Chiedi a Mia..." on the Home: the suggested questions, the conversation and the dark composer.
 *
 * SEND EXPERIENCE (like a modern assistant): Enter (or the arrow) acquires the text as the submitted
 * question, EMPTIES the composer immediately, shows the question above the bar as the user's own
 * message and, under it, Mia's reply (a discreet "Mia sta analizzando…" while the request runs).
 *
 * A CONVERSATION, not a chat page: the newest few exchanges stay visible in a bounded area above the
 * bar (it scrolls inside itself, so the operational Home is never pushed away). The conversation
 * itself is the SERVER's (`useMiaConversation`): it comes back after a refresh or a navigation, a
 * follow-up such as "Perché?" is understood from what the server holds, and the browser never sends a
 * history - only the message, the business date, the conversation id and a small hint about the screen
 * (`ui_context`, published by the screens). Exactly one request may be in flight (guarded
 * synchronously); a retry re-sends the SAME message.
 *
 * Suggested questions only ever FILL the composer - the user confirms with Enter / the arrow. The
 * composer is an auto-growing `<textarea>` (1 to 4 lines, then it scrolls): Enter sends, Shift+Enter
 * inserts a new line (and Enter during IME composition never sends). It is NEVER disabled while Mia
 * answers - focus must not be taken away from the user - only sending is blocked until the request
 * ends (the arrow turns into a spinner), and a draft of the next question can already be typed.
 * There is no microphone: no voice feature exists. There is no streaming either: the backend checks
 * the whole answer before it leaves, so the reply appears once, complete.
 *
 * ENGINE CALCULATES, MIA EXPLAINS: this component sends the message and renders the answer; every
 * fact Mia answers from is read server-side, from what NINFA already decided or calculated.
 */
export function MiaHome({ propertyId, asOfLocalDate, onFirstInput }: MiaHomeProps) {
  const [question, setQuestion] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputId = useId();

  const getUiContext = useMiaUiContextReader();
  const conversation = useMiaConversation({ propertyId, asOfLocalDate, getUiContext });
  const { exchanges } = conversation;

  const latest = exchanges[exchanges.length - 1];
  const submitting = conversation.status === "sending";
  const hasText = question.trim().length > 0;
  const canSubmit = !submitting && hasText;

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

  /** A NEW question typed in the composer: it is emptied only if it was really sent. */
  function send(text: string) {
    if (conversation.send(text)) {
      onFirstInput();
      setQuestion("");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send(question);
    // The user stays in the field they were typing in - also when the arrow (a button that is about
    // to turn into a spinner) was what they pressed - so the keyboard is never lost after sending.
    inputRef.current?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a new line. Enter while composing (IME) belongs to the composition.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send(question);
  }

  function pickSuggestedQuestion(text: string) {
    changeQuestion(text);
    inputRef.current?.focus();
  }

  function startOver() {
    if (conversation.startNew()) inputRef.current?.focus();
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
                <MiaExchangeView
                  key={exchange.id}
                  asked={exchange.question}
                  state={exchange.state}
                  isLatest={index === exchanges.length - 1}
                  onRetry={() => {
                    conversation.retry(exchange.id);
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
