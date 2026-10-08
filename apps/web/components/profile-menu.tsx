"use client";

import { useEffect, useId, useRef, useState } from "react";

import { copy } from "@/lib/copy";

import { UserIcon } from "./icons";

export interface ProfileMenuProps {
  displayName: string | null;
  email: string | null;
  onLogout: () => void;
}

/**
 * The bottom-left profile control: an avatar button that discloses the account (display name when
 * present, e-mail) and the one real action, "Esci" - which still goes through the app's existing
 * `logout()` (the caller wires it; this component never talks to the API).
 *
 * A plain disclosure (`aria-expanded` + `aria-controls`), not an ARIA `menu`: it holds information
 * and a single button, so the menu role's arrow-key contract would only get in the way. Escape
 * closes it and returns focus to the avatar; so does a click outside. Tab order is natural - the
 * panel is the next element after its button.
 */
export function ProfileMenu({ displayName, email, onLogout }: ProfileMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open]);

  return (
    <div className="profile-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="profile-menu__button"
        aria-label={copy.nav.profile}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <UserIcon />
      </button>
      {open ? (
        <div id={panelId} className="profile-menu__panel" role="group" aria-label={copy.nav.profile}>
          {displayName !== null ? <p className="profile-menu__name">{displayName}</p> : null}
          {email !== null ? <p className="profile-menu__email">{email}</p> : null}
          <button type="button" className="profile-menu__logout" onClick={onLogout}>
            {copy.shell.logout}
          </button>
        </div>
      ) : null}
    </div>
  );
}
