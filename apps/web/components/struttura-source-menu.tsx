"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import type { CardButton } from "@/lib/sources/view-model";

import { MoreIcon } from "./icons";

export interface StrutturaSourceMenuProps {
  /** The accessible name of the "..." trigger ("Azioni per PMS"). */
  label: string;
  items: CardButton[];
  /** Where an item that is a PAGE (not a dialog) goes; `undefined` = the item is an action. */
  hrefOf: (item: CardButton) => string | undefined;
  onSelect: (item: CardButton) => void;
}

/**
 * The "..." menu of a card. It lists only what can be done with this card right now (the view model decides
 * - an action that cannot be used is never here), opens on click, closes on Escape / a click outside / a
 * choice, and moves with the arrow keys. A menu with no item is not drawn at all.
 */
export function StrutturaSourceMenu({ label, items, hrefOf, onSelect }: StrutturaSourceMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const first = rootRef.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  if (items.length === 0) return null;

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    const entries = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
    const index = entries.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      event.stopPropagation();
      close(true);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      entries[(index + 1) % entries.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      entries[(index - 1 + entries.length) % entries.length]?.focus();
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <div ref={rootRef} className="struttura-menu">
      <button
        ref={triggerRef}
        type="button"
        className="struttura-more"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        <MoreIcon className="struttura-more__icon" />
      </button>
      {open ? (
        <ul id={menuId} className="struttura-menu__list" role="menu" aria-label={label} onKeyDown={handleKeyDown}>
          {items.map((item) => {
            const href = hrefOf(item);
            return (
              <li key={item.action} role="none">
                {href !== undefined ? (
                  <Link
                    className="struttura-menu__item"
                    role="menuitem"
                    href={href}
                    onClick={() => close(false)}
                  >
                    {item.label}
                  </Link>
                ) : (
                  <button
                    type="button"
                    className="struttura-menu__item"
                    role="menuitem"
                    onClick={() => {
                      close(false);
                      onSelect(item);
                    }}
                  >
                    {item.label}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
