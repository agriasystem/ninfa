"use client";

import { miaHomeCopy } from "@/lib/ask-ninfa/copy";
import { answerBlocksOf } from "@/lib/ask-ninfa/format-answer";
import type { AskState } from "@/lib/ask-ninfa/state";

import { NinfaLogo } from "./ninfa-logo";

/**
 * One exchange, drawn the same way on the Home and in the panel of the other pages: the user's own
 * message (right-aligned, softly tinted - clearly "mine", never a boxed form summary) and, under it,
 * Mia's reply (open text under her name, no card). Only the NEWEST exchange's reply is the polite live
 * region: loading and the answer are announced, older replies and the rest of the page are not read
 * again.
 */
export function MiaExchangeView({
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

    // The backend's own UNAVAILABLE and any network/HTTP failure read the same: one dignified line,
    // never a status code and never the raw message.
    case "unavailable":
    case "error":
      return (
        <div role="alert">
          <p className="mia__reply-lead">{miaHomeCopy.unavailableHeading}</p>
          <p className="mia__note">{miaHomeCopy.unavailableSupporting}</p>
          <button type="button" className="mia__retry" onClick={onRetry}>
            {miaHomeCopy.retry}
          </button>
        </div>
      );
  }
}

/** Mia's answer as short paragraphs and, when she lists several items, a real list. Plain text with
 * line structure only - see `answerBlocksOf` (nothing is interpreted as Markdown or HTML). */
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
