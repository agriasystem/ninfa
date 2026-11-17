"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { miaHomeCopy, miaPanelCopy } from "@/lib/ask-ninfa/copy";
import { MAX_QUESTION_LENGTH } from "@/lib/ask-ninfa/state";
import { propertyLocalDate } from "@/lib/date/property-date";
import { useMiaUiContextReader } from "@/lib/mia/ui-context";
import { useMiaConversation } from "@/lib/mia/use-mia-conversation";

import { ArrowUpIcon, CloseIcon, SpinnerIcon } from "./icons";
import { MiaExchangeView } from "./mia-exchange";

export interface MiaLauncherProps {
  propertyId: string;
  /** The property's own IANA time zone: the business date Mia is asked about is its "today". */
  timeZone: string;
}

/**
 * Mia on every page but the Home (where she already is): a small launcher in the shell and, when it is
 * pressed, a side panel with the same conversation. Deliberately minimal - the full redesign comes with
 * the new design system - and deliberately the SAME conversation as the Home (`useMiaConversation`): it
 * comes back from the server, it carries the hint about the screen the person is on, and it never
 * sends a history.
 *
 * The panel is a NON-modal dialog: the page behind stays usable, focus moves to the composer when it
 * opens, Escape closes it, and focus goes back to the launcher. Closing it discards only what was drawn;
 * the conversation stays on the server and comes back when the panel is opened again.
 */
export function MiaLauncher({ propertyId, timeZone }: MiaLauncherProps) {
  const [open, setOpen] = useState(false);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const panelId = useId();

  // Back on the launcher when the panel closes (never on the first render).
  useEffect(() => {
    if (wasOpenRef.current && !open) launcherRef.current?.focus();
    wasOpenRef.current = open;
  }, [open]);

  return (
    <>
      <button
        type="button"
        ref={launcherRef}
        className="mia-launcher"
        aria-label={miaPanelCopy.launcherLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        {miaPanelCopy.launcher}
      </button>
      {open ? (
        <MiaPanel
          key={propertyId}
          id={panelId}
          propertyId={propertyId}
          timeZone={timeZone}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

function MiaPanel({
  id,
  propertyId,
  timeZone,
  onClose,
}: {
  id: string;
  propertyId: string;
  timeZone: string;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const inputId = useId();

  const getUiContext = useMiaUiContextReader();
  // No streaming in V1: the backend checks the whole answer (its figures, its length) before it leaves,
  // so there is nothing safe to show earlier - the reply appears once, complete.
  const conversation = useMiaConversation({
    propertyId,
    asOfLocalDate: propertyLocalDate(new Date(), timeZone),
    getUiContext,
  });
  const { exchanges } = conversation;
  const submitting = conversation.status === "sending";
  const hasText = question.trim().length > 0;

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // Focus goes to the composer when the panel opens; Escape closes it from anywhere on the page.
  useEffect(() => {
    inputRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.isComposing) onCloseRef.current();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  // The newest exchange starts at the top of the area, so a long answer is read from its beginning.
  const latest = exchanges[exchanges.length - 1];
  const latestKey = latest === undefined ? "" : `${latest.id}:${latest.state.kind}`;
  useEffect(() => {
    const area = scrollRef.current;
    const last = area?.lastElementChild;
    if (area && last instanceof HTMLElement) area.scrollTop = last.offsetTop;
  }, [latestKey]);

  function send() {
    if (conversation.send(question)) setQuestion("");
    inputRef.current?.focus();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send();
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a new line. Enter while composing (IME) belongs to the composition.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  }

  return (
    <div
      id={id}
      className="mia-panel"
      role="dialog"
      aria-modal="false"
      aria-label={miaPanelCopy.panelLabel}
    >
      <div className="mia-panel__header">
        <span className="mia-panel__title">{miaPanelCopy.title}</span>
        <div className="mia-panel__tools">
          {exchanges.length > 0 ? (
            <button
              type="button"
              className="mia__reset"
              disabled={submitting}
              onClick={() => {
                if (conversation.startNew()) inputRef.current?.focus();
              }}
            >
              {miaHomeCopy.newConversation}
            </button>
          ) : null}
          <button
            type="button"
            className="mia-panel__close"
            aria-label={miaPanelCopy.closeLabel}
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      <div className="mia-panel__messages" ref={scrollRef}>
        {exchanges.length === 0 && !conversation.restoring ? (
          <p className="mia-panel__intro">{miaPanelCopy.intro}</p>
        ) : null}
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

      <form
        className="mia-panel__form"
        aria-label={miaPanelCopy.formLabel}
        aria-busy={submitting}
        onSubmit={handleSubmit}
        noValidate
      >
        <label className="visually-hidden" htmlFor={inputId}>
          {miaHomeCopy.inputLabel}
        </label>
        <textarea
          id={inputId}
          ref={inputRef}
          rows={2}
          className="mia-panel__input"
          placeholder={miaPanelCopy.placeholder}
          value={question}
          maxLength={MAX_QUESTION_LENGTH}
          autoComplete="off"
          enterKeyHint="send"
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="submit"
          className="mia-panel__send"
          aria-label={submitting ? miaHomeCopy.submitting : miaHomeCopy.submit}
          disabled={submitting || !hasText}
          // A mouse/touch press must not pull focus (and the on-screen keyboard) out of the input.
          onMouseDown={(event) => event.preventDefault()}
        >
          {submitting ? <SpinnerIcon className="mia__send-spinner" /> : <ArrowUpIcon />}
        </button>
      </form>
    </div>
  );
}
