"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";

import type { PropertyAccess } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import { useSession } from "@/lib/session/session-context";

import { AppSidebar, type ShellSection } from "./app-sidebar";
import { PropertyHeader } from "./property-header";
import { ShellLogoContext, type ShellLogoControl } from "./shell-logo-context";

export interface AppShellProps {
  properties: PropertyAccess[];
  selectedPropertyId: string;
  onSelectProperty: (propertyId: string) => void;
  onLoggedOut: () => void;
  /** Which sidebar section is current (the Decision Detail passes "decisioni"). */
  activeSection: ShellSection;
  /** `"home"`: the full-bleed canvas of the Home; `"page"` (default): the centred reading column
   * every other screen uses. */
  variant?: "page" | "home";
  /** `true` on the Home: the sidebar logo starts empty because the hero logo is the one on screen
   * (the Home reveals it, through `useShellLogo()`, once the logo transition has landed). */
  logoInitiallyHidden?: boolean;
  children: ReactNode;
}

/**
 * The whole authenticated shell (Home UI V1, replacing Gate 14's topbar): a sidebar with the logo
 * slot, Oggi / Decisioni / Dati / Struttura and profile | settings; and, on the content side, the
 * property header (name + local date) above the page. Dati, Struttura and Impostazioni do not exist
 * yet and are never links (see `AppSidebar`). Logout is the profile menu's "Esci" - the same
 * `logout()` Gate 14 wired, unchanged.
 */
export function AppShell({
  properties,
  selectedPropertyId,
  onSelectProperty,
  onLoggedOut,
  activeSection,
  variant = "page",
  logoInitiallyHidden = false,
  children,
}: AppShellProps) {
  const { session, logout } = useSession();
  const [logoHidden, setLogoHidden] = useState(logoInitiallyHidden);
  const logoSlotRef = useRef<HTMLDivElement>(null);

  const logoControl = useMemo<ShellLogoControl>(
    () => ({ slotRef: logoSlotRef, setHidden: setLogoHidden }),
    [],
  );

  async function handleLogout() {
    await logout();
    onLoggedOut();
  }

  return (
    <ShellLogoContext.Provider value={logoControl}>
      <div className="app-shell">
        <a className="skip-link" href="#main-content">
          {copy.nav.skipToContent}
        </a>
        <AppSidebar
          selectedPropertyId={selectedPropertyId}
          activeSection={activeSection}
          logoHidden={logoHidden}
          logoSlotRef={logoSlotRef}
          displayName={session?.user.display_name ?? null}
          email={session?.user.email ?? null}
          onLogout={() => void handleLogout()}
        />
        <div className="app-shell__content">
          <PropertyHeader
            properties={properties}
            selectedPropertyId={selectedPropertyId}
            onSelect={onSelectProperty}
          />
          <main
            id="main-content"
            tabIndex={-1}
            className={`app-shell__main app-shell__main--${variant}`}
          >
            {children}
          </main>
        </div>
      </div>
    </ShellLogoContext.Provider>
  );
}
