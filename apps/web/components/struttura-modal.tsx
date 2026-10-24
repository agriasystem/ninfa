"use client";

import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { sourcesCopy } from "@/lib/sources/copy";

import { CloseIcon } from "./icons";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface StrutturaModalProps {
  title: string;
  /** Closing is refused while `false` (a request is in flight and must not be abandoned halfway). */
  dismissible?: boolean;
  onClose: () => void;
  children: ReactNode;
  /** The ONE sentence under the title (an optional, plain introduction). */
  description?: string;
}

/**
 * The dialog every "Fonti dati" flow opens in: a labelled `role="dialog"` that traps the keyboard, closes
 * on Escape or on a click outside, and hands the focus back to what opened it. Rendered in a portal, so the
 * shell's own layout never clips or shifts it. Nothing technical: a title, a sentence, the content.
 */
export function StrutturaModal({
  title,
  dismissible = true,
  onClose,
  children,
  description,
}: StrutturaModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusTo = useRef<Element | null>(null);

  // Remember what had the focus, move it inside, keep the page behind from scrolling, and give the focus
  // back on close.
  useEffect(() => {
    returnFocusTo.current = document.activeElement;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();
    const scrollBefore = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = scrollBefore;
      if (returnFocusTo.current instanceof HTMLElement) returnFocusTo.current.focus();
    };
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && dismissible) {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0] as HTMLElement;
    const last = focusable[focusable.length - 1] as HTMLElement;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div
      className="struttura-modal"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && dismissible) onClose();
      }}
    >
      <div
        ref={panelRef}
        className="struttura-modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <header className="struttura-modal__header">
          <div>
            <h2 id={titleId} className="struttura-modal__title">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="struttura-modal__description">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            className="struttura-modal__close"
            aria-label={sourcesCopy.dialog.close}
            disabled={!dismissible}
            onClick={onClose}
          >
            <CloseIcon className="struttura-modal__close-icon" />
          </button>
        </header>
        <div className="struttura-modal__body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
