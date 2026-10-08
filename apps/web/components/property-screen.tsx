"use client";

import { useEffect, type ReactNode } from "react";

import type { PropertyAccess } from "@ninfa/contracts";

import { copy } from "@/lib/copy";
import { allAccessibleProperties, resolveSelectedProperty } from "@/lib/session/properties";
import { useSession } from "@/lib/session/session-context";

import { AppShell } from "./app-shell";
import type { ShellSection } from "./app-sidebar";
import { AuthGate } from "./auth-gate";

export interface PropertyScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  /** Called whenever the resolved property differs from what the URL asked for: a real
   * selection, or a correction of an unknown/foreign id back to a real one. The caller updates
   * the URL/query - this component never trusts an arbitrary id enough to call the API with it. */
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
  activeSection: ShellSection;
  variant?: "page" | "home";
  logoInitiallyHidden?: boolean;
  /** Rendered inside the shell for the RESOLVED property. `onPropertyInvalid` re-resolves the
   * session's properties - the page calls it when its own request answers 404 PROPERTY_NOT_FOUND. */
  children: (selected: PropertyAccess, onPropertyInvalid: () => void) => ReactNode;
}

function PropertyScreenContent({
  requestedPropertyId,
  onSelectProperty,
  onNavigateToLogin,
  activeSection,
  variant,
  logoInitiallyHidden,
  children,
}: PropertyScreenProps) {
  const { session, refresh } = useSession();
  const properties = session ? allAccessibleProperties(session) : [];
  const selected = session ? resolveSelectedProperty(session, requestedPropertyId) : null;

  useEffect(() => {
    if (selected && requestedPropertyId !== selected.id) {
      onSelectProperty(selected.id);
    }
  }, [selected, requestedPropertyId, onSelectProperty]);

  if (!session) {
    // AuthGate only ever mounts this once status === "authenticated"; TypeScript still needs
    // the narrowing.
    return null;
  }

  if (selected === null) {
    return (
      <AppShell
        properties={[]}
        selectedPropertyId=""
        onSelectProperty={onSelectProperty}
        onLoggedOut={onNavigateToLogin}
        activeSection={activeSection}
      >
        <div className="property-empty-state">
          <h1>{copy.property.emptyStateTitle}</h1>
          <p>{copy.property.emptyStateBody}</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      properties={properties}
      selectedPropertyId={selected.id}
      onSelectProperty={onSelectProperty}
      onLoggedOut={onNavigateToLogin}
      activeSection={activeSection}
      variant={variant}
      logoInitiallyHidden={logoInitiallyHidden}
    >
      {children(selected, () => void refresh())}
    </AppShell>
  );
}

/**
 * The frame every property-scoped, top-level screen shares (the Home and `/decisioni`): auth
 * bootstrap gate, property resolution (0 / 1 / N properties), and the authenticated shell.
 * Framework-free (no `next/navigation` import) - each route's `page.tsx` wires it to the real router;
 * this is what actually gets tested.
 */
export function PropertyScreen(props: PropertyScreenProps) {
  return (
    <AuthGate onUnauthenticated={props.onNavigateToLogin}>
      <PropertyScreenContent {...props} />
    </AuthGate>
  );
}
