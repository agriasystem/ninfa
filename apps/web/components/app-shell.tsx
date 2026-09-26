"use client";

import type { ReactNode } from "react";

import type { PropertyAccess } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import { useSession } from "@/lib/session/session-context";

import { PropertySelector } from "./property-selector";

export interface AppShellProps {
  properties: PropertyAccess[];
  selectedPropertyId: string;
  onSelectProperty: (propertyId: string) => void;
  onLoggedOut: () => void;
  children: ReactNode;
}

/** The whole authenticated shell (Gate 14 spec, "App shell"): NINFA wordmark, property selector,
 * account email, logout. Deliberately nothing else - no Analytics/Revenue/Costi/Personale/
 * Settings/Notifications/Ask NINFA links to features that do not exist yet. */
export function AppShell({
  properties,
  selectedPropertyId,
  onSelectProperty,
  onLoggedOut,
  children,
}: AppShellProps) {
  const { session, logout } = useSession();

  async function handleLogout() {
    await logout();
    onLoggedOut();
  }

  return (
    <div className="app-shell">
      <header className="app-shell__topbar">
        <span className="app-shell__wordmark">{copy.brand.wordmark}</span>
        <PropertySelector
          properties={properties}
          selectedPropertyId={selectedPropertyId}
          onSelect={onSelectProperty}
        />
        <div className="app-shell__account">
          {session ? <span className="app-shell__email">{session.user.email}</span> : null}
          <button type="button" onClick={() => void handleLogout()}>
            {copy.shell.logout}
          </button>
        </div>
      </header>
      <main className="app-shell__main">{children}</main>
    </div>
  );
}
